"""Поиск фрагментов резюме под требование (T06, часть B): BM25 + эмбеддинги, слияние через RRF.

- BM25 ловит точные термины: «1С», «C++», «ISO 9001». Токены — нижний регистр, ё → е, стемминг
  snowball ru + en. Кандидат — только фрагмент, где совпало хотя бы одно слово запроса.
- Эмбеддинги (sentence-transformers на CPU) ловят перефразы. Подключаются, только если
  установлен extra `embeddings` и задан EMBEDDINGS_MODEL; иначе — только BM25.
- Фильтр по разделам: если в нужных разделах ничего нет, ищем по всему документу.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

import snowballstemmer

from aihr.contracts import Document, ReqKind

log = logging.getLogger(__name__)

RRF_K = 60

_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+(?:[+#]+)?", re.IGNORECASE)


def _words(text: str) -> set[str]:
    return set(text.split())


_STOP = _words(
    """и в во на с со по к ко о об от до из за для при без над под у же ли бы не ни а но или
    то это как что чтобы так также его её их мой наш ваш свой быть был была были есть
    the a an and or of to in on for with at by from is are be as"""
)
# Общие слова формулировок требований: без них «опыт работы в X» находит X, а не заголовок
# «Опыт работы». Это лексика любой вакансии, а не предметной области (D12)
_STOP |= _words(
    """опыт опыта опытом работа работы работе работу работой знание знания знаний умение
    умения навык навыки навыков владение уверенный уверенное уверенная хороший хорошее
    хорошая понимание готовность требуется требования обязательно желательно лет год года
    experience knowledge skills skill years year ability good strong"""
)
# Стеммеры snowball хранят состояние внутри объекта и не потокобезопасны, а вакансии
# считаются параллельно (T03): у каждого потока свои экземпляры
_local = threading.local()


def _stemmers() -> tuple[Any, Any]:
    if not hasattr(_local, "ru"):
        _local.ru = snowballstemmer.stemmer("russian")
        _local.en = snowballstemmer.stemmer("english")
    return _local.ru, _local.en


# Где искать подтверждение требования данного типа
_ROLES: dict[ReqKind, list[str]] = {
    ReqKind.skill: ["skills", "experience", "about", "education"],
    ReqKind.experience: ["experience", "about"],
    ReqKind.education: ["education"],
    ReqKind.language: ["skills", "about", "education"],
    ReqKind.certificate: ["education", "skills", "other", "about"],
    ReqKind.duty: ["experience"],
    ReqKind.soft: ["about", "experience", "skills"],
}


def roles_for(kind: ReqKind) -> list[str] | None:
    return _ROLES.get(kind)


def _stem(word: str) -> str:
    ru, en = _stemmers()
    if re.fullmatch(r"[а-яё]+", word):
        return ru.stemWord(word)
    if re.fullmatch(r"[a-z]+", word):
        return en.stemWord(word)
    return word  # «1с», «c++», «9001» — как есть


def tokens(text: str) -> list[str]:
    words = [w.lower().replace("ё", "е") for w in _TOKEN_RE.findall(text)]
    return [_stem(w) for w in words if w not in _STOP and (len(w) > 1 or w.isdigit())]


Encoder = Callable[[Sequence[str]], Any]  # список текстов → матрица векторов (нормированных)


@lru_cache(maxsize=2)
def _load_encoder(model_name: str) -> Encoder | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        log.info("extra embeddings не установлен: поиск только BM25")
        return None
    try:
        model = SentenceTransformer(model_name, device="cpu")
    except Exception as exc:  # модели нет в образе и нет сети — работаем без эмбеддингов
        log.warning("модель эмбеддингов %s не загрузилась: %s", model_name, type(exc).__name__)
        return None

    def encode(texts: Sequence[str]) -> Any:
        return model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)

    return encode


def default_encoder() -> tuple[Encoder | None, bool]:
    """(кодировщик, нужны ли префиксы e5) по настройкам."""
    from aihr.config import get_settings

    name = get_settings().embeddings_model
    if not name:
        return None, False
    return _load_encoder(name), "e5" in name.lower()


class Retriever:
    def __init__(
        self,
        doc: Document,
        encoder: Encoder | None = None,
        *,
        e5_prefixes: bool = False,
        embeddings: bool = True,
    ) -> None:
        """encoder=None — кодировщик по настройкам; embeddings=False — только BM25."""
        from rank_bm25 import BM25Okapi

        self.doc = doc
        self.ids = [f.id for f in doc.fragments]
        self.roles = [f.section_role for f in doc.fragments]
        texts = [f.masked_text or f.text for f in doc.fragments]
        self._tokens = [tokens(t) for t in texts]
        self._sets = [set(t) for t in self._tokens]
        self._bm25 = BM25Okapi([t or ["∅"] for t in self._tokens]) if texts else None
        if not embeddings:
            encoder = None
        elif encoder is None:
            encoder, e5_prefixes = default_encoder()
        self._encoder = encoder
        self._e5 = e5_prefixes
        self._vectors: Any | None = None
        if encoder is not None and texts:
            passages = [f"passage: {t}" if e5_prefixes else t for t in texts]
            self._vectors = encoder(passages)

    @property
    def uses_embeddings(self) -> bool:
        return self._vectors is not None

    def _bm25_ranking(self, q: list[str], allowed: list[int]) -> list[int]:
        if not q or self._bm25 is None:
            return []
        scores = self._bm25.get_scores(q)
        qs = set(q)
        hits = [i for i in allowed if qs & self._sets[i]]
        return sorted(hits, key=lambda i: (-scores[i], -len(qs & self._sets[i]), i))

    def _embedding_ranking(self, query: str, allowed: list[int], k: int) -> list[int]:
        if self._vectors is None or self._encoder is None or not allowed:
            return []
        import numpy as np

        q = self._encoder([f"query: {query}" if self._e5 else query])[0]
        sims = np.asarray(self._vectors)[allowed] @ np.asarray(q)
        order = np.argsort(-sims)[:k]
        return [allowed[int(j)] for j in order]

    def search(
        self,
        query: str,
        terms: list[str],
        k: int = 8,
        section_roles: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        full = " ".join([query, *terms])
        q = tokens(full)
        everything = list(range(len(self.ids)))
        allowed = (
            [i for i in everything if self.roles[i] in section_roles]
            if section_roles
            else everything
        )
        result = self._fuse(q, full, allowed, k)
        if not result and section_roles:
            result = self._fuse(q, full, everything, k)  # в нужных разделах пусто — весь документ
        return result

    def _fuse(self, q: list[str], full: str, allowed: list[int], k: int) -> list[tuple[str, float]]:
        rankings = [self._bm25_ranking(q, allowed)]
        if self._vectors is not None:
            rankings.append(self._embedding_ranking(full, allowed, max(k * 2, 16)))
        fused: dict[int, float] = {}
        for ranking in rankings:
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)
        best = sorted(fused, key=lambda i: (-fused[i], i))[:k]
        return [(self.ids[i], round(fused[i], 6)) for i in best]

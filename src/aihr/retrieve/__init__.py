"""Поиск фрагментов резюме под требование.

T00: пересечение слов (по основам из snowballstemmer). T06: BM25 + синонимы, T07: эмбеддинги.
"""

from __future__ import annotations

import re

import snowballstemmer

from aihr.contracts import Document

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_stem_ru = snowballstemmer.stemmer("russian")
_stem_en = snowballstemmer.stemmer("english")


def tokens(text: str) -> list[str]:
    words = [w.lower() for w in _WORD_RE.findall(text) if len(w) > 1]
    return [_stem_en.stemWord(_stem_ru.stemWord(w)) for w in words]


class Retriever:
    def __init__(self, doc: Document) -> None:
        self.doc = doc
        self._index = [(f.id, f.section_role, set(tokens(f.text))) for f in doc.fragments]
        self._pos = {f.id: i for i, f in enumerate(doc.fragments)}

    def search(
        self,
        query: str,
        terms: list[str],
        k: int = 8,
        section_roles: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        q = set(tokens(query))
        for term in terms:
            q.update(tokens(term))
        if not q:
            return []
        scored = []
        for fid, role, toks in self._index:
            if section_roles and role not in section_roles:
                continue
            overlap = len(q & toks)
            if overlap:
                scored.append((fid, overlap / len(q)))
        scored.sort(key=lambda x: (-x[1], self._pos[x[0]]))
        return scored[:k]

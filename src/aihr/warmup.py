"""Прогрев моделей при сборке образа: `python -m aihr.warmup`.

Natasha везёт модели внутри пакета — проверяем, что они грузятся (ловим проблемы зависимостей
на сборке, а не на первом запросе). Если установлен extra `embeddings` и задан EMBEDDINGS_MODEL,
модель скачивается в HF_HOME, чтобы в рантайме не ходить в сеть.
"""

from __future__ import annotations

import logging
import sys

from aihr.config import get_settings, setup_logging

log = logging.getLogger("aihr.warmup")


def warm_natasha() -> None:
    from natasha import Doc, MorphVocab, NewsEmbedding, NewsNERTagger, Segmenter

    emb = NewsEmbedding()
    doc = Doc("Пётр Сидоров работал в Казани.")
    doc.segment(Segmenter())
    doc.tag_ner(NewsNERTagger(emb))
    MorphVocab()
    log.info("Natasha: модели загружены, NER нашёл %d сущностей", len(doc.spans))


def warm_embeddings() -> None:
    model = get_settings().embeddings_model
    if not model:
        log.info("эмбеддинги выключены (EMBEDDINGS_MODEL пуст)")
        return
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        log.info("extra embeddings не установлен — модель %s не скачиваем", model)
        return
    SentenceTransformer(model, device="cpu")
    log.info("эмбеддинги: модель %s в кэше", model)


def main() -> int:
    setup_logging("INFO")
    warm_natasha()
    warm_embeddings()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""The retrieval half: embed table descriptions, find the relevant ones.

WHY RETRIEVAL IS NEEDED AT ALL
------------------------------
A Spider database has up to ~20 tables; a real one has hundreds. Pasting every
schema into the prompt costs tokens linearly and buries the two tables that
matter in noise the model has to filter out.

And unlike code, schemas embed WELL. A table called `singer` with columns
`Name, Country, Age` genuinely lands close to "which singers are from
Netherlands?" -- the vocabulary of a schema is the vocabulary of the questions
people ask about it.
"""

from __future__ import annotations

import numpy as np

from .config import CHROMA_DIR, EMBED_DIM, EMBED_MODEL, INCLUDE_SAMPLE_ROWS, TOP_K_TABLES
from .models import Table
from .schema import describe

_model = None
_client = None


def load_model() -> None:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBED_MODEL)


def encode(texts: list[str]) -> np.ndarray:
    """Batched, L2-normalised. Normalising means Chroma's default L2 distance
    ranks results in the same order cosine similarity would -- for unit vectors
    the two are a monotonic transform of each other, so no distance-metric
    override is needed on the collection."""
    if _model is None:
        load_model()
    v = _model.encode(texts, batch_size=32, normalize_embeddings=True,
                      show_progress_bar=False)
    v = np.asarray(v, dtype=np.float32)
    assert v.shape[1] == EMBED_DIM, f"expected {EMBED_DIM}-d, got {v.shape}"
    return v


def _collection():
    """Lazily open the persistent Chroma client. One collection, `table_docs` --
    db_id and with_rows are metadata, not separate collections, because Chroma
    collections are the wrong unit to split 200 databases across: a `where`
    filter on metadata does the scoping instead (§11)."""
    global _client
    if _client is None:
        import chromadb
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client.get_or_create_collection("table_docs")


def _doc_id(db_id: str, table_name: str, with_rows: bool) -> str:
    return f"{db_id}::{table_name}::{int(with_rows)}"


def index_database(db_id: str, tables: list[Table],
                   include_samples: bool = INCLUDE_SAMPLE_ROWS) -> int:
    """Embed one database's tables. Idempotent per (db_id, table, with_rows).

    upsert(), not add() -- Chroma's add() raises on a duplicate id, and
    re-running after an interrupted index should resume rather than crash on
    the first table it already wrote. Overwriting is safe because the same
    input always produces the same embedding.
    """
    if not tables:
        return 0
    docs = [describe(t, include_samples=include_samples) for t in tables]
    vectors = encode(docs)

    _collection().upsert(
        ids=[_doc_id(db_id, t.name, include_samples) for t in tables],
        embeddings=vectors.tolist(),
        documents=docs,
        metadatas=[{"db_id": db_id, "table_name": t.name, "with_rows": include_samples}
                   for t in tables],
    )
    return len(tables)


def is_indexed(db_id: str, include_samples: bool = INCLUDE_SAMPLE_ROWS) -> bool:
    got = _collection().get(
        where={"$and": [{"db_id": db_id}, {"with_rows": include_samples}]}, limit=1)
    return len(got["ids"]) > 0


def retrieve(db_id: str, question: str, k: int = TOP_K_TABLES,
             include_samples: bool = INCLUDE_SAMPLE_ROWS) -> list[str]:
    """Top-k table descriptions for this question, within ONE database.

    The `where` filter scopes the search to db_id before ranking -- see §11 for
    why that matters and why it's not the same failure mode pgvector's post-
    filtering ANN index has.
    """
    qv = encode([question])[0]
    res = _collection().query(
        query_embeddings=[qv.tolist()],
        n_results=k,
        where={"$and": [{"db_id": db_id}, {"with_rows": include_samples}]},
    )
    return res["documents"][0]


def retrieve_all(db_id: str, include_samples: bool = INCLUDE_SAMPLE_ROWS) -> list[str]:
    """Every table, no retrieval. The control arm: does retrieval actually beat
    pasting the whole schema in? On small databases it may not, and finding that
    out is worth more than assuming."""
    got = _collection().get(
        where={"$and": [{"db_id": db_id}, {"with_rows": include_samples}]})
    # get() does not guarantee order; sort for a reproducible prompt.
    pairs = sorted(zip(got["metadatas"], got["documents"]),
                   key=lambda m: m[0]["table_name"])
    return [doc for _, doc in pairs]

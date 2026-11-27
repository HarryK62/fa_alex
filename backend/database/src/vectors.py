"""
Local knowledge base: pgvector in Postgres with OpenAI embeddings.
"""

import json
import os
from typing import Dict, List, Optional

from .local_client import LocalPostgresClient

EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


def embed(text: str) -> List[float]:
    from openai import OpenAI

    response = OpenAI().embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding


def _vector_literal(embedding: List[float]) -> str:
    return "[" + ",".join(str(x) for x in embedding) + "]"


def add_document(text: str, metadata: Optional[Dict] = None) -> str:
    """Embed and store a document. Returns its id."""
    client = LocalPostgresClient()
    response = client.execute(
        "INSERT INTO documents (text, metadata, embedding) "
        "VALUES (:text, :metadata::jsonb, :embedding::vector) RETURNING id",
        [
            {"name": "text", "value": {"stringValue": text}},
            {"name": "metadata", "value": {"stringValue": json.dumps(metadata or {})}},
            {"name": "embedding", "value": {"stringValue": _vector_literal(embed(text))}},
        ],
    )
    return response["records"][0][0]["stringValue"]


def search(query: str, top_k: int = 3) -> List[Dict]:
    """Return the closest documents as dicts with text, metadata and distance."""
    client = LocalPostgresClient()
    return client.query(
        "SELECT text, metadata, embedding <=> :embedding::vector AS distance "
        "FROM documents ORDER BY distance LIMIT :top_k",
        [
            {"name": "embedding", "value": {"stringValue": _vector_literal(embed(query))}},
            {"name": "top_k", "value": {"longValue": top_k}},
        ],
    )

"""
Local Postgres client (Postgres + pgvector in Docker).

It implements DataAPIClient.execute using Data API style parameters and
response shapes, so models.py and the scripts keep their original code.
"""

import json
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

import psycopg

from .client import DataAPIClient

DEFAULT_DATABASE_URL = "postgresql://alex:alex@localhost:5432/alex"

# Matches :name placeholders but not ::casts
_PLACEHOLDER = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


def _param_value(value: Dict) -> Any:
    """Turn a Data API value dict ({'stringValue': 'x'}) into a Python value."""
    if value.get("isNull"):
        return None
    for key in ("stringValue", "longValue", "doubleValue", "booleanValue", "blobValue"):
        if key in value:
            return value[key]
    raise ValueError(f"Unsupported Data API parameter value: {value}")


def _field(value: Any) -> Dict:
    """Turn a Python value from Postgres into a Data API field dict."""
    if value is None:
        return {"isNull": True}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"longValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (dict, list)):
        return {"stringValue": json.dumps(value)}
    # Aurora returns numerics, uuids and timestamps as strings too
    if isinstance(value, (Decimal, uuid.UUID, datetime, date)):
        return {"stringValue": str(value)}
    if isinstance(value, (bytes, memoryview)):
        return {"blobValue": bytes(value)}
    return {"stringValue": str(value)}


class LocalPostgresClient(DataAPIClient):
    """DataAPIClient replacement backed by a local Postgres connection."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
        self.database = "alex"
        self._conn: Optional[psycopg.Connection] = None

    @property
    def conn(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.database_url, autocommit=True)
        return self._conn

    def execute(self, sql: str, parameters: List[Dict] = None) -> Dict:
        params = {p["name"]: _param_value(p["value"]) for p in (parameters or [])}

        # psycopg uses %(name)s placeholders, so escape literal % first
        sql = sql.replace("%", "%%")
        sql = _PLACEHOLDER.sub(
            lambda m: f"%({m.group(1)})s" if m.group(1) in params else m.group(0), sql
        )

        with self.conn.cursor() as cur:
            cur.execute(sql, params or None)
            response: Dict[str, Any] = {"numberOfRecordsUpdated": max(cur.rowcount, 0)}
            if cur.description:
                response["columnMetadata"] = [{"name": col.name} for col in cur.description]
                response["records"] = [[_field(v) for v in row] for row in cur.fetchall()]
            return response

    def execute_statement(self, sql: str, parameters: List[Dict] = None) -> Dict:
        """Alias used by the migration and seed scripts."""
        return self.execute(sql, parameters)

    # Every statement auto-commits locally; transactions are not used by the app.
    def begin_transaction(self) -> str:
        raise NotImplementedError("Transactions are not supported ")

    def commit_transaction(self, transaction_id: str):
        raise NotImplementedError("Transactions are not supported ")

    def rollback_transaction(self, transaction_id: str):
        raise NotImplementedError("Transactions are not supported ")

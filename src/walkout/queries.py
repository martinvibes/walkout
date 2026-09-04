"""Named SQL, loaded from disk.

Queries live in sql/queries/*.sql rather than in Python string literals so they
stay reviewable, diffable, and runnable by hand against the cluster. Every
parameter is bound by ClickHouse, never interpolated -- the model chooses
*values*, never SQL.
"""

from __future__ import annotations

from functools import lru_cache

from .config import SQL_DIR

QUERY_DIR = SQL_DIR / "queries"


class UnknownQuery(KeyError):
    pass


@lru_cache(maxsize=None)
def load(name: str) -> str:
    path = QUERY_DIR / f"{name}.sql"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in QUERY_DIR.glob("*.sql")))
        raise UnknownQuery(f"no query named {name!r}. available: {available}")
    return path.read_text()


def available() -> list[str]:
    return sorted(p.stem for p in QUERY_DIR.glob("*.sql"))

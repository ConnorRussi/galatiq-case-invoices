"""Small, exact inventory lookup boundary used by the database specialist."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel, Field


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[3] / "inventory.sqlite"


class InventoryLookup(BaseModel):
    """One exact database lookup, retaining the requested spelling."""

    requested_name: str = Field(min_length=1)
    matched_item: str | None = None
    available_stock: int | None = None
    product_found: bool


def lookup_inventory_bulk(
    names: Sequence[str],
    *,
    db_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[InventoryLookup]:
    """Look up names exactly after trimming only outer whitespace.

    The SQL boundary intentionally does not remove internal whitespace or
    punctuation, change case, split words, or otherwise infer identity. The
    database specialist decides which deliberate variations to request in a
    later round.
    """

    requested = [name.strip() for name in names]
    if any(not name for name in requested):
        raise ValueError("Inventory lookup names must be non-empty")
    if not requested:
        return []

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Inventory database does not exist: {path}")

    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        cursor = connection.cursor()
        return [_lookup_one(cursor, name) for name in requested]
    finally:
        connection.close()


def _lookup_one(cursor: sqlite3.Cursor, name: str) -> InventoryLookup:
    row = cursor.execute(
        "SELECT item, stock FROM inventory WHERE item = ?",
        (name,),
    ).fetchone()
    if row is None:
        return InventoryLookup(
            requested_name=name,
            matched_item=None,
            available_stock=None,
            product_found=False,
        )
    return InventoryLookup(
        requested_name=name,
        matched_item=str(row[0]),
        available_stock=int(row[1]),
        product_found=True,
    )

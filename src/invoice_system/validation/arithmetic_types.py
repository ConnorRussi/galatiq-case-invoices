"""Shared non-arithmetic identity normalization primitive."""

from __future__ import annotations

import re


def normalize_product_name(value: str | None) -> str:
    """Create a stable lexical identity without deciding product equivalence."""

    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

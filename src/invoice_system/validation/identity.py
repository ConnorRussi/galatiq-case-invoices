"""Conservative product-identity interpretation for validation.

This module interprets source descriptions without changing them.  Arithmetic
consumes its line-to-identity mapping, while the source description remains
the requested/display value for audit and database lookup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from invoice_system.ingestion.models import NormalizedInvoice

from .arithmetic_types import normalize_product_name


# These are fulfillment qualifiers, not product variants.  The vocabulary is
# deliberately small: an unrecognized qualifier must remain unresolved rather
# than being silently stripped.
FULFILLMENT_QUALIFIERS = frozenset({"rush order"})


@dataclass(frozen=True)
class ProductIdentityMapping:
    source_line: int
    source_description: str
    resolved_product: str | None
    normalized_product: str | None
    qualifier: str | None
    resolution: str


def resolve_product_identities(invoice: NormalizedInvoice) -> list[ProductIdentityMapping]:
    """Map each named source line to a conservative product identity.

    A parenthesized suffix is interpreted only when it is a known fulfillment
    qualifier and the invoice contains the corresponding unqualified product.
    This supports a rush-order line without making punctuation removal a
    general aliasing rule.
    """

    descriptions = {
        normalize_product_name(item.item_name)
        for item in invoice.items
        if item.item_name
    }
    mappings: list[ProductIdentityMapping] = []
    for line, item in enumerate(invoice.items, start=1):
        description = (item.item_name or "").strip()
        if not description:
            continue
        match = re.fullmatch(r"(?P<base>.*?)\s*\((?P<qualifier>[^()]+)\)\s*", description)
        if match:
            base = match.group("base").strip()
            qualifier = match.group("qualifier").strip().casefold()
            base_identity = normalize_product_name(base)
            if qualifier in FULFILLMENT_QUALIFIERS and base_identity in descriptions:
                mappings.append(
                    ProductIdentityMapping(
                        source_line=line,
                        source_description=description,
                        resolved_product=base,
                        normalized_product=base_identity,
                        qualifier=qualifier,
                        resolution="fulfillment_qualifier",
                    )
                )
                continue
            mappings.append(
                ProductIdentityMapping(
                    source_line=line,
                    source_description=description,
                    resolved_product=None,
                    normalized_product=None,
                    qualifier=qualifier,
                    resolution="unresolved_qualifier",
                )
            )
            continue
        identity = normalize_product_name(description)
        mappings.append(
            ProductIdentityMapping(
                source_line=line,
                source_description=description,
                resolved_product=description,
                normalized_product=identity,
                qualifier=None,
                resolution="exact_description",
            )
        )
    return mappings

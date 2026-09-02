"""FDA Import Alert DWPE lists (66-40, 66-41) -> observations.

The page is 63,000 divs of firm blocks with no table markup and no stable
identifier: no FEI, no DUNS, no registration number. Firm name plus address
is all there is, so this is deliberately a **membership** series — "these
firms were on the list this week" — and not a firm-identity series. Renames
and acquisitions will read as a delisting plus a new listing, which is a
known and unavoidable limitation of the source.

The signal the source destroys is removal: additions carry a publish date,
delistings carry nothing at all.

Entity ids are composite — `country:<country>/firm:<firm>` — so per-country
counts are a downstream GROUP BY rather than a parse-time aggregate. Matches
the shortage parser, where paging makes parse-time counts unsafe.

A firm can occupy several blocks (multiple addresses, or product groups split
across the page), so blocks are merged **per firm** before emitting — keyed on
the firm alone, not on (country, firm). Keying on the pair split firms whose
country parsed from one block and not another, inflating an "unknown" bucket
and deflating the real ones. The first country seen for a firm wins.
That makes (entity_id, metric, observed_at) unique by construction, which is
what lets a consumer deduplicate without guessing between "sum" and "latest".
"""
import re
from html import unescape

from wss import derive

PARSER_VERSION = "1"

_BLOCK_RE = re.compile(r'<div class="div-info".*?(?=<div class="div-info"|\Z)',
                       re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_RE = re.compile(r"Date Published\s*:?\s*(\d{2})/(\d{2})/(\d{4})")
_COUNTRY_RE = re.compile(r"\b([A-Z][A-Z ]{3,30})\s*$")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:80]


def _lines(block: str) -> list[str]:
    text = unescape(_TAG_RE.sub("\n", block))
    return [line.strip() for line in text.split("\n") if line.strip()]


def parse(body: bytes, ctx: derive.ParseContext):
    html = body.decode("utf-8", errors="replace")
    blocks = _BLOCK_RE.findall(html)

    merged: dict[str, dict] = {}

    for block in blocks:
        lines = _lines(block)
        if not lines:
            continue
        firm = _slug(lines[0])
        if not firm:
            continue

        country = None
        for line in lines[:8]:
            m = _COUNTRY_RE.search(line)
            if m and len(m.group(1).strip()) > 3:
                country = m.group(1).strip()

        dates = [int(y + mm + dd) for mm, dd, y in _DATE_RE.findall(block)]
        acc = merged.setdefault(
            firm, {"country": None, "first": None, "entries": 0})
        if acc["country"] is None and country:
            acc["country"] = country
        acc["entries"] += len(dates)
        if dates:
            here = min(dates)
            acc["first"] = here if acc["first"] is None else min(acc["first"], here)

    for firm, acc in merged.items():
        entity = f"country:{_slug(acc['country'] or 'unknown')}/firm:{firm}"
        yield derive.Observation(
            entity_id=entity, metric="listed", value=1, unit="bool")
        if acc["first"] is not None:
            yield derive.Observation(
                entity_id=entity, metric="first_listed", value=acc["first"],
                unit="yyyymmdd")
        # A firm banned for 20 products is not the same event as one banned
        # for a single product.
        yield derive.Observation(
            entity_id=entity, metric="product_entries", value=acc["entries"],
            unit="count")

    # Single-endpoint source, so this headline total cannot page-split.
    yield derive.Observation(
        entity_id="alert:total", metric="firms_listed", value=len(merged),
        unit="count")


derive.register("fda-importalert.v1", parse, PARSER_VERSION)

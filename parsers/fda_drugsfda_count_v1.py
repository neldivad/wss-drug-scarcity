"""Drugs@FDA marketing-status counts per molecule -> observations.

The payload is an openFDA `count=` aggregate, so it is already the answer:

    {"results": [{"term": "Discontinued", "count": 33},
                 {"term": "Prescription",  "count": 4}]}

`marketing_status` is a CURRENT-state field with no discontinuation date, and
Drugs@FDA overwrites it in place. Sampling it monthly is what turns a supplier
exit into a dated event — which is the whole of Q14, and the reason this is a
capture rather than a lookup.

The molecule is not in the payload, so it is read back out of the request URL.
That keeps entity ids stable across cohort vintages without the parser needing
to know anything about the cohort.
"""
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from wss import derive

PARSER_VERSION = "1"

_NAME_RE = re.compile(r'products\.active_ingredients\.name:"([^"]+)"')
# Slots are stable metric names; a status FDA stops using must keep its column.
_METRIC = {
    "discontinued": "products_discontinued",
    "prescription": "products_prescription",
    "over-the-counter": "products_otc",
    "none (tentative approval)": "products_tentative",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:80]


def _molecule(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    search = (query.get("search") or [""])[0]
    m = _NAME_RE.search(unquote(search))
    return m.group(1) if m else None


def parse(body: bytes, ctx: derive.ParseContext):
    molecule = _molecule(ctx.url)
    if not molecule:
        return
    entity = f"molecule:{_slug(molecule)}"

    payload = json.loads(body)
    counts = {}
    for row in payload.get("results") or []:
        metric = _METRIC.get(str(row.get("term", "")).strip().lower())
        if metric:
            counts[metric] = int(row.get("count", 0))

    for metric, value in sorted(counts.items()):
        yield derive.Observation(
            entity_id=entity, metric=metric, value=value, unit="count")

    # Emitted every capture, including when a slot is absent, so a molecule
    # whose last marketed product disappears reads as 0 rather than as a gap.
    marketed = (counts.get("products_prescription", 0)
                + counts.get("products_otc", 0))
    yield derive.Observation(
        entity_id=entity, metric="products_marketed", value=marketed,
        unit="count")
    gone = counts.get("products_discontinued", 0)
    yield derive.Observation(
        entity_id=entity, metric="products_ever", value=marketed + gone,
        unit="count")


derive.register("fda-drugsfda-count.v1", parse, PARSER_VERSION)

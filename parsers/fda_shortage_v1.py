"""openFDA drug-shortage feed -> observations.

The feed is a snapshot of what is short *now*; resolved records leave it.
So every observation is a membership fact dated at capture time, and the
series only becomes answerable by accumulating those snapshots.

Purity rule: nothing here may depend on today's date. `first_listed` is
emitted as an absolute YYYYMMDD integer, never as an age, so re-deriving the
archive years from now reproduces byte-identical output.

Entity ids are composite — `drug:<generic>/ndc:<ndc11>` — because the feed is
paged. Emitting per-drug or per-status *counts* here would split them across
two endpoints and produce two rows with the same `observed_at` and different
values, ambiguous between "sum" and "latest". Every aggregate is a downstream
GROUP BY on the entity prefix instead.

`status_code`: 0 = Resolved, 1 = Current, 2 = To Be Discontinued.

One package NDC can carry several records (different presentations of the
same package, or a re-listing). They are merged per NDC, and where they
disagree the **worst** value wins: lowest availability, lowest status_code,
earliest first_listed, latest last_update. A package that any record calls
unavailable is not reliably available, and biasing the other way would let a
single optimistic row erase a live shortage.
"""
import json
import re

from wss import derive

PARSER_VERSION = "1"

# Ordinal so it can live in a numeric `value` column. Higher is better supply.
_STATUS = {
    "resolved": 0,
    "current": 1,
    "to be discontinued": 2,
}

_AVAILABILITY = {
    "unavailable": 0,
    "unvailable": 0,  # FDA's own typo, present in the live feed
    "limited availability": 1,
    "available": 2,
}


def _ndc11(packaged: str) -> str | None:
    """5-4-2 NDC, zero-padded from whichever segment is short."""
    parts = (packaged or "").strip().split("-")
    if len(parts) != 3:
        return None
    a, b, c = parts
    if len(a) == 4:
        a = "0" + a
    elif len(b) == 3:
        b = "0" + b
    elif len(c) == 1:
        c = "0" + c
    joined = a + b + c
    return joined if len(joined) == 11 and joined.isdigit() else None


def _yyyymmdd(value: str) -> int | None:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (value or "").strip())
    if not m:
        return None
    mm, dd, yyyy = m.groups()
    return int(yyyy + mm + dd)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:80]


def parse(body: bytes, ctx: derive.ParseContext):
    payload = json.loads(body)

    total = (payload.get("meta") or {}).get("results", {}).get("total")
    if total is not None:
        # Growth past the two paged endpoints shows up here rather than
        # silently truncating the capture.
        yield derive.Observation(
            entity_id="feed:shortages", metric="feed_records_total",
            value=int(total), unit="count")

    merged: dict[str, dict] = {}

    for record in payload.get("results") or []:
        ndc = _ndc11(record.get("package_ndc", ""))
        if not ndc:
            continue
        generic = _slug(record.get("generic_name") or "unknown")
        entity = f"drug:{generic}/ndc:{ndc}"
        acc = merged.setdefault(entity, {})

        status = _STATUS.get((record.get("status") or "").strip().lower())
        if status is not None:
            acc["status_code"] = min(status, acc.get("status_code", status))

        availability = _AVAILABILITY.get(
            (record.get("availability") or "").strip().lower())
        if availability is not None:
            acc["availability"] = min(
                availability, acc.get("availability", availability))

        first_listed = _yyyymmdd(record.get("initial_posting_date", ""))
        if first_listed:
            acc["first_listed"] = min(
                first_listed, acc.get("first_listed", first_listed))

        last_update = _yyyymmdd(record.get("update_date", ""))
        if last_update:
            acc["last_update"] = max(
                last_update, acc.get("last_update", last_update))

    _UNITS = {"status_code": "code", "availability": "ordinal",
              "first_listed": "yyyymmdd", "last_update": "yyyymmdd"}

    for entity, acc in merged.items():
        yield derive.Observation(
            entity_id=entity, metric="listed", value=1, unit="bool")
        for metric, value in acc.items():
            yield derive.Observation(
                entity_id=entity, metric=metric, value=value,
                unit=_UNITS[metric])


derive.register("fda-shortage.v1", parse, PARSER_VERSION)

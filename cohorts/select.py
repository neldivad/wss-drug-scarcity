#!/usr/bin/env python3
"""Select a vintage of the `injectable-generics` cohort. MANUAL, NEVER A CRON.

    python cohorts/select.py --selected-at 2026-09-03

Run it by hand, read the diff, commit it. Re-selecting on a schedule would
quietly delete every molecule that died between runs, which is the exact
survivorship failure the cohort machinery exists to prevent.

WHY A COHORT AT ALL. Q14 asks whether suppliers leave *before* a shortage or
after it. A panel of "drugs short today" can never answer that — by the time a
molecule qualifies, the exits already happened. So the population is the
at-risk one: injectable generics, short or not, followed forever.

    established  — top 300 injectable ANDA generics by marketed product count,
                   floor 3. The control group: mostly not short, and the only
                   way a pre-shortage exit is ever observed.
    new_entrant  — any molecule FDA has listed as short since --entrant-since,
                   at any size. This path is what stops the panel from being
                   only the drugs that were already big in 2026.

`entity_id` is the UPPERCASE active-ingredient string used to query Drugs@FDA,
verified to resolve before it is written. Ingredient names are messy and an
unverified one silently captures nothing.

COMBINATION PRODUCTS. FDA names a combination shortage by concatenating its
ingredients ("AMPICILLIN SODIUM SULBACTAM SODIUM"), which matches no single
`active_ingredients.name` and resolves to nothing. Rather than dropping them,
each is retried against the sub-phrases of its name and represented by the
one that resolves to the FEWEST products — the most specific ingredient, so
SULBACTAM SODIUM rather than AMPICILLIN.

`.exact` is the GATE, substring is the QUERY, and the distinction matters
both ways:

  - A substring match rewards meaningless fragments. "Fewest products" picked
    AMINO out of AMINO ACID and MONOHYDRATE out of DEXTROSE MONOHYDRATE,
    because rare fragments match few things. So a sub-phrase is only accepted
    if `.exact` says it is genuinely an ingredient name.
  - But `.exact` alone over-rejects. CEFOTAXIME is not an exact ingredient
    name — the ingredient is CEFOTAXIME SODIUM — so exact-only dropped the
    one drug in this repo with 100% supplier attrition. A full name that
    matches loosely is therefore kept as-is; only *fragments* need the gate.

On real ingredient names the two agree exactly (ATROPINE SULFATE: 71 either
way), so querying loosely costs nothing.

It is still a proxy for a combination: SULBACTAM SODIUM counts every product
whose ingredient is sulbactam sodium, which is nearly but not exactly the
ampicillin combination. A supplier-base trend for a closely related product
set, not an exact count for the combination itself.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wss.cohort import CohortCriteria, select_vintage, write_vintage  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Dosage-form words FDA appends to a shortage record's generic_name. Drugs@FDA
# keys on the ingredient alone, so these have to come off or the name resolves
# to nothing — 276 of 404 candidates were lost to exactly this.
FORM_WORDS = re.compile(
    r"\b(injection|injectable|tablet|tablets|capsule|capsules|solution|"
    r"suspension|ointment|cream|gel|powder|syrup|kit|patch|lotion|spray|"
    r"aerosol|inhalation|ophthalmic|otic|topical|oral|intravenous|"
    r"intramuscular|subcutaneous|film|coated|delayed|extended|release|"
    r"concentrate|emulsion|lyophilized|for|and|prefilled|syringe|vial)\b",
    re.I)
UA = "wss-drug-scarcity cohort selection (+https://github.com/neldivad/wss-drug-scarcity)"


def api(url: str, params: list[tuple[str, str]]) -> dict:
    cmd = ["curl", "-s", "--max-time", "60", "-4", "-G", url, "-H", f"User-Agent: {UA}"]
    for key, value in params:
        cmd += ["--data-urlencode", f"{key}={value}"]
    out = subprocess.run(cmd, capture_output=True)
    try:
        return json.loads(out.stdout)
    except Exception:
        return {"error": {"code": "PARSE"}}


def marketed_injectable_generics() -> dict[str, int]:
    """generic_name -> currently marketed ANDA injectable products."""
    d = api("https://api.fda.gov/drug/ndc.json", [
        ("search", 'dosage_form:"INJECTION" AND marketing_category:"ANDA"'),
        ("count", "generic_name.exact"), ("limit", "1000")])
    return {r["term"].strip().upper(): r["count"] for r in d.get("results", [])}


def shortage_first_listed() -> dict[str, str]:
    """UPPERCASE ingredient -> earliest FDA listing date, from OUR derived table.

    Read from the repo's own observations, not from the live feed: the cohort
    must be reproducible from committed data.
    """
    rows = []
    for part in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with part.open(encoding="utf-8", newline="") as fh:
            rows.extend(csv.DictReader(fh))
    first: dict[str, str] = {}
    for r in rows:
        if r["metric"] != "first_listed" or r["source_id"] != "fda.shortages.current":
            continue
        drug = r["entity_id"].split("/", 1)[0].replace("drug:", "").replace("-", " ")
        value = str(r["value"])
        iso = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
        key = ingredient_of(drug)
        if not key:
            continue
        first[key] = min(first.get(key, iso), iso)
    return first


def ingredient_of(name: str) -> str:
    """Strip dosage-form words down to the ingredient Drugs@FDA keys on."""
    s = FORM_WORDS.sub(" ", name.replace(",", " "))
    return re.sub(r"\s+", " ", s).strip().upper()


def product_count(ingredient: str, exact: bool = False) -> int | None:
    """Total products for an ingredient, or None if the name resolves to nothing.

    `exact=True` asks whether the string IS an ingredient name, which is how
    fragments like MONOHYDRATE are rejected.
    """
    field = "products.active_ingredients.name"
    if exact:
        field += ".exact"
    d = api("https://api.fda.gov/drug/drugsfda.json", [
        ("search", f'{field}:"{ingredient}"'),
        ("count", "products.marketing_status")])
    results = d.get("results")
    if not results:
        return None
    return sum(int(r.get("count", 0)) for r in results)


def sub_phrases(name: str) -> list[str]:
    """Contiguous word runs, longest first — candidate ingredients in a combo."""
    words = name.split()
    if len(words) < 2:
        return []
    out = []
    for size in range(len(words) - 1, 0, -1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start:start + size])
            if phrase != name:
                out.append(phrase)
    return out


def resolve_ingredient(name: str) -> tuple[str, int] | None:
    """The queryable ingredient for a molecule, and its product count.

    The full name first, loosely — CEFOTAXIME finds cefotaxime sodium, and a
    full name cannot be a fragment. Failing that, the sub-phrase that is a
    real ingredient (`.exact`) and resolves to the fewest products: the most
    specific ingredient in a combination, and the closest available proxy for
    the combination itself.
    """
    total = product_count(name)
    if total is not None:
        return name, total
    best: tuple[str, int] | None = None
    for phrase in sub_phrases(name):
        if len(phrase) < 5:
            continue
        if product_count(phrase, exact=True) is None:
            continue  # a fragment, not an ingredient name
        count = product_count(phrase)
        if count is not None and (best is None or count < best[1]):
            best = (phrase, count)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selected-at", required=True, help="ISO date to freeze under")
    ap.add_argument("--top-n", type=int, default=300)
    ap.add_argument("--floor", type=float, default=3)
    ap.add_argument("--entrant-since", default="2010-01-01")
    args = ap.parse_args()

    marketed = marketed_injectable_generics()
    shortages = shortage_first_listed()
    print(f"  injectable ANDA generics : {len(marketed)}", file=sys.stderr)
    print(f"  molecules seen in shortage: {len(shortages)}", file=sys.stderr)

    candidates = []
    marketed = {ingredient_of(k): v for k, v in marketed.items() if ingredient_of(k)}
    for name in sorted(set(marketed) | set(shortages)):
        candidates.append({
            "id": name,
            "products_marketed": marketed.get(name),
            "first_listed": shortages.get(name, ""),
        })

    criteria = CohortCriteria(
        metric_key="products_marketed", created_key="first_listed",
        established_top_n=args.top_n, established_floor=args.floor,
        new_entrant_since=args.entrant_since, id_key="id")
    vintage = select_vintage(candidates, criteria, selected_at=args.selected_at)
    print(f"  selected before verification: {len(vintage.members)}", file=sys.stderr)

    # Resolve every ingredient string to something Drugs@FDA answers for. An
    # unverified name captures nothing and would sit in the registry as a
    # permanently failing endpoint.
    with ThreadPoolExecutor(max_workers=4) as ex:
        resolved = list(ex.map(lambda m: resolve_ingredient(m.entity_id),
                               vintage.members))
    dropped, proxied, kept = [], [], []
    for member, result in zip(vintage.members, resolved):
        if result is None:
            dropped.append(member.entity_id)
            continue
        ingredient, _ = result
        if ingredient != member.entity_id:
            proxied.append((member.entity_id, ingredient))
            member.entity_id = ingredient
        kept.append(member)
    # A proxy can collide with a molecule already selected on its own name.
    seen: dict[str, object] = {}
    for member in kept:
        if member.entity_id in seen:
            for path in member.paths:
                if path not in seen[member.entity_id].paths:
                    seen[member.entity_id].paths.append(path)
            continue
        seen[member.entity_id] = member
    vintage.members = sorted(seen.values(), key=lambda m: m.entity_id)
    print(f"  resolved in Drugs@FDA      : {len(vintage.members)} "
          f"({len(proxied)} via a combination proxy, {len(dropped)} dropped)",
          file=sys.stderr)

    path = write_vintage(REPO / "cohorts" / "injectable-generics", vintage)
    print(f"wrote {path.relative_to(REPO)} — {len(vintage.members)} members")
    if proxied:
        print(f"\ncombinations represented by their most specific ingredient "
              f"({len(proxied)}) — a proxy, see the module docstring:")
        for original, ingredient in proxied[:20]:
            print(f"  {original[:56]:<58} -> {ingredient}")
    if dropped:
        print(f"\nstill unresolved ({len(dropped)}), not captured:")
        for name in dropped[:20]:
            print(f"  {name}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

Every chart answers a numbered question from the README, or says plainly that
it cannot yet:

  fragility-benchmark.svg   Q8  injectables against their share of the market
  time-on-list.svg          Q1  how long current shortages have been listed
  supply-concentration.svg  Q7  packages per drug — who has one supplier left
  import-bans.svg           Q6  DWPE membership by country, denominator-free
  shortage-duration.svg     Q2  deliberately empty until captures accrue

Charts read the derived table, never the raw archive. Stdlib only,
deterministic: the same observations always produce the same bytes.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "examples" / "charts"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
HUE = "#2a78d6"
HUE_SOFT = "#9ec5f4"
WARN = "#c2410c"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Q8's denominator. NOT in the derived table because it describes every
# marketed drug, not just short ones: openFDA /drug/ndc.json count by
# dosage_form, 2026-09-02 — 9,883 injectable of 130,081 products.
MARKET_INJECTABLE_SHARE = 0.076


def rows() -> list[dict]:
    out = []
    for part in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with part.open(encoding="utf-8", newline="") as fh:
            out.extend(csv.DictReader(fh))
    return out


def state(obs: list[dict], source: str, metric: str) -> dict[str, str]:
    """Latest value per entity for one metric — the current-state query.

    NOT `observed_at == max(observed_at)`. A paged source stamps each endpoint
    with its own fetch time, so a single global max silently keeps only the
    last page. Taking the newest row per entity is correct for both paged and
    single-endpoint sources.
    """
    best: dict[str, tuple[str, str]] = {}
    for r in obs:
        if r["source_id"] != source or r["metric"] != metric:
            continue
        prev = best.get(r["entity_id"])
        if prev is None or r["observed_at"] > prev[0]:
            best[r["entity_id"]] = (r["observed_at"], r["value"])
    return {k: v for k, (_, v) in best.items()}


def last_seen(obs: list[dict], source: str) -> str:
    stamps = [r["observed_at"] for r in obs if r["source_id"] == source]
    return max(stamps) if stamps else ""


def svg_text(x, y, text, *, size, fill, anchor="start", weight="normal",
             tabular=False) -> str:
    style = "font-variant-numeric: tabular-nums;" if tabular else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family=\'{FONT}\' '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" style="{style}">{escape(text)}</text>')


def bar(x, y, w, h, colour=HUE, r=4) -> str:
    r = min(r, max(w / 2, 0.1), h / 2)
    return (f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} q{r},0 {r},{r} '
            f'v{h - 2 * r:.1f} q0,{r} -{r},{r} h-{w - r:.1f} z" fill="{colour}"/>')


def wrap(width, height, title, desc, body) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{escape(title)}">\n<title>{escape(title)}</title>\n'
            f"<desc>{escape(desc)}</desc>\n"
            f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n'
            f"{body}\n</svg>\n")


def ranked_bars(data, out: Path, *, title, subtitle, caption, desc,
                highlight=0, unit="") -> str:
    width, left, right, top = 900.0, 230.0, 96.0, 74.0
    bar_h, gap = 14.0, 6.0
    height = top + len(data) * (bar_h + gap) + 34
    vmax = max(v for _, v in data)
    span = width - left - right

    body = [svg_text(24, 30, title, size=16, fill=INK, weight="600"),
            svg_text(24, 50, subtitle, size=12, fill=INK2)]
    step = 50 if vmax > 120 else 10 if vmax > 25 else 5
    tick = 0
    while tick <= vmax:
        gx = left + tick / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" '
                    f'y2="{height - 30}" stroke="{GRID}" stroke-width="1"/>')
        body.append(svg_text(gx, height - 16, str(tick), size=10, fill=MUTED,
                             anchor="middle", tabular=True))
        tick += step
    body.append(f'<line x1="{left}" y1="{top - 8}" x2="{left}" '
                f'y2="{height - 30}" stroke="{BASELINE}" stroke-width="1"/>')

    for i, (label, value) in enumerate(data):
        y = top + i * (bar_h + gap)
        w = max(1.5, value / vmax * span)
        colour = HUE if (not highlight or i < highlight) else HUE_SOFT
        body.append(bar(left, y, w, bar_h, colour))
        name = label if len(label) <= 38 else label[:37].rstrip(" (") + "…"
        body.append(svg_text(left - 10, y + bar_h - 3, name, size=11,
                             fill=INK2, anchor="end"))
        body.append(svg_text(left + w + 7, y + bar_h - 3, f"{value:,}{unit}",
                             size=11, fill=INK, weight="600", tabular=True))

    body.append(svg_text(24, height - 4, caption, size=10, fill=MUTED))
    out.write_text(wrap(width, height, title, desc, "\n".join(body)),
                   encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(data)} bars"


def q8_fragility(obs) -> str:
    """Injectables: share of the market against share of shortages."""
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    inj = {e: v for e, v in state(obs, src, "is_injectable").items()
           if e in current}
    share = sum(int(v) for v in inj.values()) / len(inj)

    width, height, left, top = 900, 300, 230, 74
    span = width - left - 96
    body = [svg_text(24, 30, "Q8 — injectables are 9x over-represented in shortages",
                     size=16, fill=INK, weight="600"),
            svg_text(24, 50, "share of products that are injectable, market against "
                     "shortage list", size=12, fill=INK2)]
    for i, (label, value, colour) in enumerate([
            ("all marketed drug products", MARKET_INJECTABLE_SHARE, HUE_SOFT),
            ("drugs currently in shortage", share, WARN)]):
        y = top + 30 + i * 64
        w = max(2.0, value * span)
        body.append(bar(left, y, w, 30, colour))
        body.append(svg_text(left - 10, y + 20, label, size=12, fill=INK2,
                             anchor="end"))
        body.append(svg_text(left + w + 8, y + 20, f"{value:.1%}", size=13,
                             fill=INK, weight="600", tabular=True))
    body.append(f'<line x1="{left}" y1="{top + 20}" x2="{left}" y2="{top + 168}" '
                f'stroke="{BASELINE}" stroke-width="1"/>')
    body.append(svg_text(24, height - 46,
                         f"enrichment: {share / MARKET_INJECTABLE_SHARE:.1f}x",
                         size=13, fill=INK, weight="600"))
    body.append(svg_text(24, height - 26,
                         "Market denominator: openFDA /drug/ndc.json by dosage_form, "
                         "9,883 injectable of 130,081 products (2026-09-02).",
                         size=10, fill=MUTED))
    body.append(svg_text(24, height - 10,
                         "Shortage share is computed from this repo's published table; "
                         "the denominator is not, and is stated above.",
                         size=10, fill=MUTED))
    out = OUT_DIR / "fragility-benchmark.svg"
    out.write_text(wrap(width, height, "Injectable fragility against market share",
                        "Two bars comparing the injectable share of all marketed "
                        "drugs with the injectable share of drugs in shortage.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {share:.1%} vs {MARKET_INJECTABLE_SHARE:.1%}"


def q1_time_on_list(obs) -> str:
    """How long has each current shortage been on FDA's list?"""
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    year = int(last_seen(obs, src)[:4])
    first: dict[str, int] = {}
    for entity, value in state(obs, src, "first_listed").items():
        if entity not in current:
            continue
        drug = entity.split("/", 1)[0]
        y = int(value) // 10000
        first[drug] = min(first.get(drug, y), y)

    buckets = [("10+ years", 10, 99), ("5-10 years", 5, 10),
               ("2-5 years", 2, 5), ("1-2 years", 1, 2), ("under a year", 0, 1)]
    data = []
    for label, lo, hi in buckets:
        data.append((label, sum(1 for y in first.values()
                                if lo <= year - y < hi)))
    return ranked_bars(
        data, OUT_DIR / "time-on-list.svg",
        title="Q1 — how long current shortages have already lasted",
        subtitle=f"distinct generic drugs in shortage, by years since FDA first "
                 f"listed them ({len(first)} drugs)",
        caption="Time ON FDA'S LIST, not time unavailable to patients. Ages are "
                "FDA's own posting dates; this repo cannot yet measure a shortage "
                "that ENDED, which is Q2.",
        desc="Bar chart of how many drugs in shortage fall into each duration band.",
        highlight=2, unit=" drugs")


def q7_concentration(obs) -> str:
    """Packages still listed per drug — one is a single point of failure."""
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    per = defaultdict(int)
    for entity in current:
        per[entity.split("/", 1)[0]] += 1
    dist = defaultdict(int)
    for n in per.values():
        key = "1 package" if n == 1 else "2" if n == 2 else \
              "3-5" if n <= 5 else "6-10" if n <= 10 else "11+"
        dist[key] += 1
    order = ["1 package", "2", "3-5", "6-10", "11+"]
    data = [(k, dist[k]) for k in order if dist[k]]
    return ranked_bars(
        data, OUT_DIR / "supply-concentration.svg",
        title="Q7 — how many packages of each shorted drug are still listed",
        subtitle=f"{len(per)} drugs currently in shortage, by distinct package "
                 f"NDCs on the list",
        caption="Counts a field rather than resolving a company, so acquisitions "
                "and renames cannot distort it (Q4). A drug at one package is not "
                "proof of one supplier — unlisted packages are not visible here.",
        desc="Distribution of how many package NDCs each shorted drug still has.",
        highlight=1, unit=" drugs")


def q6_import_bans(obs) -> str:
    src = "fda.importalert.66-40"
    per = defaultdict(int)
    for entity in state(obs, src, "listed"):
        per[entity.split("/", 1)[0].split(":", 1)[1]] += 1
    data = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))[:12]
    data = [(k.replace("-", " "), v) for k, v in data]
    return ranked_bars(
        data, OUT_DIR / "import-bans.svg",
        title="Q6 — firms barred from shipping drugs to the US (Import Alert 66-40)",
        subtitle=f"{sum(per.values())} manufacturing sites on the GMP-failure "
                 f"list, by country",
        caption="RAW COUNTS WITH NO DENOMINATOR — see Q12. FDA publishes no "
                "fetchable list of registered sites per country, so these cannot "
                "be turned into rates. 'unknown' is the parser failing to read a "
                "free-text address, not a hidden country.",
        desc="Bar chart of how many firms from each country appear on FDA Import "
             "Alert 66-40.",
        highlight=2, unit=" firms")


def q2_placeholder(obs) -> str:
    """The founding question, deliberately empty until captures accrue."""
    src = "fda.shortages.current"
    captures = len({r["observed_at"] for r in obs if r["source_id"] == src})
    width, height = 900, 260
    body = [svg_text(24, 30, "Q2 — shortages that ended, and how long they took",
                     size=16, fill=INK, weight="600"),
            svg_text(24, 50, "deliberately empty", size=12, fill=INK2)]
    body.append(f'<rect x="24" y="74" width="{width - 48}" height="128" rx="6" '
                f'fill="none" stroke="{GRID}" stroke-width="1" '
                f'stroke-dasharray="5 4"/>')
    body.append(svg_text(width / 2, 128,
                         f"{captures} capture(s). No shortage has begun and ended "
                         "inside this record yet.",
                         size=13, fill=INK2, anchor="middle"))
    body.append(svg_text(width / 2, 152,
                         "FDA retains 7 resolved records out of 1,623. Nothing "
                         "can import this history — it was deleted.",
                         size=12, fill=MUTED, anchor="middle"))
    body.append(svg_text(width / 2, 176,
                         "The series starts the week capture started, and this "
                         "chart fills itself in.",
                         size=12, fill=MUTED, anchor="middle"))
    body.append(svg_text(24, height - 12,
                         "A longitudinal repo should say so on day one rather "
                         "than ship an empty axis.", size=10, fill=MUTED))
    out = OUT_DIR / "shortage-duration.svg"
    out.write_text(wrap(width, height, "Shortage duration — not yet answerable",
                        "Placeholder explaining that resolved-shortage durations "
                        "require accumulated captures.", "\n".join(body)),
                   encoding="utf-8")
    return f"{out.relative_to(REPO)} — placeholder, {captures} capture(s)"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    obs = rows()
    if not obs:
        raise SystemExit("no observations — run `wss derive` first")
    for line in (q8_fragility(obs), q1_time_on_list(obs), q7_concentration(obs),
                 q6_import_bans(obs), q2_placeholder(obs)):
        print(line)


if __name__ == "__main__":
    main()

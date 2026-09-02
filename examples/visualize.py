#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

The test every figure here has to pass: **after reading it, can someone act
without running another query?** A count of drugs fails that test — it tells
you a number and sends you back for the names. So each figure names the
drugs, gives their therapeutic class, and puts the decision in the subtitle.

  whats-short.svg        Q1  which drugs, how long, what class — the stockpile list
  single-supplier.svg    Q7  drugs down to one listed package — the watchlist
  enforcement-year.svg   Q6  GMP import bans by year and origin — is the base shrinking
  shortage-duration.svg  Q2  deliberately empty until captures accrue

Charts read the derived table, never the raw archive. Stdlib only,
deterministic: the same observations always produce the same bytes.

Palette is the dataviz reference instance, categorical slots in fixed order,
validated (scripts/validate_palette.js): all checks pass with a contrast WARN
on three slots, which is why every mark carries a visible text label.
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
DEEMPH = "#d5d4cc"
# Categorical slots, fixed order, never cycled. A 6th class folds into "other".
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
OTHER = "#8a8880"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Q1's context number. NOT in the derived table: it describes every marketed
# drug, not only short ones. openFDA /drug/ndc.json by dosage_form, 2026-09-02
# — 9,883 injectable of 130,081 products.
MARKET_INJECTABLE_SHARE = 0.076


def rows() -> list[dict]:
    out = []
    for part in sorted((REPO / "derived" / "observations").glob("*.csv")):
        with part.open(encoding="utf-8", newline="") as fh:
            out.extend(csv.DictReader(fh))
    return out


def state(obs, source: str, metric: str) -> dict[str, str]:
    """Latest value per entity for one metric — the current-state query.

    NOT `observed_at == max(observed_at)`. A paged source stamps each endpoint
    with its own fetch time, so a single global max silently keeps only the
    last page.
    """
    best: dict[str, tuple[str, str]] = {}
    for r in obs:
        if r["source_id"] != source or r["metric"] != metric:
            continue
        prev = best.get(r["entity_id"])
        if prev is None or r["observed_at"] > prev[0]:
            best[r["entity_id"]] = (r["observed_at"], r["value"])
    return {k: v for k, (_, v) in best.items()}


def last_seen(obs, source: str) -> str:
    stamps = [r["observed_at"] for r in obs if r["source_id"] == source]
    return max(stamps) if stamps else ""


def pretty(slug: str) -> str:
    return slug.replace("drug:", "").replace("category:", "").replace("-", " ")


def txt(x, y, s, *, size, fill, anchor="start", weight="normal", tab=False):
    style = "font-variant-numeric: tabular-nums;" if tab else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family=\'{FONT}\' '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" style="{style}">{escape(s)}</text>')


def para(x, y, text, *, size, fill, chars, leading=17.0):
    """Wrap a long line. SVG has no text flow, so overflow is silent — this is
    the only thing standing between a caption and the right edge of the page."""
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if len(trial) > chars and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    out = [txt(x, y + i * leading, line, size=size, fill=fill)
           for i, line in enumerate(lines)]
    return out, len(lines) * leading


def bar(x, y, w, h, colour, r=4):
    r = min(r, max(w / 2, 0.1), h / 2)
    return (f'<path d="M{x:.1f},{y:.1f} h{w - r:.1f} q{r},0 {r},{r} '
            f'v{h - 2 * r:.1f} q0,{r} -{r},{r} h-{w - r:.1f} z" fill="{colour}"/>')


def wrap(w, h, title, desc, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">\n'
            f"<title>{escape(title)}</title>\n<desc>{escape(desc)}</desc>\n"
            f'<rect width="{w}" height="{h}" fill="{SURFACE}"/>\n{body}\n</svg>\n')


def legend(items, x, y):
    out, cx = [], x
    for label, colour in items:
        out.append(f'<rect x="{cx:.1f}" y="{y - 9:.1f}" width="10" height="10" '
                   f'rx="2" fill="{colour}"/>')
        out.append(txt(cx + 15, y, label, size=11, fill=INK2))
        cx += 15 + len(label) * 6.3 + 16
    return out


def shortage_facts(obs):
    """Per-drug: years listed, classes, packages — everything the charts need."""
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    year_now = int(last_seen(obs, src)[:4])

    first, packages = {}, defaultdict(int)
    for entity in current:
        packages[entity.split("/", 1)[0]] += 1
    for entity, value in state(obs, src, "first_listed").items():
        if entity in current:
            drug = entity.split("/", 1)[0]
            y = int(value) // 10000
            first[drug] = min(first.get(drug, y), y)

    classes = defaultdict(list)
    for entity in state(obs, src, "in_category"):
        drug, category = entity.split("/", 1)
        classes[drug].append(pretty(category))
    for v in classes.values():
        v.sort()

    inj = {e: v for e, v in state(obs, src, "is_injectable").items()
           if e in current}
    return {"first": first, "packages": packages, "classes": classes,
            "year": year_now, "current": current,
            "inj_share": sum(int(v) for v in inj.values()) / max(1, len(inj))}


def q1_whats_short(obs) -> str:
    """Named drugs, ranked by how long they have been short, class-coloured."""
    f = shortage_facts(obs)
    ranked = sorted(f["first"].items(), key=lambda kv: (kv[1], kv[0]))[:18]

    # Colour by primary class, but only the classes actually on this chart.
    primary = {d: (f["classes"].get(d) or ["unclassified"])[0] for d, _ in ranked}
    counts = defaultdict(int)
    for c in primary.values():
        counts[c] += 1
    top = [c for c, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
    colour_of = {c: SLOTS[i] for i, c in enumerate(top)}

    width, left, right = 980.0, 300.0, 150.0
    row_h, gap = 15.0, 7.0
    raw_max = max(f["year"] - y for _, y in ranked)
    vmax = raw_max + (-raw_max % 5)   # clean ceiling; bars must not pass the axis
    span = width - left - right

    body = [txt(24, 32, "Q1 — what is short, for how long, and in what class",
                size=17, fill=INK, weight="600")]
    lead, dy = para(24, 54, "The 18 longest-running US drug shortages still "
                    "unresolved. Bar length is years on FDA's list, colour is "
                    "the drug's primary therapeutic class. Decision this "
                    "supports: what a hospital or wholesaler should hold buffer "
                    "stock of — every drug here has been short at least eight "
                    "years, so none is a transient disruption.",
                    size=12, fill=INK2, chars=118)
    body += lead

    # Vertical layout flows from the measured text height. Fixed offsets are
    # how a caption ends up sitting on top of a legend.
    legend_y = 54 + dy + 10
    top_y = legend_y + 26
    plot_bottom = top_y + len(ranked) * (row_h + gap)
    axis_y = plot_bottom + 18
    height = axis_y + 66

    body += legend([(c, colour_of[c]) for c in top] +
                   ([("other", OTHER)] if len(counts) > len(top) else []),
                   24, legend_y)

    tick = 0
    while tick <= vmax:
        gx = left + tick / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top_y - 10}" x2="{gx:.1f}" '
                    f'y2="{plot_bottom + 4}" stroke="{GRID}" stroke-width="1"/>')
        body.append(txt(gx, axis_y, str(tick), size=10, fill=MUTED,
                        anchor="middle", tab=True))
        tick += 5
    body.append(txt(left + span / 2, axis_y + 18, "years on FDA's shortage list",
                    size=11, fill=MUTED, anchor="middle"))
    body.append(f'<line x1="{left}" y1="{top_y - 10}" x2="{left}" '
                f'y2="{plot_bottom + 4}" stroke="{BASELINE}" stroke-width="1"/>')

    for i, (drug, y0) in enumerate(ranked):
        y = top_y + i * (row_h + gap)
        years = f["year"] - y0
        w = max(2.0, years / vmax * span)
        colour = colour_of.get(primary[drug], OTHER)
        body.append(bar(left, y, w, row_h, colour))
        name = pretty(drug)
        name = name if len(name) <= 44 else name[:43] + "…"
        body.append(txt(left - 10, y + row_h - 3, name, size=11, fill=INK2,
                        anchor="end"))
        # Direct label on every bar: the contrast WARN obliges visible values.
        body.append(txt(left + w + 7, y + row_h - 3, f"{years} yr  since {y0}",
                        size=11, fill=INK, weight="600", tab=True))

    foot, _ = para(24, height - 26,
                   "Time ON FDA'S LIST, not time unavailable to patients. "
                   f"{f['inj_share']:.0%} of drugs in shortage are injectables, "
                   f"against {MARKET_INJECTABLE_SHARE:.1%} of all marketed "
                   "products — sterile injectables are where scarcity lives.",
                   size=10, fill=MUTED, chars=150, leading=14)
    body += foot

    out = OUT_DIR / "whats-short.svg"
    out.write_text(wrap(width, height, "Longest-running US drug shortages",
                        "Horizontal bars naming the 18 longest-running US drug "
                        "shortages, coloured by therapeutic class.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(ranked)} named drugs"


def q7_single_supplier(obs) -> str:
    """The watchlist: drugs down to one listed package. A table, not a chart."""
    f = shortage_facts(obs)
    solo = sorted(d for d, n in f["packages"].items() if n == 1)

    width = 980.0
    row_h = 26.0
    height = 150 + len(solo) * row_h + 54
    body = [
        txt(24, 32, "Q7 — drugs in shortage with a single package still listed",
            size=17, fill=INK, weight="600"),
        txt(24, 54, f"{len(solo)} of {len(f['packages'])} drugs currently in "
            "shortage have exactly one package NDC on FDA's list.",
            size=12, fill=INK2),
        *para(24, 74, "Decision this supports: these are the drugs where one "
              "more delisting means none — the substitution plans worth writing "
              "before they are needed, not after.",
              size=12, fill=INK2, chars=118)[0],
        txt(24, 118, "drug", size=10, fill=MUTED, weight="600"),
        txt(430, 118, "therapeutic class", size=10, fill=MUTED, weight="600"),
        txt(width - 24, 118, "years short", size=10, fill=MUTED, weight="600",
            anchor="end"),
        f'<line x1="24" y1="126" x2="{width - 24}" y2="126" '
        f'stroke="{BASELINE}" stroke-width="1"/>',
    ]
    for i, drug in enumerate(solo):
        y = 150 + i * row_h
        if i % 2 == 0:
            body.append(f'<rect x="24" y="{y - 16:.1f}" width="{width - 48}" '
                        f'height="{row_h - 2}" fill="#f4f3ee"/>')
        klass = ", ".join(f["classes"].get(drug, ["unclassified"]))
        klass = klass if len(klass) <= 44 else klass[:43] + "…"
        years = f["year"] - f["first"].get(drug, f["year"])
        body.append(txt(30, y, pretty(drug), size=12, fill=INK))
        body.append(txt(430, y, klass, size=12, fill=INK2))
        body.append(txt(width - 30, y, f"{years}", size=12, fill=INK,
                        anchor="end", weight="600", tab=True))

    body.append(txt(24, height - 14,
                    "A single listed package is not proof of a single "
                    "manufacturer — packages not on the shortage list are "
                    "invisible here. It is a shortlist to check, not a verdict.",
                    size=10, fill=MUTED))
    out = OUT_DIR / "single-supplier.svg"
    out.write_text(wrap(width, height, "Drugs down to one listed package",
                        "Table naming the drugs in shortage that have only one "
                        "package NDC listed, with therapeutic class.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(solo)} drugs named"


def q6_enforcement(obs) -> str:
    """GMP import bans by year of first listing, split by origin."""
    src = "fda.importalert.66-40"
    first = state(obs, src, "first_listed")
    per_year = defaultdict(lambda: defaultdict(int))
    for entity, value in first.items():
        country = entity.split("/", 1)[0].split(":", 1)[1]
        key = country if country in ("china", "india") else "rest of world"
        per_year[int(value) // 10000][key] += 1
    years = sorted(per_year)
    series = [("china", SLOTS[0]), ("india", SLOTS[1]),
              ("rest of world", DEEMPH)]

    width, left, right, top_y = 980.0, 60.0, 30.0, 152.0
    plot_h = 230.0
    height = top_y + plot_h + 104
    vmax = max(sum(per_year[y].values()) for y in years)
    step = (width - left - right) / len(years)
    col_w = min(30.0, step - 8)

    total = sum(sum(v.values()) for v in per_year.values())
    cn = sum(per_year[y]["china"] for y in years)
    inn = sum(per_year[y]["india"] for y in years)
    body = [txt(24, 32, "Q6 — when firms were barred from shipping drugs to "
                "the US", size=17, fill=INK, weight="600")]
    lead, dy = para(24, 54, f"All {total} manufacturing sites on Import Alert "
                    "66-40 (GMP failure), by the year FDA first listed them. "
                    "Decision this supports: whether the qualified-supplier base "
                    "is shrinking, and where. Bars are additions, not the "
                    "standing total — nothing here shows firms that got off the "
                    "list, because FDA keeps no record of that.",
                    size=12, fill=INK2, chars=118)
    body += lead
    body += legend([(f"China ({cn})", SLOTS[0]), (f"India ({inn})", SLOTS[1]),
                    (f"rest of world ({total - cn - inn})", DEEMPH)],
                   24, 54 + dy + 14)

    tick = 0
    while tick <= vmax:
        gy = top_y + plot_h - tick / vmax * plot_h
        body.append(f'<line x1="{left}" y1="{gy:.1f}" x2="{width - right}" '
                    f'y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        body.append(txt(left - 10, gy + 3, str(tick), size=10, fill=MUTED,
                        anchor="end", tab=True))
        tick += 10
    body.append(txt(24, top_y - 12, "firms first listed", size=11, fill=MUTED))

    for i, year in enumerate(years):
        x = left + i * step + (step - col_w) / 2
        y_cursor = top_y + plot_h
        for name, colour in series:
            n = per_year[year][name]
            if not n:
                continue
            h = n / vmax * plot_h
            # 2px surface gap between stacked segments
            body.append(bar(x, y_cursor - h, col_w, max(1.5, h - 2), colour, r=3))
            y_cursor -= h
        tot = sum(per_year[year].values())
        body.append(txt(x + col_w / 2, y_cursor - 6, str(tot), size=10,
                        fill=INK2, anchor="middle", tab=True))
        body.append(txt(x + col_w / 2, top_y + plot_h + 16, str(year)[2:],
                        size=10, fill=MUTED, anchor="middle", tab=True))
    body.append(f'<line x1="{left}" y1="{top_y + plot_h}" x2="{width - right}" '
                f'y2="{top_y + plot_h}" stroke="{BASELINE}" stroke-width="1"/>')

    foot, _ = para(24, height - 44,
                   "RAW COUNTS WITH NO DENOMINATOR. FDA publishes no fetchable "
                   "list of registered sites per country, so these cannot be "
                   "turned into rates — 'more Chinese firms banned' may only "
                   "mean 'more Chinese firms' (Q12). Country is parsed from a "
                   "free-text address; firms whose country cannot be read fall "
                   "into rest of world.", size=10, fill=MUTED, chars=140,
                   leading=14)
    body += foot
    out = OUT_DIR / "enforcement-year.svg"
    out.write_text(wrap(width, height, "GMP import bans by year and origin",
                        "Stacked columns of firms added to FDA Import Alert "
                        "66-40 each year, split China, India, rest of world.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(years)} years, {total} firms"


def q2_placeholder(obs) -> str:
    src = "fda.shortages.current"
    captures = len({r["observed_at"] for r in obs if r["source_id"] == src})
    width, height = 980, 250
    body = [
        txt(24, 32, "Q2 — shortages that ended, and how long they took",
            size=17, fill=INK, weight="600"),
        txt(24, 54, "Deliberately empty.", size=12, fill=INK2),
        f'<rect x="24" y="76" width="{width - 48}" height="120" rx="6" '
        f'fill="#f4f3ee"/>',
        txt(width / 2, 118, f"{captures} capture(s) so far. No shortage has "
            "begun and ended inside this record yet.", size=13, fill=INK2,
            anchor="middle"),
        txt(width / 2, 144, "FDA retains 7 resolved records out of 1,623, so no "
            "archive anywhere can backfill this.", size=12, fill=MUTED,
            anchor="middle"),
        txt(width / 2, 168, "The series starts the week capture started, and "
            "this figure fills itself in.", size=12, fill=MUTED, anchor="middle"),
        txt(24, height - 14, "A longitudinal repo should say so on day one "
            "rather than ship an empty axis.", size=10, fill=MUTED),
    ]
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
    for line in (q1_whats_short(obs), q7_single_supplier(obs),
                 q6_enforcement(obs), q2_placeholder(obs)):
        print(line)


if __name__ == "__main__":
    main()

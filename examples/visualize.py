#!/usr/bin/env python3
"""Render charts from derived/observations/*.csv as SVG.

    python examples/visualize.py

The test every figure here has to pass: **after reading it, can someone act
without running another query?** A count of drugs fails that test — it tells
you a number and sends you back for the names. So each figure names the
drugs, gives their therapeutic class, and puts the decision in the subtitle.

  whats-short.svg        Q1  which drugs, how long, what class — the stockpile list
  shortage-age.svg       Q1  age structure of the list: churn against a permanent core
  availability.svg       Q3  severity right now — which drugs have nothing available
  supplier-attrition.svg Q13 how many approved makers each shorted drug has left
  single-supplier.svg    Q7  drugs down to one listed package — the watchlist
  enforcement-year.svg   Q6  GMP import bans by year and origin — is the base shrinking
  shortage-duration.svg  Q2  deliberately empty until captures accrue
  supplier-exits.svg     Q14 deliberately empty until the cohort source is active

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
# One hue, two shades, for the before/after dumbbell. Validated as an ordinal
# ramp: monotone lightness, visible step gap, light end clears the surface
# (#9ec5f4 failed that last check at 1.74:1).
HUE = SLOTS[0]
HUE_SOFT = "#6ba3e6"
# Status palette, fixed and never themed. Availability IS a status — this is
# the legitimate use, not a series colour. warning/serious are sub-3:1 on a
# light surface by design, so every segment carries a visible label.
CRITICAL = "#d03b3b"
WARNING = "#fab219"
GOOD = "#0ca30c"
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


def capture_days(obs, source: str) -> int:
    """Distinct capture DAYS, not distinct observed_at.

    Each endpoint carries its own fetch time, so counting timestamps counts
    endpoints — a 275-endpoint source would report "438 captures" after two
    runs. The same paging trap as `state()`; it bites anywhere a capture is
    counted rather than looked up.
    """
    return len({r["observed_at"][:10] for r in obs
                if r["source_id"] == source})


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


def q1_age_structure(obs) -> str:
    """How old is the current shortage list — churn, or a permanent core?

    This is the population view that the named top-18 cannot show, and it
    carries the survivorship warning that applies to both: a shortage that
    ENDED is not in the feed, so this is the age of what is still open, never
    the age of all shortages.
    """
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    year_now = int(last_seen(obs, src)[:4])
    first: dict[str, int] = {}
    for entity, value in state(obs, src, "first_listed").items():
        if entity not in current:
            continue
        drug = entity.split("/", 1)[0]
        y = int(value) // 10000
        first[drug] = min(first.get(drug, y), y)

    bands = [("under 1 year", 0, 1), ("1-2 years", 1, 2), ("2-5 years", 2, 5),
             ("5-10 years", 5, 10), ("10 years or more", 10, 999)]
    data = [(label, sum(1 for y in first.values() if lo <= year_now - y < hi))
            for label, lo, hi in bands]
    total = sum(n for _, n in data)
    recent = data[0][1] + data[1][1]
    chronic = total - recent
    old = data[3][1] + data[4][1]

    width, left, right = 980.0, 230.0, 150.0
    row_h, gap = 26.0, 12.0
    body = [txt(24, 32, "Q1 — is the shortage list churn, or a permanent core?",
                size=17, fill=INK, weight="600")]
    lead, dy = para(24, 54, f"The {total} drugs in shortage today, by how long "
                    "each has been listed. Decision this supports: whether to "
                    "treat a new shortage as a passing disruption or as the "
                    "start of something permanent — the answer differs sharply "
                    "by which band it lands in.", size=12, fill=INK2, chars=118)
    body += lead
    top_y = 54 + dy + 22
    plot_bottom = top_y + len(data) * (row_h + gap)
    height = plot_bottom + 88
    vmax = max(n for _, n in data)
    span = width - left - right

    for i, (label, n) in enumerate(data):
        y = top_y + i * (row_h + gap)
        w = max(2.0, n / vmax * span)
        # Emphasis, not a value ramp: the old tail is the story, the rest is
        # context, and the categories are ordered so a ramp would double-encode.
        # Emphasis on the chronic bands, which are the finding. Ordered
        # categories, so a value ramp would double-encode bar length as hue.
        colour = SLOTS[0] if i >= 2 else DEEMPH
        body.append(bar(left, y, w, row_h, colour))
        body.append(txt(left - 12, y + row_h - 8, label, size=12, fill=INK2,
                        anchor="end"))
        body.append(txt(left + w + 10, y + row_h - 8,
                        f"{n} drugs   {n / total:.0%}", size=12, fill=INK,
                        weight="600", tab=True))
    body.append(f'<line x1="{left}" y1="{top_y - 8}" x2="{left}" '
                f'y2="{plot_bottom - gap + 4}" stroke="{BASELINE}" '
                f'stroke-width="1"/>')

    note, ndy = para(24, plot_bottom + 14,
                     f"This is not churn. {chronic} of the {total} drugs short "
                     f"today have been short more than two years and "
                     f"{old} more than five. Only {recent} arrived in the last "
                     "two years. A US drug shortage is a chronic condition, "
                     "not an incident.", size=12, fill=INK2, chars=118)
    body += note
    foot, _ = para(24, plot_bottom + 20 + ndy,
                   "SURVIVORSHIP: a shortage that ENDED left the feed, so this "
                   "is the age of what is still open and never the age of all "
                   "shortages. The recent bands are therefore overstated "
                   "relative to a true onset distribution. Fixing that is Q16, "
                   "and only accumulated capture fixes it. Tested and rejected: "
                   "month-of-year shows no seasonality once batch postings are "
                   "collapsed to one date per drug.",
                   size=10, fill=MUTED, chars=150, leading=14)
    body += foot
    out = OUT_DIR / "shortage-age.svg"
    out.write_text(wrap(width, height, "Age structure of the shortage list",
                        "Bar chart of how long each drug currently in shortage "
                        "has been listed, in duration bands.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {total} drugs, {recent / total:.0%} under two years"


def q3_availability(obs) -> str:
    """Severity, not duration: which drugs have no available package today.

    `availability` is the only severity signal FDA publishes, and it is the
    difference between a drug that is rationed and one that is simply gone.
    Every other figure here measures how LONG; this one measures how BAD.
    """
    src = "fda.shortages.current"
    current = {e for e, v in state(obs, src, "status_code").items() if v == "1"}
    avail = {e: int(v) for e, v in state(obs, src, "availability").items()
             if e in current}

    per: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for entity, value in avail.items():
        per[entity.split("/", 1)[0]][value] += 1
    rows = [(drug, counts) for drug, counts in per.items() if sum(counts) >= 3]
    rows.sort(key=lambda r: (-r[1][0] / sum(r[1]), -sum(r[1]), r[0]))
    rows = rows[:16]

    total_pk = sum(sum(c) for c in per.values())
    total_un = sum(c[0] for c in per.values())
    none_left = sum(1 for _, c in per.items() if c[1] + c[2] == 0)

    # Severity by dosage form: injectables are not merely over-represented in
    # shortage, they are also the worst affected once short.
    inj = state(obs, src, "is_injectable")
    form = {True: [0, 0], False: [0, 0]}
    for entity, value in avail.items():
        bucket = form[inj.get(entity) == "1"]
        bucket[0] += 1
        bucket[1] += 1 if value == 0 else 0

    # Severity by class: the class with the MOST packages is not the class
    # with the worst rate — exactly the denominator trap this repo warns about.
    cats = state(obs, src, "in_category")
    per_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    drug_cats: dict[str, list[str]] = defaultdict(list)
    for entity in cats:
        drug, category = entity.split("/", 1)
        drug_cats[drug].append(category.replace("category:", ""))
    for entity, value in avail.items():
        for category in drug_cats.get(entity.split("/", 1)[0], []):
            per_cat[category][0] += 1
            per_cat[category][1] += 1 if value == 0 else 0
    ranked_cats = sorted(((c, n, u) for c, (n, u) in per_cat.items() if n >= 20),
                         key=lambda r: -r[2] / r[1])
    worst_cat = ranked_cats[0] if ranked_cats else ("", 1, 0)
    biggest_cat = max(per_cat.items(), key=lambda kv: (kv[1][0], kv[0])) \
        if per_cat else ("", [1, 0])

    width, left, right = 980.0, 300.0, 190.0
    row_h, gap = 17.0, 8.0
    body = [txt(24, 32, "Q3 — which shortages are rationed, and which have "
                "nothing left", size=17, fill=INK, weight="600")]
    lead, dy = para(24, 54, "FDA reports availability per package. Decision "
                    "this supports: triage. A drug with limited supply needs "
                    "conservation; a drug with none needs a substitute today, "
                    "and the two are not the same problem.",
                    size=12, fill=INK2, chars=118)
    body += lead
    legend_y = 54 + dy + 10
    top_y = legend_y + 28
    plot_bottom = top_y + len(rows) * (row_h + gap)
    height = plot_bottom + 76
    span = width - left - right

    body += legend([("unavailable", CRITICAL), ("limited", WARNING),
                    ("available", GOOD)], 24, legend_y)

    for i, (drug, counts) in enumerate(rows):
        y = top_y + i * (row_h + gap)
        n = sum(counts)
        x = left
        for value, colour in ((0, CRITICAL), (1, WARNING), (2, GOOD)):
            if not counts[value]:
                continue
            w = counts[value] / n * span
            # 2px surface gap between stacked segments
            body.append(bar(x, y, max(1.5, w - 2), row_h, colour, r=3))
            x += w
        name = drug.replace("drug:", "").replace("-", " ")
        name = name if len(name) <= 40 else name[:39] + "…"
        body.append(txt(left - 10, y + row_h - 4, name, size=11, fill=INK2,
                        anchor="end"))
        body.append(txt(left + span + 12, y + row_h - 4,
                        f"{counts[0]} of {n} unavailable", size=11, fill=INK,
                        weight="600", tab=True))

    note, ndy = para(24, plot_bottom + 16,
                     f"{none_left} drugs in shortage have no available package "
                     f"at all, and {total_un} of {total_pk} listed packages are "
                     "unavailable. Injectables are "
                     f"{form[True][1] / form[True][0]:.0%} unavailable against "
                     f"{form[False][1] / form[False][0]:.0%} for other forms, so "
                     "they are not merely over-represented in shortage but worse "
                     f"affected once short. And {worst_cat[0]} is the worst class "
                     f"by rate ({worst_cat[2] / worst_cat[1]:.0%} of its packages "
                     f"unavailable) while {biggest_cat[0]} has the most packages "
                     "— severity and volume rank differently.",
                     size=12, fill=INK2, chars=118)
    body += note
    foot, _ = para(24, plot_bottom + 22 + ndy,
                   "Availability is self-reported by the manufacturer and "
                   "refers to that package, not to what a given hospital can "
                   "actually obtain. Drugs with fewer than three listed "
                   "packages are omitted here so a single package does not "
                   "read as 100%.", size=10, fill=MUTED, chars=150, leading=14)
    body += foot
    out = OUT_DIR / "availability.svg"
    out.write_text(wrap(width, height, "Availability of drugs in shortage",
                        "Stacked bars of unavailable, limited and available "
                        "packages for each drug currently in shortage.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(rows)} drugs, {none_left} with nothing available"


def q13_attrition(obs) -> str:
    """How much of each shorted drug's approved supply base is left.

    A dumbbell: before and after per item is exactly what this is — everyone
    ever approved to make it, against everyone still making it.
    """
    src = "fda.drugsfda.cohort-status"
    short = {e.split("/", 1)[0].replace("drug:", "")
             for e, v in state(obs, "fda.shortages.current", "status_code").items()
             if v == "1"}
    marketed = state(obs, src, "products_marketed")
    ever = state(obs, src, "products_ever")

    rows = []
    for entity, ever_value in ever.items():
        molecule = entity.replace("molecule:", "")
        if int(ever_value) < 10:
            continue
        if not any(drug.startswith(molecule) for drug in short):
            continue
        rows.append((molecule, int(marketed.get(entity, 0)), int(ever_value)))

    # "cefotaxime" and "cefotaxime-sodium" are the same supply base counted
    # twice; keep the shorter name when one is a prefix of the other and the
    # numbers agree.
    rows.sort(key=lambda r: (len(r[0]), r[0]))
    kept: list[tuple[str, int, int]] = []
    for row in rows:
        if any(row[0].startswith(k[0]) and (row[1], row[2]) == (k[1], k[2])
               for k in kept):
            continue
        kept.append(row)
    kept.sort(key=lambda r: (r[1] / r[2], r[0]))
    kept = kept[:16]

    width, left, right = 980.0, 300.0, 130.0
    row_h = 22.0
    body = [txt(24, 32, "Q13 — why doesn't someone else just make it?",
                size=17, fill=INK, weight="600")]
    lead, dy = para(24, 54, "Every product ever approved to make each drug, "
                    "against those still marketed. Decision this supports: "
                    "which shortages are a manufacturing problem and which are "
                    "an exit problem — a drug whose makers all left will not be "
                    "fixed by asking the survivors to try harder.",
                    size=12, fill=INK2, chars=118)
    body += lead
    legend_y = 54 + dy + 10
    top_y = legend_y + 30
    plot_bottom = top_y + len(kept) * row_h
    height = plot_bottom + 74
    vmax = max(r[2] for r in kept)
    span = width - left - right

    body += legend([("ever approved", HUE_SOFT), ("still marketed", HUE)],
                   24, legend_y)

    tick = 0
    step = 25 if vmax > 60 else 10
    while tick <= vmax:
        gx = left + tick / vmax * span
        body.append(f'<line x1="{gx:.1f}" y1="{top_y - 12}" x2="{gx:.1f}" '
                    f'y2="{plot_bottom}" stroke="{GRID}" stroke-width="1"/>')
        body.append(txt(gx, plot_bottom + 18, str(tick), size=10, fill=MUTED,
                        anchor="middle", tab=True))
        tick += step
    body.append(txt(left + span / 2, plot_bottom + 36, "approved products",
                    size=11, fill=MUTED, anchor="middle"))
    body.append(f'<line x1="{left}" y1="{top_y - 12}" x2="{left}" '
                f'y2="{plot_bottom}" stroke="{BASELINE}" stroke-width="1"/>')

    for i, (molecule, mk, ev) in enumerate(kept):
        y = top_y + i * row_h + row_h / 2 - 4
        x_ever = left + ev / vmax * span
        x_now = left + mk / vmax * span
        body.append(f'<line x1="{x_now:.1f}" y1="{y:.1f}" x2="{x_ever:.1f}" '
                    f'y2="{y:.1f}" stroke="{HUE_SOFT}" stroke-width="2"/>')
        body.append(f'<circle cx="{x_ever:.1f}" cy="{y:.1f}" r="5" '
                    f'fill="{HUE_SOFT}"/>')
        # 2px surface ring so the two marks stay distinct where they overlap
        body.append(f'<circle cx="{x_now:.1f}" cy="{y:.1f}" r="5" '
                    f'fill="{HUE}" stroke="{SURFACE}" stroke-width="2"/>')
        name = molecule.replace("-", " ")
        name = name if len(name) <= 40 else name[:39] + "…"
        body.append(txt(left - 10, y + 4, name, size=11, fill=INK2,
                        anchor="end"))
        body.append(txt(left + span + 14, y + 4, f"{mk} of {ev}", size=11,
                        fill=INK, weight="600", tab=True))

    foot, _ = para(24, height - 26,
                   "Counts PRODUCTS (a strength and form), not firms, so this "
                   "measures market exits rather than distinct companies — "
                   "which is the point: it is immune to renames and "
                   "acquisitions. Cefotaxime is at zero and has been short "
                   "since 2015.", size=10, fill=MUTED, chars=150, leading=14)
    body += foot
    out = OUT_DIR / "supplier-attrition.svg"
    out.write_text(wrap(width, height, "Approved makers left per shorted drug",
                        "Dumbbell chart comparing products ever approved with "
                        "products still marketed, for drugs in shortage.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — {len(kept)} molecules"


def q2_placeholder(obs) -> str:
    src = "fda.shortages.current"
    captures = capture_days(obs, src)
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


def q14_placeholder(obs) -> str:
    """Supplier-exit timing — needs the cohort source active."""
    src = "fda.drugsfda.cohort-status"
    captures = capture_days(obs, src)
    molecules = len({r["entity_id"] for r in obs if r["source_id"] == src})
    width, height = 980, 262
    body = [
        txt(24, 32, "Q14 — do suppliers leave before a shortage, or after it?",
            size=17, fill=INK, weight="600"),
        txt(24, 54, "Deliberately empty.", size=12, fill=INK2),
        f'<rect x="24" y="76" width="{width - 48}" height="132" rx="6" '
        f'fill="#f4f3ee"/>',
        txt(width / 2, 116, f"{molecules} cohort molecules have a baseline, "
            f"from {captures} day(s) of capture. A level, not yet a trend.",
            size=13, fill=INK2, anchor="middle"),
        txt(width / 2, 142, "Drugs@FDA gives each product's CURRENT marketing "
            "status and no discontinuation date — not in the API, and not in "
            "FDA's own bulk file.", size=12, fill=MUTED, anchor="middle"),
        txt(width / 2, 164, "Sampling it monthly is what turns an exit into a "
            "dated event. Nothing published can backfill it.", size=12,
            fill=MUTED, anchor="middle"),
        txt(width / 2, 186, "The source is written and paused; flipping "
            "status: active starts the series.", size=12, fill=MUTED,
            anchor="middle"),
        txt(24, height - 14, "Q13 shows how far attrition has already gone. "
            "This one asks when it happened, and only capture answers that.",
            size=10, fill=MUTED),
    ]
    out = OUT_DIR / "supplier-exits.svg"
    out.write_text(wrap(width, height, "Supplier exit timing — not yet answerable",
                        "Placeholder explaining that dating supplier exits "
                        "requires the cohort source to be active.",
                        "\n".join(body)), encoding="utf-8")
    return f"{out.relative_to(REPO)} — placeholder, {molecules} molecules"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    obs = rows()
    if not obs:
        raise SystemExit("no observations — run `wss derive` first")
    for line in (q1_whats_short(obs), q1_age_structure(obs),
                 q3_availability(obs), q13_attrition(obs),
                 q7_single_supplier(obs), q6_enforcement(obs),
                 q2_placeholder(obs), q14_placeholder(obs)):
        print(line)


if __name__ == "__main__":
    main()

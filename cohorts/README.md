# cohorts/

**Membership is chosen once, by hand, on stated criteria, and followed forever
— including the members that die.**

Re-selecting "the drugs short today" every quarter would silently delete every
shortage that resolved and turn this into a record of survivors. That is the
exact failure the repo exists to document, so it must not be the way the repo
picks its own sample.

## injectable-generics

The population Q14 needs: injectable generic molecules **whether or not they
are currently short**. A panel of only-short drugs can never answer "did
suppliers leave before the shortage" — by the time a molecule would qualify,
the exits already happened. The control group is the point.

**304 members** at the 2026-09-03 vintage, on two paths — top injectable ANDA
generics by marketed product count (the control group, mostly not short) and
any molecule FDA has listed as short since 2010 at any size (which keeps
tomorrow's shortage in the sample while it is still small).

`entity_id` is the UPPERCASE active-ingredient string used to query
Drugs@FDA, **verified to resolve before it is written**. An unverified name
would sit in the registry as a permanently failing endpoint that captures
nothing and never errors.

### Resolving the messy names

FDA names a combination shortage by concatenating its ingredients
(`AMPICILLIN SODIUM SULBACTAM SODIUM`), which matches no single
`active_ingredients.name`. 52 of 304 members are therefore represented by a
**proxy**: the most specific ingredient in the combination.

Getting this right took three passes, and the count alone never showed which
pass was correct — only reading the matched names did:

| rule | result | what was wrong |
| --- | --- | --- |
| substring only | 275 kept, 64 dropped | combinations silently lost, including one in the repo's own headline chart |
| substring + fewest products | 312 kept, 5 dropped | rewarded rare *fragments* — `AMINO ACID` → `AMINO`, `DEXTROSE MONOHYDRATE` → `MONOHYDRATE` |
| `.exact` only | 282 kept, 33 dropped | over-rejected: `CEFOTAXIME` is not an exact ingredient name (it is cefotaxime sodium), losing the one drug at 100% attrition |
| **`.exact` as gate, substring as query** | **304 kept, 12 dropped** | ✓ |

So: a full name is matched loosely, because a full name cannot be a fragment.
A *sub-phrase* is only accepted if `.exact` confirms it is genuinely an
ingredient name. On real ingredient names the two agree exactly
(`ATROPINE SULFATE`: 71 products either way).

**A proxy over-counts.** `SULBACTAM SODIUM` counts every product whose
ingredient is sulbactam sodium, which is nearly but not exactly the ampicillin
combination. Read those members as a supplier-base trend for a closely related
product set, not an exact count for the combination.

### The 12 still dropped

Mostly not drugs (`PERITONEAL DIALYSIS`, `AMINO ACID`), radiopharmaceuticals
(`NH3N13`, `FLUDEOXYGLUCOSE F18`) — and three misspellings in FDA's own
shortage feed: `IRINOTECAN HYDROCHLOIDE`, `METOROPROLOL TARTRATE`,
`NALXONE HYDROCHLORIDE`. They are left dropped rather than hand-corrected;
a typo that FDA fixes will resolve on its own at the next selection.

## Running a selection

```bash
python cohorts/select.py --selected-at 2026-12-01   # writes a new vintage
python cohorts/build_registry.py                    # regenerates the entry
git diff                                            # READ IT
```

Never on a cron. `write_vintage` refuses to overwrite an existing date, and
the effective cohort is the union of every vintage — once in, never out.

`registry/fda.drugsfda.cohort-status.yml` is **generated**. Edit the script or
the cohort, never the YAML.

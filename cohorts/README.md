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

| path | rule | members |
| --- | --- | --- |
| `established` | top 300 injectable ANDA generics by marketed product count, floor 3 | 84 |
| `new_entrant` | any molecule FDA has listed as short since 2010-01-01, **any size** | 153 |
| both | | 38 |

275 members at the 2026-09-03 vintage. The `new_entrant` path is what keeps
tomorrow's shortage in the sample while it is still small.

`entity_id` is the UPPERCASE active-ingredient string used to query
Drugs@FDA, **verified to resolve before it is written** — 64 candidates were
dropped at selection, almost all multi-ingredient combinations that have no
single `active_ingredients.name`. An unverified name would sit in the registry
as a permanently failing endpoint.

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

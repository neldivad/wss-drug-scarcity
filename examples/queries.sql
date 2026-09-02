-- wss-drug-scarcity — the query patterns that matter.
--
--   duckdb -c ".read examples/queries.sql"
--
-- Entity ids are composite, so every aggregate is a prefix GROUP BY:
--   drug:<generic>/ndc:<ndc11>       shortage feed, one row per package
--   drug:<generic>/category:<class>  therapeutic class membership
--   country:<country>/firm:<firm>    import alert membership
--   molecule:<ingredient>            Drugs@FDA cohort counts
--
-- METRICS
--   listed                 1 = on the list at this capture
--   status_code            0 Resolved, 1 Current, 2 To Be Discontinued
--   availability           0 Unavailable, 1 Limited, 2 Available
--   is_injectable          1 if the dosage form is an injection
--   in_category            1 = drug belongs to that therapeutic class
--   first_listed           YYYYMMDD, when FDA first posted it
--   last_update            YYYYMMDD, when FDA last touched it
--   product_entries        products covered by one banned firm
--   firms_listed           total firms on an import alert
--   products_marketed      still Prescription or OTC in Drugs@FDA
--   products_discontinued  marketing_status Discontinued
--   products_ever          marketed + discontinued
--   feed_records_total     size of the shortage feed, a growth alarm
--
-- Dates are absolute integers, never ages, so a re-derive years from now
-- reproduces byte-identical output.
--
-- CURRENT STATE IS PER ENTITY, NOT PER TIMESTAMP. The shortage feed is paged,
-- and each endpoint carries its own fetch time, so filtering on
-- `observed_at = (SELECT max(observed_at) ...)` silently keeps only the last
-- page — it drops a third of the drugs and nothing warns you. Take the newest
-- row per entity instead. That is what `latest_state` does, and every query
-- below builds on it.

CREATE OR REPLACE VIEW obs AS
SELECT * FROM read_csv_auto('derived/observations/*.csv', union_by_name=true);

CREATE OR REPLACE VIEW latest_state AS
SELECT * FROM (
  SELECT *, row_number() OVER (
    PARTITION BY series_id, entity_id, metric ORDER BY observed_at DESC
  ) AS rn
  FROM obs
) WHERE rn = 1;

-- Q8. Dosage-form fragility needs a denominator. This is the numerator half.
-- status_code = 1 is Current: 70 generics at first capture. Dropping the
-- status filter gives 239, which counts discontinued and resolved packages
-- too and is NOT the shortage figure.
SELECT count(DISTINCT split_part(entity_id, '/', 1)) AS generics_in_shortage
FROM latest_state
WHERE metric = 'status_code' AND value = 1;

-- Q8b. The full finding, reproducible from this table alone: what share of
-- packages in shortage are injectable? (Market denominator is 7.6% — openFDA
-- /drug/ndc.json by dosage_form — so this is a ~9x enrichment.)
SELECT round(100.0 * avg(i.value), 1) AS pct_injectable
FROM latest_state i
JOIN latest_state s USING (entity_id)
WHERE i.metric = 'is_injectable' AND s.metric = 'status_code' AND s.value = 1;

-- Q1. Duration. This is the query that CANNOT be answered from one capture,
-- and becomes answerable as weeks accrue: the first and last week each NDC
-- was seen on the list, which is the thing FDA deletes.
SELECT split_part(entity_id, '/', 1)            AS drug,
       count(DISTINCT date_trunc('week', observed_at)) AS weeks_seen,
       min(observed_at)::DATE                   AS first_seen_by_us,
       max(observed_at)::DATE                   AS last_seen_by_us
FROM obs
WHERE metric = 'listed' AND source_id = 'fda.shortages.current'
GROUP BY 1
ORDER BY weeks_seen DESC, drug
LIMIT 20;

-- Q1b. FDA's own first-listed date, for shortages that predate our capture.
-- Note this is time ON THE LIST, not time unavailable to patients.
SELECT split_part(entity_id, '/', 1) AS drug,
       min(value)::BIGINT            AS first_listed_yyyymmdd
FROM obs
WHERE metric = 'first_listed' AND source_id = 'fda.shortages.current'
GROUP BY 1
ORDER BY 2
LIMIT 15;

-- Q3. Availability trend per drug. Flat until several weeks accrue — that is
-- the point, not a bug. 0 Unavailable, 1 Limited, 2 Available.
SELECT date_trunc('week', observed_at)::DATE AS week,
       split_part(entity_id, '/', 1)         AS drug,
       avg(value)                            AS mean_availability,
       count(*)                              AS packages
FROM obs
WHERE metric = 'availability'
GROUP BY 1, 2
ORDER BY drug, week;

-- Q4/Q7. Supplier fragility WITHOUT tracking company identity: how many
-- distinct packages carry each drug. Immune to renames and acquisitions,
-- because it counts a field rather than resolving an entity.
SELECT split_part(entity_id, '/', 1) AS drug,
       count(DISTINCT entity_id)     AS packages_listed
FROM latest_state
WHERE metric = 'status_code' AND value = 1
GROUP BY 1
HAVING packages_listed = 1
ORDER BY drug;

-- Q6. Import-ban membership by country. A RAW COUNT WITH NO DENOMINATOR —
-- see Q12 in the README before quoting any of these numbers.
SELECT split_part(entity_id, '/', 1) AS country,
       count(*)                      AS firms
FROM latest_state
WHERE metric = 'listed' AND source_id = 'fda.importalert.66-40'
GROUP BY 1
ORDER BY firms DESC
LIMIT 12;

-- Q6b. THE DELISTING DETECTOR — the series nothing else in the world keeps.
-- Firms present in the previous capture and absent from the latest one.
-- Empty until at least two captures exist.
WITH caps AS (
  SELECT DISTINCT observed_at FROM obs
  WHERE source_id = 'fda.importalert.66-40' ORDER BY 1 DESC LIMIT 2
),
latest AS (SELECT max(observed_at) AS t FROM caps),
prior  AS (SELECT min(observed_at) AS t FROM caps)
SELECT entity_id AS delisted_firm
FROM obs
WHERE metric = 'listed' AND source_id = 'fda.importalert.66-40'
  AND observed_at = (SELECT t FROM prior)
  AND (SELECT t FROM prior) <> (SELECT t FROM latest)
  AND entity_id NOT IN (
    SELECT entity_id FROM obs
    WHERE metric = 'listed' AND source_id = 'fda.importalert.66-40'
      AND observed_at = (SELECT t FROM latest))
ORDER BY 1;

-- Health check: is the feed growing past the two paged endpoints?
-- If feed_records_total exceeds 2000, add a third endpoint.
SELECT observed_at::DATE AS day, max(value) AS feed_records_total
FROM obs WHERE metric = 'feed_records_total'
GROUP BY 1 ORDER BY 1;

-- Q14. THE SUPPLIER-EXIT DETECTOR — the reason the cohort exists.
-- Molecules whose marketed-product count fell between two captures, with how
-- far they fell. Empty until the cohort source is active and has two captures.
WITH ranked AS (
  SELECT entity_id, observed_at, value,
         lag(value)       OVER w AS prev_value,
         lag(observed_at) OVER w AS prev_at
  FROM obs
  WHERE metric = 'products_marketed'
    AND source_id = 'fda.drugsfda.cohort-status'
  WINDOW w AS (PARTITION BY entity_id ORDER BY observed_at)
)
SELECT entity_id                       AS molecule,
       prev_at::DATE                   AS from_capture,
       observed_at::DATE               AS to_capture,
       prev_value                      AS suppliers_before,
       value                           AS suppliers_after,
       prev_value - value              AS lost
FROM ranked
WHERE prev_value IS NOT NULL AND value < prev_value
ORDER BY lost DESC, molecule;

-- Q14b. Did the exit come BEFORE the shortage? Joins each molecule's supplier
-- losses to the date FDA first listed any of its packages. A negative gap
-- means suppliers left before FDA ever called it short.
WITH exits AS (
  SELECT entity_id, min(observed_at) AS first_loss
  FROM (
    SELECT entity_id, observed_at, value,
           lag(value) OVER (PARTITION BY entity_id ORDER BY observed_at) AS prev
    FROM obs
    WHERE metric = 'products_marketed'
      AND source_id = 'fda.drugsfda.cohort-status'
  )
  WHERE prev IS NOT NULL AND value < prev
  GROUP BY 1
),
listed AS (
  SELECT replace(split_part(entity_id, '/', 1), 'drug:', '') AS drug,
         min(value)                                          AS first_listed
  FROM latest_state
  WHERE metric = 'first_listed' AND source_id = 'fda.shortages.current'
  GROUP BY 1
)
SELECT e.entity_id, e.first_loss::DATE, l.first_listed
FROM exits e LEFT JOIN listed l
  ON replace(e.entity_id, 'molecule:', '') = l.drug
ORDER BY 1;

-- Q3. SEVERITY, the signal every duration query misses. A drug can sit on the
-- list for a decade while shipping, or be listed last month with nothing
-- available at all. 0 unavailable, 1 limited, 2 available.
SELECT split_part(a.entity_id, '/', 1)                        AS drug,
       count(*)                                               AS packages,
       sum(CASE WHEN a.value = 0 THEN 1 ELSE 0 END)           AS unavailable,
       round(100.0 * sum(CASE WHEN a.value = 0 THEN 1 ELSE 0 END)
             / count(*), 0)                                   AS pct_unavailable
FROM latest_state a
JOIN latest_state s USING (entity_id)
WHERE a.metric = 'availability' AND s.metric = 'status_code' AND s.value = 1
GROUP BY 1
HAVING packages >= 3
ORDER BY pct_unavailable DESC, packages DESC;

-- Q3b. Severity by therapeutic class. The class with the MOST packages is not
-- the class with the worst rate — anaesthesia leads on volume, oncology on
-- severity. Always rank on the rate, never the count.
SELECT replace(split_part(c.entity_id, '/', 2), 'category:', '') AS therapeutic_class,
       count(*)                                                  AS packages,
       round(100.0 * sum(CASE WHEN a.value = 0 THEN 1 ELSE 0 END)
             / count(*), 0)                                      AS pct_unavailable
FROM latest_state a
JOIN latest_state c
  ON split_part(c.entity_id, '/', 1) = split_part(a.entity_id, '/', 1)
 AND c.metric = 'in_category'
JOIN latest_state s ON s.entity_id = a.entity_id
 AND s.metric = 'status_code' AND s.value = 1
WHERE a.metric = 'availability'
GROUP BY 1
HAVING packages >= 20
ORDER BY pct_unavailable DESC;

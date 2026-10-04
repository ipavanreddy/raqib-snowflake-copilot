---
name: synthetic-banking-data
description: Generate realistic, referentially consistent synthetic banking data (customers, accounts, counterparties, transactions, digital events, loans, liquidity) with planted AML/fraud typologies and a ground-truth file, then load it into Snowflake. Use when a demo, test or hackathon needs bank data without touching production or personal data.
tools:
  - bash
  - read
  - write
  - sql_execute
  - snowflake_sql_execute
---

# Synthetic Banking Data with Ground Truth

Builds a privacy-safe dataset whose suspicious patterns are **known**, so you can measure detection recall and false positives.

## What you get
- **10 CSVs:** customers, accounts (valid-checksum UAE IBANs), counterparties, transactions, digital_events, loans, liquidity_daily, country_risk, watchlist (fictional names), and planted_cases (ground truth).
- **Planted typologies:**
  - structuring below a cash threshold
  - rapid pass-through or layering
  - money-mule fan-in network with a collector
  - high-risk jurisdiction wires
  - dormant-account reactivation
  - watchlist near-matches (spelling variants)
  - profile deviation
  - account takeover (device, IP, reset and beneficiary sequence)
  - one multi-typology "hero" case for demos
- **Realistic noise:** salary and remittance cycles, card spend, benign cash, benign device changes and beneficiary additions. Detection rules have to discriminate rather than just fire.
- **Deterministic:** set it with `--seed`.

## Steps
1. Generate:
   ```bash
   python data_gen/generate.py --out data/generated --seed 42 --individuals 1800 --corporates 350
   ```
   Scale up with larger `--individuals` / `--corporates` values; runtime is about linear.
2. Inspect `data/generated/manifest.json` (row counts) and `planted_cases.csv` (ground truth).
3. Load into Snowflake:
   ```sql
   PUT file://data/generated/*.csv @RAQIB.RAW.LANDING AUTO_COMPRESS=TRUE OVERWRITE=TRUE;
   ```
   Then run `sql/02_raw_tables.sql`. Its final query is a row-count check; compare it with the manifest.
4. Validate referential integrity:
   ```sql
   SELECT COUNT(*) FROM RAQIB.RAW.TRANSACTIONS t LEFT JOIN RAQIB.RAW.ACCOUNTS a USING (ACCOUNT_ID) WHERE a.ACCOUNT_ID IS NULL;   -- expect 0
   SELECT COUNT(*) FROM RAQIB.RAW.ACCOUNTS a LEFT JOIN RAQIB.RAW.CUSTOMERS c USING (CUSTOMER_ID) WHERE c.CUSTOMER_ID IS NULL;    -- expect 0
   ```
5. Measure detection against the ground truth (after the detection layer is built):
   ```sql
   WITH exp AS (SELECT p.CUSTOMER_ID, s.VALUE::VARCHAR RULE_ID FROM RAQIB.RAW.PLANTED_CASES p, LATERAL FLATTEN(SPLIT(p.EXPECTED_RULE,'|')) s)
   SELECT RULE_ID, COUNT(*) planted,
          COUNT_IF(EXISTS (SELECT 1 FROM RAQIB.DETECT.ALERTS a WHERE a.CUSTOMER_ID = exp.CUSTOMER_ID AND a.RULE_ID = exp.RULE_ID)) detected
   FROM exp GROUP BY 1 ORDER BY 1;
   ```

## Adapting
- **New typology:** add a block in `plant_typologies()` that calls `g.plant(...)`, then add a matching rule and a test in `tests/test_detection.py`.
- **Another country:** change `COUNTRIES`, `FX`, `EMIRATES`/`BRANCHES`, the name lists and `BANK_CODE`.
- Keep watchlist names fictional. Never seed with real people.

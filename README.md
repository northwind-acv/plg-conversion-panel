# Northwind CRM — PLG Analytics Case

Why are paying customers down while signups are up?

## Contents

| Path | What it is |
|---|---|
| `docs/` | Published site (GitHub Pages): analysis and data methodology |
| `sql/00_load_raw.sql` | Local only: loads the CSVs into `sessions`, `signups`, `opportunities` (in Snowflake these tables already exist) |
| `sql/01_clean.sql` | Cleaned tables. Rules R1–R14, each documented inline |
| `sql/02_funnel.sql` | Funnel metrics: monthly cohorts, product split, origin slices, finance view |
| `sql/03_decomposition.sql` | Kitagawa decomposition of the change in monthly wins (volume / mix / rate) |
| `build/` | Renders `docs/analysis.html` and `docs/data-methodology.html` from the SQL tables (formatting and charts only; no analysis logic) |
| `data/` | Raw extracts as received: `sessions.csv`, `signups.csv`, `opportunities.csv` |

## Reproduce

Queries are Snowflake SQL that also runs unchanged in [DuckDB](https://duckdb.org). Locally, from the repo root:

```bash
duckdb northwind.duckdb < sql/00_load_raw.sql
duckdb northwind.duckdb < sql/01_clean.sql
duckdb northwind.duckdb < sql/02_funnel.sql
duckdb northwind.duckdb < sql/03_decomposition.sql
```

## Key definitions

- **Win / paying customer:** opportunity with `amount > 0`, closed within 30 days of signup.
- **Cohort:** signup month. Q1 = Jan–Mar 2026 (pre Free CRM), Q2 = Apr–Jun 2026 (post launch).

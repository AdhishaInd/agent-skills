---
name: cse-financials
description: >-
  Build and extend a database of Colombo Stock Exchange (CSE, Sri Lanka) company financials: company and report
  index from the CSE API, report PDF downloads for a chosen period range, and CSE-specific conventions (Rs.'000 /
  Rs. Mn units, banks, insurers, unit trusts, 25th-of-month closers, USD reporters). Use whenever the work involves
  CSE / cse.lk companies or reports - "do the next years", "add 2022-2024", "download CSE reports", "rebuild the CSE
  database", "why is <CSE symbol> missing". Works together with the financial-statement-extraction skill, which
  holds the extraction method, checker, transcription format and publishing steps.
---

# CSE financials

The CSE layer on top of **financial-statement-extraction** (load that skill too: it has the method, the pipeline
and the publishing rules). This skill covers what is specific to the Colombo Stock Exchange: where the data comes
from, how to scope a run, and the local conventions that decide how a statement is read.

## Project

The user names the project directory in `CLAUDE.md` / `AGENTS.md`; ask if it is not there. Standard layout:
`db/cse_financials.db`, `schema/schema.sql`, `raw_api/` (cached API responses), `reports/<SYMBOL>/<doc>.pdf`,
`extracted_final/`, `extracted_final_v/`, `reviewed/vision/`, `docs/` (dated recovery notes, `LIMITATIONS.md`).
If the project exists, its code is current; this skill's scripts are snapshots.

## New project (from nothing)

```
mkdir -p <proj>/{db,schema,reports} && cd <proj>
cp -r <this skill>/scripts/bootstrap/scripts <this skill>/scripts/bootstrap/reviewed .
cp <financial-statement-extraction>/assets/schema.sql schema/
python -I scripts/load_master.py db/cse_financials.db schema/schema.sql scripts raw_api
```
`load_master.py` creates the database and loads, from the CSE API (responses cached in `raw_api/`, so reruns are
offline): companies, securities, sectors, directors, the full report index (`report_document`, ~22k rows back to
2000, period ends parsed from titles) and the line-item dictionary (via `seed.py`; do not also load
`dictionary.sql`). About a minute with a warm cache. `reviewed/` holds hand-checked overrides (`scan_readings.py`:
company successions and template overrides; `label_aliases.py`: approved label spellings).

## Next years (the usual job)

1. **Download the period block**:
   `python -I <this skill>/scripts/download.py db/cse_financials.db reports 6 --from 2022-10-01 --to 2024-09-30 --undated-since 2023`
   (resumable; identical files are marked SKIPPED). The first run was 2024-10-01..2026-09-30.
   Earlier years are already in the report index (it goes back to 2000). Reports filed after the index was built
   are not: refreshing means a rebuild, because `load_master.py` creates the schema and fails on an existing
   database. Delete `raw_api/financials_*.json`, run `load_master.py` into a **new** db file, set `local_path` /
   `extraction_status='DOWNLOADED'` for PDFs already on disk (`reports/<SYM>/<doc>.pdf`), run `load_facts.py` on
   it with the published source dir, compare report statuses and fact counts with the old db, then swap (keep a
   backup). The project's `pipeline/rebuild_all.sh` does these steps in place.
2. Then follow financial-statement-extraction from step 2 (parse all, load, triage, batches, stage, publish, close
   out). Load into the same database: facts are keyed by report, so years never overwrite each other.
3. Expect ~80% EXTRACTED from the parser; older years have more scans, so plan an OCR pass (GPU helps) and more
   vision batches.

## CSE conventions that decide a reading

Details and the API reference: **references/cse.md**. The short version:
- Units: "Rs.'000" = 1000, "Rs. Mn" = 1,000,000, a bare "Rs." column header = full rupees. Units often sit only in
  a page note ("all amounts in Sri Lanka Rupees '000").
- Currency LKR, except USD functional-currency reporters (e.g. MGT): store USD, never convert.
- Scope: banks' own columns are COMPANY ("Bank"); companies without subsidiaries are COMPANY only.
- Fiscal years mostly end 31 March (about 285 of 350 companies; interims for June, September, December
  quarters); banks, insurers and some others end 31 December. Some close on the 25th (Union Chemicals): BS at the printed date, IS at month end.
- Unit trusts and funds (CAL funds) show "net assets attributable to unitholders" instead of equity; a new fund may
  have a first period of 5 months (allowed only through `FIRST_PERIOD` in `load_facts.py`).
- Insurers print fund balance sheets beside the company's: take the company's.
- Many filings marked ANNUAL/INTERIM are not reports (errata letters, notices of meeting, twenty largest
  shareholders): record the reason, do not chase statements.

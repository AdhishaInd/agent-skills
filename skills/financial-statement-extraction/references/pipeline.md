# Pipeline map

## Contents
1. Data flow
2. Modules
3. Parsed table JSON (the contract between every stage)
4. Database essentials
5. Loader rules that refuse columns
6. Setting up a new project
7. Adapting to another market

## 1. Data flow

```
exchange API / filings ──your downloader──> reports/<SYM>/<doc>.pdf  + report_document rows
        │
extract_all.py ──> parse_report.parse_pdf(pdf, ctx)       (segment -> columns -> checks; OCR words for scans)
        │                     └─> extracted_final/<doc>.json
reviewed/vision/<doc>.txt ──vision_tables.py──> overlay JSON (vision table replaces parsed tables of its kind)
        │
extracted_final_v/ = extracted_final + overlay   (the published source)
        │
load_facts.py <db> <dir> ──> financial_fact, reported_label, reporting_period (rebuilt from scratch each run)
        │                     only PASS columns; label -> line_item only through exact label_alias
stage_publish.py: staged copy -> audit vs published -> backup + swap
```

## 2. Modules (`scripts/pipeline/`)

| Module | Job | Key functions |
|---|---|---|
| `tokens.py` | words, rows, numbers, dates, units (shared; change with care) | `clean_num`, `page_rows`, `parse_date`, `months_in`, `unit_in`, `currency_in`, `scope_word` |
| `segment.py` | find statement titles, group pages/rows into statement segments, continuations | `statement_tables`, `heading_type`, `page_panels` |
| `columns.py` | what each numeric column means (date, months, scope, audit, unit); read rows into values with sections | `find_columns`, `interpret_columns`, `read_rows` |
| `checks.py` | arithmetic checks, column status | `check_table`, `column_status`, `table_status` |
| `ocr_words.py` | OCR returning `get_text("words")`-shaped tuples so the same parser reads scans; page triage; cache | `OcrDoc`, `triage_page`, `Cache`; env `CSE_OCR`, `CSE_OCR_GPU`, `CSE_OCR_THREADS`, `CSE_OCR_CACHE` |
| `parse_report.py` | one PDF -> tables (no DB). OCR only if text gave no passing IS/BS and image pages exist | `parse_pdf(path, ctx)`; CLI `parse_report.py <pdf> '<ctx json>'` |
| `extract_all.py` | parallel, resumable parse of all downloaded reports | `--workers N --force --tickers A,B` |
| `normalize.py` | the one place text is standardised (labels, names, sections) | `label`, `section_code`, `cash_flow_section`, `is_expense_prefix` |
| `vision_tables.py` | transcriptions -> parser tables (`extractor="vision"`), checked | `parse_file`, `main(in_dir, extracted, out_dir)` |
| `load_facts.py` | JSON -> facts; unit proof; refusals; per-report status | `period`, `label`, `load_column` |

Downloading is exchange-specific and lives in a companion skill (`cse-financials/scripts/download.py` for CSE).

`ctx` for `parse_pdf`: `{"period_end": "YYYY-MM-DD", "category": "ANNUAL|INTERIM", "symbol": ...}` - the report's
own period end anchors header dates.

## 3. Parsed table JSON

`extracted_*/<doc>.json`: `{"pages": n, "scanned": bool, "tables": [table, ...], "vision": [...], ...}`

```json
{"stmt": "IS|OCI|BS|CF", "title": "...", "page": 25, "extractor": "text|ocr|vision",
 "columns": [{"scope": "GROUP|COMPANY", "date": "2025-03-31", "months": 12, "audit": "AUDITED|UNAUDITED|UNKNOWN",
              "unit": 1000, "unit_known": true, "currency": "LKR", "unit_source": "page|vision|..."}],
 "rows": [{"label": "Revenue", "prefix": "", "section": "NONE|ASSET_C|LIAB_NC|OPERATING|...",
           "values": {"0": 132796423.0, "1": 113411460.0}, "page": 25}],
 "checks": [["pbt-tax=profit", 0, 120.0, 120.0, true]], "issues": []}
```
Values are as printed (negative for brackets); `unit` scales them in the loader. `months` is null for BS.

## 4. Database essentials (`assets/schema.sql`)

- `company`, `security` (symbols; voting/non-voting share one company), `report_document` (document_id = exchange
  report id, category, title, period_end_date from the title, local_path, extraction_status
  PENDING/DOWNLOADED/EXTRACTED/PARTIAL/FAILED).
- `reporting_period`: INSTANT (BS, end date only) or DURATION (starts on the 1st, `months` agrees with the dates -
  enforced by CHECK). One period has one form.
- `reported_label` (raw + normalized label per company, statement type, section) -> `line_item` via `label_alias`
  (exact matches only; unmapped labels wait in `v_unmapped_labels` for review).
- `financial_fact`: document, period, label, scope, value, unit_scale, currency, audit_status, is_restated, page_no.
  Comparatives are stored under the report that printed them, so restated figures never overwrite originals.
- Statement types: IS, OCI, BS, CF, SOCE, SEG, KPI.

## 5. Loader refusals (read `load.log`)

- column not PASS (`... column UNCHECKED/FAIL`)
- IS/CF column without months, or months not 3/6/9/12 (exception list `FIRST_PERIOD` for a new fund's first period)
- column dated after the report's own period end, compared by **month** (25th-of-month closers)
- same period and scope given different values by two tables of one report
- column equal to the difference of two others (a variance column)
- same label twice in a column with different values
- no unit printed and none provable from other reports. Unit proof: each other report of the company is a separate
  witness; matching on section + label (label alone only if unambiguous); >= 3 agreeing lines; witnesses that
  disagree on scale prove nothing.

## 6. New project / new years

1. A venv with `pymupdf` (+ `rapidocr-onnxruntime`, or `onnxruntime-gpu`, for OCR of scans).
2. Create the DB: `schema.sql`, then `dictionary.sql` (statement types, 252 standard line items, 471 exact label
   aliases), both in `assets/`:
   `python -I -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); [c.executescript(open(f).read()) for f in sys.argv[2:]]" db/x.db schema.sql dictionary.sql`
3. Fill `company`, `security` and `report_document` rows from the exchange (companion skill, or your own script):
   `report_document` needs document_id, company_id, category (ANNUAL/INTERIM), title, period_end_date (from the
   title), source_url; the downloader sets local_path, sha256 and extraction_status=DOWNLOADED.
4. Copy `scripts/pipeline/` into the project as `pipeline/` (or keep using the skill's copy).
5. Download -> extract_all -> stage_publish -> triage -> batches -> stage_publish, as in SKILL.md.
   (`stage_publish.py` needs a published DB to compare against: for the very first load, copy the empty DB into
   place and accept the all-new audit.)
6. Unmapped labels collect in `v_unmapped_labels`: approve exact aliases into `label_alias` in reviewed batches;
   facts load either way, mapping only affects the standardised view.

## 7. Adapting to another market

The parser was tuned on Sri Lankan reports (IFRS presentation, rupees). The arithmetic, the formats and the workflow
are market-neutral; these places carry local assumptions:
- Currency and unit words: `tokens.unit_in` / `currency_in`, `columns.py` (`unit_words`, default currency),
  `parse_report.py` (currency regex). Add your currency words (e.g. "INR", "Rs. crore" = 10,000,000, "KES '000").
- Default currency `LKR` when none is printed: `columns.py` and `load_facts.py`. Change it to your market's.
- OCR vocabulary (`ocr_words.VOCAB_TEXT`) is English accounting words - fine for English filings.
- Label aliases in `dictionary.sql` come from Sri Lankan reports; most IFRS labels match, new spellings go through
  step 6 above.
- Fiscal quirks (companies closing on the 25th, first periods of new funds) are handled generically (month-level
  comparison, `FIRST_PERIOD` allow-list in `load_facts.py`).
Test on 20-30 reports of different industries (bank, insurer, trading company, fund) before a full run.

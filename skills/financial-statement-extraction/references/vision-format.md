# Transcription format (`reviewed/vision/<doc>.txt`)

Read by `pipeline/vision_tables.py`. Examples: `assets/examples/48833.txt` (normal annual), `47253.txt` (scan,
unlabelled totals), `47742.txt` (UNITS line), `52188.txt` (fund, first period).

```
# comment: company, report, pages read, anything doubtful (supplied labels, skipped columns, print errors)
TABLE IS 25 | Statement of Comprehensive Income
COLS GROUP 2025-03-31 12 AUDITED 1000 LKR ; GROUP 2024-03-31 12 AUDITED 1000 LKR ; COMPANY 2025-03-31 12 AUDITED 1000 LKR ; COMPANY 2024-03-31 12 AUDITED 1000 LKR
Revenue | 1,234 | 1,100 | 900 | 800
Other comprehensive income            <- a line without '|' is a heading (sets BS sections, CF sections)
Cost of sales | (500) | - | (400) | (300)
PAGE 26                               <- lines after this come from page 26 (statement continues)
[Total assets] | 9,999 | 8,888 | ...   <- bracketed label = total printed with no label, supplied by position
| 1,234 | 5,678                       <- empty label: unlabelled subtotal of unclear meaning
MISSING BS | clear reason with the printed evidence
UNITS 1000 LKR                        <- outside a TABLE: unit for parsed tables whose unit was unreadable
```

## COLS fields (one per column, `;`-separated)
`scope date months audit unit currency`
- scope `GROUP` (consolidated) or `COMPANY` (separate; also a bank's own column, and any company with no group).
- date = period end, `YYYY-MM-DD`. Durations (IS/CF) are stored at **month end**; a company closing on the 25th
  still gets month-end IS dates (schema: durations run from the 1st to a month end). BS dates are the printed date.
- months 3/6/9/12 for IS/CF (0 for BS). Other lengths are refused unless the loader's `FIRST_PERIOD` lists the report.
- audit `AUDITED` / `UNAUDITED` / `UNKNOWN`. Annual report statements: AUDITED. Interim: UNAUDITED unless the column
  header itself says audited. "Restated" with no audit word: UNKNOWN (or UNAUDITED in interims - be consistent).
- unit 1 / 1000 / 1000000 as printed (Rs.'000 = 1000, Rs. Mn = 1000000). currency LKR / USD / ...

## Rules
- Transcribe only what is printed. Never invent, adjust or "fix" a figure to make a check pass. Brackets negative,
  '-' nil. Fix only words cut off by a cell edge; join wrapped labels into one line.
- Labels exactly as printed. Never relabel a printed label, even when it is clearly wrong (a 'Total Liabilities' row
  that holds current liabilities): keep it, let the check fail, write `MISSING` with the evidence.
- Statements: IS (P&L, with OCI if on the same statement; a separate OCI page may be skipped), BS, CF. Skip changes
  in equity, multi-year summaries, highlights, segment tables, notes.
- Skip variance / change % columns, side columns from other periods that contradict the report, and the restated
  opening balance column (e.g. 1 April 2023) when it is a third BS date.
- Only this report's periods. A column whose header is evidently misprinted (wrong year on a continuation page,
  "As at" on a P&L, "September-December" for a quarter) may be read by its evident meaning - say so in a comment.
- One TABLE per statement and scope layout; group and company on separate pages = two TABLEs.
- When the parser already loaded a statement, do not add a TABLE of that kind: a vision table replaces every parsed
  table of its kind in that report.
- If the table cannot pass because the print is wrong, keep the TABLE and add the `MISSING` line too: if the
  checker is later extended, it loads with no new reading.

## Valid MISSING reasons (always with the printed evidence)
- the document has no such statement (say what it is: errata letter, notice of meeting, shareholder list)
- printed figures do not reconcile ("total 3,115,995,977 vs equity + liabilities 3,115,995,968")
- labels misprinted on the page (which row holds what)
- unit printed nowhere and no figure in the report fixes it
- period not 3/6/9/12 months (e.g. 15-month year after a year-end change) - keep the comparatives that are
- page unreadable (scan quality) - only after a zoomed crop

## Finding the PDF
`select local_path from report_document where document_id=50325` (sqlite3 CLI or python sqlite3) -> e.g.
`reports/MSL/50325.pdf` (relative to the project). Parser JSON files do not carry the path.

## Check command
Use the `vision_tables.py` that sits with the checker you are running (a project may keep its own copy; the skill's
is `scripts/pipeline/vision_tables.py`).
```
python -I <path>/vision_tables.py reviewed/vision extracted_final <scratch>/vis_out | grep -E "^(DOC1|DOC2) "
```
Each column must show PASS. Totals 1-2 units off their parts pass (printed rounding, see checks.md); keep them as
printed and note them in a comment. FAILED lists the failing check and figures: re-read (zoom) those lines. UNCHECKED: a
needed total line was not recognised - look at the labels (split label? unlabelled total? unusual layout?).

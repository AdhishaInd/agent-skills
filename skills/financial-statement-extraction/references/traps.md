# Data traps (each cost real time once)

Learned on Colombo Stock Exchange filings; exchange API quirks are in the companion skill (cse-financials).

## Contents
1. Dates and periods
2. Units and currency
3. Scope, audit status, restatements
4. Document types that look like reports
5. PDFs, text layers, OCR
6. Process traps

## 1. Dates and periods
- Exchange-supplied dates are often unreliable (filing dates, 1970, typos): take period ends from report titles.
- Companies closing on another day than month end (e.g. the 25th): BS on the printed date; IS/CF durations at month end; the loader
  compares "after the report's period end" by month.
- Header misprints: wrong years on a continuation page (dates carried from page 1 decide), "As at 31 March" on a P&L
  (it is the year), "September - December" for a quarter. Read by evident meaning; note it.
- Year-end changes give 15-month periods: not loadable; keep the 12-month comparatives.
- New funds: first period may be e.g. 5 months - only via the `FIRST_PERIOD` exception, stored from the 1st.
- Interim side columns such as "Group unaudited year ended 31 Dec" that do not match the December report: skip.
- The audited prior-year column in an interim is the year-end, 12 months.

## 2. Units and currency
- Units are printed in a header, a page note ("all amounts in Sri Lanka Rupees '000"), or only in the column header
  ("Rs.") - read them from the page; never infer from size alone.
- No unit printed: EPS x shares, or the same report's BS header, can fix it - say so. The loader's unit proof uses
  other reports as independent witnesses (restated comparatives broke a merged lookup once).
- Statements in USD (functional currency, e.g. MGT): currency USD, not converted.
- Total-assets outliers (x300 off the company's median) catch scale errors the arithmetic cannot.

## 3. Scope, audit status, restatements
- Bank-only figures: COMPANY. Company with no subsidiaries: COMPANY. A company that lost its subsidiary: COMPANY.
- Group and company P&L on separate pages: two tables.
- Audit: annual = AUDITED; interim = UNAUDITED unless the column says audited. Do not mark a prior year-end audited
  because "year-ends usually are" - it made one company's 31 March balance sheet audited in one report and unaudited
  in the next.
- Restated / reclassified comparatives differ from the original report: store each under the report that printed it
  (never overwrite). Different figures for one date across reports are expected, not an error.
- Interim BS for the year-end date and the audited annual BS can differ (audit adjustments): both load, told apart by
  report and audit status.

## 4. Document types that look like reports
- Errata: often only a covering letter + one corrected statement; usually no BS. Some are identical copies.
- "Annual report" filings that are notices of meeting, further announcements, twenty-largest-shareholder lists.
- Fund / unit trust reports: no equity, "net assets attributable to unitholders".
- Insurance companies: fund balance sheets beside the company's (an insurer's fund BS was once loaded as the company's).
- Multi-year summaries and financial highlights pass additive checks: not primary statements, never load them.
- Variance columns pass every additive check: the loader refuses a column equal to the difference of two others.

## 5. PDFs, text layers, OCR
- Text PDFs often paste statement pages as images (no text layer on exactly those pages) - the parser then never
  sees the statement (`not_found`).
- Many scans carry a junk OCR text layer ("9,O4349L") and are not flagged as scanned: render the image.
- Rotated scan pages; statements split across two scans (assets on one, liabilities on the next).
- pdfplumber splits some tables into single characters; pymupdf/pypdf read them. Headings can be lost: anchor on
  table headers.
- Labels detached from their figures in the text layer (label on one line, figures on the next) make UNCHECKED.
- OCR: `rapidocr-onnxruntime`; GPU via `onnxruntime-gpu` (CUDA 12 builds; a 576 driver cannot run CUDA 13),
  `CSE_OCR_GPU=1`, ~3 workers on a 4 GB card, ~6x faster than CPU. With OCR on, a full parse stalls on uncached
  scans: parse with `CSE_OCR=0`, then OCR the target list separately. Background jobs die with the session even
  under nohup: keep runs resumable (extract_all skips finished files).

## 6. Process traps
- Re-parse ALL reports after a parser change and compare per report against the published outputs; a drop in
  passing columns is often a correct refusal of data that was wrong before - read the printed header first.
- Every published change goes through a staged load and audit (`stage_publish.py`).
- Agents' "MISSING because the checker does not recognise ..." is a code task, not a reading task.
- Spot-check loaded figures against page images after parser changes (a sample, not all).

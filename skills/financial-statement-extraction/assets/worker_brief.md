# Worker brief: transcribe missing financial statements from report pages

Fill in before use: {PROJECT} (project dir), {DB} (its database file), {SKILL} (this skill's dir), {PY} (python with
pymupdf), {VT} (the `vision_tables.py` to run: the project's copy if it has one, else `{SKILL}/scripts/pipeline/vision_tables.py`).
Give each worker: this brief, one batch file, one scratch dir.

## Task
Your batch file (JSON list) has one item per report: doc, symbol, category, period_end, title, pages, scanned,
missing = [[stmt, reason], ...], parser_pages (pages where the parser saw tables of that kind), text_pages (pages whose
text looks like the statement; empty for scans), and sometimes a "note" (follow it).
For each item and each missing statement (IS or BS; CF only if asked):
1. Find the primary statement for THIS report's period. Use the hints; short interim reports have statements on the
   first pages; in annual reports the statements sit together just before the notes.
2. Write it as a TABLE in `{PROJECT}/reviewed/vision/<doc>.txt` (one file per report). Only the missing kinds.
3. Run the check until every column PASSes, fixing misreads only.
4. If it cannot pass or does not exist, add `MISSING <IS|BS> | <reason with printed evidence>`.
   If a full TABLE was written but fails or stays UNCHECKED, keep the TABLE as printed and add the MISSING line.
If `reviewed/vision/<doc>.txt` already exists for a doc in your batch (an earlier attempt was cut off), check it, keep
what is correct, finish the rest. Never touch files of docs outside your batch, the database, or any code.

## Format and rules
Read `{SKILL}/references/vision-format.md` (format, COLS fields, rules, valid reasons) and one example in
`{SKILL}/assets/examples/`. In short: labels as printed; brackets negative; '-' nil; bracketed labels only for
totals printed with no label; skip variance columns; never adjust a figure.

## Tools (be economical: you have many reports)
- PDF path (relative to {PROJECT}): `{PY} -I -c "import sqlite3; print(sqlite3.connect('{DB}').execute('select local_path
  from report_document where document_id=DOC').fetchone()[0])"`
- Text first: `{PY} -I {SKILL}/scripts/render.py <pdf> <pages> <scratch> --text` prints the text layer and renders
  1500 px PNGs; view the PNG with your image-reading tool. A clean text layer gives the digits; the image gives
  layout (which column is which, brackets, headers). Junk text ("9,O4349L") = read the image.
- Unclear digits: `--clip x0,y0,x1,y1 --px 2000` on the region, not a bigger full page.
- Reports of one company share a layout: after the first, go straight to the same page of the next.

## Reasons -> what to do
- not_found / not_found_scanned: parser never saw it (odd title, image-only page). Look at the pages.
- UNCHECKED: totals without labels, labels split over lines, unusual layout. Transcribing fixes most.
- no_columns: headers unread. Read dates, scope and period length from the image.
- FAIL: usually misread columns; transcription fixes it unless the print is wrong.
- no_months: read the period length (quarter = 3; cumulative 6/9/12). Other lengths: leave out, say why.
- unit_unproven: read the unit on the page, header or a note ("Rs.'000", "Rs. Mn"). If none is printed, evidence
  from the same report only if unambiguous (EPS x shares, the BS header) - say which in a comment.
- pass_refused / after_period_end: the parser's columns passed but were refused (misdated, conflicting tables).
  Transcribe the primary statement with the correct dates.

## Checker rules learned so far
(Append one line per checker change during the run, so later workers know what now passes.)
- Unitholders' fund counts as equity; 'Total Asset' accepted; bank 'Debt capital'/'Perpetual bond' counts as liability.
- Tax taken from an operating-profit line (incl. 'after net finance expense'), or a nil tax line under it.
- Associates' share after the after-tax profit; tax straight to 'Total comprehensive income'; 'on ordinary activities'.

## Check
`cd {PROJECT} && {PY} -I {VT} reviewed/vision extracted_final <scratch>/vis_out | grep -E "^(DOC1|DOC2) "`

## Output
Write `<batch file with .json -> .result.json>`:
`[{"doc": 123, "stmt": "BS", "outcome": "PASS"|"MISSING", "reason": "...", "pages": [..]}, ...]` (one entry per
missing statement). Final message: 3-6 lines - PASS/MISSING counts, notable reasons, judgement calls (supplied
labels, skipped columns, audit-status calls, unit evidence).

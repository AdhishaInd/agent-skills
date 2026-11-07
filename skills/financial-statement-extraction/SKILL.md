---
name: financial-statement-extraction
description: >-
  Extract income statement, balance sheet and cash flow figures from company financial report PDFs (annual and
  interim/quarterly reports, scans included) into a relational database, with arithmetic checks so only trustworthy
  figures load. Use this skill whenever the user wants to extract, load, recover or audit financial statement figures
  from report PDFs, build or extend a financials database from exchange filings, fix reports that are PARTIAL/FAILED,
  transcribe statement pages from images, run subagent batches over many reports, or check why a statement did not
  load - even if they only say "do the remaining reports", "do the next years" or "why is X missing". For Colombo
  Stock Exchange (CSE, Sri Lanka) work, also use the cse-financials skill.
---

# Financial statement extraction

Turns report PDFs into checked facts: `financial_fact(document, period, label, scope, value, unit, audit status)`.
Built and proven on two years of Colombo Stock Exchange filings (2,707 reports, 720k figures, 99.4% fully loaded).
The method is what makes it fast: an automatic parser does most reports, arithmetic checks decide what is trusted, a
triage step says exactly why each remaining statement failed, and only those statements are read from page images,
in batches, by subagents. Every change reaches the published database only through a staged load and an audit.

## The one rule everything rests on

**A figure loads only if its column passes arithmetic checks** (assets = equity + liabilities; profit before tax -
tax = profit; owners + NCI = profit; cash flow sections sum to the net change; opening + change = closing). Nothing is
adjusted to make a check pass. Checks allow only printed rounding (a few units of the last printed digit: 2 for two
terms, 3 for three, 5 for more), so a total 1-2 units off its parts passes and more is a reading or print error.
This is why a parser, an OCR engine, a vision transcription and a human can all feed the same database: the checks,
not the source, decide. When a check fails, either the reading is wrong (re-read) or the print is wrong
(record why, leave it out). The checks are blind to two things, so plausibility guards cover them: the **scale**
(a wrong stated unit adds up at any size) and the **period length** (a quarter labelled as a year adds up too). The
loader tests each column against the company's other reports, the parser tests interim periods against the financial
year, and the audit counts both (references/traps.md, sections 1-2).

Corollaries that matter in practice:
- Labels stay exactly as printed and map to standard line items only through exact aliases (`label_alias`), never
  fuzzy matching. A misprinted label makes a statement unloadable rather than silently wrong.
- A total printed with no label may get a bracketed label (`[Total assets]`) because its position defines it.
- "UNCHECKED" (no check possible) is not "FAIL". It usually means a layout the checker does not know yet - fix the
  checker once, and every report with that layout loads (see references/checks.md).

## Where things are

- `scripts/pipeline/` - the pipeline: `parse_report.py` (PDF -> JSON tables), `segment.py`, `columns.py`,
  `tokens.py`, `checks.py`, `ocr_words.py` (OCR as fake text layer), `load_facts.py` (JSON -> DB, only passing
  columns), `vision_tables.py` (image transcriptions -> JSON tables), `extract_all.py`, `normalize.py`.
  Map, data shapes and how to adapt it to another market: **references/pipeline.md**.
- `scripts/triage.py`, `scripts/make_batches.py`, `scripts/render.py`, `scripts/stage_publish.py` - the helpers for
  the steps below.
- `assets/schema.sql` (database), `assets/dictionary.sql` (252 standard line items + 471 exact label aliases),
  `assets/worker_brief.md` (brief for transcription workers), `assets/examples/` (transcription files).
- **The project directory**: where the database, PDFs and outputs live. The user names it in `CLAUDE.md` /
  `AGENTS.md` (e.g. "Financials project: ~/stocks/cse_financials"); ask if it is not there. Layout: `db/<name>.db`,
  `reports/<SYMBOL>/<doc>.pdf`, parser output `extracted_final/`, published source `extracted_final_v/`,
  transcriptions `reviewed/vision/`, notes `docs/`. If the project has its own `pipeline/`, treat it as the current
  code (this skill's copy may be older).

Always run Python with `-I` (isolated) and `CSE_OCR=0` unless OCR is wanted (the `CSE_` prefix is historical).
A report's PDF: `select local_path from report_document where document_id=?` (relative to the project dir), then
`python -I scripts/render.py <pdf> <pages> <out_dir> --text` to dump the text layer and render the pages.

## Workflow

### 1. Scope and download
Pick the period range; take period ends from report titles (exchange filing dates are unreliable). Fill
`report_document` rows (one per report: company, category ANNUAL/INTERIM, title, period end, source URL), then
download in parallel and resumably. The exchange-specific part (API, URLs, quirks) belongs in a companion skill -
`cse-financials` for Colombo. Keep each block of years as its own run of these steps. Before a new market or new
years, read **references/traps.md**: it lists the data traps that cost the most time.

### 2. Parse everything with one parser version
`python -I scripts/pipeline/extract_all.py <db> <out_dir> --workers N` with `CSE_OCR=0` (about 9 min for 2,700
reports), then a separate OCR pass for scans (GPU if available; see traps). After any parser change re-parse **all**
reports and compare per report - partial re-parses make the database unreproducible.

### 3. Load and read the status
`load_facts.py` (through `stage_publish.py`, step 6) gives each report EXTRACTED (IS and BS loaded), PARTIAL or
FAILED. Expect roughly 80% EXTRACTED from the parser alone.

### 4. Triage what is left - before looking at any page
```
python -I scripts/triage.py <db> <extracted_dir> triage.json --pdf-hints
python -I scripts/make_batches.py triage.json batches/ --target=12
```
Triage gives each missing statement's reason (`not_found`, `UNCHECKED`, `FAIL`, `no_columns`, `no_months`,
`unit_unproven`, `pass_refused`...) and where to look. Read the counts: a big cluster with one reason (e.g. 100
UNCHECKED) often means a checker gap or a loader rule - fixing code beats transcribing hundreds of pages. Also check
whether FAILED reports are statements at all: notices, shareholder lists and errata are common and need only a
recorded reason.

### 5. Transcribe from images, in batches
Each worker gets one batch file and `assets/worker_brief.md` (fill in the paths). It finds the statement page,
reads it (text layer first, image for layout and anything doubtful), writes `reviewed/vision/<doc>.txt`, runs
`vision_tables.py` on its docs until every column PASSes, and writes `bNN.result.json`. The worker needs a model that
can read images. Format and rules: **references/vision-format.md**. Running workers in parallel, usage limits,
resuming and reviewing results: **references/orchestration.md**. Without subagents, work through the batches one
after another with the same brief.

While batches run, read each result summary as it arrives:
- Recurring "UNCHECKED because the checker does not recognise X" -> extend `checks.py` (references/checks.md),
  retest the affected files with `vision_tables.py`, append the rule to the brief so later batches know. Tables
  already written then pass without re-transcription.
- Judgement calls (audit status, restated columns, odd period lengths, supplied labels) -> check they follow the
  brief; correct centrally (e.g. a sed over COLS lines) rather than re-running a worker.

### 6. Stage, audit, publish
```
python -I scripts/stage_publish.py --project <dir>            # stage + audit only
python -I scripts/stage_publish.py --project <dir> --publish  # after reading the audit
```
Publishing is refused if the audit shows reports leaving EXTRACTED, reports becoming empty, integrity/FK errors,
new unit or column-scale outliers, interim periods that fit no financial year, new 10x conflicts between reports,
or facts lost/changed in reports that have no transcription file (that means a code change touched
data nobody re-read). Gains outside vision reports are normal (a resolved conflict frees another report's column) but
look at each one. Publish in stages (finished batches first) so work survives interruptions; then run the project's
tests if it has any.

### 7. Close out every statement
The goal is: every missing statement is either loaded or has a stated reason. Build the per-statement outcome table
(loaded / not loaded + reason from the `MISSING` lines and result files). For each not-loaded statement, check whether
the same figures are already loaded from another report (next year's comparatives, the matching interim) - usually
they are, and that turns a "gap" into "covered". Record outcomes in the project docs.

## Token and time economy

- Triage first; never send a worker to "find what is wrong" without the reason and page hints.
- Text layer before image: a clean text layer confirms digits for free; the image settles layout. Render 1500 px; crop
  (`render.py --clip`) instead of rendering whole pages larger. Scans with junk text layers ("9,O4349L") need images.
- Batch by company: one layout, many quarters. ~10 reports or ~12 cost units per batch, about 6 workers at once.
- Workers write the full table even when a check stays UNCHECKED, plus a `MISSING` line: if the checker is extended
  later, the table loads without another read.
- Fix systematic issues in code (checker, loader) once, centrally; re-run `vision_tables.py` (seconds) instead of
  re-reading pages.
- The orchestrator does not view page images except to settle a dispute; it reads summaries, runs checks and audits.
- Keep worker summaries to 3-6 lines; details belong in file comments.

## Definition of done

Per report: EXTRACTED, or PARTIAL/FAILED with a reason per missing statement that names the printed evidence
(e.g. "printed total 3,115,995,977 vs equity + liabilities 3,115,995,968"), or "covered by report N". Published only
through `stage_publish.py`, with a backup, audit clean (or every flag explained), tests passing, and the outcome table
plus a dated note in the project docs.

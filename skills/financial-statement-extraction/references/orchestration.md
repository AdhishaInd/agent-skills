# Running transcription batches in parallel

Works with any agent that can start subagents (Claude Code, Codex, or an orchestrator that delegates to other
models). Without subagents, process the batches one after another with the same brief - slower, same result.

## Setup
1. `triage.py` -> `make_batches.py` -> `batches/bNN.json` (in a scratch dir).
2. Copy `assets/worker_brief.md` next to the batches and fill in its placeholders.
3. Prompt per worker (keep it this short; the brief carries the rules):
   > Read and follow <brief path>. Your batch: <batches/bNN.json>. Your scratch dir: <w/bNN>. Do every item; write
   > bNN.result.json next to the batch file.
   Add "An earlier attempt was cut off; see the resume rule in the brief" when relaunching.
4. Workers must be able to read images (scans and image-only pages). Tell any worker on an unfamiliar model
   explicitly: render the pages and *look at* the PNGs, never guess figures, never edit code or the database.

## Concurrency and limits
- About 6 workers at once. More finish faster but run into account usage limits mid-run, and a limit stops every
  running worker at once.
- Workers save files as they go, so nothing is lost. After a limit resets, resume a stopped worker in place if your
  agent can message it (it keeps its context); a new worker must be told to check the existing files first.
- Start the next batch as each one finishes (one slot freed, one launched), so the pool stays full.
- When one provider's limit is hit, workers on another provider's model can carry on with the same brief and batch
  files - in the first run, OpenAI Codex workers took over from Claude workers mid-run and did clean work.
- Typical cost: ~100-150k tokens and 3-6 minutes per batch of ~10 reports / 12-16 statements.

## Reviewing results (orchestrator)
As each summary arrives:
- PASS counts: nothing to do.
- "MISSING: checker does not recognise <layout>": extend `checks.py` (references/checks.md), re-run
  `vision_tables.py` on those files, run the checker tests, append the rule to the brief.
- Judgement calls: compare with the brief (audit status, restated columns, unit evidence, supplied labels).
  Correct centrally (sed over `COLS` lines) - cheaper than a re-run.
- Print errors (figures that do not add up): accept; the reason is recorded.
- Possible conflicts between reports (restated comparatives): fine - each loads under its own report.

## Publishing in stages
Publish finished batches while others run (`stage_publish.py --publish`): exclude docs of unfinished batches from
the overlay (copy only finished files to a temp vision dir and point `--vision` at it), so half-written files never
load. Final pass over everything at the end.

## Closing
Build the outcome table: every missing statement -> loaded, or reason (MISSING line / result file), or covered by
another report (same date loaded from a later report's comparatives or the matching interim, with matching totals).
Write a dated note in the project docs (and a limitations list, if the project keeps one).

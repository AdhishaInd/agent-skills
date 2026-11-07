# agent-skills

Skills for AI coding agents (Claude Code, Codex, and other tools that read `SKILL.md` skills).

| Skill | What it does | Say something like |
|---|---|---|
| [financial-statement-extraction](skills/financial-statement-extraction/SKILL.md) | Turns company report PDFs (annual and quarterly, scans included) into a database of income statement, balance sheet and cash flow figures. Only figures whose columns pass arithmetic checks are loaded. The agent finds out why each remaining statement failed, reads just those pages from images in parallel batches, and publishes through a staged load and an audit. | "extract the financials from these reports", "why didn't X load", "do the remaining reports" |
| [cse-financials](skills/cse-financials/SKILL.md) | The Colombo Stock Exchange (Sri Lanka) layer: builds the company and report index from the CSE API, downloads reports for a period range, and covers the conventions of CSE statements (Rs.'000 / Rs. Mn, banks, insurers, unit trusts). Uses financial-statement-extraction. | "do the next CSE years", "add 2022-2024", "rebuild the CSE database" |

## How well it works

Built on a real run: two years of CSE filings, 2,707 reports and 720,520 figures.
- 99.4% of reports loaded both statements (income statement and balance sheet).
- Every statement that did not load has a recorded reason: an errata letter with no balance sheet, or figures already
  loaded from another report.
- A Codex agent given only these skills and a scanned report reproduced the verified transcription exactly: 4 columns,
  82 figures.

The approach:
1. An automatic parser loads about 80% of reports.
2. `triage.py` says why each remaining statement failed and which pages to look at.
3. Agents transcribe only those statements from page images, about 10 reports per batch, several batches at once.
4. Fixes go into code, not into re-reading: one new checker rule loads every report with that layout.
5. `stage_publish.py` refuses to publish if any figure outside the re-read reports changed.

## Install

**Claude Code** (plugin, one command each, updates with `/plugin marketplace update`):
```
/plugin marketplace add AdhishaInd/agent-skills
/plugin install financial-statements@agent-skills
```

**Codex, or Claude Code without the plugin**: copy the skill folders into your agent's skills directory:
```
git clone https://github.com/AdhishaInd/agent-skills
cp -R agent-skills/skills/* ~/.claude/skills/   # Claude Code
cp -R agent-skills/skills/* ~/.codex/skills/    # Codex
```
Install both skills: `cse-financials` uses `financial-statement-extraction`.

## Requirements

- Python 3 (tested on 3.12) with `pymupdf`. SQLite comes with Python.
- For scans: `rapidocr-onnxruntime`. `onnxruntime-gpu` with CUDA 12 is about 6x faster on a small GPU.
- A model that can read images, for transcribing scanned or image-only statement pages.
- Optional: an agent that can run subagents, to process batches in parallel. Without one, batches run one after
  another.

## Your settings

Put your project directory in your `CLAUDE.md` or `AGENTS.md`, for example:
```
Financials project: ~/stocks/cse_financials
```
Updating the skills then never overwrites your settings.

## Other markets

The method, checks, transcription format and publishing steps work for any market. The parser's unit and currency
words and the default currency are tuned for Sri Lanka; `financial-statement-extraction/references/pipeline.md`
("Adapting to another market") lists where to change them. A skill for another exchange can follow the shape of
`cse-financials`.

## License

MIT

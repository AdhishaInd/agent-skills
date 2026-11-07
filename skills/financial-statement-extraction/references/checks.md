# Arithmetic checks (`pipeline/checks.py`)

## Contents
1. What a check is and when a column passes
2. The checks
3. Tolerance
4. Layouts the checker already knows (with the report that taught it)
5. Extending the checker safely

## 1. Check and column status

A check is `[name, column_index, left, right, passed]`. Rows are found by exact label shape *and* position (tax lies
between profit before tax and profit; total assets before total equity and liabilities), so a check cannot pass on a
look-alike row elsewhere.

`column_status(table)` gives each column:
- **PASS** - at least one *core* check and every check passed. Only PASS columns load.
- **FAIL** - any check failed.
- **UNCHECKED** - no core check could be made (needed total line not found). Not an error in the figures; usually
  a label or layout the checker does not know.

## 2. The checks

| Name | Core | Meaning |
|---|---|---|
| `assets=equity+liabilities` | BS core | total assets = equity (+NCI) + liabilities (or current + non-current liabilities, + held-for-sale) |
| `equity+liabilities=total` | | equity + liabilities = printed "total equity and liabilities" |
| `current+noncurrent assets=total assets` | | |
| `current+noncurrent liabilities=total liabilities` | | |
| `pbt-tax=profit` | IS core | profit before tax -/+ tax (+ discontinued) = profit |
| `continuing+discontinued=profit` | | |
| `parent+nci=profit` | | owners of the parent + non-controlling interest = profit (or TCI) |
| `profit+associates after tax=profit` | | after-tax profit + associates' share printed after tax = final profit |
| `revenue-cost=gross profit` | | |
| `cf sections=net change` | CF core | operating + investing + financing = net change in cash |
| `opening+net change=closing` | | |

A check whose terms are all nil is not written (0 = 0 proves nothing).

## 3. Tolerance

Figures are compared as printed: a few units of the last printed digit - 2 for two terms, 3 for three, 5 for more
(each printed term carries its own rounding). A table in Rs.'000 allows Rs.2,000; one printed to one decimal allows
0.2. It never scales with the size of the figures, so a statement in whole rupees that is 12 rupees off fails - and
that is right: it is a print inconsistency, not rounding. Never widen the tolerance to rescue a report.

## 4. Layouts already handled

Each of these was a cluster of UNCHECKED reports until the checker learned it. Before writing a new rule, check the
list - and when a worker reports "UNCHECKED because ...", match it here first.

| Layout | Example | Rule |
|---|---|---|
| Unitholders' fund instead of equity (unit trusts) | CAL funds | 'net assets attributable to unitholders' / 'unitholders' fund' count as equity |
| 'Total Asset' (singular) | CABO 51403 | accepted |
| Bank 'Debt capital' / 'Perpetual bond' between total liabilities and equity | HDFC | counted with liabilities |
| No PBT line: tax taken from 'Profit from operations' / 'operating activities' / 'Operating profit' | ACAP, CABO, BUKI | that line is PBT if the next line with figures is tax |
| Same, 'from operations after net finance expense' with an earlier 'Profit from operations' | LALU | try every operating-profit line; use the one directly followed by tax |
| Tax line printed nil ('-') in every column right below operating profit | ACAP 48827 | counts as the tax line; profit must equal operating profit |
| PBT 'before income tax and VAT on financial services' only | Abans | used as PBT when no other before-tax line exists |
| Associates' share added after the after-tax profit, then the attributed profit | LALU 51414 | `profit+associates after tax=profit`; attribution checked against the final line |
| No profit line: tax leads straight to 'Total comprehensive income for the period' (no OCI) | Panasian | TCI is the profit line for the core check |
| 'Profit on ordinary activities before/after taxation' | SWAD | accepted in PBT and profit patterns |
| Expense lines printed unsigned under 'Less:' (banks) | NDB, PABC | handled via expense prefixes in `normalize.is_expense_prefix` |
| Group and company statements on separate pages | many | separate tables, each checked |

## 5. Extending the checker safely

1. Find the smallest pattern that describes the layout, anchored by position (e.g. "the next line with figures is
   the tax line"), not a broad regex that could match elsewhere.
2. Test on the affected transcriptions only (copy them to a temp dir):
   `python -I scripts/vision_tables.py <tmp_dir> extracted_final <tmp_out>` - every column should PASS.
3. Run the checker test scripts of the project (e.g. `scripts/test_checks_recovery2.py`, `test_recovery3.py`).
4. Stage + audit the whole database (`stage_publish.py`): the natural-key diff must show **no lost or changed facts
   outside the transcribed reports**. A checker change applies to every parsed report; gains elsewhere are possible
   (inspect them), losses are not acceptable.
5. Append one line describing the new rule to the worker brief so running batches stop reporting it.

A printing error the checker *should* reject (e.g. cost of sales printed positive while gross profit adds it, owners
+ NCI that do not sum to profit) stays rejected: keep the table as printed and write the `MISSING` reason.

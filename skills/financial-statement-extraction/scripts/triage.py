"""Triage: for every PARTIAL / FAILED report, which main statement (IS/BS) is missing and why, plus page hints.

Reads the database (what is loaded) and the parser output (what was read and why it was refused), so a worker knows
where to look before rendering a single page. This is the step that makes the vision pass cheap: most "missing"
statements are not missing at all, they were read and refused for one specific reason.

Usage:
  python -I triage.py <db> <extracted_dir> <out.json> [--status PARTIAL,FAILED] [--pdf-hints]

Output JSON: {"<doc>:<IS|BS>": {"reason": ..., "symbol": ..., "category": ..., "period_end": ..., "title": ...,
              "pages": n, "scanned": bool, "parser_pages": [...], "text_pages": [...]}}
Reasons (most to least actionable):
  pass_refused      columns passed the checks but the loader refused them (conflict, mis-dated, period after report end)
  unit_unproven     figures pass, no unit printed/read and none provable from other reports
  no_months         IS columns whose period length could not be read (or is not 3/6/9/12)
  after_period_end  column dated after the report's own period end (header misread)
  FAIL              arithmetic failed (usually misread columns; sometimes the print is wrong)
  UNCHECKED         no core check possible (unlabelled totals, split labels, unknown layout)
  no_columns        headers not interpreted
  not_found / not_found_scanned   parser never saw the statement (odd title, image-only page)
--pdf-hints adds text_pages: pages whose text layer looks like that statement (needs pymupdf and local_path in the db).
"""
import collections
import json
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "pipeline"))
if pathlib.Path("pipeline/checks.py").exists():  # run from a project dir: use its (possibly newer) checker
    sys.path.insert(0, str(pathlib.Path("scripts").resolve())); sys.path.insert(0, str(pathlib.Path("pipeline").resolve()))
from checks import column_status  # noqa: E402

BS_WORDS = re.compile(r"total assets|financial position|balance sheet|total equity and liabilities", re.I)
IS_WORDS = re.compile(r"profit before (income )?tax|income statement|profit or loss|comprehensive income|revenue", re.I)


def text_pages(path, kind, limit=400):
    import pymupdf
    rx = BS_WORDS if kind == "BS" else IS_WORDS
    out = []
    try:
        doc = pymupdf.open(path)
    except Exception:
        return out
    for i, pg in enumerate(doc):
        if i >= limit:
            break
        t = pg.get_text()
        if len(rx.findall(t)) >= 2 and len(re.findall(r"\d{1,3}(?:,\d{3})+", t)) >= 15:
            out.append(i + 1)
    return out


def main(db, extracted, out_path, statuses=("PARTIAL", "FAILED"), pdf_hints=False):
    c = sqlite3.connect(db)
    q = f"""select r.document_id, r.category, r.period_end_date, r.title, r.local_path,
      (select symbol from security x where x.company_id=r.company_id limit 1),
      (select group_concat(distinct st.code) from financial_fact f join reported_label rl using(label_id)
         join statement_type st using(statement_type_id) where f.document_id=r.document_id)
      from report_document r where extraction_status in ({','.join('?' * len(statuses))})"""
    out, cnt = {}, collections.Counter()
    for doc, cat, pe, title, path, sym, have in c.execute(q, statuses):
        have = set((have or "").split(","))
        f = pathlib.Path(extracted) / f"{doc}.json"
        x = json.loads(f.read_text()) if f.exists() else {"tables": []}
        for s in [s for s in ("IS", "BS") if s not in have]:
            kinds = [s] + (["OCI"] if s == "IS" else [])
            ts = [t for t in x["tables"] if t.get("stmt") in kinds and not t.get("deferred")]
            if not ts:
                why = "not_found" + ("_scanned" if x.get("scanned") else "")
            else:
                sts = []
                for t in ts:
                    if not t.get("columns"):
                        sts.append("no_columns")
                        continue
                    st = column_status(t)
                    for j, col in enumerate(t["columns"]):
                        v = st.get(j)
                        if v == "PASS":
                            if col["date"] > (pe or "9999"):
                                v = "after_period_end"
                            elif s != "BS" and col.get("months") not in (3, 6, 9, 12):
                                v = "no_months"
                            elif col.get("unit_known") is False:
                                v = "unit_unproven"
                            else:
                                v = "pass_refused"
                        sts.append(v)
                why = next((p for p in ("pass_refused", "unit_unproven", "no_months", "after_period_end", "FAIL",
                                        "UNCHECKED", "no_columns") if p in sts), "other")
            item = dict(reason=why, symbol=sym, category=cat, period_end=pe, title=title, pages=x.get("pages"),
                        scanned=bool(x.get("scanned")),
                        parser_pages=sorted({t.get("page") for t in ts if t.get("page")}))
            if pdf_hints and path and not item["scanned"]:
                item["text_pages"] = text_pages(path, s)
            out[f"{doc}:{s}"] = item
            cnt[(s, why)] += 1
    pathlib.Path(out_path).write_text(json.dumps(out, indent=0))
    for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]):
        print(*k, v)
    print(len({k.split(':')[0] for k in out}), "reports,", len(out), "missing statements ->", out_path)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    st = next((x.split("=", 1)[1] for x in sys.argv if x.startswith("--status=")), "PARTIAL,FAILED")
    main(*a[:3], statuses=tuple(st.split(",")), pdf_hints="--pdf-hints" in sys.argv)

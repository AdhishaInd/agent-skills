"""Stage, audit and (optionally) publish: the only safe way to change the published database.

Steps (each must succeed before the next):
  1. vision overlay: vision_tables.py turns <vision_dir>/*.txt into parser JSON over <extracted_dir> -> <source>.new
     (a vision statement replaces every parsed table of its kind in that report).
  2. copy the published db to <db>.staged and run load_facts.py on it (rebuilds all statement facts).
  3. audit staged vs published: status counts, reports that left EXTRACTED, reports that became empty, integrity,
     foreign keys, period-length changes, total-assets unit outliers (x300 off the company's median), and a natural-key
     fact diff: (document, label, end date, months, scope) -> value. Facts lost or changed in reports WITHOUT a vision
     file are the alarm: a checker or loader change has touched data nobody re-read.
  4. --publish: back up the published db, swap in the staged db and the new source dir.
     Refuses if the audit shows regressions, empties, integrity/FK errors or lost/changed facts outside vision reports,
     unless --force (only after explaining each one).

Usage:
  python -I stage_publish.py --project <dir> [--db db/x.db (default: the only *.db in <dir>/db)] [--extracted extracted_final] [--vision reviewed/vision]
                             [--source extracted_final_v] [--publish] [--force]
Run from anywhere; paths are relative to --project. Set CSE_OCR=0 (the loader never needs OCR).
"""
import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import shutil
import sqlite3
import statistics
import subprocess
import sys

PIPE = pathlib.Path(__file__).resolve().parent / "pipeline"


def run(cmd, log):
    with open(log, "w") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env={**os.environ, "CSE_OCR": "0"})
    if r.returncode:
        sys.exit(f"failed ({r.returncode}): {' '.join(map(str, cmd))}\n  see {log}:\n" + pathlib.Path(log).read_text()[-2000:])


def facts(s, db):
    return {r[:5]: r[5] for r in s.execute(f"""select f.document_id, rl.normalized_label, pp.end_date, pp.months,
            f.entity_scope, f.value from {db}.financial_fact f join {db}.reported_label rl using(label_id)
            join {db}.reporting_period pp using(period_id)""")}


def outliers(s, db):
    g = collections.defaultdict(list)
    for c, sc, cur, d, v in s.execute(f"""select f.company_id, f.entity_scope, f.currency, f.document_id, f.value
            from {db}.financial_fact f join {db}.reported_label rl using(label_id) join {db}.line_item li using(line_item_id)
            where li.code='BS_TOTAL_ASSETS' and f.value>0"""):
        g[(c, sc, cur)].append((d, v))
    out = set()
    for vs in g.values():
        if len(vs) >= 3:
            med = statistics.median(v for _, v in vs)
            out |= {d for d, v in vs if v / med > 300 or med / v > 300}
    return out


def audit(staged, published, vision_docs):
    s = sqlite3.connect(staged)
    s.execute(f"attach '{published}' as p")
    q = lambda x: s.execute(x).fetchall()  # noqa: E731
    r = {"facts": [q("select count(*) from p.financial_fact")[0][0], q("select count(*) from financial_fact")[0][0]],
         "status_before": dict(q("select extraction_status,count(*) from p.report_document group by 1")),
         "status_after": dict(q("select extraction_status,count(*) from report_document group by 1")),
         "extracted_regressed": [x[0] for x in q("""select a.document_id from report_document a join p.report_document b
              using(document_id) where b.extraction_status='EXTRACTED' and a.extraction_status<>'EXTRACTED'""")],
         "now_empty": [x[0] for x in q("""select document_id from (select document_id from p.financial_fact group by 1)
              except select document_id from (select document_id from financial_fact group by 1)""")],
         "integrity": q("pragma integrity_check")[0][0], "fk_errors": len(q("pragma foreign_key_check"))}
    a, b = facts(s, "p"), facts(s, "main")
    lost = [k for k in a if k not in b]
    chg = [k for k in a if k in b and a[k] != b[k]]
    gain = [k for k in b if k not in a]
    out_v = lambda ks: collections.Counter(k[0] for k in ks if k[0] not in vision_docs)  # noqa: E731
    r["diff"] = {"lost": len(lost), "changed": len(chg), "gained": len(gain),
                 "lost_outside_vision": dict(out_v(lost).most_common(20)),
                 "changed_outside_vision": dict(out_v(chg).most_common(20)),
                 "gained_outside_vision": dict(out_v(gain).most_common(20))}
    o1, o2 = outliers(s, "p"), outliers(s, "main")
    r["new_unit_outliers"] = sorted(o2 - o1)
    bad = bool(r["extracted_regressed"] or r["now_empty"] or r["integrity"] != "ok" or r["fk_errors"]
               or r["diff"]["lost_outside_vision"] or r["diff"]["changed_outside_vision"] or r["new_unit_outliers"])
    return r, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--db", help="relative to --project; default: the only *.db file in <project>/db")
    ap.add_argument("--extracted", default="extracted_final")
    ap.add_argument("--vision", default="reviewed/vision")
    ap.add_argument("--source", default="extracted_final_v")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--force", action="store_true")
    o = ap.parse_args()
    P = pathlib.Path(o.project).resolve()
    if not o.db:
        dbs = [f for f in (P / "db").glob("*.db") if not f.name.startswith("backup") and "staged" not in f.name]
        if len(dbs) != 1:
            sys.exit(f"give --db: found {len(dbs)} candidate databases in {P / 'db'}")
        o.db = str(dbs[0].relative_to(P))
    db, ext, vis, src = P / o.db, P / o.extracted, P / o.vision, P / o.source
    new, staged, logs = P / (o.source + ".new"), P / (o.db + ".staged"), P / "logs" / "stage"
    logs.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    # Prefer the project's own code (it may be newer than this skill's snapshot); fall back to the snapshot.
    vt = next((f for f in (P / "scripts/vision_tables.py", P / "pipeline/vision_tables.py") if f.exists()), PIPE / "vision_tables.py")
    lf = next((f for f in (P / "pipeline/load_facts.py",) if f.exists()), PIPE / "load_facts.py")
    print("code:", vt, lf)
    overlay = logs / "vision_out"
    shutil.rmtree(overlay, ignore_errors=True)
    run([py, "-I", vt, vis, ext, overlay], logs / "vision.log")
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(ext, new)
    for f in overlay.glob("*.json"):
        shutil.copy(f, new / f.name)
    shutil.copy(db, staged)
    run([py, "-I", lf, staged, new], logs / "load.log")
    vision_docs = {int(f.stem) for f in overlay.glob("*.json")}
    r, bad = audit(staged, db, vision_docs)
    (logs / "audit.json").write_text(json.dumps(r, indent=1))
    print(json.dumps(r, indent=1))
    fails = [l for l in (logs / "vision.log").read_text().splitlines() if "'FAIL'" in l or "MISSING" in l]
    print(f"\nvision: {len(vision_docs)} reports, {len(fails)} lines with FAIL/MISSING (see {logs / 'vision.log'})")
    print("load summary:", (logs / "load.log").read_text().strip().splitlines()[-3:])
    if not o.publish:
        print("\nstaged only. Review the audit, then rerun with --publish.")
        return
    if bad and not o.force:
        sys.exit("\nAUDIT FLAGS ABOVE: not publishing. Explain each one, fix, or rerun with --force.")
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db.with_name(f"backup_{stamp}_{db.name}")
    shutil.copy(db, backup)
    shutil.copy(staged, db)
    if src.exists():
        shutil.rmtree(src)
    new.rename(src)
    print(f"\npublished. backup: {backup}. Now run the project's tests.")


if __name__ == "__main__":
    main()

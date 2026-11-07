"""Split triage output into worker batches of similar cost, keeping one company's reports together.

Reports of one company share a layout, so a worker that has read one quarter reads the next in a fraction of the
tokens. Batches are balanced by an estimated cost: scanned or not-found statements cost more than refused ones.

Usage: python -I make_batches.py <triage.json> <out_dir> [--target 12]
Writes <out_dir>/bNN.json (list of items, one per report, with "missing": [[stmt, reason], ...]) and prints a summary.
"""
import collections
import json
import pathlib
import sys

COST = {"not_found_scanned": 2.0, "not_found": 1.5, "FAIL": 1.2, "UNCHECKED": 1.0, "no_columns": 1.0,
        "no_months": 0.8, "after_period_end": 0.8, "pass_refused": 0.8, "unit_unproven": 0.5, "other": 1.0}


def main(triage, out_dir, target=12.0):
    t = json.loads(pathlib.Path(triage).read_text())
    docs = collections.OrderedDict()
    for key, it in sorted(t.items(), key=lambda kv: (kv[1].get("symbol") or "", kv[0])):
        doc, stmt = key.split(":")
        d = docs.setdefault(int(doc), dict(doc=int(doc), **{k: v for k, v in it.items() if k != "reason"}, missing=[]))
        d["missing"].append([stmt, it["reason"]])
        d["weight"] = round(sum(COST.get(r, 1.0) for _, r in d["missing"]) * (1.3 if (it.get("pages") or 0) > 60 else 1), 1)
    by_co = collections.OrderedDict()
    for d in docs.values():
        by_co.setdefault(d.get("symbol") or str(d["doc"]), []).append(d)
    batches, cur, w = [], [], 0.0
    for items in by_co.values():
        cw = sum(i["weight"] for i in items)
        if cur and w + cw > target * 1.25:
            batches.append(cur)
            cur, w = [], 0.0
        cur += items
        w += cw
        if w >= target:
            batches.append(cur)
            cur, w = [], 0.0
    if cur:
        batches.append(cur)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for n, b in enumerate(batches, 1):
        (out / f"b{n:02d}.json").write_text(json.dumps(b, indent=1))
        print(f"b{n:02d}", len(b), "reports", round(sum(i['weight'] for i in b), 1), "cost",
              sorted({i.get('symbol') for i in b if i.get('symbol')})[:6])
    print(len(batches), "batches ->", out)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    tg = next((float(x.split("=", 1)[1]) for x in sys.argv if x.startswith("--target=")), 12.0)
    main(a[0], a[1], tg)

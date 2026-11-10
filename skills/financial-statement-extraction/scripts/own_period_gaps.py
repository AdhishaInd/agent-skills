"""Own-period completeness: for every loaded report and statement (IS, BS, CF), is the report's own period loaded,
is it covered by another report, and if neither, why the parser's columns for that date did not load.

Usage: python -I scripts/own_period_gaps.py <db> <source_dir> <out.json>
Reasons: no_table (statement not found), no_own_column (table has no column for the report's date),
         no_months, unit_unproven, FAIL, UNCHECKED, pass_refused (passed but the loader refused it).
"""
import collections, json, pathlib, sqlite3, sys
sys.path.insert(0, 'pipeline')
from checks import column_status  # noqa: E402

db, src, out = sys.argv[1:4]
c = sqlite3.connect(db)
STMT = {'IS': (1, 2), 'BS': (3,), 'CF': (4,)}
docs = c.execute("""select d.document_id, co.ticker, d.company_id, d.category, d.period_end_date, d.title
                    from report_document d join company co using(company_id)
                    where d.extraction_status in ('EXTRACTED','PARTIAL') and d.period_end_date is not null""").fetchall()
loaded = collections.defaultdict(set)     # (doc, stmt) -> months loaded at own date
covered = set()                            # (company, stmt, yyyy-mm)
for doc, cid, st, end, m in c.execute("""select f.document_id, f.company_id, rl.statement_type_id, p.end_date, p.months
        from financial_fact f join reporting_period p using(period_id) join reported_label rl using(label_id)
        where rl.statement_type_id in (1,2,3,4) group by 1,2,3,4,5"""):
    s = 'IS' if st in (1, 2) else 'BS' if st == 3 else 'CF'
    loaded[(doc, s, end[:7])].add(m)
    covered.add((cid, s, end[:7]))
res, summary = {}, collections.Counter()
for doc, tk, cid, cat, pe, title in docs:
    f = pathlib.Path(src) / f'{doc}.json'
    j = json.loads(f.read_text()) if f.exists() else {'tables': []}
    for s in ('IS', 'BS', 'CF'):
        if loaded.get((doc, s, pe[:7])):
            summary[(s, 'loaded')] += 1
            continue
        if (cid, s, pe[:7]) in covered:
            summary[(s, 'covered_elsewhere')] += 1
            continue
        tabs = [t for t in j['tables'] if t.get('stmt') in ((s, 'OCI') if s == 'IS' else (s,)) and not t.get('deferred')]
        reason, detail = 'no_table', []
        if tabs:
            reason = 'no_own_column'
            for t in tabs:
                stat = column_status(t) if t.get('columns') else {}
                for i, col in enumerate(t.get('columns', [])):
                    if col['date'][:7] != pe[:7]:
                        continue
                    st = stat.get(i)
                    if st == 'PASS':
                        r = ('no_months' if s != 'BS' and col.get('months') not in (3, 6, 9, 12)
                             else 'unit_unproven' if col.get('unit_known') is False else 'pass_refused')
                    else:
                        r = st or 'UNCHECKED'
                    detail.append((t['page'], col['scope'], col.get('months'), r))
            order = ['pass_refused', 'unit_unproven', 'no_months', 'FAIL', 'UNCHECKED']
            rs = [d[3] for d in detail]
            reason = next((o for o in order if o in rs), reason)
        res[f'{doc}:{s}'] = dict(symbol=tk, category=cat, period_end=pe, title=title, reason=reason,
                                 extractor=sorted({t.get('extractor') or '' for t in tabs}),
                                 pages=sorted({t['page'] for t in tabs}), detail=detail)
        summary[(s, reason)] += 1
pathlib.Path(out).write_text(json.dumps(res, indent=0))
for k, v in sorted(summary.items()):
    print(k, v)
print('uncovered own periods:', len(res))

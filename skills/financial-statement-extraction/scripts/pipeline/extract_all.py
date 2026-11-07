"""Run the statement parser over downloaded reports in parallel. Resumable unless --force.
Usage: python -I pipeline/extract_all.py <db> <out_dir> [--limit N] [--force] [--workers N] [--tickers A,B]"""
import argparse, concurrent.futures as cf, datetime as dt, json, os, pathlib, sqlite3, sys, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import parse_report as P
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reviewed"))
try:
    from scan_readings import FYE_CHANGED
except ImportError:
    FYE_CHANGED = {}

def work(job):
    ctx, out = job
    try:
        r = P.parse_pdf(ctx["path"], ctx)
    except Exception as e:
        r = dict(document_id=ctx["document_id"], pages=0, tables=[], issues=[f"crash: {type(e).__name__}: {str(e)[:200]}"])
    r.update(ticker=ctx["ticker"], category=ctx["category"], title=ctx["title"], period_end=ctx["period_end"], template=ctx["template"], fye=ctx["fye"])
    pathlib.Path(out).write_text(json.dumps(r))
    return ctx["document_id"]

def jobs(db, outdir, a):
    con = sqlite3.connect(db)
    q = """SELECT d.document_id, c.ticker, d.category, d.title, d.period_end_date, d.local_path, t.code, c.fiscal_year_end_month
           FROM report_document d JOIN company c USING (company_id) JOIN reporting_template t USING (template_id)
           WHERE d.category IN ('INTERIM','ANNUAL') AND d.extraction_status <> 'SKIPPED'"""
    disk = {int(f.stem): str(f) for f in pathlib.Path(a.reports).glob("*/*.pdf")}
    rows = [r[:5] + (disk[r[0]],) + r[6:] for r in con.execute(q).fetchall() if r[0] in disk]
    if a.tickers: rows = [r for r in rows if r[1] in a.tickers.split(",")]
    if a.docs:
        wanted = {int(x) for x in pathlib.Path(a.docs).read_text().split()}
        rows = [r for r in rows if r[0] in wanted]
    rows.sort(key=lambda r: hash(r[0]) % 9973)
    out = []
    for doc, tk, cat, title, pe, path, tpl, fye in rows:
        if not pathlib.Path(path).exists(): continue
        f = outdir / f"{doc}.json"
        if f.exists() and not a.force: continue
        out.append((dict(document_id=doc, ticker=tk, category=cat, title=title, period_end=pe, path=path, template=tpl, fye=fye, fye_extra=FYE_CHANGED.get(tk, ())), str(f)))
    return out[:a.limit] if a.limit else out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("db"); ap.add_argument("out"); ap.add_argument("--limit", type=int); ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 2)); ap.add_argument("--tickers"); ap.add_argument("--reports", default="reports"); ap.add_argument("--docs", help="file of document ids to process"); a = ap.parse_args()
    outdir = pathlib.Path(a.out); outdir.mkdir(exist_ok=True)
    js = jobs(a.db, outdir, a); t0 = time.time()
    with cf.ProcessPoolExecutor(a.workers) as ex:
        for n, _ in enumerate(ex.map(work, js, chunksize=4), 1):
            if n % 200 == 0: print(n, "of", len(js), round(time.time() - t0), "s", flush=True)
    print("extracted", len(js), "in", round(time.time() - t0), "s", flush=True)

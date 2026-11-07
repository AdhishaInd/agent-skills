"""Download in-scope reports with parallel connections, then record them in the database. Resumable.
Scope: interim and annual reports for periods ending FROM..TO (inclusive), plus undated ones uploaded since --undated-since.
The first run used 2024-10-01..2026-09-30, undated since 2025. Run each block of years separately.
Usage: python -I download.py <db> <out_dir> <workers> [--from 2024-10-01] [--to 2026-09-30] [--undated-since 2025]"""
import concurrent.futures as cf, hashlib, json, pathlib, sqlite3, sys, time, urllib.parse, urllib.request
import argparse
ap = argparse.ArgumentParser(); ap.add_argument("db"); ap.add_argument("out"); ap.add_argument("workers", type=int)
ap.add_argument("--from", dest="start", default="2024-10-01"); ap.add_argument("--to", dest="end", default="2026-09-30")
ap.add_argument("--undated-since", default="2025"); a = ap.parse_args()
db, out, workers = a.db, pathlib.Path(a.out), a.workers
con = sqlite3.connect(db)
rows = con.execute("""SELECT d.document_id, c.ticker, d.source_url FROM report_document d JOIN company c USING (company_id)
  WHERE d.category IN ('INTERIM','ANNUAL') AND ((d.period_end_date >= ? AND d.period_end_date <= ?)
     OR (d.period_end_date IS NULL AND d.uploaded_at >= ?))""", (a.start, a.end, a.undated_since)).fetchall()
print(len(rows), "in scope", flush=True)
def fetch(row):
    doc, tk, url = row
    d = out / tk.split("#")[0]; d.mkdir(parents=True, exist_ok=True); f = d / f"{doc}.pdf"
    if f.exists() and f.stat().st_size > 0: return doc, str(f), None
    tmp = f.with_suffix(".part")
    for attempt in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(urllib.parse.quote(url, safe=":/"), headers={"User-Agent": "Mozilla/5.0"}), timeout=180).read()
            tmp.write_bytes(b); tmp.rename(f); time.sleep(0.1)
            return doc, str(f), None
        except Exception as e:
            err = str(e)[:80]; time.sleep(3 * (attempt + 1))
    return doc, None, err
done = fails = 0; t0 = time.time(); results = []
with cf.ThreadPoolExecutor(workers) as ex:
    for doc, path, err in ex.map(fetch, rows):
        results.append((doc, path, err)); done += 1; fails += err is not None
        if done % 200 == 0: print(done, round(time.time() - t0), "s; fails", fails, flush=True)
dupes = []
for doc, path, err in results:
    if not path: continue
    sha = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    cid = con.execute("SELECT company_id FROM report_document WHERE document_id=?", (doc,)).fetchone()[0]
    other = con.execute("SELECT document_id FROM report_document WHERE company_id=? AND sha256=? AND document_id<>?", (cid, sha, doc)).fetchone()
    if other:
        dupes.append((doc, other[0])); con.execute("UPDATE report_document SET local_path=?, extraction_status='SKIPPED' WHERE document_id=?", (path, doc))
    else:
        con.execute("UPDATE report_document SET local_path=?, sha256=?, extraction_status='DOWNLOADED' WHERE document_id=?", (path, sha, doc))
con.commit()
json.dump(dict(fails=[r for r in results if r[2]], identical_files=dupes), open(out / "download_report.json", "w"))
print("finished; ok", done - fails, "fails", fails, "identical files skipped", len(dupes), flush=True)

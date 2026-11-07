"""Load parsed statements into financial_fact. Only columns that pass their arithmetic checks are loaded.

Rebuilds statement data from scratch each run: financial_fact, reported_label and reporting_period.
Usage: python -I pipeline/load_facts.py <db> <extracted_dir>
"""
import collections
import datetime as dt
import glob
import json
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "scripts"))
import checks  # noqa: E402
import normalize  # noqa: E402

db, src = sys.argv[1], sys.argv[2]
con = sqlite3.connect(db)
con.execute("PRAGMA foreign_keys=ON")
for t in ("financial_fact", "reported_label", "reporting_period"):
    con.execute(f"DELETE FROM {t}")
con.execute("UPDATE report_document SET extraction_status='DOWNLOADED', extractor=NULL WHERE extraction_status IN ('EXTRACTED','PARTIAL','FAILED')")

ST = dict(con.execute("SELECT code, statement_type_id FROM statement_type"))
ITEM_ST = dict(con.execute("SELECT line_item_id, statement_type_id FROM line_item"))
ALIAS = {}
for st_id, section, lab, item in con.execute("SELECT statement_type_id, section, normalized_label, line_item_id FROM label_alias"):
    ALIAS[(st_id, section, lab)] = item
FYE = dict(con.execute("SELECT company_id, fiscal_year_end_month FROM company"))
CO = {int(r[0]): r[1] for r in con.execute("SELECT document_id, company_id FROM report_document")}
PER_SHARE = re.compile(r"per (ordinary |voting |non voting )?share|earnings per|\beps\b|dividend per|net assets? value per|per unit", re.I)

stats = collections.Counter()
refused = collections.Counter()
label_ids, period_ids = {}, {}
LABEL_ITEM = {}


def period(cid, kind, end, months):
    key = (cid, kind, end, months)
    if key in period_ids:
        return period_ids[key]
    e = dt.date.fromisoformat(end)
    fye = FYE.get(cid) or 12
    fy = e.year if e.month <= fye else e.year + 1
    start = None
    if kind == "DURATION":
        m = e.month - months + 1
        y = e.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        start = dt.date(y, m, 1).isoformat()
    try:
        con.execute("""INSERT OR IGNORE INTO reporting_period(company_id,period_kind,start_date,end_date,months,fiscal_year)
                       VALUES (?,?,?,?,?,?)""", (cid, kind, start, end, months if kind == "DURATION" else None, fy))
    except sqlite3.IntegrityError:
        period_ids[key] = None   # e.g. an end date that is not a month end
        return None
    pid = con.execute("SELECT period_id FROM reporting_period WHERE company_id=? AND period_kind=? AND end_date=? AND COALESCE(start_date,'')=COALESCE(?,'')",
                      (cid, kind, end, start)).fetchone()
    period_ids[key] = pid[0] if pid else None
    return period_ids[key]


def label(cid, stmt, section, raw, prefix, split_sections=False):
    """Exact alias match only. A wrapped label is tried joined to the line above it first.
    split_sections: the same words also appear under another section of this column, so only an alias for this
    section may map it; an any-section alias would give both lines the same meaning."""
    st_id = ST[stmt]
    candidates = ([f"{prefix} {raw}"] if prefix else []) + [raw]
    for text in candidates:
        n = normalize.label(text)
        if not n:
            continue
        item = ALIAS.get((st_id, section, n)) or (None if split_sections else ALIAS.get((st_id, "ANY", n)))
        if item:
            sec = section if (st_id, section, n) in ALIAS else "NONE"
            return _label_row(cid, ITEM_ST[item], sec, text, n, item)
    n = normalize.label(raw)
    return _label_row(cid, st_id, section, raw, n, None) if n else None


def _label_row(cid, st_id, section, raw, n, item):
    key = (cid, st_id, section, n)
    if key in label_ids:
        return label_ids[key]
    con.execute("""INSERT OR IGNORE INTO reported_label(company_id,statement_type_id,section,raw_label,normalized_label,line_item_id,mapping_method,sign_factor)
                   VALUES (?,?,?,?,?,?,?,?)""", (cid, st_id, section, raw, n, item, "ALIAS" if item else "UNMAPPED",
                                                 -1 if normalize.is_expense_prefix(raw) else 1))
    label_ids[key] = con.execute("SELECT label_id FROM reported_label WHERE company_id=? AND statement_type_id=? AND section=? AND normalized_label=?", key).fetchone()[0]
    LABEL_ITEM[label_ids[key]] = item
    return label_ids[key]


doc_tables = collections.defaultdict(set)
doc_ocr = set()   # documents with figures read by OCR
doc_vision = set()   # documents with figures read by eye from page images (scripts/vision_tables.py)
deferred = []   # columns printed without a unit, resolved after all others are in


def rows_of(t, j):
    """(label, prefix, section, page, value) for one column. A label printed twice with different values is refused."""
    vals = collections.defaultdict(set)
    for r in t["rows"]:
        v = r["values"].get(str(j), r["values"].get(j))
        if v is not None and r["label"]:
            vals[(r.get("section") or "NONE", normalize.label(r["label"]))].add(v)
    out = []
    for r in t["rows"]:
        v = r["values"].get(str(j), r["values"].get(j))
        if v is None or not r["label"]:
            continue
        if len(vals[(r.get("section") or "NONE", normalize.label(r["label"]))]) > 1:
            stats["lines refused: same label twice in a column with different values"] += 1
            continue
        out.append((r["label"], r.get("prefix") or "", r.get("section") or "NONE", r.get("page"), v))
    return out


# Reports whose own first period is not a quarter multiple: a new fund's first annual report. Listed one by one,
# because any other odd period length is a misread header. Stored as whole months from the 1st (schema rule).
FIRST_PERIOD = {52188: 5}   # CALU: CAL Three Year Closed End Fund, 31 Oct 2025 to 31 Mar 2026

DOC_END = dict(con.execute("SELECT document_id, period_end_date FROM report_document"))


def load_column(cid, doc, stmt, col, lines, unit, seen):
    # A report cannot hold figures for a period ending after its own period end: such a date was misread.
    end = DOC_END.get(doc)
    # Compared by month: periods are dated at month end, and some companies close on the 25th (UCAR).
    if end and col["date"][:7] > end[:7]:
        refused[f"{stmt} column dated after the report's own period end"] += 1
        return 0
    kind = "INSTANT" if stmt == "BS" else "DURATION"
    months = None if kind == "INSTANT" else col.get("months")
    if kind == "DURATION" and months not in (3, 6, 9, 12) and not (months is not None and FIRST_PERIOD.get(doc) == months):
        refused[f"{stmt} column without months"] += 1
        return 0
    pid = period(cid, kind, col["date"], months)
    if pid is None:
        refused[f"{stmt} column with an invalid period"] += 1
        return 0
    n = 0
    sections_of = collections.defaultdict(set)
    for raw, prefix, section, page, v in lines:
        sections_of[normalize.label(raw)].add(section)
    resolved = []
    for raw, prefix, section, page, v in lines:
        lid = label(cid, stmt, section, raw, prefix, split_sections=len(sections_of[normalize.label(raw)]) > 1)
        if lid is not None:
            resolved.append((raw, page, v, lid, LABEL_ITEM.get(lid)))
    # Two different lines claiming one standard item with different values: neither is trusted for that item.
    by_item = collections.defaultdict(set)
    for raw, page, v, lid, item in resolved:
        if item:
            by_item[item].add(round(v, 6))
    clashing = {i for i, vs in by_item.items() if len(vs) > 1}
    if clashing:
        stats["lines refused: two lines give one standard item different values"] += sum(1 for x in resolved if x[4] in clashing)
    for raw, page, v, lid, item in resolved:
        if item in clashing:
            continue
        scale = 1 if PER_SHARE.search(raw) else unit
        key = (pid, col["scope"], lid)
        value = round(v * scale, 4)
        if key in seen:
            if abs(seen[key] - value) > 1e-6:
                stats["same line with two values, second refused"] += 1
            continue
        seen[key] = value
        try:
            con.execute("""INSERT INTO financial_fact(company_id,document_id,period_id,label_id,entity_scope,value,unit_scale,currency,audit_status,page_no)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (cid, doc, pid, lid, col["scope"], value, scale, col.get("currency") or "LKR", col.get("audit") or "UNKNOWN", page))
            n += 1
        except sqlite3.IntegrityError as e:
            stats[f"refused by database: {str(e)[:60]}"] += 1
    stats["facts"] += n
    return n


files = sorted(glob.glob(f"{src}/*.json"))
for n_file, f in enumerate(files, 1):
    d = json.loads(pathlib.Path(f).read_text())
    doc = d["document_id"]
    cid = CO.get(doc)
    if cid is None:
        continue
    seen = {}
    claims = collections.defaultdict(list)
    for ti, t in enumerate(d["tables"]):
        if t.get("deferred") or t.get("stmt") not in ("IS", "OCI", "BS", "CF") or not t.get("columns"):
            continue
        st_ = checks.column_status(t)
        for j, col in enumerate(t["columns"]):
            if st_.get(j) == "PASS":
                months = None if t["stmt"] == "BS" else col.get("months")
                claims[(t["stmt"], col["scope"], col["date"], months)].append((ti, j))
    # The schema keeps one value per document/period/label. Reports may repeat their
    # complete statements translated into another currency. Prefer the first stated
    # currency for that statement/period; retain translations in raw parser outputs.
    alternate_currency = set()
    for key, cols in list(claims.items()):
        stated = [(ti, j) for ti, j in cols if d["tables"][ti]["columns"][j].get("unit_known")]
        candidates = stated or cols
        first_ti, first_j = min(candidates, key=lambda x: (d["tables"][x[0]].get("page", 10**9), x))
        primary = d["tables"][first_ti]["columns"][first_j].get("currency") or "LKR"
        keep = []
        for ti, j in cols:
            if (d["tables"][ti]["columns"][j].get("currency") or "LKR") != primary:
                alternate_currency.add((ti, j))
                stats["translated columns retained only in parser output"] += 1
            else:
                keep.append((ti, j))
        claims[key] = keep
    ambiguous = set()
    # A variance column (this year minus last year) passes every additive check, so look for it directly:
    # a column equal to the difference of two other columns on every shared line is refused.
    for ti, t in enumerate(d["tables"]):
        if t.get("deferred") or t.get("stmt") not in ("IS", "OCI", "BS", "CF") or not t.get("columns"):
            continue
        n_cols = len(t["columns"])
        vals = [{i: r["values"].get(str(j), r["values"].get(j)) for i, r in enumerate(t["rows"]) if r["label"]} for j in range(n_cols)]
        for j in range(n_cols):
            for a in range(n_cols):
                for b in range(n_cols):
                    if len({j, a, b}) < 3:
                        continue
                    common = [i for i in vals[j] if vals[j][i] is not None and vals[a].get(i) is not None and vals[b].get(i) is not None and (vals[a][i] or vals[b][i])]
                    if len(common) >= 4 and all(abs(vals[j][i] - (vals[a][i] - vals[b][i])) <= 2.0 for i in common):
                        if (ti, j) not in ambiguous:
                            ambiguous.add((ti, j))
                            stats["columns refused: equal to the difference of two other columns"] += 1
    for key, cols in claims.items():
        if len(cols) < 2:
            continue
        vals = [{normalize.label(x[0]): x[4] for x in rows_of(d["tables"][ti], j)} for ti, j in cols]
        if any(abs(a[k] - b[k]) > 1e-6 for a in vals for b in vals for k in a.keys() & b.keys()):
            ambiguous.update(cols)
            stats["columns refused: same period and scope, different values"] += len(cols)
    for ti, t in enumerate(d["tables"]):
        stmt = t.get("stmt")
        if t.get("deferred") or stmt not in ("IS", "OCI", "BS", "CF") or not t.get("columns"):
            continue
        status = checks.column_status(t)
        for j, col in enumerate(t["columns"]):
            if status.get(j) != "PASS":
                refused[f"{stmt} column {status.get(j)}"] += 1
                continue
            if (ti, j) in ambiguous or (ti, j) in alternate_currency:
                continue
            lines = rows_of(t, j)
            if col.get("unit_known") is False:
                deferred.append((cid, doc, stmt, col, lines))
                continue
            if load_column(cid, doc, stmt, col, lines, col.get("unit") or 1, seen):
                doc_tables[doc].add(stmt)
                if t.get("extractor") == "ocr":
                    doc_ocr.add(doc)
                if t.get("extractor") == "vision" or col.get("unit_source") == "vision":
                    doc_vision.add(doc)
    if n_file % 500 == 0:
        con.commit()
        print(n_file, "documents", dict(stats), flush=True)
con.commit()

# Restrict comparative-unit lookups by company and scope instead of scanning every fact.
con.execute("CREATE INDEX IF NOT EXISTS ix_fact_company_scope_period ON financial_fact(company_id, entity_scope, period_id)")

# Columns printed with no unit: find the unit from the same lines in the company's other reports.
for cid, doc, stmt, col, lines in deferred:
    kind = "INSTANT" if stmt == "BS" else "DURATION"
    # Each other report is a separate witness: a later report can restate the comparatives, so figures from
    # different reports are never mixed. Within a report, lines are matched on section and label (one label can be
    # printed under two sections, e.g. a lease liability under non-current and current liabilities), else on the
    # label alone when it has one value there. A report proves a scale when at least 3 lines all give it.
    other = collections.defaultdict(dict)
    by_label = collections.defaultdict(lambda: collections.defaultdict(set))
    for odoc, section, n_label, val in con.execute("""SELECT f.document_id, rl.section, rl.normalized_label, f.value FROM financial_fact f JOIN reported_label rl USING (label_id)
            JOIN reporting_period p USING (period_id) WHERE f.company_id=? AND f.document_id<>? AND f.entity_scope=? AND p.end_date=?
            AND p.period_kind=? AND COALESCE(p.months,0)=? AND f.currency=?""",
                                    (cid, doc, col["scope"], col["date"], kind, col.get("months") or 0 if kind == "DURATION" else 0, col.get("currency") or "LKR")):
        other[odoc][(section, n_label)] = val
        by_label[odoc][n_label].add(val)
    proven = set()
    for odoc in other:
        ratios = []
        for raw, _, section, _, v in lines:
            if not v or PER_SHARE.search(raw):
                continue
            n = normalize.label(raw)
            o = other[odoc].get((section, n))
            if o is None and len(by_label[odoc].get(n, ())) == 1:
                o = next(iter(by_label[odoc][n]))
            if o is not None:
                ratios.append(o / v)
        for scale in (1, 1000, 1000000):
            if len(ratios) >= 3 and all(abs(r / scale - 1) < 0.002 for r in ratios):
                proven.add(scale)
    # Two reports proving different scales contradict each other: nothing is proven.
    choice = proven.pop() if len(proven) == 1 else None
    if choice is None:
        refused[f"{stmt} column refused: no unit printed and none provable from other reports"] += 1
        continue
    stats[f"unit proven from other reports: x{choice}"] += 1
    if load_column(cid, doc, stmt, col, lines, choice, {}):
        doc_tables[doc].add(stmt)

for f in files:
    doc = int(pathlib.Path(f).stem)
    got = doc_tables.get(doc, set())
    status = "EXTRACTED" if {"IS", "BS"} <= got else "PARTIAL" if got else "FAILED"
    extractor = "pymupdf+vision" if doc in doc_vision else "pymupdf+ocr" if doc in doc_ocr else "pymupdf"
    con.execute("UPDATE report_document SET extraction_status=?, extractor=? WHERE document_id=?", (status, extractor, doc))
con.commit()
print("documents with OCR figures", len(doc_ocr), "with vision figures", len(doc_vision))
print("documents", len(files), dict(stats))
print("refused columns", dict(refused))
print("status", con.execute("SELECT category, extraction_status, COUNT(*) FROM report_document WHERE extraction_status<>'PENDING' GROUP BY 1,2").fetchall())
print("labels", con.execute("SELECT COUNT(*), SUM(line_item_id IS NOT NULL) FROM reported_label").fetchone(),
      "facts mapped", con.execute("SELECT COUNT(*), SUM(rl.line_item_id IS NOT NULL) FROM financial_fact f JOIN reported_label rl USING(label_id)").fetchone())

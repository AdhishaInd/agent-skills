"""Load parsed statements into financial_fact. Only columns that pass their arithmetic checks are loaded.

Rebuilds statement data from scratch each run: financial_fact, reported_label and reporting_period.
Usage: python -I pipeline/load_facts.py <db> <extracted_dir>
"""
import math, statistics, collections
import calendar
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
con.execute(re.search(r"CREATE TABLE IF NOT EXISTS statement_check_flag \(.*?\n\);", pathlib.Path(__file__).resolve()
                      .parent.parent.joinpath("schema", "schema.sql").read_text(), re.S).group(0))
con.execute("DELETE FROM statement_check_flag")
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


CHECK_NOTES = []   # (cid, doc, stmt, col, misses, accepted reasons) for loaded columns whose checks were not exact


def note_checks(cid, doc, stmt, col, t, j):
    """Record a loaded column that passed only within the rounding tolerance, or by a reviewed acceptance."""
    mine = [c for c in (t.get("checks") or []) if c[1] == j and c[4]]
    misses = [(c[0], abs(c[2] - c[3]), c[5][len("accepted: "):] if len(c) > 5 else None) for c in mine if abs(c[2] - c[3]) > 1e-6]
    if misses:
        CHECK_NOTES.append((cid, doc, stmt, dict(col), misses))


def load_column(cid, doc, stmt, col, lines, unit, seen):
    # A report cannot hold figures for a period ending after its own period end: such a date was misread.
    end = DOC_END.get(doc)
    # Compared by month: periods are dated at month end, and some companies close on the 25th (UCAR).
    if end and col["date"][:7] > end[:7]:
        refused[f"{stmt} column dated after the report's own period end"] += 1
        return 0
    kind = "INSTANT" if stmt == "BS" else "DURATION"
    months = None if kind == "INSTANT" else col.get("months")
    if kind == "DURATION" and col.get("date"):
        # durations are stored at month end; a company closing on the 25th (UCAR) prints the 25th
        d = dt.date.fromisoformat(col["date"])
        last = calendar.monthrange(d.year, d.month)[1]
        if 24 <= d.day < last:
            col = dict(col, date=dt.date(d.year, d.month, last).isoformat())
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
                deferred.append((cid, doc, stmt, col, lines, ti))
                continue
            if load_column(cid, doc, stmt, col, lines, col.get("unit") or 1, seen):
                note_checks(cid, doc, stmt, col, t, j)
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
table_scale = collections.defaultdict(set)   # (doc, table) -> scales proven for its columns (one printed unit)
unproven = []
for cid, doc, stmt, col, lines, ti in deferred:
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
        unproven.append((cid, doc, stmt, col, lines, ti))
        continue
    table_scale[(doc, ti)].add(choice)
    stats[f"unit proven from other reports: x{choice}"] += 1
    if load_column(cid, doc, stmt, col, lines, choice, {}):
        doc_tables[doc].add(stmt)
# A cash flow with no unit, in a report whose other statements loaded with a known unit: the cash flow repeats
# some of their figures (profit before tax from the income statement). An exact match on a sizeable figure at the
# same date, length and scope proves the scale.
CROSS = {"profit before tax", "profit before taxation", "profit before income tax", "loss before tax",
         "profit loss before tax", "profit loss before taxation", "profit loss before income tax",
         "loss before taxation", "loss before income tax"}
still = []
for cid, doc, stmt, col, lines, ti in unproven:
    if stmt != "CF":
        still.append((cid, doc, stmt, col, lines, ti)); continue
    same = {}
    for n_label, val in con.execute("""SELECT rl.normalized_label, f.value FROM financial_fact f JOIN reported_label rl USING (label_id)
            JOIN reporting_period p USING (period_id) WHERE f.document_id=? AND rl.statement_type_id IN (1, 2) AND f.entity_scope=?
            AND p.end_date=? AND p.months=? AND f.currency=?""", (doc, col["scope"], col["date"], col.get("months") or 0, col.get("currency") or "LKR")):
        if n_label in CROSS:
            same[n_label] = val
    found = set()
    for raw, _, section, _, v in lines:
        n = normalize.label(raw)
        if n in CROSS and v and abs(v) >= 10000 and n in same:
            for scale in (1, 1000, 1000000):
                if abs(same[n] / (v * scale) - 1) < 1e-6:
                    found.add(scale)
    if len(found) != 1:
        still.append((cid, doc, stmt, col, lines, ti)); continue
    choice = found.pop()
    table_scale[(doc, ti)].add(choice)
    stats[f"cash flow unit proven by the same report's profit before tax: x{choice}"] += 1
    if load_column(cid, doc, stmt, col, lines, choice, {}):
        doc_tables[doc].add(stmt)
unproven = still
# A table has one printed unit: a column no other report covers (usually the current period) takes the scale proven
# for another column of the same table.
for cid, doc, stmt, col, lines, ti in unproven:
    scales = table_scale.get((doc, ti), set())
    if len(scales) != 1:
        refused[f"{stmt} column refused: no unit printed and none provable from other reports"] += 1
        continue
    choice = next(iter(scales))
    stats[f"unit proven by another column of the same table: x{choice}"] += 1
    if load_column(cid, doc, stmt, col, lines, choice, {}):
        doc_tables[doc].add(stmt)

# Stated units checked against the company's other reports. Arithmetic checks pass at any scale, so a header that
# says Rs.'000 over figures printed in rupees (REEF 48796) loads 1000x too large unseen. A column is suspect when
# its lines sit >= 300x (or <= 1/300) from the same lines' median in the company's other reports (amounts per month
# for periods). A suspect column is rescaled only when another report proves the exact figures at one other scale
# (>= 3 lines, within 0.2%), as for columns printed without a unit; otherwise its facts are removed.
def unit_sanity(statements=(1, 2, 3, 4)):
    per_month = lambda v, m: abs(v) / (m or 1)
    level = collections.defaultdict(list)    # (cid, scope, currency, kind, label) -> [(doc, size)]
    cols = collections.defaultdict(list)     # one statement column: (cid, doc, statement, pid, scope, currency)
    for fid, cid, doc, pid, scope, cur, lid, v, m, kind, nl, sec, raw, st in con.execute("""
            SELECT f.fact_id, f.company_id, f.document_id, f.period_id, f.entity_scope, f.currency, f.label_id, f.value,
                   p.months, p.period_kind, rl.normalized_label, rl.section, rl.raw_label, rl.statement_type_id
            FROM financial_fact f JOIN reporting_period p USING (period_id) JOIN reported_label rl USING (label_id)
            WHERE f.value <> 0 AND rl.statement_type_id IN (1, 2, 3, 4)"""):
        if PER_SHARE.search(raw):
            continue
        level[(cid, scope, cur, kind, lid)].append((doc, per_month(v, m)))
        cols[(cid, doc, st, pid, scope, cur)].append((fid, lid, v, m, kind, nl, sec, raw))
    suspects, col_r = [], {}
    for key, facts in cols.items():
        cid, doc, st, pid, scope, cur = key
        if st not in statements:
            continue
        ratios = []
        for fid, lid, v, m, kind, *_ in facts:
            others = [x for d, x in level[(cid, scope, cur, kind, lid)] if d != doc]
            if len(others) >= 3:
                ratios.append(per_month(v, m) / statistics.median(others))
        if len(ratios) >= 3:
            r = statistics.median(ratios)
            col_r[key] = r
            if not 1 / 300 < r < 300:
                suspects.append((key, facts, r, len(ratios)))
    suspect_keys = {x[0] for x in suspects}
    proven_in = collections.defaultdict(set)   # (doc, statement) -> scales proven for a column of that table
    decided = {}
    for key, facts, r, n in suspects:
        cid, doc, st, pid, scope, cur = key
        kind, months = facts[0][4], facts[0][3]
        end = con.execute("SELECT end_date FROM reporting_period WHERE period_id=?", (pid,)).fetchone()[0]
        proven = set()
        for odoc, in con.execute("SELECT DISTINCT document_id FROM financial_fact WHERE company_id=? AND document_id<>?", (cid, doc)):
            if (cid, odoc, st, pid, scope, cur) in suspect_keys:
                continue   # a report flagged for the same column is no witness: wrong reports can agree
            o = {}
            for sec, nl, val in con.execute("""SELECT rl.section, rl.normalized_label, f.value FROM financial_fact f JOIN reported_label rl USING (label_id)
                    JOIN reporting_period p USING (period_id) WHERE f.document_id=? AND f.entity_scope=? AND f.currency=? AND p.end_date=?
                    AND p.period_kind=? AND COALESCE(p.months,0)=? AND rl.statement_type_id=?""", (odoc, scope, cur, end, kind, months or 0, st)):
                o[(sec, nl)] = val
            rs = [o[(sec, nl)] / v for _, _, v, _, _, nl, sec, raw in facts if (sec, nl) in o]
            for scale in (1, 1000, 1000000, 0.001, 0.000001):
                if len(rs) >= 3 and all(abs(x / scale - 1) < 0.002 for x in rs):
                    proven.add(scale)
        # Reports can disagree with each other (two wrong reports agree on the wrong scale). Take the proven scale
        # that brings the column to the company's usual level; with none near it, a report confirming the stated
        # scale keeps it (the company median may itself be misled by its own wrong reports).
        near = [k for k in proven if 1 / 30 < r * k < 30]
        decided[key] = (min(near, key=lambda k: abs(math.log(r * k))) if near else 1 if 1 in proven else None)
        if decided[key]:
            proven_in[(doc, st)].add(decided[key])
    changed_docs = set()
    for key, facts, r, n in suspects:
        cid, doc, st, pid, scope, cur = key
        k, how = decided[key], "exact figures in another report"
        calm = [col_r[c] for c in col_r if c[1] == doc and c[2] == st and c not in suspect_keys]
        if k is None and any(1 / 3 < r / x < 3 for x in calm):
            k = 1   # an unflagged column of the same table (one printed unit) sits at the same level
        if k == 1 or (k is None and 1 in proven_in[(doc, st)]):
            print(f"UNIT_SANITY doc={doc} stmt={st} period={pid} scope={scope} {cur} lines={n} median_ratio={r:.4g} -> "
                  "kept (stated unit confirmed by another report)", flush=True)
            continue
        if k is None and len(proven_in[(doc, st)]) == 1:
            # another column of the same table (one printed unit) was proven; take its scale if this column fits it
            k0 = next(iter(proven_in[(doc, st)]))
            if 1 / 3 < r * k0 < 3:
                k, how = k0, "same table's proven unit"
        if k is None and n < 5:
            continue   # too few comparable lines to overrule the printed unit
        changed_docs.add(doc)
        print(f"UNIT_SANITY doc={doc} stmt={st} period={pid} scope={scope} {cur} lines={n} median_ratio={r:.4g} -> "
              + (f"rescale x{k:g} ({how})" if k else "refuse"), flush=True)
        if k:
            con.executemany("UPDATE financial_fact SET value=ROUND(value*?, 4), unit_scale=unit_scale*? WHERE fact_id=?",
                            [(k, k, f[0]) for f in facts])
            stats[f"stated unit disproved by other reports: rescaled x{k:g}"] += 1
        else:
            con.executemany("DELETE FROM financial_fact WHERE fact_id=?", [(f[0],) for f in facts])
            refused["column refused: stated unit >=300x off the company's other reports, no proof of the right one"] += 1
            stats["facts"] -= len(facts)
    for doc in changed_docs:
        doc_tables[doc] = {s for s, in con.execute("""SELECT DISTINCT st.code FROM financial_fact f JOIN reported_label rl USING (label_id)
                JOIN statement_type st USING (statement_type_id) WHERE f.document_id=?""", (doc,))}
    con.commit()




def cf_matches_income_statement():
    """A cash flow starts from the same report's profit before tax. A cash flow column whose profit before tax is
    exactly 1000x (or 1/1000x, a million) the income statement's for the same report, period and scope was read at
    the wrong scale (KDL: cash flows printed in Rs.'000 under a bare 'Rs.' header): rescale the column."""
    rows = con.execute("""
        SELECT c.document_id, c.period_id, c.entity_scope, c.currency, c.value, i.value
        FROM financial_fact c JOIN reported_label rc ON rc.label_id = c.label_id
        JOIN financial_fact i ON i.document_id = c.document_id AND i.period_id = c.period_id
             AND i.entity_scope = c.entity_scope AND i.currency = c.currency
        JOIN reported_label ri ON ri.label_id = i.label_id JOIN line_item li ON li.line_item_id = ri.line_item_id
        WHERE rc.statement_type_id = 4 AND li.code = 'IS_PBT' AND c.value <> 0 AND abs(i.value) >= 10000
          AND (rc.normalized_label LIKE '%before tax%' OR rc.normalized_label LIKE '%before taxation%'
               OR rc.normalized_label LIKE '%before income tax%')""").fetchall()
    done, fixed = set(), {}
    for doc, pid, scope, cur, cv, iv in rows:
        if (doc, pid, scope, cur) in done:
            continue
        for k in (1000, 1000000, 0.001, 0.000001):
            if abs(iv / (cv * k) - 1) < 1e-6:
                done.add((doc, pid, scope, cur))
                ids = [r[0] for r in con.execute("""SELECT f.fact_id FROM financial_fact f JOIN reported_label rl USING (label_id)
                        WHERE f.document_id=? AND f.period_id=? AND f.entity_scope=? AND f.currency=? AND rl.statement_type_id=4""",
                                                 (doc, pid, scope, cur))]
                con.executemany("UPDATE financial_fact SET value=ROUND(value*?, 4), unit_scale=unit_scale*? WHERE fact_id=?",
                                [(k, k, i) for i in ids])
                stats[f"cash flow rescaled x{k:g} to match the same report's profit before tax"] += 1
                print(f"CF_SCALE doc={doc} period={pid} scope={scope} x{k:g} ({len(ids)} lines)", flush=True)
                fixed.setdefault(doc, set()).add(k)
                break
    # the report's other cash flow columns share the printed unit: give them the same scale
    for doc, ks in fixed.items():
        if len(ks) != 1:
            continue
        k = next(iter(ks))
        for pid, scope, cur in con.execute("""SELECT DISTINCT f.period_id, f.entity_scope, f.currency FROM financial_fact f
                JOIN reported_label rl USING (label_id) WHERE f.document_id=? AND rl.statement_type_id=4""", (doc,)).fetchall():
            if (doc, pid, scope, cur) in done:
                continue
            con.execute("""UPDATE financial_fact SET value=ROUND(value*?, 4), unit_scale=unit_scale*? WHERE fact_id IN
                    (SELECT f.fact_id FROM financial_fact f JOIN reported_label rl USING (label_id) WHERE f.document_id=?
                     AND f.period_id=? AND f.entity_scope=? AND f.currency=? AND rl.statement_type_id=4)""", (k, k, doc, pid, scope, cur))
            stats[f"cash flow rescaled x{k:g} with the same report's other columns"] += 1
            print(f"CF_SCALE doc={doc} period={pid} scope={scope} x{k:g} (same report)", flush=True)
    con.commit()


unit_sanity((1, 2, 3))         # income statements and balance sheets first (REEF's P&L is the wrong one, not its cash flow)
cf_matches_income_statement()  # then cash flows against their own report's profit before tax (KDL)
unit_sanity()                  # and once more, now that the company's corrected history is in place

# Flags for columns that passed within rounding or by acceptance, now that the final scales are known.
STMT_TYPES = {"IS": (1, 2), "OCI": (1, 2), "BS": (3,), "CF": (4,)}
for cid, doc, stmt, col, misses in CHECK_NOTES:
    kind = "INSTANT" if stmt == "BS" else "DURATION"
    end = col["date"]
    if kind == "DURATION":
        d_ = dt.date.fromisoformat(end)
        last_ = calendar.monthrange(d_.year, d_.month)[1]
        if 24 <= d_.day < last_:
            end = dt.date(d_.year, d_.month, last_).isoformat()
    pid = period_ids.get((cid, kind, end, None if kind == "INSTANT" else col.get("months")))
    if pid is None:
        continue
    st_ids = STMT_TYPES[stmt]
    scale = con.execute(f"""SELECT MAX(f.unit_scale) FROM financial_fact f JOIN reported_label rl USING (label_id)
                            WHERE f.document_id=? AND f.period_id=? AND f.entity_scope=?
                              AND rl.statement_type_id IN ({",".join("?" * len(st_ids))}) AND f.unit_scale IS NOT NULL""",
                        (doc, pid, col["scope"], *st_ids)).fetchone()[0]
    if scale is None:
        continue   # the column's facts were refused later (unit checks)
    for flag, group in (("ACCEPTED", [m for m in misses if m[2]]), ("ROUNDING", [m for m in misses if not m[2]])):
        if not group:
            continue
        con.execute("""INSERT OR REPLACE INTO statement_check_flag(company_id,document_id,period_id,entity_scope,statement,flag,
                       max_difference,checks,reason) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (cid, doc, pid, col["scope"], stmt, flag, max(m[1] for m in group) * scale,
                     "; ".join(f"{m[0]} {m[1]:g}" for m in group), group[0][2]))
        stats[f"columns flagged {flag}"] += 1
con.commit()

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

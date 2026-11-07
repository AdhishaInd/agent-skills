"""Create the database and load companies, securities, directors and the report index.

Usage (from the project root): python -I scripts/load_master.py <db> <schema.sql> <scripts_dir> <cache_dir>
API responses are cached as JSON, so reruns do not hit the CSE site again.
No PDFs are downloaded here.
"""
import calendar
import collections
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

db_path, schema_path, scripts_dir, cache_dir = sys.argv[1:5]
sys.path.insert(0, scripts_dir)
import normalize  # noqa: E402
import seed  # noqa: E402
sys.path.insert(0, str(pathlib.Path(scripts_dir).resolve().parent / "reviewed"))
import scan_readings  # noqa: E402

CACHE = pathlib.Path(cache_dir)
CACHE.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.cse.lk",
           "Content-Type": "application/x-www-form-urlencoded"}
COLOMBO = dt.timezone(dt.timedelta(hours=5, minutes=30))
CLASS_BY_SUFFIX = {"N": "VOTING", "X": "NON_VOTING", "U": "UNIT", "R": "RIGHTS", "P": "PREFERENCE", "W": "WARRANT"}
TEMPLATE_BY_SECTOR = {"Banks": "BANK", "Insurance": "INSURANCE", "Diversified Financials": "FINANCE"}
# CSE sector text is free-form. Strings too vague to place ("Trading", "Services", "Industrials",
# "Banks Finance & Insurance") are left NULL, with the original text kept in company.cse_sector_raw.
SECTOR_ALIASES = {
    "food beverage & tobacco": "Food, Beverage & Tobacco",
    "real estate (6010)": "Real Estate Management & Development",
    "real estate management&development": "Real Estate Management & Development",
    "real estate development": "Real Estate Management & Development",
    "power and energy": "Utilities",
    "independent power producers & energy traders": "Utilities",
    "investment banking & brokerage": "Diversified Financials",
    "diversified financial": "Diversified Financials",
    "diversified financial services": "Diversified Financials",
    "consumer finance": "Diversified Financials",
    "materials (1510)": "Materials",
    "45103010 - application software": "Software & Services",
    "capital goods.": "Capital Goods",
    "healthcare equipment & services": "Health Care Equipment & Services",
    "- property & casualty insurance": "Insurance",
    "multi-line insurance": "Insurance",
}
MONTHS = {m: i for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def clean_sector(raw, by_lower):
    key = " ".join((raw or "").split()).lower()
    return SECTOR_ALIASES.get(key) or by_lower.get(key.replace("real estate management & development",
                                                               "real estate management & development"))


def period_end_from_title(title):
    """Return the ISO period-end date written in a report title, or None."""
    text = re.sub(r"\s+", " ", title or "")
    found = []
    for d, m, y in re.findall(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:of\s+)?([A-Za-z]{3,9})\.?,?\s*(\d{4})\b", text):
        found.append((y, MONTHS.get(m[:3].lower()), d))
    for m, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s*(\d{1,2})\s*(?:st|nd|rd|th)?,?\s*(\d{4})\b", text):
        found.append((y, MONTHS.get(m[:3].lower()), d))
    for d, m, y in re.findall(r"\b(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{4})\b", text):
        found.append((y, int(m), d))
    for y, m, d in re.findall(r"\b(\d{4})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{1,2})\b", text):
        found.append((y, int(m), d))
    for y, m, d in found:
        try:
            if m and 2000 <= int(y) <= dt.date.today().year + 1:  # rejects title typos such as 3013
                return dt.date(int(y), m, int(d)).isoformat()
        except ValueError:
            pass
    return None


def annual_end_from_title(title, fye_month):
    """Period end for titles with only a year, e.g. 'Annual Report 2023/2024' or 'Annual Report 2012'."""
    if not fye_month:
        return None
    text = title or ""
    pair = re.search(r"\b(20\d{2})\s*[-/]\s*(20\d{2}|\d{2})\b", text)
    single = re.search(r"\b(20\d{2})\b", text)
    if pair:
        tail = pair.group(2)
        year = int(tail) if len(tail) == 4 else int(pair.group(1)[:2] + tail)
    elif single:
        year = int(single.group(1))
    else:
        return None
    last_day = calendar.monthrange(year, fye_month)[1]
    return dt.date(year, fye_month, last_day).isoformat()


def api(endpoint, **params):
    key = endpoint + ("_" + re.sub(r"\W", "_", params["symbol"]) if "symbol" in params else "")
    cached = CACHE / f"{key}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    req = urllib.request.Request("https://www.cse.lk/api/" + endpoint,
                                 data=urllib.parse.urlencode(params).encode(), headers=HEADERS)
    for attempt in range(3):
        try:
            data = json.load(urllib.request.urlopen(req, timeout=40))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    cached.write_text(json.dumps(data))
    time.sleep(0.2)
    return data


def from_ms(ms, date_only=False):
    if not isinstance(ms, (int, float)):
        return None
    moment = dt.datetime.fromtimestamp(ms / 1000, COLOMBO)
    return moment.date().isoformat() if date_only else moment.isoformat(timespec="seconds")


def parse_issue_date(text):
    try:
        return dt.datetime.strptime(text.title(), "%d/%b/%Y").date().isoformat()
    except (AttributeError, ValueError):
        return None


def source_url(path):
    return "https://cdn.cse.lk/" + (path if path.startswith("cmt/") else "cmt/" + path)


con = sqlite3.connect(db_path)
con.executescript(pathlib.Path(schema_path).read_text())
seed.apply(con)
templates = dict(con.execute("SELECT code, template_id FROM reporting_template"))
today = dt.date.today().isoformat()

for s in api("allSectors"):
    if s["name"] not in ("ALL SHARE PRICE INDEX", "S&P SL20"):
        con.execute("INSERT OR IGNORE INTO sector(sector_id,name,cse_index_code) VALUES (?,?,?)",
                    (s["sectorId"], s["name"], s.get("indexCode")))
con.execute("UPDATE sector SET name='Real Estate Management & Development' WHERE name='Real Estate Management&Development'")
sectors = dict(con.execute("SELECT name, sector_id FROM sector"))
sectors_lower = {k.lower(): k for k in sectors}

def api_get(endpoint):
    cached = CACHE / f"{endpoint}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    req = urllib.request.Request("https://www.cse.lk/api/" + endpoint, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    data = json.load(urllib.request.urlopen(req, timeout=40))
    cached.write_text(json.dumps(data))
    return data


# Current securities plus delisted ones. Delisted companies keep their reports on the CDN.
delisted = api_get("deListedEntities")["content"]
delisted_symbols = {d["symbol"] for d in delisted}
securities = {s["symbol"]: s for s in api_get("allSecurityCode")}
for s in api("tradeSummary")["reqTradeSummery"] + delisted:
    securities.setdefault(s["symbol"], s)
securities = [securities[k] for k in sorted(securities, key=lambda x: (x in delisted_symbols, x))]
trading_status = {}
for endpoint, key in (("main_boards", "reqMainBoards"), ("secondBoard", "reqSecondBoards"), ("default_board", "reqDefaultBoards"),
                      ("empower_boards", "reqEmpowerBoards"), ("divi_siri_board", "reqDirisaviBoards")):
    for row in api(endpoint)[key]:
        trading_status[row["symbol"]] = row.get("tradingStatus")
errors, seen_docs, seen_companies = [], 0, set()
dropped_docs, dropped_officers, ticker_conflicts, name_conflicts = [], [], [], []
stubs = {}
code_list = {c["symbol"]: c for c in api_get("cntSecurity")["content"]}
for n, sec in enumerate(securities, 1):
    symbol = sec["symbol"]
    def optional(endpoint, default):
        try:
            return api(endpoint, symbol=symbol)
        except Exception as exc:
            stubs[symbol] = str(exc)[:40]
            return default

    info = optional("companyInfoSummery", {}).get("reqSymbolInfo") or {}
    profile = optional("companyProfile", {})
    fin = optional("financials", {})
    for key in ("infoQuarterlyData", "infoAnnualData", "infoOtherData"):
        fin.setdefault(key, [])
    summary = (profile.get("reqComSumInfo") or [None])[0]
    if not summary:
        # CSE no longer serves a profile for some delisted securities; its code list still has id and name.
        known = code_list.get(symbol.split(".")[0])
        if not known:
            errors.append((symbol, "no company summary or code-list entry"))
            continue
        summary = {"securityId": known["securityId"], "name": known["name"]}
    company_id = summary["securityId"]

    if company_id not in seen_companies:
        seen_companies.add(company_id)
        sector = clean_sector(summary.get("sector"), sectors_lower) or ""
        unit_fund = symbol.split(".")[-1].startswith("U") and "." in symbol
        template = "FUND" if unit_fund else TEMPLATE_BY_SECTOR.get(sector, "GENERAL")

        # CSE's manualDate and finYearEnd are unreliable, so use the dates written in annual report titles.
        months = [end[5:7] for end in (period_end_from_title(a.get("fileText")) for a in fin["infoAnnualData"]) if end]
        fye = int(collections.Counter(months).most_common(1)[0][0]) if months else None
        if fye is None:
            fye = {"1": 3, "2": 12}.get(str(summary.get("finYearEnd")))
        established = re.search(r"\d{4}", summary.get("established") or "")
        about = " ".join((b.get("body") or "").strip() for b in profile.get("infoCompanyBusinessSummary") or [])
        ticker, company_name = symbol.split(".")[0], " ".join(summary["name"].split())
        if con.execute("SELECT 1 FROM company WHERE ticker=?", (ticker,)).fetchone():
            ticker_conflicts.append((symbol, company_id, company_name))
            ticker = f"{ticker}#{company_id}"
        if con.execute("SELECT 1 FROM company WHERE name=? COLLATE NOCASE", (company_name,)).fetchone():
            name_conflicts.append((symbol, company_id, company_name))
            company_name = f"{company_name} [{ticker}]"
        con.execute(
            """INSERT INTO company(company_id,ticker,name,sector_id,cse_sector_raw,template_id,board_type,listing_status,trading_status,established_year,
               fiscal_year_end_month,registered_office,phone,fax,email,website,secretaries,auditors,
               business_summary,fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (company_id, ticker, company_name, sectors.get(sector), summary.get("sector"), templates[template],
             summary.get("boardType"), "DELISTED" if symbol in delisted_symbols else "LISTED", trading_status.get(symbol), int(established.group()) if established else None, fye,
             summary.get("registeredOffice") or summary.get("registerOffice"), summary.get("tel1"),
             summary.get("fax"), summary.get("email1"), summary.get("web"), summary.get("secretaries"),
             summary.get("auditors"), about or None, today))

        for d in profile.get("infoCompanyDirector") or []:
            first, last = d.get("firstName") or "", (d.get("lastName") or "").strip()
            role = re.search(r"\((.*)\)", first)
            designation = role.group(1).strip() if role else None
            name = " ".join((re.sub(r"\(.*\)", "", first).strip() + " " + last).split())
            low = (designation or "").lower()
            executive = None if not low else int("non-executive" not in low and "non executive" not in low
                                                   and "executive" in low)
            independent = None if not low else int("independent" in low and "non independent" not in low
                                                    and "non-independent" not in low)
            key = normalize.name(name)
            if not key:
                continue
            # One person per exact name; CSE's id identifies the directorship.
            con.execute("INSERT OR IGNORE INTO person(full_name,normalized_name) VALUES (?,?)", (name, key))
            pid = con.execute("SELECT person_id FROM person WHERE normalized_name=?", (key,)).fetchone()[0]
            cur = con.execute("""INSERT OR IGNORE INTO company_officer(company_id,person_id,cse_director_id,designation,
                           is_executive,is_independent,as_of_date) VALUES (?,?,?,?,?,?,?)""",
                        (company_id, pid, d.get("directorId"), designation, executive, independent, today))
            if cur.rowcount == 0:
                dropped_officers.append((symbol, name))

        for category, rows in (("INTERIM", fin["infoQuarterlyData"]), ("ANNUAL", fin["infoAnnualData"]),
                               ("OTHER", fin["infoOtherData"])):
            for r in rows:
                if not r.get("path"):
                    continue
                end = period_end_from_title(r.get("fileText"))
                if end is None and category == "ANNUAL":
                    end = annual_end_from_title(r.get("fileText"), fye)
                cur = con.execute(
                    """INSERT OR IGNORE INTO report_document(document_id,company_id,category,title,source_url,
                       period_end_date,cse_manual_date,uploaded_at,authorized_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (r["id"], company_id, category, (r.get("fileText") or "").strip() or "(untitled)",
                     source_url(r["path"]), end, from_ms(r.get("manualDate"), True),
                     from_ms(r.get("uploadedDate")), from_ms(r.get("authorizedDate"))))
                if cur.rowcount == 0:
                    dropped_docs.append((symbol, r["id"], (r.get("fileText") or "").strip()))
                seen_docs += 1

    suffix = symbol.split(".")[1][0] if "." in symbol else ""
    isin = info.get("isin")
    if isin and con.execute("SELECT 1 FROM security WHERE isin=?", (isin,)).fetchone():
        isin = None
    status = "DELISTED" if symbol in delisted_symbols else "LISTED"
    if status == "LISTED":   # a company is listed if any of its securities is
        con.execute("UPDATE company SET listing_status='LISTED' WHERE company_id=?", (company_id,))
    con.execute("""INSERT INTO security(security_id,company_id,symbol,isin,share_class,listing_status,par_value,issue_date,
                   quantity_issued) VALUES (?,?,?,?,?,?,?,?,?)""",
                (sec["id"], company_id, symbol, isin, CLASS_BY_SUFFIX.get(suffix, "OTHER"), status,
                 info.get("parValue"), parse_issue_date(info.get("issueDate")), info.get("quantityIssued")))
    if n % 40 == 0:
        con.commit()
        print(f"{n}/{len(securities)} securities", flush=True)

# Official index membership beats the free-text profile field. Tested: 250 of 257 agreed.
members = json.loads((CACHE / "sector_members.json").read_text()) if (CACHE / "sector_members.json").exists() else {}
all_sectors = {k.replace(" ", "").lower(): v for k, v in dict(con.execute("SELECT name, sector_id FROM sector")).items()}
con.execute("UPDATE company SET sector_source='COMPANY_PROFILE' WHERE sector_id IS NOT NULL")
for sym, names in members.items():
    sid = next((all_sectors.get(n.replace(" ", "").lower()) for n in names if n.replace(" ", "").lower() in all_sectors), None)
    row = con.execute("SELECT company_id FROM security WHERE symbol=?", (sym,)).fetchone()
    if sid and row:
        con.execute("UPDATE company SET sector_id=?, sector_source='OFFICIAL_INDEX' WHERE company_id=?", (sid, row[0]))
fund = templates["FUND"]
for cid, tk, sname, tid in con.execute("""SELECT c.company_id, c.ticker, s.name, c.template_id FROM company c LEFT JOIN sector s USING (sector_id)""").fetchall():
    if tid != fund:
        con.execute("UPDATE company SET template_id=? WHERE company_id=?", (templates[TEMPLATE_BY_SECTOR.get(sname, "GENERAL")], cid))
for tk, code in scan_readings.TEMPLATE_OVERRIDE.items():
    con.execute("UPDATE company SET template_id=? WHERE ticker=?", (templates[code], tk))
for old, new in scan_readings.SUCCESSOR.items():
    con.execute("UPDATE company SET successor_company_id=? WHERE company_id=?", (new, old))
con.commit()
print("sector source:", con.execute("SELECT sector_source, COUNT(*) FROM company GROUP BY 1").fetchall())
print("errors:", len(errors), errors[:10])
print("documents refused as duplicates:", dropped_docs)
print("securities with partial data from CSE:", sorted(stubs))
print("ticker conflicts:", ticker_conflicts)
print("name conflicts:", name_conflicts)
print("listing:", con.execute("SELECT listing_status, COUNT(*) FROM company GROUP BY 1").fetchall(),
      con.execute("SELECT share_class, listing_status, COUNT(*) FROM security GROUP BY 1,2").fetchall())
print("trading status:", con.execute("SELECT trading_status, COUNT(*) FROM company GROUP BY 1").fetchall())
print("officer rows refused as duplicates:", dropped_officers)
for t in ("sector", "company", "security", "person", "company_officer", "report_document", "line_item", "label_alias"):
    print(t, con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
print("template", con.execute("""SELECT t.code, COUNT(*) FROM company c JOIN reporting_template t USING(template_id)
                                 GROUP BY 1""").fetchall())
print("category", con.execute("SELECT category, COUNT(*) FROM report_document GROUP BY 1").fetchall())
print("no sector", con.execute("SELECT COUNT(*) FROM company WHERE sector_id IS NULL").fetchone()[0],
      "no fiscal month", con.execute("SELECT COUNT(*) FROM company WHERE fiscal_year_end_month IS NULL").fetchone()[0])
print("no reports", con.execute("""SELECT COUNT(*) FROM company c WHERE NOT EXISTS
                                   (SELECT 1 FROM report_document d WHERE d.company_id=c.company_id)""").fetchone()[0])
print("fiscal months", con.execute("SELECT fiscal_year_end_month, COUNT(*) FROM company GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("date range", con.execute("SELECT MIN(period_end_date), MAX(period_end_date) FROM report_document").fetchone())
print("period end from title", con.execute("""SELECT category, COUNT(period_end_date), COUNT(*) FROM report_document GROUP BY 1""").fetchall())
print("sector NULL:", con.execute("SELECT ticker, cse_sector_raw FROM company WHERE sector_id IS NULL").fetchall())
print("JKH/COMB fiscal", con.execute("SELECT ticker, fiscal_year_end_month FROM company WHERE ticker IN ('JKH','COMB','ABAN','CINS','HPL','JXG')").fetchall())

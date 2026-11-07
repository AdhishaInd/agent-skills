"""Works out what each numeric column means and reads rows into values."""
import calendar
import datetime as dt
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import normalize  # noqa: E402
from tokens import *  # noqa: F401,F403,E402
from tokens import MON, MONTHS, DASH, CUM, _iso, period_sign, month_range, date_range, day_month  # noqa: E402


def find_columns(rows, tol=11):
    """Cluster right edges of numeric tokens. Returns column right edges, keeping those used by several rows."""
    xs = [right_edge(w) for r in rows for w in r if is_num(w[4]) and (len(w[4]) >= 3 or "," in w[4] or "." in w[4]) or w[4] in DASH and False]
    if not xs:
        return []
    xs.sort()
    clusters, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= tol and x - cur[0] <= 2.2 * tol:
            cur.append(x)
        else:
            clusters.append(cur)
            cur = [x]
    clusters.append(cur)
    need = max(3, int(0.12 * len([r for r in rows if any(is_num(w[4]) for w in r)])))
    return [sum(c) / len(c) for c in clusters if len(c) >= need]


def assign_marks(marks, cols):
    """Give each column the value of the header mark above it. marks: [(x_centre, value)], left to right.
    Equal blocks are used when the marks sit over them, e.g. Group | Group | % | Bank | Bank | %."""
    marks = sorted(marks)
    n, k = len(cols), len(marks)
    if k == 1:
        return [marks[0][1]] * n
    if n % k == 0:
        size = n // k
        spans = [(cols[i * size]["x"] - 70, cols[i * size + size - 1]["x"] + 25) for i in range(k)]
        if all(a <= m[0] <= b for m, (a, b) in zip(marks, spans)):
            return [marks[i // size][1] for i in range(n)]
    out = []
    for c in cols:
        x = c["x"] - 20
        out.append(min(marks, key=lambda m: abs(m[0] - x))[1])
    return out


def interpret_columns(rows, ctx, title):
    """Work out what each numeric column means from the rows above the first data row."""
    edges = find_columns(rows)
    if not edges:
        return None, ["no numeric columns"]
    first = None
    for i, r in enumerate(rows):
        nums = [w for w in r if is_num(w[4]) and (re.search(r",\d{3}(?:\D|$)", w[4]) or len(w[4].strip("()-")) >= 5)]
        lab = [w for w in r if not is_num(w[4])]
        if len(nums) >= 1 and lab and not parse_date(text_of(r)):
            first = i
            break
    if first is None:
        return None, ["no data rows"]
    head = rows[:first]
    head_text = " ".join(text_of(r) for r in head)
    cols = [dict(x=x, scope=None, date=None, months=None, audit="UNKNOWN", change=False, note=False, unit=None) for x in edges]

    def nearest(cx):
        return min(range(len(cols)), key=lambda j: abs(cols[j]["x"] - cx))

    scope_marks, year_marks, month_marks, dm_marks = [], [], {}, {}
    label_signs = []  # period words in the label area, e.g. 'For the period ended 31 December'
    left = cols[0]["x"] - 75
    single_date = re.compile(r"^\(?\d{1,2}[./-](?:\d{1,2}|[A-Za-z]{3})[./-]\d{2,4}\)?$")
    year_re = re.compile(r"\(?(20\d\d)\)?(?:\s*/\s*(\d{2,4}))?")
    unit_words = re.compile(r"(?i)\(?\b(?:rs|lkr|usd)\b\.?\)?|'?\s*000'?s?\b|\(?\b(?:un\s*-?\s*)?audited\b\)?|\(?\brestated\b\)?")
    month_only_headers = []
    range_starts = {}
    fiscal_year_columns = set()
    # A period length can be stacked: 'Three' above 'Months Ended', or 'Year' above 'ended'. Join only a bare
    # number word (or Year/Quarter) with the fragment on the next header row, centred within 40 points of it.
    stacked = {}
    num_word = re.compile(r"(?i)\(?(?:three|six|nine|twelve|0?3|0?6|0?9|12)\)?(?:\s*\(\d{1,2}\))?")
    for i in range(len(head) - 1):
        for x0, x1, t in chunks(head[i]):
            if num_word.fullmatch(t.strip()):
                below_word = r"(?i)months?\b"
            elif re.fullmatch(r"(?i)year|quarter", t.strip()):
                below_word = r"(?i)end(?:ed|ing)\b"
            else:
                continue
            below = [(bx0, bt) for bx0, bx1, bt in chunks(head[i + 1])
                     if re.match(below_word, bt.strip()) and abs((bx0 + bx1) / 2 - (x0 + x1) / 2) <= 40]
            if len(below) == 1:
                stacked[(i + 1, round(below[0][0]))] = t.strip() + " " + below[0][1]
    for header_row, r in enumerate(head):
        # A date can wrap vertically: 'December' above '31, 2024'. Match only
        # neighbouring, horizontally aligned month-only and day/year fragments.
        for x0, x1, t in chunks(r):
            j = _col_for(cols, x1)
            printed_date = parse_date(t)
            if j is not None and printed_date:
                if re.search(r"\bto\s*\)?$", t, re.I):
                    range_starts[j] = (header_row, printed_date)
                elif j in range_starts and 0 < header_row - range_starts[j][0] <= 2:
                    start = dt.date.fromisoformat(range_starts[j][1]).strftime("%d/%m/%Y")
                    end = dt.date.fromisoformat(printed_date).strftime("%d/%m/%Y")
                    rg = date_range(f"{start} to {end}")
                    if rg:
                        cols[j]["date"], cols[j]["months"] = rg
            if re.fullmatch(rf"{MON}\.?", t.strip(), re.I):
                month_only_headers.append((header_row, (x0 + x1) / 2, MONTHS[t.strip().rstrip(".").lower()], x1))
            # 'December 24' over a column: a two-digit year, never a day, since a period never ends on the 24th.
            # Accept only when the number is not the month's last day and is within 3 years of the report.
            my = re.fullmatch(rf"({MON})\.?\s*[’']?(\d{{2}})", t.strip(), re.I)
            if my and j is not None and ctx.get("period_end"):
                mo, yy = MONTHS[my.group(1).lower()], 2000 + int(my.group(2))
                if int(my.group(2)) != calendar.monthrange(yy, mo)[1] and abs(yy - int(ctx["period_end"][:4])) <= 3:
                    cols[j]["date"] = _iso(yy, mo, calendar.monthrange(yy, mo)[1])
            dy = re.fullmatch(r"(\d{1,2}),?\s+(20\d\d)", t.strip())
            if dy:
                cx = (x0 + x1) / 2
                aligned = {mo for row, mx, mo, _ in month_only_headers if 0 < header_row - row <= 2 and abs(mx - cx) <= 35}
                j = _col_for(cols, x1)
                if len(aligned) == 1 and j is not None:
                    cols[j]["date"] = _iso(int(dy.group(2)), aligned.pop(), int(dy.group(1)))
        # Dates printed as one word are placed by their own position before words are grouped, so a date printed
        # close to a 'Variance' heading is not carried over to the variance column.
        rest = []
        # Recover only years joined to a neighbouring change heading. Other year
        # fragments (especially split fiscal years) retain their normal parsing.
        joined_years = []
        for x0, x1, t in chunks(r):
            without_change = re.sub(r"(?i)\b(?:change|variance|growth|chg)\b|%", " ", t)
            if without_change != t and year_re.fullmatch(unit_words.sub(" ", without_change).strip()):
                joined_years.append((x0, x1))
        for w in r:
            if re.fullmatch(r"\(?20\d\d\)?", w[4]) and any(x0 <= w[0] and w[2] <= x1 for x0, x1 in joined_years):
                j = _col_for(cols, w[2])
                if j is not None:
                    year_marks.append((j, int(w[4].strip("()")), None))
            if single_date.match(w[4]) and parse_date(w[4]):
                j = _col_for(cols, w[2])
                if j is not None:
                    cols[j]["date"] = parse_date(w[4])
                continue
            rest.append(w)
        r = rest
        for x0, x1, t in chunks(r):
            t = stacked.get((header_row, round(x0)), t)
            cx = (x0 + x1) / 2
            if scope_word(t):
                scope_marks.append((cx, scope_word(t)))
                continue
            if x1 < left:
                # label area: says something about the whole table
                sg = period_sign(t)
                if sg:
                    label_signs.append(sg)
                if day_month(t) and not parse_date(t):
                    dm_marks.setdefault("label", []).append((cx, day_month(t)))
                continue
            # a span of dates gives the end date and the length, e.g. '01.04.2024 to 31.12.2024'
            rg = date_range(t)
            if rg and x1 - x0 < 170:
                j = _col_for(cols, x1)
                if j is not None:
                    cols[j]["date"] = rg[0]
                    cols[j]["months"] = cols[j]["months"] or rg[1]
                continue
            # one fragment can hold several columns, e.g. 'Group Company' or '30.06.2026 31.03.2026'
            d = parse_date(t)
            if d and x1 - x0 < 110:
                j = _col_for(cols, x1)
                if j is not None:
                    cols[j]["date"] = d
                    m_here = months_in(t)
                    if m_here:
                        cols[j]["months"] = m_here
                continue
            # a year, alone or printed with the unit, e.g. '2024', '(2023)', "Rs. '000 2026", '2024/25'
            ym = year_re.fullmatch(unit_words.sub(" ", t).strip())
            if ym:
                j = _col_for(cols, x1)
                if j is not None:
                    year_marks.append((j, int(ym.group(1)), ym.group(2)))
                if ym.group(0) == t.strip():
                    continue
            low = t.lower()
            if re.search(r"change|chg|growth|variance|\bvar\b|movement|inc\s*/|\(dec|^%$|^\(?%\)?$|increase", low):
                j = _col_for(cols, x1)
                if j is not None:
                    cols[j]["change"] = True
                continue
            if re.fullmatch(r"\W*notes?\W*", low):
                j = _col_for(cols, x1, slack=25)
                if j is not None:
                    cols[j]["note"] = True
                continue
            sg = period_sign(t)
            if sg:
                month_marks.setdefault(header_row, []).append((cx, sg, x0, x1))
            if not d:
                dmk = day_month(t)
                if not dmk:
                    mr = month_range(t)
                    dmk = (mr[0], None) if mr else None
                if dmk:
                    dm_marks.setdefault(header_row, []).append((cx, dmk, x0, x1))
            if re.search(r"un\s*-?audited|provisional", low) and x1 - x0 < 90:
                j = _col_for(cols, x1, slack=25)
                if j is not None:
                    cols[j]["audit"] = "UNAUDITED"
            elif re.search(r"audited", low) and x1 - x0 < 90:
                j = _col_for(cols, x1, slack=25)
                if j is not None:
                    cols[j]["audit"] = "AUDITED"
            u = unit_in(t)
            if u and x1 - x0 < 90:
                j = _col_for(cols, x1, slack=25)
                if j is not None:
                    cols[j]["unit"] = u

    def spread(marks, key):
        """Give columns the values of one header row's marks: by position when several, by span when one."""
        if len(marks) > 1:
            for c, v in zip(cols, assign_marks([(m[0], m[1]) for m in marks], cols)):
                # Marks above a subset of columns do not describe a distant
                # audited-year column or another period block.
                if not min(m[2] for m in marks) - 30 <= c["x"] <= max(m[3] for m in marks) + 50:
                    continue
                if c[key] is None or key == "months" and c[key] == CUM and isinstance(v, int):
                    c[key] = v
        else:
            # one mark: it covers the columns under it, or all of them if it is a full-width line
            cx, v, x0, x1 = marks[0]
            for c in cols:
                if (c[key] is None or key == "months" and c[key] == CUM and isinstance(v, int)) and (abs(c["x"] - cx) < 95 or x0 - 10 <= c["x"] - 30 and c["x"] <= x1 + 30):
                    c[key] = v

    for marks in month_marks.values():
        spread(marks, "months")
    for c in cols:
        c["dm"] = None
    # A month alone on the row over a year is the usual wrapped 'December' / '2024' header. A month printed
    # directly over a year column belongs to that column, so set it before day-month marks such as
    # '31st March' are spread over neighbouring columns by position.
    year_cols = {j for j, _, _ in year_marks}
    for _, mx, mo, mx1 in month_only_headers:
        j = _col_for(cols, mx1)
        if j in year_cols and cols[j]["dm"] is None:
            cols[j]["dm"] = (mo, None)
    for k, marks in dm_marks.items():
        if k != "label":
            spread(marks, "dm")

    # Otherwise keep the nearest printed month instead of the report's latest quarter.
    for j, _, _ in year_marks:
        if cols[j]["dm"] is None:
            near = [(abs(mx - (cols[j]["x"] - 20)), mo) for _, mx, mo, _ in month_only_headers]
            if near:
                distance = min(n[0] for n in near)
                months = {mo for dist, mo in near if dist <= distance + 2}
                if distance <= 50 and len(months) == 1:
                    cols[j]["dm"] = (months.pop(), None)

    # Year-only headers take day and month from the text over them, from nearby text, or the report's period end.
    dm = None
    if ctx.get("period_end"):
        pe = dt.date.fromisoformat(ctx["period_end"])
        dm = (pe.month, pe.day)
    m = None if dm else re.search(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({MON})\b", head_text + " " + title, re.I)
    if m:
        dm = (MONTHS[m.group(2).lower()], int(m.group(1)))
    elif dm is None:
        m = re.search(rf"\b({MON})\s+(\d{{1,2}})\b", head_text + " " + title, re.I)
        if m:
            dm = (MONTHS[m.group(1).lower()], int(m.group(2)))
    label_dm = {v for _, v in dm_marks.get("label", [])}
    if dm is None and len(label_dm) == 1:
        dm = label_dm.pop()
    fye = ctx.get("fye")
    pe_iso = ctx.get("period_end")
    for j, y, y2 in year_marks:
        if cols[j]["date"] is not None:
            continue
        mo, day = cols[j]["dm"] or dm or (None, None)
        if mo is None:
            continue
        if y2 and fye and fye != 12 and int(y2[-2:]) == (y + 1) % 100 and mo <= fye:
            # '2024/25' names a financial year ending in month fye of 2025: its months up to fye fall in 2025,
            # later months (e.g. December in an April-March year) fall in 2024.
            y = y + 1
        last = calendar.monthrange(y, mo)[1]
        cols[j]["date"] = _iso(y, mo, min(day or last, last))
        if y2 and int(y2[-2:]) == y % 100 and (not fye or mo == fye):
            fiscal_year_columns.add(j)

    # Scope
    global_scope = None
    lt = (title + " " + head_text).lower()
    if scope_marks:
        # the same scope word can repeat on later header rows; use one row's worth of marks
        seen, uniq = set(), []
        for cx, v in sorted(scope_marks):
            key = (round(cx / 20), v)
            if key not in seen:
                seen.add(key); uniq.append((cx, v))
        for c, v in zip(cols, assign_marks(uniq, cols)):
            c["scope"] = v
    else:
        if re.search(r"\bconsolidated\b|\bgroup\b", lt):
            global_scope = "GROUP"
        elif re.search(r"\bcompany\b|\bbank\b", lt):
            global_scope = "COMPANY"
        for c in cols:
            c["scope"] = global_scope or ctx.get("default_scope", "COMPANY")

    gu = unit_in(head_text + " " + title)
    if not gu:
        # a unit note printed under or beside the table, e.g. 'All figures in Rs.'000'
        notes = [text_of(r) for r in rows if not any(is_num(w[4]) for w in r)]
        units = {u for u in (unit_in(x) for x in notes) if u}
        gu = units.pop() if len(units) == 1 else None
    cur = currency_in(head_text) or "LKR"
    issues = []
    for c in cols:
        if c["note"] and c["date"] is not None:
            # a 'Note' heading just left of a dated column: the note numbers have no column of their own
            c["note"] = False
    _fill_months(cols, title, label_signs, head, fye, issues)
    # An explicitly printed consecutive financial-year range establishes a full
    # year only when no shorter period was stated elsewhere in the header.
    for j in fiscal_year_columns:
        if cols[j]["months"] is None:
            cols[j]["months"] = 12
    keep = []
    for c in cols:
        c.pop("dm", None)
        if c["change"] or c["note"]:
            continue
        if c["date"] is None:
            issues.append(f"column at x={c['x']:.0f} has no date")
            continue
        c["unit_known"] = bool(c["unit"] or gu)
        c["unit"] = c["unit"] or gu or 1
        c["currency"] = cur
        c["currency_known"] = currency_in(head_text) is not None
        keep.append(c)
    seen = {}
    for c in keep:
        key = (c["scope"], c["date"], c["months"])
        if key in seen:
            issues.append(f"columns at x={seen[key]:.0f} and x={c['x']:.0f} claim the same scope, date and months")
        seen.setdefault(key, c["x"])
    return dict(first=first, cols=keep, all_cols=cols), issues


def _cum_months(date, fye):
    """Months from the start of the financial year to a month-end date."""
    if not date or not fye:
        return None
    d = dt.date.fromisoformat(date)
    if d.day < 28:
        return None
    n = (d.month - fye - 1) % 12 + 1
    return n if n in (3, 6, 9, 12) else None


def fit_interim_periods(cols, stmt, ctx, issues):
    """In an interim report a period is the quarter (3), the year to date, or a full financial year ending in a
    year-end month. Arithmetic checks cannot see a wrong length, so a column claiming any other period is a
    misread header or a misprint ('Year Ended 30 June' over a first-quarter cash flow). Give it the year-to-date
    or quarter length when exactly that slot is free for its scope and date; otherwise drop the column."""
    if ctx.get("category") != "INTERIM" or stmt not in ("IS", "CF") or not ctx.get("fye"):
        return cols
    fye = ctx["fye"]
    ends = {fye} | set(ctx.get("fye_extra") or ())

    def fits(c):
        m, d = c.get("months"), c.get("date")
        if not m or not d:
            return True
        mo = int(d[5:7])
        return m == 3 or m == _cum_months(d, fye) or (m == 12 and mo in ends) or any(
            m == _cum_months(d, e) for e in ends)

    # the only end dates an interim's own columns use: the period end, a year before it, the last year end
    pe = ctx.get("period_end")
    dates = set()
    if pe:
        y, mo = int(pe[:4]), int(pe[5:7])
        dates = {pe, _iso(y - 1, mo, calendar.monthrange(y - 1, mo)[1])}
        for e in ends:
            ye = y if e <= mo else y - 1
            dates.add(_iso(ye, e, calendar.monthrange(ye, e)[1]))
    keep = []
    for c in cols:
        if fits(c):
            keep.append(c)
            continue
        taken = {o["months"] for o in cols if o is not c and o["scope"] == c["scope"] and o["date"] == c["date"]}
        free = [m for m in dict.fromkeys([_cum_months(c["date"], fye), 3]) if m and m not in taken]
        if c["date"] not in dates:
            # the date is suspect too (e.g. a year joined to the wrong 'Year ended 31 March'): no guess is safe
            free = []
        if free:
            issues.append(f"{c['scope']} {c['date']}: printed/read as {c['months']} months, which is not a period of "
                          f"this financial year; read as {free[0]} months")
            c["months"] = free[0]
            c["period_refit"] = True
            keep.append(c)
        else:
            issues.append(f"{c['scope']} {c['date']}: {c['months']} months is not a period of this financial year "
                          f"and no free slot fits; column dropped")
    return keep


def _fill_months(cols, title, label_signs, head, fye, issues):
    """Resolve 'year to date' marks to a number, then give columns with no mark of their own the table's period,
    taken from the title or the label area. A table-wide period never makes a column repeat another's claim."""
    data = [c for c in cols if not (c["change"] or c["note"])]
    for c in data:
        if c["months"] == CUM:
            c["months"] = _cum_months(c["date"], fye)
            if c["months"] is None:
                issues.append(f"column at x={c['x']:.0f}: period to date, months not known")
    signs = [s for s in [period_sign(title)] + label_signs if s]
    if not signs and not any(c["months"] for c in data):
        # nothing placed: fall back to any one period word in the header
        signs = [s for s in (period_sign(t) for r in head for _, _, t in chunks(r)) if s]
    for c in data:
        if c["months"] is not None:
            continue
        vals = {_cum_months(c["date"], fye) if s == CUM else s for s in signs} - {None}
        if len(vals) != 1:
            if signs:
                issues.append(f"column at x={c['x']:.0f}: months not clear")
            continue
        v = vals.pop()
        if any(o is not c and o["months"] == v and o["scope"] == c["scope"] and o["date"] == c["date"] for o in data):
            issues.append(f"column at x={c['x']:.0f}: months {v} would repeat another column")
            continue
        c["months"] = v


def _col_for(cols, x1, slack=16):
    j = min(range(len(cols)), key=lambda i: abs(cols[i]["x"] - x1))
    # headers are often centred over a column, so allow for that
    return j if abs(cols[j]["x"] - x1) <= slack + 24 else None


_PCT = re.compile(r"\(?[-+]?\d{1,5}(?:\.\d+)?\s*%\)?")


def read_rows(rows, spec, stmt):
    """Turn table rows into labelled values aligned to columns."""
    out, section, prev_text, block = [], "NONE", "", ""
    all_cols = spec["all_cols"]
    keep_ids = {id(c) for c in spec["cols"]}
    for r in rows:
        nums, labs = [], []
        dropped_pct = False
        for w in r:
            if is_num(w[4]) or w[4] in DASH:
                nums.append(w)
            elif _PCT.fullmatch(w[4].strip()) and w[0] >= all_cols[0]["x"] - 75:
                # a '% change' column printed beside the figures, e.g. '(33%)': not part of the label
                dropped_pct = True
                continue
            else:
                labs.append(w)
        label = " ".join(w[4] for w in labs).strip()
        if dropped_pct:
            label = re.sub(r"\s*\(\s*$", "", label)
        if re.fullmatch(r"(?i)page\s*\d*\s*of\s*\d*", label):
            continue
        code = normalize.section_code(label) if label else None
        data = [w for w in nums if not (w[4] in DASH)]
        n_label = normalize.label(label) if label else ""
        if stmt == "CF":
            cf = normalize.cash_flow_section(label) if label else None
            if cf:
                section = cf
        if not data:
            # A line break can put the end of the before-tax label below its
            # values. Join only this unambiguous incomplete core-check label.
            if (stmt in ("IS", "OCI") and out
                    and re.search(r"\bbefore(?: income)?$", normalize.label(out[-1]["label"]))
                    and re.fullmatch(r"(?:income )?tax(?:ation)?(?: expense)?", n_label)):
                out[-1]["label"] += " " + label
                prev_text = ""
                continue
            if code and stmt == "BS":
                section = code
            # 'Profit attributable to:' and 'Total comprehensive income attributable to:' head the rows under them
            if stmt in ("IS", "OCI") and re.search(r"attributable to$", n_label):
                block = n_label
            prev_text = label
            continue
        if stmt in ("IS", "OCI") and block and not re.search(r"(holders|owners|shareholders|parent|company|bank|controlling|minority)", n_label):
            block = ""
        if stmt in ("IS", "OCI") and re.search(r"attributable to ", n_label):
            block = ""
        vals = {}
        for w in nums:
            x = right_edge(w)
            j = min(range(len(all_cols)), key=lambda i: abs(all_cols[i]["x"] - x))
            if abs(all_cols[j]["x"] - x) > 26:
                continue
            c = all_cols[j]
            if id(c) in keep_ids:
                vals[spec["cols"].index(c)] = clean_num(w[4])
        # A small integer just after the label with no column of its own is a note reference.
        if not label:
            prev_text = ""
            if vals:
                out.append(dict(label="", prefix="", section=section, values=vals, y=round(r[0][1])))
            continue
        total_like = normalize.label(label).startswith("total ") or code is not None
        shown = f"{block} {label}" if block else label
        cf_total = stmt == "CF" and re.match(r"^net cash|^cash (generated|used|flows?)|^net (increase|decrease)|^cash and cash equivalents|^effect of|^exchange", n_label)
        out.append(dict(label=shown, prefix=prev_text if not block and not re.search(r"\d", prev_text or "") else "",
                        section="NONE" if total_like or cf_total else section, values=vals, y=round(r[0][1])))
        prev_text = ""
    return out



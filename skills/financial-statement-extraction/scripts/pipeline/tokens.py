"""Words, rows, numbers, dates and units. Owner: shared; change only with care."""
import calendar
import datetime as dt
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import normalize  # noqa: E402

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
MON = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
NUM = re.compile(r"^\(?-?\d[\d,]*(?:\.\d+)?\)?%?$")
DASH = {"-", "–", "—", "--", "- -"}


def clean_num(t):
    t = t.strip().rstrip("%")
    if t in DASH:
        return None
    neg = t.startswith("(") or t.startswith("-") or t.endswith(")")
    v = t.strip("()-").replace(",", "")
    try:
        x = float(v)
    except ValueError:
        return None
    return -x if neg else x


def is_num(t):
    return bool(NUM.match(t))


def page_rows(page):
    """Group words into rows by vertical centre, and join split number tokens such as '( 1,234 )'."""
    # Duplicate text layers can paint the same word twice at exactly the same box.
    # Keep adjacent equal values at different positions; only identical painted words are redundant.
    words, seen_words = [], set()
    for w in page.get_text("words"):
        key = tuple(w[:5])
        if w[4].strip() and key not in seen_words:
            words.append(w)
            seen_words.add(key)
    if not words:
        return []
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    heights = sorted(w[3] - w[1] for w in words)
    med = heights[len(heights) // 2]
    rows, cur, cy = [], [], None
    for w in words:
        yc = (w[1] + w[3]) / 2
        if cy is None or abs(yc - cy) <= max(2.5, 0.42 * med):
            cur.append(w)
            cy = yc if cy is None else (cy * (len(cur) - 1) + yc) / len(cur)
        else:
            rows.append(cur)
            cur, cy = [w], yc
    rows.append(cur)
    out = []
    for r in rows:
        r.sort(key=lambda w: w[0])
        merged = []
        for w in r:
            x0, y0, x1, y1, t = w[0], w[1], w[2], w[3], w[4]
            if merged:
                p = merged[-1]
                gap = x0 - p[2]
                # '(' + '1,234)', '1,234' + ')', '(1,234' + ')', '6' + ',442,087'
                if gap < 4 and (p[4] in ("(", "-") and re.match(r"^[\d,.]+\)?$", t) or (t == ")" and re.search(r"\d$", p[4])) or (t.startswith(",") and re.search(r"\d$", p[4]))):
                    merged[-1] = (p[0], p[1], x1, p[3], p[4] + t)
                    continue
            merged.append((x0, y0, x1, y1, t))
        out.append(merged)
    return out


def right_edge(w):
    return w[2] - (3.0 if w[4].endswith(")") else 0)


def text_of(row):
    return " ".join(w[4] for w in row)


def chunks(row, gap=9):
    out, cur = [], []
    for w in row:
        if cur and w[0] - cur[-1][2] > gap:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return [(c[0][0], c[-1][2], " ".join(x[4] for x in c)) for c in out]


def parse_date(text, default_year=None):
    """Return ISO date from a header fragment, or None."""
    t = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", text.strip(), flags=re.I).replace("’", "'").translate(str.maketrans({"‐": "-", "‑": "-", "–": "-", "−": "-"}))
    m = re.search(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4}|\d{2})\b", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        if mo > 12 and d <= 12:
            # month first, as in 12/31/2024
            d, mo = mo, d
        return _iso(y, mo, d)
    m = re.search(r"\b(\d{4})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})\b", t)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(rf"\b(\d{{1,2}})\s*[-./ ]?\s*({MON})\b\.?\s*[-.,/' ]*\s*(\d{{4}}|\d{{2}})\b", t, re.I)
    if m:
        y = int(m.group(3))
        return _iso(y + 2000 if y < 100 else y, MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(rf"\b({MON})\b\.?\s*(\d{{1,2}})\s*[,.]?\s*(\d{{4}})\b", t, re.I)
    if m:
        return _iso(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    m = re.search(rf"\b(20\d\d)\s+({MON})\b\.?\s*(\d{{1,2}})\b", t, re.I)   # '2025 Dec 31'
    if m:
        return _iso(int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)))
    # 'March 2024', 'Mar-24' or "Mar'24"; a two-digit year needs a mark, so 'March 31' stays a day
    m = re.search(rf"\b({MON})\b\s*(?:[-.,/' ]+\s*(\d{{4}})|\s*[-./']\s*(\d{{2}}))\b", t, re.I)
    if m:
        y = int(m.group(2) or m.group(3))
        y = y + 2000 if y < 100 else y
        mo = MONTHS[m.group(1).lower()]
        return _iso(y, mo, calendar.monthrange(y, mo)[1])
    return None


def _iso(y, mo, d):
    try:
        return dt.date(y, mo, d).isoformat() if 2000 <= y <= 2035 else None
    except ValueError:
        return None


CUM = "CUM"  # a period from the start of the financial year to the column's date, length not printed


def period_sign(text):
    """What a header fragment says about a column's period length: 3, 6, 9, 12, CUM (year to date, number not
    printed) or None. A number printed wins over words."""
    t = text.lower().replace("–", "-")
    m = re.search(r"\b(three|six|nine|twelve|3|6|9|12|03|06|09)\s*(?:\(\s*\d{1,2}\s*\))?\s*[- ]?\s*months?\b", t)
    if m:
        return {"three": 3, "six": 6, "nine": 9, "twelve": 12, "3": 3, "6": 6, "9": 9, "12": 12, "03": 3, "06": 6, "09": 9}[m.group(1)]
    r = month_range(t)
    if r:
        return r[1]
    if re.search(r"\bquarter\b|\bqtr\b|\bquarterly\b", t):
        return 3
    if re.search(r"\byear\s+to\s+date\b|\bytd\b|\bcumulative\b|\bcum\.?$|\bperiod\b", t):
        return CUM
    if re.search(r"\byear\s+ended\b|\bfinancial\s+year\b|\bfor\s+the\s+year\b|\byear\s+to\b|\byear\s+ending\b", t):
        return 12
    return None


def months_in(text):
    v = period_sign(text)
    return v if isinstance(v, int) else None


def month_range(text):
    """'April - December' or '01 April to 31 December': (end month, months) when the span is 3, 6, 9 or 12 months."""
    t = text.lower().replace("–", "-")
    m = re.search(rf"\b(?:\d{{1,2}}(?:st|nd|rd|th)?\s*)?({MON})\b\.?(?:\s*,?\s*\d{{4}})?\s*(?:-|to)\s*(?:\d{{1,2}}(?:st|nd|rd|th)?\s*)?({MON})\b", t)
    if not m:
        return None
    a, b = MONTHS[m.group(1)], MONTHS[m.group(2)]
    n = (b - a) % 12 + 1
    return (b, n) if n in (3, 6, 9, 12) else None


def date_range(text):
    """'01.04.2024 to 31.12.2024' or '1st April 2024 - 31st December 2024': (end date, months), or None."""
    t = text.replace("–", "-")
    parts = re.split(r"\s+(?:to|-)\s+|(?<=\d{4})\s*-\s*(?=\d)", t, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    a, b = parse_date(parts[0]), parse_date(parts[1])
    if not a or not b:
        return None
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    n = round((db - da).days / 30.44)
    return (b, n) if n in (3, 6, 9, 12) and da.day <= 2 and db.day >= 28 else None


def day_month(text):
    """A day and month printed without a year, e.g. '31 March' or 'March 31': (month, day), or None."""
    t = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", text.strip().lower())
    m = re.search(rf"\b(\d{{1,2}})\s*[-./ ]?\s*({MON})\b(?!\.?\s*[-.,/' ]*\s*\d)", t)
    if m:
        return MONTHS[m.group(2)], int(m.group(1))
    m = re.search(rf"\b({MON})\b\.?\s*(\d{{1,2}})\b(?!\s*[,.]?\s*\d{{2,4}})", t)
    if m:
        return MONTHS[m.group(1)], int(m.group(2))
    return None


def unit_in(text):
    t = text.lower().replace("’", "'")
    if re.search(r"'?\s*000s?\b|\bthousands?\b", t) and re.search(r"rs|lkr|rupee|usd|\$|'000", t):
        return 1000
    if re.search(r"\b(?:rs\.?|lkr|usd)\s*\.?\s*(?:mn|mns|mlns?|million|millions|m)\b|\bmillions?\b|\bmns?\b", t):
        return 1000000
    if re.search(r"\b(?:rs\.?|lkr|usd)\s*\.?\s*(?:bn|billions?)\b", t):
        return 1000000000
    # a currency on its own, e.g. a 'Rs.' column header, means figures are printed in full
    if re.fullmatch(r"\W*(?:rs|lkr|rupees|usd|us\s*\$)\W*", t):
        return 1
    return None


def currency_in(text):
    t = text.lower()
    if re.search(r"\busd\b|us\s*\$|\b(?:us|united states) dollars?\b", t):
        return "USD"
    if re.search(r"\brs\b|\brs\.|\blkr\b|rupee", t):
        return "LKR"
    return None


def scope_word(text):
    t = text.lower()
    if re.fullmatch(r"\W*(group|consolidated|consol\.?)\W*", t):
        return "GROUP"
    # a company with equity-accounted investees and no subsidiaries presents these in place of group figures
    if re.fullmatch(r"\W*(the\s+)?(company|bank)\s*(and|&)\s*(its\s+)?(equity[- ]accounted\s+)?investees?\W*", t):
        return "GROUP"
    if re.fullmatch(r"\W*(company|bank|the company|the bank|parent|corporation|fund|society)\W*", t):
        return "COMPANY"
    return None



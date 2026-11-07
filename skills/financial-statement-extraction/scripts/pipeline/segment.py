"""Finds statement titles and groups rows and pages into statement segments."""
import calendar
import datetime as dt
import difflib
import functools
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import normalize  # noqa: E402
from tokens import *  # noqa: F401,F403,E402
from tokens import MON, MONTHS  # noqa: E402

HEADINGS = [
    ("CF", re.compile(r"statement\s+of\s+cash\s*flows?|cash\s*flows?\s+statements?|cash\s*flow\s+information$", re.I)),
    ("SOCE", re.compile(r"statements?\s+of\s+changes?\s+in|changes?\s+in\s+equity\s+statement|statement\s+of\s+equity", re.I)),
    ("BS", re.compile(r"statements?\s+of\s+financial\s+position|balance\s+sheet", re.I)),
    ("IS", re.compile(r"income\s+statements?|statements?\s+of\s+(?:profit|comprehensive\s+income|income)|profit\s+(?:or|and|&)\s+loss(?:\s+account|\s+statement)?|comprehensive\s+income\s+statement", re.I)),
]
HEAD_PREFIX = re.compile(r"^\W*(?:\d+\W+)?(?:(?:the|group|company|bank|consolidated|condensed|interim|unaudited|audited|summarised|summary|separate|provisional|and|&|-)\s+)*", re.I)


TITLE_VOCAB = ["statement", "statements", "financial", "position", "comprehensive", "income", "profit",
               "flows", "balance", "changes", "equity", "consolidated"]


REAL_WORDS = {"settlement", "settlements", "segment", "segments", "finance", "positive", "condition", "statemente"}


@functools.lru_cache(maxsize=50000)
def _fix_word(w):
    """A title word misspelt or misread in a text layer ('STATMENET', 'STATEAAENT', 'S1'AJ'EMENT') to its spelling."""
    if re.fullmatch(r"[0O][FTI]|Of|OT", w):
        return "OF"
    core = re.sub(r"[^A-Za-z]", "", w)
    if len(core) < 5 or core.lower() in TITLE_VOCAB or core.lower() in REAL_WORDS:
        return w
    if core.lower().startswith("of") and len(core) >= 8:      # 'OFFINANCIAL'
        rest = _fix_word(w[2:]) if w[:2].lower() == "of" else w
        if rest.lower() in TITLE_VOCAB:
            return "OF " + rest
    low = core.lower()
    junk = bool(re.search(r"[A-Za-z][^A-Za-z\s.,:()]+[A-Za-z]", w))      # letters misread as digits or marks
    best = max(TITLE_VOCAB, key=lambda v: difflib.SequenceMatcher(None, low, v).ratio())
    if difflib.SequenceMatcher(None, low, best).ratio() >= (0.65 if junk else 0.8) and abs(len(low) - len(best)) <= 3:
        return best.upper() if core.isupper() or junk else best
    return w


def heading_type(text):
    """A statement title, not a mention of one inside a table or a sentence."""
    code = _heading_type(text)
    if code or len(text.split()) > 12 or not re.search(r"[A-Za-z]{3}", text):
        return code
    fixed = " ".join(_fix_word(w) for w in text.split())
    return _heading_type(fixed) if fixed != " ".join(text.split()) else None


def _heading_type(text):
    t = text.strip()
    # Explanatory note sentences and expense labels can start with the name
    # of a statement, but they do not introduce that primary statement.
    if re.search(r"\b(?:shows?|showing|charged|reversed)\b", t, re.I):
        return None
    if len(t) > 110 or len(t.split()) > 16 or re.match(r"^\s*(notes?\b|\d+[.)]?\s+notes?\b)", t, re.I):
        return None
    letters = [c for c in t if c.isalpha()]
    caps = bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.8
    rest = HEAD_PREFIX.sub("", t) if not caps else t
    for code, rx in HEADINGS:
        m = rx.search(rest)
        if m and (caps or m.start() == 0 or rx.match(t)):
            return code
    return None


class _Panel:
    """A vertical strip of a page, offering the page's word interface."""
    def __init__(self, words):
        self.words = words

    def get_text(self, kind="words", *a, **k):
        return self.words if kind == "words" else " ".join(w[4] for w in self.words)


def _numeric_rows(rows):
    return sum(1 for r in rows if sum(is_num(w[4]) for w in r) >= 2)


TITLE_WORD = re.compile(r"^(?:statements?|income|balance|cash|profit)$", re.I)


def _heading_starts(row, gap=12):
    """Left edges of statement titles in a row of side-by-side text blocks."""
    groups, cur = [], []
    for w in row:
        if cur and w[0] - cur[-1][2] > gap:
            groups.append(cur)
            cur = []
        cur.append(w)
    groups.append(cur)
    starts = []
    for g in groups:
        for k, w in enumerate(g):
            if (k == 0 or TITLE_WORD.match(w[4])) and heading_type(text_of(g[k:])):
                starts.append(w[0])
                break
    return starts


def _lead_heading(row, gap=40):
    """A title standing apart at the start of a row whose other text belongs to a neighbouring column."""
    for k in range(1, len(row)):
        if row[k][0] - row[k - 1][2] > gap:
            return heading_type(text_of(row[:k]))
    return None


def _repair_glyph_heights(page, words):
    """Some embedded fonts report six-point text with 34-point glyph boxes.
    Use the font size and baseline only for those invalid boxes, so distinct
    table rows do not collapse into one row when grouped by vertical centre.
    """
    heights = sorted(w[3] - w[1] for w in words)
    if not heights or heights[len(heights) // 2] <= 20:
        return words
    try:
        blocks = page.get_text("dict")["blocks"]
    except (AttributeError, KeyError, TypeError):
        return words
    fixes = {}
    for b in blocks:
        for ln_no, line in enumerate(b.get("lines", [])):
            if abs(line.get("dir", (1, 0))[1]) > 0.1:
                continue
            spans = [s for s in line.get("spans", [])
                     if s.get("size", 0) > 0 and s["bbox"][3] - s["bbox"][1] > 2.5 * s["size"]]
            if spans:
                fixes[(b["number"], ln_no)] = spans
    repaired = []
    for w in words:
        spans = fixes.get((w[5], w[6]), []) if len(w) >= 7 else []
        span = next((s for s in spans if s["bbox"][0] - 1 <= (w[0] + w[2]) / 2 <= s["bbox"][2] + 1), None)
        if span:
            baseline, size = span["origin"][1], span["size"]
            w = (w[0], baseline - 0.8 * size, w[2], baseline + 0.2 * size, *w[4:])
        repaired.append(w)
    return repaired


def _upright(page):
    """A page whose text runs vertically (a landscape table on a rotated page) with its words turned to read across."""
    words = _repair_glyph_heights(page, page.get_text("words"))
    try:
        tall = sum(1 for w in words if len(w[4]) >= 4 and w[3] - w[1] > 2 * (w[2] - w[0]))
        if tall < 20 or tall < 0.5 * len(words):
            return _Panel(words)
        import pymupdf
        blocks = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
        height, width = page.mediabox.height, page.mediabox.width
    except Exception:
        return _Panel(words)
    up = down = flat = 0
    for b in blocks:
        for ln in b.get("lines", []):
            n = len(ln["spans"])
            dx, dy = ln["dir"]
            if abs(dy) > 0.9:
                up += n * (dy < 0)
                down += n * (dy > 0)
            else:
                flat += n
    if max(up, down) <= 2 * flat or max(up, down) < 20:
        return _Panel(words)
    turned = []
    for x0, y0, x1, y1, *rest in words:
        if up >= down:      # reading upwards: across = -y, down the page = x
            turned.append((height - y1, x0, height - y0, x1, *rest))
        else:
            turned.append((y0, width - x1, y1, width - x0, *rest))
    return _Panel(turned)


def page_panels(page):
    """Rows of each statement on a page, splitting the page into strips when titles of separate statements
    sit side by side on one line (landscape pages with two or three statements in columns)."""
    page = _upright(page)
    rows = page_rows(page)
    width = max((w[2] for r in rows for w in r), default=0)
    best = []
    for r in rows:
        if sum(is_num(w[4]) for w in r) > 1:
            continue
        starts = _heading_starts(r)
        if len(starts) >= 2 and min(b - a for a, b in zip(starts, starts[1:])) >= max(150, 0.2 * width) and len(starts) > len(best):
            best = starts
    if not best:
        return [rows]
    cuts = [x - 2 for x in best[1:]]
    words = [w for w in page.words if w[4].strip()]
    strips = [[] for _ in range(len(cuts) + 1)]
    for w in words:
        strips[sum(w[0] >= c for c in cuts)].append(w)
    panels = [page_rows(_Panel(ws)) for ws in strips]
    if sum(_numeric_rows(p) >= 4 for p in panels) < 2:
        return [rows]
    return panels


def _subline_heading(row):
    """A title set on two baselines that page_rows merged with a neighbouring line, so that its words
    interleave by x ('STATEMENT For the Twelve OF month CASH FLOW period ended'): test each baseline alone."""
    lines = {}
    for w in row:
        key = next((k for k in lines if abs(k - w[3]) <= 1.0), w[3])
        lines.setdefault(key, []).append(w)
    if len(lines) < 2:
        return None
    for ws in lines.values():
        h = heading_type(text_of(sorted(ws, key=lambda w: w[0])))
        if h:
            return h
    return None


SUPPLEMENTARY = re.compile(r"(?i)\b(?:life\s+(?:insurance\s+)?fund|policyholders?[’']?\s+fund|participants?[’']?\s+fund|"
                           r"takaful\s+fund|supplement(?:al|ary)\b(?!\s+information)|segment(?:al)?\s+(?:review|analysis|information|report))")


def _wrapped_line(rows, i):
    """The second line of a wrapped label or sentence, such as 'Financial assets at fair value through' /
    'Profit or Loss', or '... reclassified to the' / 'statement of profit or loss'."""
    if i == 0:
        return False
    prev = rows[i - 1]
    if rows[i][0][1] - max(w[3] for w in prev) > 6:
        return False
    label = " ".join(w[4] for w in prev if not is_num(w[4]) and w[4] not in ("-", "–"))
    return bool(re.search(r"\b(?:the|to|of|in|into|from|and|or|its|through|at|by|for|with|on)\s*$", label, re.I))


CONTENT_SIGNS = {
    "BS": [r"total\s+assets", r"total\s+(?:equity|liabilities)|stated\s+capital"],
    "IS": [r"revenue|turnover|gross\s+(?:profit|income)", r"before\s+(?:income\s+)?tax|profit\s*/?\s*(?:\(loss\)\s*)?for\s+the\s+(?:period|year)"],
    "CF": [r"operating\s+activities", r"investing\s+activities"],
}


def _untitled(units, segments):
    """Statements whose title is missing from the text layer (an image or a misread scan): a page of table rows
    carrying the line items of a statement type that no titled segment supplied."""
    have = {s["stmt"] for s in segments}
    used = {(pno, id(rows)) for s in segments for pno, rows in s["pages"]}
    found = []
    for code, signs in CONTENT_SIGNS.items():
        if code in have:
            continue
        for pno, rows in units:
            if _numeric_rows(rows) < 8 or any(u[0] == pno for u in used):
                continue
            labels = [text_of(r) for r in rows]
            # An errata annexure quotes several statement totals in its correction
            # rows. It is not a primary statement, even when those totals happen
            # to satisfy the content signatures below.
            if any(re.search(r"amended\s+to\s+read|casting\s+errors?|\berrata\b", t, re.I)
                   for t in labels[:8]):
                continue
            if all(any(re.search(rx, t, re.I) for t in labels) for rx in signs):
                if code == "IS" and any(re.search(r"operating\s+activities", t, re.I) for t in labels):
                    continue    # a cash flow statement starting from profit before tax
                found.append(dict(stmt=code, title=f"(untitled {code})", pages=[(pno, rows)], closed=True))
                used.add((pno, id(rows)))
                break
    return found


def _balance_sheet_continuation(current, pno, rows):
    """A repeated title on the equity half of an otherwise unfinished BS.
    Require identical date/scope/unit headers, not just adjacent BS titles.
    """
    if current is None or current["stmt"] != "BS" or current["pages"][-1][0] + 1 != pno:
        return False

    def header_and_section(body):
        for i, row in enumerate(body[:15]):
            label = normalize.label(text_of(row))
            if label in ("assets", "equity"):
                return [text_of(r).strip() for r in body[:i]], label
        return None, None

    first_header, first_section = header_and_section(current["pages"][0][1])
    next_header, next_section = header_and_section(rows)
    if first_section != "assets" or next_section != "equity" or not first_header or first_header != next_header:
        return False
    before = [normalize.label(text_of(r)) for _, body in current["pages"] for r in body]
    after = [normalize.label(text_of(r)) for r in rows]
    end = re.compile(r"^total (?:equity and liabilities|liabilities and equity)\b")
    return (any(re.match(r"^total assets\b", t) for t in before)
            and any(re.match(r"^total liabilities\b", t) for t in before)
            and not any(end.search(t) for t in before)
            and any(end.search(t) for t in after))


def statement_tables(doc, ctx):
    """Yield statement segments: consecutive rows under one heading, continuing over pages when marked."""
    segments, current = [], None
    units = [(pno, rows) for pno in range(len(doc)) for rows in page_panels(doc[pno])]
    primary_units = []
    for pno, rows in units:
        if not rows:
            current = None
            continue
        # Subsidiary summaries inside an explicitly headed notes page belong
        # to that note, not to the reporting entity's primary statements.
        note_heading = any(re.fullmatch(r"notes?\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial\s+statements?(?:\s*\(?cont(?:inue)?d[.)]*)?",
                                        " ".join(text_of(r) for r in rows[i:i + count]).strip(), re.I)
                           for i in range(min(10, len(rows))) for count in (1, 2, 3))
        if note_heading:
            current = None
            continue
        primary_units.append((pno, rows))
        numeric_rows = sum(1 for r in rows if sum(is_num(w[4]) for w in r) >= 2)
        marks = []
        for i, r in enumerate(rows):
            t = text_of(r)
            if not _wrapped_line(rows, i):
                # A heading can share its baseline with comparative date/year
                # columns. Only accept the isolated leading title in that case;
                # matching the whole numeric row could mistake a line item for
                # a heading.
                if sum(is_num(w[4]) for w in r) <= 1:
                    h = heading_type(t) or _lead_heading(r) or _subline_heading(r)
                else:
                    h = _lead_heading(r)
                start = i
            elif (sum(is_num(w[4]) for w in r) <= 1 and not any(is_num(w[4]) for w in rows[i - 1])
                  and re.match(r"(?i)(?:consolidated\s+|company\s+|group\s+|separate\s+)?(?:statements?|income|balance|cash)\b",
                               text_of(rows[i - 1]).strip())
                  and not heading_type(text_of(rows[i - 1]))):
                # A title wrapped after its connector word: 'STATEMENT OF' / 'PROFIT OR LOSS'.
                t = text_of(rows[i - 1]) + " " + t
                h = heading_type(t)
                start = i - 1
            else:
                h = None
            if h:
                # Fund and supplemental statements (an insurer's 'LIFE INSURANCE FUND' balance sheet, a bank's
                # 'SUPPLEMENTAL' one) repeat the entity's dates, so they would clash with the primary statement.
                # Keep them as their own segment type, which is parsed but never loaded.
                near = " ".join(text_of(x) for x in rows[max(0, start - 1):i + 1] if len(text_of(x).split()) <= 8)
                if SUPPLEMENTARY.search(near):
                    h = "SUPP"
                if start and re.fullmatch(r"consolidated|group|company|bank|separate", text_of(rows[start - 1]).strip(), re.I):
                    if min(w[1] for w in rows[start]) - max(w[3] for w in rows[start - 1]) <= 20:
                        start -= 1
                        t = text_of(rows[start]) + " " + t
                marks.append((start, h, t))
        if not marks and current is not None and numeric_rows >= 4 and not current["closed"]:
            current["pages"].append((pno, rows))     # a table running on with no heading
            continue
        if numeric_rows < 4:
            current = None
            continue
        if not marks:
            current = None
            continue
        # keep only the first mark of a run of headings of one type, with table rows beneath it
        last_end = 0
        for k, (i, h, t) in enumerate(marks):
            end = marks[k + 1][0] if k + 1 < len(marks) and marks[k + 1][1] != h else len(rows)
            if k + 1 < len(marks) and marks[k + 1][1] == h and marks[k + 1][0] - i <= 3:
                continue    # repeated heading line
            body = rows[i:end]
            if sum(1 for r in body if sum(is_num(w[4]) for w in r) >= 2) < 4:
                continue
            contd = bool(re.search(r"cont[.'’d]|continued", t, re.I))
            if current is not None and current["stmt"] == h and (contd or h == "BS" and _balance_sheet_continuation(current, pno, body)):
                current["pages"].append((pno, body))
            else:
                current = dict(stmt=h, title=t, pages=[(pno, body)], closed=False)
                segments.append(current)
            last_end = end
    return segments + _untitled(primary_units, segments)



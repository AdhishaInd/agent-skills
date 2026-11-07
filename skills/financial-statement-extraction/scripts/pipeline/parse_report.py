"""Reads the primary statements from one report PDF. No database access.

A table that fails its checks is still written, marked failed, so the loader can refuse it and the failure can be studied.

Scanned reports and reports with statement pages pasted as images go through the same parser, using OCR words from
ocr_words.py. OCR runs only when the text layer gave no passing income statement or balance sheet and image pages exist.
Each table records extractor "text" or "ocr". An OCR table has trusted=True only if it has checks and all of them pass.
CSE_OCR=0 turns OCR off (default on).
"""
import json
import pathlib
import re
import sys

import pymupdf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import normalize  # noqa: E402
from checks import check_table, find  # noqa: E402
from columns import interpret_columns, read_rows, fit_interim_periods  # noqa: E402
import ocr_words  # noqa: E402
from segment import statement_tables  # noqa: E402

SCANNED_ISSUE = "little or no text: probably scanned"
# Above this many image pages a report is too long to OCR every table-like page when the headings cannot be read.
SHORT_REPORT_IMAGE_PAGES = 25


_BS_END = re.compile(r"^total (equity and liabilities|liabilities and equity|equity liabilities|liabilities and shareholders funds|shareholders funds and liabilities|capital and liabilities|equity and liability)")
_BS_AFTER = re.compile(r"per (ordinary |voting )?share|contingent|commitments|net asset")
_CF_END = re.compile(r"^cash and cash equiv[a-z]*ents? (at|as at) (the )?(end|close)|^closing cash|^cash and cash equiv[a-z]*ents (at )?end of")
_IS_FOREIGN = re.compile(r"^total assets$|^stated capital$|^total equity$|^total liabilities$|^total equity and liabilities$|^property plant and equipment$|^retained earnings$|^cash and cash equivalents$|^inventories$|^trade and other (receivables|payables)$|^net cash")


_UNIT_NOTE = re.compile(r"(?i)\b(all\s+)?(amounts?|values?|figures?)\s+(are\s+)?(stated\s+|expressed\s+|presented\s+|shown\s+)?in\b")


def page_unit_note(page):
    """Return (scale, currency) from one unambiguous statement-page unit declaration."""
    from tokens import unit_in, currency_in
    found = set()
    currency = r"(?:lkr|rs\.?|(?:sri\s+lankan?\s+)?rupees?|usd|us\s*\$|(?:us|united\s+states)\s+dollars?)"
    standalone = re.compile(rf"(?i)^\s*\(?\s*(?:(?:all|expressed|stated|presented|shown)\s+)?in\s+(?:{currency}(?:\s+(?:thousands?|millions?|billions?))?|(?:thousands?|millions?|billions?)\s+of\s+{currency})\s*\)?\s*$")
    for line in page.get_text("text").splitlines():
        if (_UNIT_NOTE.search(line) or standalone.fullmatch(line)) and not re.search(r"(?i)per share|eps", line):
            currencies = {currency_in(token) for token in re.findall(r"(?i)lkr|rs\.?|rupees?|usd|us\s*\$|(?:us|united\s+states)\s+dollars?", line)} - {None}
            scales = [bool(re.search(rx, line, re.I)) for rx in (
                r"000s?\b|\bthousands?\b", r"\b(?:millions?|mns?|mlns?|m)\b", r"\b(?:billions?|bn)\b")]
            if len(currencies) > 1 or sum(scales) > 1:
                return None
            u = unit_in(line)
            if u is None:
                # Only a plain currency declaration establishes unscaled amounts. Unknown scale words stay unknown.
                tail = re.sub(r"(?i),?\s*unless otherwise stated\.?", "", line)
                tail = re.sub(r"(?i)^.*?\bin\s+", "", tail).strip(" ().")
                if re.fullmatch(currency, tail, re.I):
                    u = 1
            if u and currency_in(line):
                found.add((u, currency_in(line)))
    return found.pop() if len(found) == 1 else None


def header_unit_note(rows):
    """Read a shared unit from the statement header, never from body/per-share rows."""
    from tokens import text_of, chunks, unit_in, currency_in
    head = " ".join(text_of(r) for r in rows)
    if re.search(r"(?i)per share|\beps\b", head):
        return None
    currencies = {currency_in(m.group()) for m in re.finditer(
        r"(?i)\blkr\b|\brs\.?|\brupees?\b|\busd\b|us\s*\$|(?:us|united\s+states)\s+dollars?", head)} - {None}
    scales = [bool(re.search(rx, head, re.I)) for rx in (
        r"000s?\b|\bthousands?\b", r"\b(?:millions?|mns?|mlns?|m)\b", r"\b(?:billions?|bn)\b")]
    if len(currencies) != 1 or sum(scales) > 1:
        return None
    currency = currencies.pop()
    scale = unit_in(head)
    if scale is not None:
        return scale, currency
    # A standalone currency chunk in a multi-column heading establishes full units.
    if any(unit_in(text) == 1 for row in rows for _, _, text in chunks(row)):
        return 1, currency
    return None


def trim_rows(stmt, rows):
    """Cut a table at the end of its statement, so notes and share data printed below it are not read as lines."""
    labels = [normalize.label(r["label"]) for r in rows]
    # A second statement stacked under the first (often the company's own under the group's) starts by
    # repeating the first line. Cut there, so its lines are never read under the first statement's heading.
    firsts = [t for t in labels[:3] if t]
    if firsts:
        again = [i for i, t in enumerate(labels) if i > 2 and t == firsts[0]]
        if again:
            rows, labels = rows[:again[0]], labels[:again[0]]
    if stmt == "BS":
        ends = [i for i, t in enumerate(labels) if _BS_END.search(t)]
        if ends:
            i = ends[0] + 1
            while i < len(rows) and i <= ends[0] + 4 and _BS_AFTER.search(labels[i]):
                i += 1
            return rows[:i]
    if stmt == "CF":
        ends = [i for i, t in enumerate(labels) if _CF_END.search(t)]
        if ends:
            return rows[:ends[0] + 1]
    if stmt in ("IS", "OCI"):
        for i, t in enumerate(labels):
            if _IS_FOREIGN.search(t):
                return rows[:i]
    return rows


def read_tables(doc, ctx):
    """Parse statements from a document, or from an OcrDoc wrapping one. Tables say which pages they came from."""
    tables = []
    ocr_pages = getattr(doc, "ocr_pages", {})
    for seg in statement_tables(doc, ctx):
        extractor = "ocr" if any(pno in ocr_pages for pno, _ in seg["pages"]) else "text"
        if seg["stmt"] in ("SOCE", "SUPP"):
            tables.append(dict(stmt=seg["stmt"], title=seg["title"], page=seg["pages"][0][0] + 1, deferred=True, extractor=extractor))
            continue
        rows_first = seg["pages"][0][1]
        spec, issues = interpret_columns(rows_first, ctx, seg["title"])
        table = dict(stmt=seg["stmt"], title=seg["title"][:120], page=seg["pages"][0][0] + 1, issues=issues, rows=[], columns=[], checks=[], extractor=extractor)
        if spec and spec["cols"]:
            spec["cols"] = fit_interim_periods(spec["cols"], seg["stmt"], ctx, issues)
        if spec and spec["cols"]:
            rows = []
            for i, (pno, body) in enumerate(seg["pages"]):
                part = body[spec["first"]:] if i == 0 else body
                for row in read_rows(part, spec, seg["stmt"]):
                    row["page"] = pno + 1
                    rows.append(row)
            if any(c.get("unit_known") is False for c in spec["cols"]):
                note = page_unit_note(doc[seg["pages"][0][0]])
                source = "page note"
                if note is None:
                    note = header_unit_note(rows_first[:spec["first"]])
                    source = "statement header"
                if note:
                    for c in spec["cols"]:
                        if (c.get("unit_known") is False
                                and (not c.get("currency_known") or c.get("currency") == note[1])):
                            c["unit"], c["currency"] = note
                            c["unit_known"] = True
                            c["unit_source"] = source
            elif any(c.get("unit") == 1 for c in spec["cols"]):
                # A bare 'Rs.' over a column reads as full rupees, but a page note such as 'In thousands of rupees'
                # can say otherwise. When the two disagree the unit is not known: leave it to proof from other reports.
                note = page_unit_note(doc[seg["pages"][0][0]])
                if note and note[0] != 1:
                    for c in spec["cols"]:
                        if c.get("unit") == 1 and c.get("currency", "LKR") == note[1]:
                            c["unit_known"] = False
            table["rows"] = trim_rows(seg["stmt"], rows)
            if len(table["rows"]) < len(rows):
                table["rows_trimmed"] = len(rows) - len(table["rows"])
            table["columns"] = [{k: c[k] for k in ("scope", "date", "months", "audit", "unit", "unit_known", "currency")} | ({"unit_source": c["unit_source"]} if "unit_source" in c else {}) | ({"period_refit": True} if c.get("period_refit") else {}) for c in spec["cols"]]
            if (seg["stmt"] == "IS" and not find(table["rows"], r"before (income )?(tax|taxation)")
                    and not (find(table["rows"], r"^(revenue|turnover|sales)\b")
                             and find(table["rows"], r"^gross (profit|loss)\b"))
                    and re.search(r"comprehensive", seg["title"], re.I)):
                table["stmt"] = "OCI"
            table["checks"] = check_table(table["stmt"], table["rows"], len(spec["cols"]))
        if extractor == "ocr":
            table["trusted"] = bool(table["checks"]) and all(c[4] for c in table["checks"])
            low, lowest = doc.low_confidence_numbers([pno for pno, _ in seg["pages"]])
            table["ocr_low_confidence_numbers"] = low
            table["ocr_lowest_confidence"] = lowest
        tables.append(table)
    return tables


def statements_wanted(tables):
    """IS and BS, unless a table of that kind already passes its checks."""
    passing = {t["stmt"] for t in tables if t.get("checks") and all(c[4] for c in t["checks"])}
    return [s for s in ("IS", "BS") if s not in passing]


def _found(tables, stmt):
    return any(t["stmt"] == stmt and t.get("rows") for t in tables)


def _read_with_ocr(doc, path, ctx, candidates, needed, result):
    docid = ctx.get("document_id") or pathlib.Path(path).stem
    ocr_doc = ocr_words.OcrDoc(doc, docid, path, candidates)
    ocr_doc.read_statement_pages(needed)
    tables = read_tables(ocr_doc, ctx) if ocr_doc.ocr_pages else None
    if (tables is None or not all(_found(tables, s) for s in needed)) and len(candidates) <= SHORT_REPORT_IMAGE_PAGES:
        before = len(ocr_doc.ocr_pages)
        ocr_doc.read_all_table_like()
        if len(ocr_doc.ocr_pages) > before:
            tables = read_tables(ocr_doc, ctx)
    result["ocr"] = ocr_doc.stats()
    return tables


def parse_pdf(path, ctx):
    doc = pymupdf.open(path)
    result = dict(document_id=ctx.get("document_id"), pages=len(doc), tables=[], issues=[])
    chars = sum(len(doc[i].get_text("text")) for i in range(min(len(doc), 40)))
    result["text_chars_first40"] = chars
    scanned = chars < 40 * min(len(doc), 40)
    use_ocr = ocr_words.ocr_enabled()
    if scanned and not use_ocr:
        result["issues"].append(SCANNED_ISSUE)
        return result
    if not scanned:
        result["tables"] = read_tables(doc, ctx)
    result["scanned"] = scanned
    needed = statements_wanted(result["tables"]) if use_ocr else []
    candidates = ocr_words.image_pages(doc) if needed else []
    if not candidates:
        if scanned:
            result["issues"].append(SCANNED_ISSUE)
        return result
    try:
        tables = _read_with_ocr(doc, path, ctx, candidates, needed, result)
    except Exception as e:
        result["issues"].append(f"ocr crash: {type(e).__name__}: {str(e)[:200]}")
        if scanned:
            result["issues"].append(SCANNED_ISSUE)
        return result
    if tables is not None:
        result["tables"] = tables
    if not any(t.get("extractor") == "ocr" for t in result["tables"]):
        result["issues"].append(f"ocr found no statement tables in {len(candidates)} image pages")
    return result


if __name__ == "__main__":
    path = sys.argv[1]
    ctx = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(parse_pdf(path, ctx), indent=0)[:4000])

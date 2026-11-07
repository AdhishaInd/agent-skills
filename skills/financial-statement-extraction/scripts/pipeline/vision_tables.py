"""Statements read by eye from page images, turned into parser tables.

Used for statements the parser cannot read: odd layouts, poor scans, and statements on pages the parser never
found. The figures still have to pass the same arithmetic checks as any parsed table before they load, and the
tables are marked extractor='vision' so they can always be told apart from parsed ones.

Source files: reviewed/vision/<document_id>.txt, one or more blocks:

    TABLE IS 25 | Statement of Comprehensive Income
    COLS COMPANY 2025-03-31 12 AUDITED 1 LKR ; COMPANY 2024-03-31 12 AUDITED 1 LKR
    Revenue | 132,796,423 | 113,411,460
    Other comprehensive income              <- a line with no '|' is a heading
    Direct expenses | (42,592,994) | -       <- brackets are negative; '-' is nil and left empty

COLS fields per column: scope, period end, months (0 on a balance sheet), audit, unit (1, 1000, 1000000), currency.
A line may continue onto later pages: 'PAGE 26' sets the page for the lines after it.
'MISSING <stmt> | <reason>' records that the report has no usable statement of that kind and why (no table is written).
'UNITS <unit> <currency>' outside a table gives the unit printed on the pages for parsed tables whose figures pass
but whose unit the parser could not read (e.g. 'all amounts in Sri Lanka Rupees 000's' on a scan).
The rows are given section codes the same way columns.read_rows does, so labels map through the same aliases.

Usage: python -I scripts/vision_tables.py <in_dir> <extracted_dir> <out_dir>
  writes <out_dir>/<doc>.json: the parsed output with each vision statement replacing the parsed one of its kind.
"""
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "pipeline"))
import normalize  # noqa: E402
from checks import check_table, column_status  # noqa: E402

NUM = re.compile(r"^\(?-?[\d,]*\.?\d+\)?$")


def value(s):
    s = s.strip().replace(" ", "")
    if s in ("", "-", "–", "—", "nil", "Nil"):
        return None
    if not NUM.match(s):
        raise ValueError(f"not a figure: {s!r}")
    neg = s.startswith("(") or s.startswith("-")
    v = float(s.strip("()").replace(",", "").lstrip("-"))
    return -v if neg else v


def rows_from(lines, stmt, page):
    """Same section and prefix rules as columns.read_rows, on transcribed lines."""
    out, section, prev_text, block = [], "NONE", "", ""
    for raw in lines:
        if raw.startswith("PAGE "):
            page = int(raw.split()[1])
            continue
        if "|" not in raw:
            label = raw.strip()
            n_label = normalize.label(label)
            code = normalize.section_code(label)
            if stmt == "CF" and normalize.cash_flow_section(label):
                section = normalize.cash_flow_section(label)
            if code and stmt == "BS":
                section = code
            if stmt in ("IS", "OCI") and re.search(r"attributable to$", n_label):
                block = n_label
            prev_text = label
            continue
        label, *vals = [p.strip() for p in raw.split("|")]
        vals = {j: v for j, v in enumerate(value(x) for x in vals) if v is not None}
        n_label = normalize.label(label)
        if stmt == "CF" and label and normalize.cash_flow_section(label):
            section = normalize.cash_flow_section(label)
        if stmt in ("IS", "OCI") and block and not re.search(r"(holders|owners|shareholders|parent|company|bank|controlling|minority)", n_label):
            block = ""
        if stmt in ("IS", "OCI") and re.search(r"attributable to ", n_label):
            block = ""
        if not label:
            prev_text = ""
            out.append(dict(label="", prefix="", section=section, values=vals, page=page))
            continue
        code = normalize.section_code(label)
        total_like = n_label.startswith("total ") or code is not None
        shown = f"{block} {label}" if block else label
        cf_total = stmt == "CF" and re.match(r"^net cash|^cash (generated|used|flows?)|^net (increase|decrease)|^cash and cash equivalents|^effect of|^exchange", n_label)
        out.append(dict(label=shown, prefix=prev_text if not block and not re.search(r"\d", prev_text or "") else "",
                        section="NONE" if total_like or cf_total else section, values=vals, page=page))
        prev_text = ""
    return out


def parse_file(path):
    tables, cur, units, missing = [], None, None, {}
    for raw in pathlib.Path(path).read_text().splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("MISSING "):
            head, _, why = line.partition("|")
            missing[head.split()[1]] = why.strip()
            cur = None
        elif line.startswith("UNITS "):
            _, u, ccy = line.split()
            units = (int(u), ccy)
            cur = None
        elif line.startswith("TABLE "):
            head, _, title = line.partition("|")
            _, stmt, page = head.split()
            cur = dict(stmt=stmt, title=title.strip(), page=int(page), lines=[], cols=[])
            tables.append(cur)
        elif line.startswith("COLS "):
            for c in line[5:].split(";"):
                scope, date, months, audit, unit, cur_ = c.split()
                cur["cols"].append(dict(scope=scope, date=date, months=int(months) or None, audit=audit,
                                        unit=int(unit), unit_known=True, currency=cur_, unit_source="vision"))
        else:
            cur["lines"].append(line.strip())
    out = []
    for t in tables:
        rows = rows_from(t["lines"], t["stmt"], t["page"])
        width = max((max(r["values"], default=-1) for r in rows), default=-1) + 1
        if width > len(t["cols"]):
            raise ValueError(f"{path}: {t['stmt']} p{t['page']} has a line with more figures than columns")
        table = dict(stmt=t["stmt"], title=t["title"], page=t["page"], issues=[], rows=rows, columns=t["cols"],
                     extractor="vision")
        table["checks"] = check_table(t["stmt"], rows, len(t["cols"]))
        out.append(table)
    return out, units, missing


def main(in_dir, extracted, out_dir):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    for f in sorted(pathlib.Path(in_dir).glob("*.txt")):
        doc = f.stem
        base = json.loads((pathlib.Path(extracted) / f"{doc}.json").read_text())
        vt, units, missing = parse_file(f)
        if missing:
            base["vision_missing"] = missing
            for k, why in missing.items():
                print(doc, k, "MISSING:", why)
        kinds = {t["stmt"] for t in vt}
        # The vision statement replaces every parsed table of its kind, so the two can never compete for one period.
        kept = [t for t in base["tables"] if t.get("stmt") not in kinds]
        if units:
            for t in kept:
                for c in t.get("columns") or []:
                    if c.get("unit_known") is False:
                        c["unit"], c["currency"], c["unit_known"], c["unit_source"] = units[0], units[1], True, "vision"
                        base["vision_units"] = True
                        print(doc, t["stmt"], f"p{t['page']}", "unit set from image", units, column_status(t))
        base["tables"] = kept + vt
        base["vision"] = sorted(kinds)
        (out / f"{doc}.json").write_text(json.dumps(base))
        for t in vt:
            st = column_status(t)
            fails = [c for c in t["checks"] if not c[4]]
            print(doc, t["stmt"], f"p{t['page']}", [st.get(j) for j in range(len(t["columns"]))],
                  "FAILED: " + "; ".join(f"{c[0]} col{c[1]} {c[2]} vs {c[3]}" for c in fails) if fails else "")


if __name__ == "__main__":
    main(*sys.argv[1:4])

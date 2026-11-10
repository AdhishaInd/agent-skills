"""Arithmetic checks that decide whether a table can be trusted.

Each check is [name, column_index, left, right, passed]. Rows are chosen by exact label shape and by their
position in the statement (tax lies between profit before tax and profit, the investing line lies after the
operating line), so a check cannot pass on a look-alike row elsewhere in the table.

Figures are compared as printed, so the tolerance is a few units of the printed figure: 2 for two terms, 3 for
three, 5 for more, since each printed term carries its own rounding. A printed unit is one digit in the last place
the terms show, so a table in Rs.'000 allows Rs.2,000 and one printed to one decimal allows 0.2. It never scales
with the size of the figures. A check whose terms are all nil is not written, because 0 = 0 proves nothing.

column_status: a column is PASS if it has a core check and every check passed, FAIL if any check failed, and
UNCHECKED if no core check could be made. table_status summarises the columns; the loader keeps PASS columns.
"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import normalize  # noqa: E402

BS_CORE = "assets=equity+liabilities"
IS_CORE = "pbt-tax=profit"
CF_CORE = "cf sections=net change"
CORE_CHECKS = {BS_CORE, IS_CORE, CF_CORE}
BS_ASSETS = "current+noncurrent assets=total assets"
BS_LIABS = "current+noncurrent liabilities=total liabilities"
BS_TOTAL = "equity+liabilities=total"
IS_DISC = "continuing+discontinued=profit"
IS_NCI = "parent+nci=profit"
IS_ASSOC = "profit+associates after tax=profit"
IS_GP = "revenue-cost=gross profit"
CF_CASH = "opening+net change=closing"

# Words a profit line can start with, in any printed order: 'profit/(loss)', '(loss)/profit', 'profit or loss'.
_WORD = r"p(?:rof|of|rot)[il]?t|profi|loss|surplus|deficit|earnings"
_PL = rf"(?:net |operating )?(?:{_WORD})(?: (?:or |and )?(?:{_WORD}))?"
_PERIOD = r"(?: for the (?:period|year|quarter|financial year|(?:three|six|nine|twelve) months)(?: (?:period|year))?)"
_TAXWORD = r"(?:income |corporate )?tax(?:es|ation)?"
_NOT_INCOME_TAX = r"financial services|value added|\bvat\b|\bnbt\b|nation building|levy|levies|crown|economic service"

PBT = re.compile(rf"^{_PL}(?: (?:from|on) ordinary activities)?{_PERIOD}? before ?(?:all )?{_TAXWORD}\b")
# Some reports (e.g. Asia Capital, CABO interims) take tax straight from 'Profit / Loss from Operating Activities' or
# 'Profit from operations'.
# It is taken as profit before tax only when no before-tax line exists and the next line with figures is the tax line.
PBT_OPERATING = re.compile(rf"^{_PL} from (?:operating activities|operations?)(?: after (?:net )?finance (?:expenses?|costs?|income))?$|^operating {_PL}$")
PBT_AFTER_VAT = re.compile(rf"^{_PL} after (?:vat|value added tax|taxes? on financial services|tax on financial services)")
TAX_WINDOW = 9  # rows from profit before tax to profit; anything further apart is not one statement's lines
PROFIT = re.compile(rf"^{_PL}(?: (?:from|on) ordinary activities)?(?: after {_TAXWORD})?{_PERIOD}?(?: after {_TAXWORD})?(?: (?:from )?(?:continuing|continued) operations?)?{_PERIOD}?(?: attributable to .*)?$")
TAX = re.compile(r"\btax(?:es|ation)?\b")
PROFIT_WORD = re.compile(r"^(?:net )?(?:profit|loss)\b")
DISCONTINUED = re.compile(r"discontinu")
CONTINUING = re.compile(r"continu(?:ing|ed) operations?")
TCI = re.compile(r"^total comprehensive")
PARENT = re.compile(r"(?:equity ?holders?|shareholders?|owners?)\b.*\b(?:parent|company|bank|society|group|corporation)\b|^(?:attributable to )?(?:the )?(?:equity ?holders?|shareholders?|owners?)(?: of the (?:parent|company|bank))?$|^parent$|^(?:the )?(?:company|bank)$")
NCI = re.compile(r"non controlling|minority")
GROSS = re.compile(r"^gross (?:profit|loss)(?: (?:profit|loss))?$")
COST = re.compile(r"^(?:cost of (?:sales?|revenue|goods sold|services?|turnover)|direct (?:costs?|expenses))(?: and services)?$")
REVENUE = re.compile(r"^(?:net )?(?:revenue|turnover|sales)(?: from contracts? with customers?)?(?: net)?$")

ASSETS = re.compile(r"^total assets?$")
TEL = re.compile(r"^total (?:equity and$|equity and (?:total )?liabilit|liabilities and (?:total )?(?:shareholders |share holders |stockholders |owners )?(?:equity|funds|capital)|(?:shareholders |stockholders )?(?:funds|equity|capital)(?: and reserves)? and (?:total )?liabilit|capital reserves and liabilit|reserves and liabilit)")
EQUITY_ALL = re.compile(r"^total equity$")
EQUITY = re.compile(r"^(?:total )?(?:(?:shareholders |stockholders |owners )?equity|shareholders funds|capital and reserves|equity and reserves)$"
                    # unit trusts and funds: the unitholders' fund stands where equity would be
                    r"|^(?:total )?(?:net assets attributable to (?:the )?unit ?holders|unit ?holders funds?)$")
EQUITY_PARENT = re.compile(r"^(?:total )?equity attributable|^total equity excluding non controlling|^total equity capital and\b")
LIABS = re.compile(r"^total (?:liabilities|liability)$")
CUR_ASSETS = re.compile(r"^total current assets$")
NC_ASSETS = re.compile(r"^total non current assets$")
CUR_LIABS = re.compile(r"^total current liabilit(?:ies|y)$")
NC_LIABS = re.compile(r"^total non current liabilit(?:ies|y)$")
HELD_FOR_SALE = re.compile(r"held for (?:sale|distribution)|disposal group")
# A bank's perpetual bond shown as its own block between total liabilities and equity (HDFC).
DEBT_CAPITAL = re.compile(r"^(?:debt capital|perpetual (?:bonds?|debentures?))$")

_CASHLINE = r"^(?:(?:net )?(?:cash ?flows?|cash|funds)|net flows? from|net (?:used in |generated |\(used in\) )+(?:from|in))\b.*\b"   # incl. 'Net Flow from ...', 'Net Generated from ...'
CF_OP = re.compile(_CASHLINE + r"(?:operating activities|operations?|operating)\b")
CF_INV = re.compile(_CASHLINE + r"(?:investing|investment activities)\b")
CF_FIN = re.compile(_CASHLINE + r"(?:in)?(?:financing|finance activities)\b")   # 'used infinancing' (missing space)
CF_NET = re.compile(r"^(?:net |total )?(?:net )?(?:increase|decre?ase|changes?|movements?)\b.*\b(?:cash|period|year)\b|^net (?:cash ?flows?|cash|funds)\b.*\b(?:inflow|outflow|increase|decrease|period|year)\b|^net (?:inflow|outflow)")
CF_FX = re.compile(r"(?:effect|impact|gain|loss|difference|adjustment|movement|change|fluctuation)s?\b.*\b(?:exchange|currency|translation)|^(?:net )?(?:foreign )?(?:exchange|currency|translation)\b|^(?:un)?reali[sz]ed (?:foreign )?exchange\b")   # 'Unrealised exchange loss/(gain) on cash' (CHMX)
CF_OD = re.compile(r"^(?:less )?(?:bank )?over ?drafts?\b|^bank overdrafts?\b")   # an overdraft line bridging opening and closing cash (BLUE)
CF_NET_TAIL = re.compile(r"^(?:cash )?equivalents during the (?:period|year)$")   # tail of a wrapped net-change label
CF_OPEN = re.compile(r"(?:cash|cash ?flows?|bank)\b.*\b(?:beginning|start|commencement|opening)\b|^opening\b.*\b(?:cash|balance)\b|^balance at (?:the )?(?:beginning|start)")
CF_OPEN_BARE = re.compile(r"^at (?:the )?(?:beginning|start) of (?:the )?(?:period|year)")
CF_CLOSE = re.compile(r"(?:cash|bank)\b.*\b(?:end|close|closing)\b|^closing\b.*\b(?:cash|balance)\b|^balance at (?:the )?(?:end|close)")
CF_CLOSE_BARE = re.compile(r"^at (?:the )?(?:end|close) of (?:the )?(?:period|year)")
CF_TAIL = 8  # rows after the financing total that can still belong to the statement if no closing line was read
CF_OUT = re.compile(r"\b(?:used|outflow)\b")
CF_IN = re.compile(r"\b(?:from|generated|inflow|provided)\b")


def find(rows, *patterns):
    """First row with values whose label matches, trying the patterns in order."""
    for rx in patterns:
        for r in rows:
            if re.search(rx, normalize.label(r["label"])) and r["values"]:
                return r
    return None


def _v(row, j):
    """Printed value of a row in a column. A table read back from JSON has string keys."""
    vals = row["values"]
    return vals[j] if j in vals else vals.get(str(j))


def _nil(row, j):
    """Value with a dash or blank counted as nil, for lines that may be empty in one column."""
    v = _v(row, j)
    return 0.0 if v is None else v


def _places(x):
    for k in range(4):
        if abs(round(x, k) - x) < 1e-9:
            return k
    return 4


def _tolerance(terms):
    unit = 10.0 ** -max(_places(t) for t in terms)
    return unit * (2 if len(terms) <= 2 else 3 if len(terms) == 3 else 5)


def _add(res, name, j, lefts, right, terms):
    """Write a check. lefts holds the left sides the statement's layout allows; the closest one is reported."""
    terms = [t for t in terms if t is not None]
    if not any(terms):
        return
    left = min(lefts, key=lambda x: abs(x - right))
    res.append([name, j, left, right, abs(left - right) <= _tolerance(terms) + 1e-9])


def _at(rows, rx, start=0, end=None, skip=None):
    """Index of the first row in [start, end) with values and a matching label, or None."""
    for i in range(start, len(rows) if end is None else end):
        if rows[i]["values"] and rx.search(rows[i]["norm"]) and not (skip and skip.search(rows[i]["norm"])):
            return i
    return None


CONTINUATION = re.compile(r"^(?:activities|(?:operating|investing|financing) activities|operations|equivalents|cash equivalents|(?:cash )?equivalents during the (?:period|year)|equity and liabilities|liabilities|tax|taxation|income tax|(?:the )?(?:period|year))$")


def _prepare(rows):
    """Add the label to match on: printed change columns ('>100%') and note references are not part of the name."""
    out = []
    for r in rows:
        norm = re.sub(r"\b\d+\b", " ", normalize.label(r["label"]))
        norm = re.sub(r"\brs$", "", norm.strip())  # 'Rs. '000' after the name
        norm = re.sub(r"\s+(?:notes?(?: [a-z])?|[a-z])\s*$", "", " ".join(norm.split()))
        norm = re.sub(r"\bl(?=n[a-z])", "i", norm)  # 'lncrease', 'lncome': a text layer reading I as l
        if CONTINUATION.search(norm) and r.get("prefix"):
            norm = normalize.label(r["prefix"]) + " " + norm
        out.append(dict(r, norm=norm))
    return out


def _balance_sheet(rows, n):
    res = []
    ta = _at(rows, ASSETS)
    tel = _at(rows, TEL, ta + 1 if ta is not None else 0)
    if tel is None:
        tel = _at(rows, TEL)
    # With the assets half unread, 'total assets' can only come from a segment note further on.
    if ta is not None and tel is not None and ta > tel and rows[ta].get("page") != rows[tel].get("page"):
        ta = None
    tl = _at(rows, LIABS)
    nci = _at(rows, NCI)
    tca, tnca = _at(rows, CUR_ASSETS), _at(rows, NC_ASSETS)
    tcl, tncl = _at(rows, CUR_LIABS), _at(rows, NC_LIABS)
    te_all = _at(rows, EQUITY_ALL)
    equity_rows = [i for i, r in enumerate(rows) if r["values"] and EQUITY.search(r["norm"]) and i != te_all]
    parent_rows = [i for i, r in enumerate(rows) if r["values"] and EQUITY_PARENT.search(r["norm"])]

    def equity(j):
        """The equity totals this column prints, as term lists. Total equity comes first; a shareholders' total may exclude NCI."""
        out = []
        if te_all is not None and _v(rows[te_all], j) is not None:
            out.append([_v(rows[te_all], j)])
        for i in equity_rows + parent_rows:
            if _v(rows[i], j) is not None:
                out.append([_v(rows[i], j)])
                if nci is not None and _v(rows[nci], j) is not None:
                    out.append([_v(rows[i], j), _v(rows[nci], j)])
        return out

    def liabilities(j):
        if tl is not None and _v(rows[tl], j) is not None:
            stop = min([i for i in equity_rows + parent_rows + [te_all, tel] if i is not None and i > tl], default=tl)
            debt = [_nil(r, j) for r in rows[tl + 1:stop] if r["values"] and DEBT_CAPITAL.search(r["norm"])]
            return [_v(rows[tl], j)] + debt
        if tcl is not None and tncl is not None:
            last = max(tcl, tncl)
            end = tel if tel is not None and tel > last else min(last + 4, len(rows))
            held = [_nil(r, j) for r in rows[last + 1:end] if r["values"] and HELD_FOR_SALE.search(r["norm"])]
            return [_nil(rows[tcl], j), _nil(rows[tncl], j)] + held
        return None

    # Some reports print the liability subtotals and the grand total with no label under 'total equity'. They are
    # taken only as one unbroken run of figures that ends the statement, and each column must meet both
    # assets = grand total and equity + subtotals = grand total.
    unlabelled = []
    if tel is None and tl is None and tcl is None and tncl is None and ta is not None and te_all is not None and ta < te_all:
        for i in range(te_all + 1, len(rows)):
            if not rows[i]["values"] or rows[i].get("page") != rows[te_all].get("page"):
                break
            if not rows[i]["norm"]:
                unlabelled.append(i)
        if len(unlabelled) < 2:
            unlabelled = []

    for j in range(n):
        a = _v(rows[ta], j) if ta is not None else None
        b = _v(rows[tel], j) if tel is not None else None
        eqs, li = equity(j), liabilities(j)
        if unlabelled and a is not None and _v(rows[te_all], j) is not None and _v(rows[unlabelled[-1]], j) is not None:
            g, e = _v(rows[unlabelled[-1]], j), _v(rows[te_all], j)
            subs = [_nil(rows[i], j) for i in unlabelled[:-1]]
            _add(res, BS_CORE, j, [a], g, [a, g])
            _add(res, BS_TOTAL, j, [e + sum(subs)], g, [e] + subs + [g])
            continue
        if a is not None and b is not None:
            _add(res, BS_CORE, j, [a], b, [a, b])
        elif a is not None and eqs and li:
            eq = min(eqs, key=lambda e: abs(sum(e) + sum(li) - a))
            _add(res, BS_CORE, j, [a], sum(eq) + sum(li), [a] + eq + li)
        if b is not None and eqs and li:
            eq = min(eqs, key=lambda e: abs(sum(e) + sum(li) - b))
            _add(res, BS_TOTAL, j, [sum(eq) + sum(li)], b, eq + li + [b])
        if a is not None and tca is not None and tnca is not None and _v(rows[tca], j) is not None and _v(rows[tnca], j) is not None:
            last = max(tca, tnca)
            held = [_nil(r, j) for r in rows[last + 1:ta] if r["values"] and HELD_FOR_SALE.search(r["norm"])] if ta > last else []
            terms = [_v(rows[tca], j), _v(rows[tnca], j)] + held
            _add(res, BS_ASSETS, j, [sum(terms)], a, terms + [a])
        if tl is not None and tcl is not None and tncl is not None and _v(rows[tl], j) is not None:
            last = max(tcl, tncl)
            held = [_nil(r, j) for r in rows[last + 1:tl] if r["values"] and HELD_FOR_SALE.search(r["norm"])] if tl > last else []
            terms = [_nil(rows[tcl], j), _nil(rows[tncl], j)] + held
            _add(res, BS_LIABS, j, [sum(terms)], _v(rows[tl], j), terms + [_v(rows[tl], j)])
    return res


def _tax_amount(lines, j):
    """Tax of the column from the tax lines. A last line that totals the ones above it is the tax figure."""
    vals = [_nil(r, j) for r in lines]
    if len(vals) > 1 and abs(abs(sum(vals[:-1])) - abs(vals[-1])) <= _tolerance(vals):
        return vals[-1]
    return sum(vals)


def _income_statement(rows, n):
    res = []
    skip = re.compile(_NOT_INCOME_TAX)
    pbt = _at(rows, PBT, skip=skip)
    if pbt is None:
        pbt = _at(rows, PBT_AFTER_VAT)
    if pbt is None:
        # 'Profit before income tax and VAT on financial services': with no other before-tax line, this is the line
        # both taxes are taken from; the tax lines between it and profit are summed.
        pbt = _at(rows, PBT)
    if pbt is None:
        # The operating-profit line the tax is taken from: the next line with figures must be the tax line.
        for op in (i for i, r in enumerate(rows) if r["values"] and PBT_OPERATING.search(r["norm"])):
            nxt = next((i for i in range(op + 1, len(rows)) if rows[i]["values"]), None)
            # A tax line printed nil ('-') in every column right below counts too; profit must then equal it.
            if op + 1 < len(rows) and not rows[op + 1]["values"] and TAX.search(rows[op + 1]["norm"]) and not PROFIT_WORD.search(rows[op + 1]["norm"]):
                nxt = op + 1
            if nxt is not None and TAX.search(rows[nxt]["norm"]) and not PROFIT_WORD.search(rows[nxt]["norm"]):
                pbt = op
                break
    if pbt is not None:
        # 'Profit attributable to discontinued operations' is a part of profit, never the profit line.
        pat = _at(rows, PROFIT, pbt + 1, min(pbt + TAX_WINDOW, len(rows)), skip=DISCONTINUED)
        if pat is None:
            # No profit line: tax lines lead straight to total comprehensive income, with no OCI between (Panasian).
            after = [i for i in range(pbt + 1, min(pbt + TAX_WINDOW, len(rows))) if rows[i]["values"]]
            k = 0
            while k < len(after) and TAX.search(rows[after[k]]["norm"]) and not PROFIT_WORD.search(rows[after[k]]["norm"]):
                k += 1
            if 0 < k < len(after) and TCI.search(rows[after[k]]["norm"]):
                pat = after[k]
        if pat is not None:
            # 'Operating profit before taxes' or 'Profit before tax' can precede the line that tax is taken from.
            pbt = max(i for i in range(pbt, pat) if rows[i]["values"] and (i == pbt or (PBT.search(rows[i]["norm"]) and not skip.search(rows[i]["norm"]))))
            between = [r for r in rows[pbt + 1:pat] if r["values"]]
            disc = [r for r in between if DISCONTINUED.search(r["norm"])]
            tax = [r for r in between if TAX.search(r["norm"]) and r not in disc and not PROFIT_WORD.search(r["norm"])]
            final = pat
            if CONTINUING.search(rows[pat]["norm"]):
                nxt = _at(rows, PROFIT, pat + 1, skip=re.compile(f"{CONTINUING.pattern}|discontinu"))
                end = nxt if nxt is not None else min(pat + TAX_WINDOW, len(rows))
                ds = [i for i in range(pat + 1, end) if rows[i]["values"] and DISCONTINUED.search(rows[i]["norm"])]
                if ds:
                    # The total of both is printed right after the discontinued line, in some reports under a
                    # 'total comprehensive income' label; only that position is taken, never a later one.
                    after = _at(rows, re.compile(""), ds[-1] + 1)
                    if after is not None and after != nxt and TCI.search(rows[after]["norm"]):
                        nxt = after
                if nxt is None:
                    ds = []
                if ds:
                    d = ds[-1]  # the after-tax line, if before-tax and tax lines are printed too
                    final = nxt
                    for j in range(n):
                        c, dv, f = _v(rows[pat], j), _nil(rows[d], j), _v(rows[nxt], j)
                        if c is not None and f is not None:
                            _add(res, IS_DISC, j, [c + dv], f, [c, dv, f])
            for j in range(n):
                a, p = _v(rows[pbt], j), _v(rows[pat], j)
                if a is None or p is None:
                    continue
                if not tax and abs(a - p) > _tolerance([a, p]):
                    continue  # no tax line was read, so nothing says what connects these two figures
                t = _tax_amount(tax, j) if tax else 0.0
                extra = sum(_nil(r, j) for r in disc)
                terms = [a, t, p] + [_nil(r, j) for r in disc]
                _add(res, IS_CORE, j, [a - abs(t) + extra, a + abs(t) + extra], p, terms)
            if final == pat:
                # Share of associates added after the after-tax profit, then the profit that is attributed (LALU).
                nxt = next((i for i in range(pat + 1, min(pat + 4, len(rows))) if rows[i]["values"]), None)
                fin = next((i for i in range(nxt + 1, min(nxt + 3, len(rows))) if rows[i]["values"]), None) if nxt is not None else None
                if fin is not None and ASSOC_AFTER_TAX.search(rows[nxt]["norm"]) and PROFIT.search(rows[fin]["norm"]):
                    final = fin
                    for j in range(n):
                        c, s_, f = _v(rows[pat], j), _nil(rows[nxt], j), _v(rows[fin], j)
                        if c is not None and f is not None:
                            _add(res, IS_ASSOC, j, [c + s_], f, [c, s_, f])
            _attribution(res, rows, pat, final, n)
    _gross_profit(res, rows, n)
    return res


ASSOC_AFTER_TAX = re.compile(r"^share of (?:net )?(?:profit|loss|results?)\b.*\bassociate.*\bnet of tax")
ATTRIBUTION_WINDOW = 30  # rows after profit that can hold the split; later text is notes run on to the table
OTHER_STATEMENT = re.compile(r"^total (?:assets|equity|liabilities)\b|operating activities|^equity attributable|^total equity attributable")


def _attribution(res, rows, pat, final, n):
    """Parent + NCI = profit. Pairs can also split continuing or discontinued profit or total comprehensive income,
    so a pair is only held against profit if it matches none of those."""
    stop = min(final + ATTRIBUTION_WINDOW, len(rows))
    for i in range(final + 1, stop):
        if OTHER_STATEMENT.search(rows[i]["norm"]):
            stop = i
            break
    pairs = []
    for i in range(final + 1, stop):
        if rows[i]["values"] and NCI.search(rows[i]["norm"]):
            near = [k for k in (i - 1, i + 1) if final < k < stop and rows[k]["values"] and PARENT.search(rows[k]["norm"]) and not NCI.search(rows[k]["norm"])]
            if near:
                pairs.append((near[0], i))
    if not pairs:
        return
    other = [i for i in range(pat, stop) if rows[i]["values"] and i != final and (i == pat or DISCONTINUED.search(rows[i]["norm"]) or TCI.search(rows[i]["norm"]))]
    for j in range(n):
        f = _v(rows[final], j)
        if f is None:
            continue
        rest = []
        for k, i in pairs:
            if _v(rows[k], j) is None and _v(rows[i], j) is None:
                continue
            x, y = _nil(rows[k], j), _nil(rows[i], j)
            if abs(x + y - f) <= _tolerance([x, y, f]):
                _add(res, IS_NCI, j, [x + y], f, [x, y, f])
                rest = None
                break
            if not any(_v(rows[o], j) is not None and abs(x + y - _v(rows[o], j)) <= _tolerance([x, y, _v(rows[o], j)]) for o in other):
                rest.append((x, y))
        if rest:
            x, y = rest[0]
            _add(res, IS_NCI, j, [x + y], f, [x, y, f])


def _gross_profit(res, rows, n):
    gp = _at(rows, GROSS)
    if gp is None:
        return
    before = [i for i in range(gp) if rows[i]["values"]]
    if len(before) < 2:
        return
    c, r = rows[before[-1]], rows[before[-2]]
    if not (COST.search(c["norm"]) and REVENUE.search(r["norm"])):
        return
    for j in range(n):
        rv, cv, g = _v(r, j), _v(c, j), _v(rows[gp], j)
        if rv is not None and cv is not None and g is not None:
            _add(res, IS_GP, j, [rv - abs(cv)], g, [rv, cv, g])


def _section(row, j):
    """Section total as printed, and the same with the sign its label states, e.g. 'net cash used in' printed unbracketed."""
    v = _v(row, j)
    if v is not None and v > 0 and CF_OUT.search(row["norm"]) and not CF_IN.search(row["norm"]):
        return v, -v
    return v, v


def _cash_flow(rows, n):
    """Sections (at least two of operating, investing, financing; small companies often have no investing or no
    financing activities) must add up to the net change in cash, or, when no net change line is printed, to
    closing minus opening cash. Opening + net change = closing is checked too."""
    res = []
    before = re.compile(r"\bbefore\b")
    first_inv = _at(rows, CF_INV, skip=before)
    first_fin = _at(rows, CF_FIN, (first_inv + 1) if first_inv is not None else 0, skip=before)
    nxt = first_inv if first_inv is not None else first_fin
    if nxt is None:
        # only an operating section (a fund with no investing or financing flows): its total must equal the net
        # change, and opening + net change must equal closing - two independent printed figures
        ops1 = [i for i in range(len(rows)) if rows[i]["values"] and CF_OP.search(rows[i]["norm"])]
        if not ops1:
            return res
        nxt = ops1[-1] + 1
        single = True
    else:
        single = False
    # The operating total is the last such line before the next section: 'cash generated from operations' comes first.
    ops = [i for i in range(nxt) if rows[i]["values"] and CF_OP.search(rows[i]["norm"])]
    if not ops:
        return res
    net_ops = [i for i in ops if rows[i]["norm"].startswith("net ")]
    op = (net_ops or ops)[-1]
    # An unlabelled total after tax and interest paid is the section's real total, e.g. CDB and SUN print it that way.
    blanks = [i for i in range(op + 1, nxt) if rows[i]["values"] and not rows[i]["norm"]]
    op_alt = blanks[-1] if blanks else None
    totals, nil_idx = [op], set()
    if first_inv is None or first_fin is None:
        # a section total printed with dashes in every column ('Net cash generated from financing activities  -')
        for rx, have in ((CF_INV, first_inv), (CF_FIN, first_fin)):
            if have is None:
                k = next((i for i in range(op + 1, len(rows)) if not rows[i]["values"] and rows[i]["norm"].startswith("net ")
                          and rx.search(rows[i]["norm"])), None)
                if k is not None:
                    nil_idx.add(k)
    if first_inv is not None:
        # The investing total is the last matching line of its section.
        stop = first_fin if first_fin is not None else len(rows)
        later = [i for i in range(first_inv, stop) if rows[i]["values"] and CF_INV.search(rows[i]["norm"]) and not before.search(rows[i]["norm"])]
        if not later:
            return res
        totals.append(later[-1])
    if first_fin is not None:
        totals.append(first_fin)
    totals = sorted(set(totals) | nil_idx)
    last = totals[-1]
    # No financing total, but lines between the investing total and the net change / opening cash (SWAD, CHMX 49992
    # print the financing items without a total; the heading has no figures so it is not in rows): those lines are
    # offered as the financing section, as an alternative sum only - still held to the net change or closing - opening.
    fin_items = []
    if first_fin is None and first_inv is not None and not any(CF_FIN.search(rows[k]["norm"]) for k in nil_idx):
        for i in range(last + 1, len(rows)):
            nm = rows[i]["norm"]
            if CF_NET.search(nm) or CF_OPEN.search(nm) or CF_CLOSE.search(nm) or CF_FX.search(nm) or CF_NET_TAIL.search(nm):
                break
            if rows[i]["values"]:
                fin_items.append(i)
    net = _at(rows, CF_NET, last + 1)
    opening = _at(rows, CF_OPEN, last + 1)
    closing = _at(rows, CF_CLOSE, (opening if opening is not None else last) + 1)
    if len(totals) + bool(fin_items) < 2 and not (single and None not in (net, opening, closing)):
        return res
    window = closing if closing is not None else min(last + CF_TAIL, len(rows))
    fx = [i for i in range(last + 1, window) if rows[i]["values"] and CF_FX.search(rows[i]["norm"]) and i != net]
    # an overdraft line printed between opening and closing cash bridges the two, like an exchange line
    if opening is not None and closing is not None:
        fx += [i for i in range(opening + 1, closing) if rows[i]["values"] and CF_OD.search(rows[i]["norm"]) and i not in fx]
    disc = [i for i in range(last + 1, net if net is not None else last + 1) if rows[i]["values"] and DISCONTINUED.search(rows[i]["norm"])]
    for j in range(n):
        # a section total printed as a dash in this column (it has figures in others) is nil
        sections = [(0.0, 0.0) if k in nil_idx or _v(rows[k], j) is None else _section(rows[k], j) for k in totals]
        nv = _v(rows[net], j) if net is not None else None
        ov = _v(rows[opening], j) if opening is not None else None
        cv = _v(rows[closing], j) if closing is not None else None
        if op_alt is not None and _v(rows[op_alt], j) is not None and sections[0][0] is not None:
            # Only a line that totals the operating line and the lines under it; a blank-labelled line further
            # down is an investing item whose name was lost.
            parts = [sections[0][0]] + [_nil(r, j) for r in rows[op + 1:op_alt] if r["values"]]
            if abs(sum(parts) - _v(rows[op_alt], j)) <= _tolerance(parts + [_v(rows[op_alt], j)]) + 1e-9:
                sections[0] = (_v(rows[op_alt], j),) * 2
        fxs = [_nil(rows[k], j) for k in fx]
        change = nv if nv is not None else (cv - ov) if (ov is not None and cv is not None) else None
        if change is not None and all(x[0] is not None for x in sections):
            extra = sum(_nil(rows[k], j) for k in disc)
            fin = sum(_nil(rows[k], j) for k in fin_items)
            lefts = []
            for base in (sum(x[0] for x in sections) + extra, sum(x[1] for x in sections) + extra):
                for b in ([base, base + fin] if fin_items else [base]):
                    lefts += [b] + [b + m * sum(fxs) for m in (1, -1)] * bool(fxs)
            parts = [x[0] for x in sections] + [_nil(rows[k], j) for k in fin_items] + ([nv] if nv is not None else [ov, cv]) + fxs
            _add(res, CF_CORE, j, lefts, change, parts)
        if nv is not None and ov is not None and cv is not None:
            lefts = [ov + nv] + [ov + nv + m * sum(fxs) for m in (1, -1)] * bool(fxs)
            _add(res, CF_CASH, j, lefts, cv, [ov, nv, cv] + fxs)
    return res


def check_table(stmt, rows, n):
    """Arithmetic checks per column. Returns list of [name, column, left, right, passed]."""
    rows = _prepare(rows)
    if stmt == "BS":
        return _balance_sheet(rows, n)
    if stmt in ("IS", "OCI"):
        return _income_statement(rows, n)
    if stmt == "CF":
        return _cash_flow(rows, n)
    return []


def column_status(table):
    """{column_index: 'PASS'|'FAIL'|'UNCHECKED'} for a parsed table."""
    checks = table.get("checks")
    n = len(table.get("columns") or [])
    if checks is None:
        checks = check_table(table.get("stmt"), table.get("rows") or [], n)
    out = {j: "UNCHECKED" for j in range(n)}
    for j in {c[1] for c in checks}:
        mine = [c for c in checks if c[1] == j]
        if not all(c[4] for c in mine):
            out[j] = "FAIL"
        elif any(c[0] in CORE_CHECKS for c in mine):
            out[j] = "PASS"
        else:
            out[j] = "UNCHECKED"
    return out


def table_status(table):
    """PASS if any column passes, since bad columns are refused one by one. Else FAIL if any fails, else UNCHECKED."""
    states = set(column_status(table).values())
    return "PASS" if "PASS" in states else "FAIL" if "FAIL" in states else "UNCHECKED"

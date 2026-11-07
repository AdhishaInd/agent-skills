"""OCR that looks like page.get_text("words"), so the same parser reads scanned pages.

OcrDoc wraps a pymupdf document. Pages chosen for OCR answer get_text("words") with tuples in points; every other
call and every other page goes to the real pymupdf object. Nothing here decides what a number means.

Cost control: pages with an image are first read at low resolution (top of page only) to find statement headings and
page orientation. A heading counts only if it starts a short line near the top of a page that is not a notes page.
Long reports are swept from a quarter of the way in; reaching the notes first means the statements lie before, so the
sweep turns back. Only statement pages and their continuation pages are read at full resolution. Pages with no text
drawn as vector outlines are treated like image pages. Everything goes to
ocr_cache/<docid>.json as raw line boxes, so a rerun does no OCR and word splitting can change without new OCR.

Commands: python -I pipeline/ocr_words.py list [--workers N] [--tickers A,B] [--out file.tsv] [--reports dir] [--db file]
          python -I pipeline/ocr_words.py show <pdf> <page number> [--words]
"""
import json
import math
import os
import pathlib
import re
import sys
import time
import unicodedata

import pymupdf

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE_VERSION = 1
FULL_LONG_SIDE = 2400       # pixels on the long side of a page, about 205 dpi on A4
LOW_LONG_SIDE = 1100        # about 95 dpi on A4
NOMINAL_LONG_SIDE = 842     # pages far from A4 size are scaled to this, because the parser's tolerances are in points
MIN_TEXT_CHARS = 40
MIN_IMAGE_COVER = 0.5
MIN_OUTLINE_PATHS = 300   # a page with no text but this many paths has its text drawn as outlines
MIN_BOXES_TEXT_PAGE = 8     # fewer boxes than this at low resolution: a photo or a divider
MIN_BOXES_TABLE_PAGE = 15
MAX_CONTINUATION_PAGES = 2
START_FRACTION = 0.25      # where the sweep of a long report starts
AFTER_PAGES = 3            # pages looked at after everything wanted has been seen
RUN_GAP_PAGES = 3          # pages without a heading that end a run of statement pages
LOW_CONFIDENCE = 0.90
# Seconds per page for the estimate from `list`; measured on the test set, one thread per process.
EST_TRIAGE_S = 2.5
EST_FULL_S = 14.0

VOCAB_TEXT = "of the and in income cash financial to at other for assets profit net total tax from on loss rs as liabilities equity year plc comprehensive period interest company bank value a statement statements operating share current finance expenses activities non march fair cost december property increase capital or no equivalents per with decrease investment paid shares equipment before plant ended loans trade due group related benefit receivables lanka used flows investments balance expense deferred lease gain are dividend changes borrowings by sri earnings annual revenue is ltd note limited lkr report notes through companies interim attributable impairment change holders term provision liability financing insurance intangible during gross pvt reserve controlling payables amounts market shareholders been operations amortised end right colombo use investing accounting ordinary level depreciation losses have generated these stated received instruments that proceeds fund parent act price under public bearing an defined not exchange services parties inventories sale revaluation be retirement disposal number reversal asset months deposits securities less purchase beginning flow director gains position page costs acquisition rate nil employee years information private sales debt stage holdings has actuarial reserves subsidiaries land short measured customers was audited after obligations which accounted benefits taxation banks reporting holding administrative mn basic amount january amortisation life part form were dividends directors subsidiary issue payable premium april ceylon pages adjustments effect compliance retained working issued mrs figures foreign integral biological date obligation quarter policies advances held balances reclassified voting gratuity requirements management may ratio commission distribution transactions repayment consolidated recognised charge receivable segment overdraft board analysis fee credit loan lkas amortization taxes there prepared national interests unaudited results subsequent investees properties overdrafts business above fixed traded plan million commitments payments than items adjusted payment hand government trust fvoci general one claims contract minimum party valuation currency usd long based its leasing periods owners option development employees basis road people stock will condensed out unit treasury commercial float off all accordance plans highest bonds seylan diluted hatton lowest written trading name building available standard debentures february percentage movement measurement surplus capitalization transfer deductions within buildings derivative contingent risk others write contracts funds brackets slfrs executive indicate over quoted provisions last carrying chairman selling this associate significant translation required agreements audit reinsurance corporate adjustment singer central listing dec transferred personnel charges contingencies fvtpl registered june requirement allowance average follows given perera office sampath investee subject direct principal silva rental recorded contribution statutory incorporated made material shareholding transfers rupees presentation vat listed section following expenditure rules growth it closing maturity nature final rates including first set repurchase takaful events weighted amounting nine integrated additions oci hayleys plantations obtained placements disclosed preparation bn amana regulatory classified assumptions fernando depositors staff continuing rentals equivalent banking future leases prepayments shareholder certify disclosures hotels rule method three terms any accumulated administration subordinated associates joint service provisional discount below times discontinued bearer fees differences up fully impact disclosure hire expected require twenty products assessment july between rights remeasurement policy bills more billion corporation appointed security tier tea advance dfcc entity sub standards outstanding those managing mawatha institutions construction new previous receipts mar progress capitalisation deposit work thousands september return motor forward account our their performance amortized salary rent key freehold further lands presented earning goodwill recoverable five power profits portion respect opening employment union carried acquired values governance chief included mohamed approved added place directly miss cargills segmental prices result effective tel derecognition cse components scrip facilities galle estate incurred margin repayments inventory major earned unquoted review officer international creditors details since independent hierarchy debts transaction provided ultimate debenture includes arising impaired post consumable borrowing hnb grants sanasa monthly sheet settlement comparable into book type largest bond fvtoci accounts against relating inter approval adequacy softlogic same where lankan time difference entities back guarantees prime portfolio marketing keells investor accrued applicable days inputs would classification unclaimed inland asia debtors chartered leasehold considered reinsurers line table contributions fax recognition underwriting comparative lolc goods also outflow twelve annually us accordingly refer local ceded amendments ceo ratios distributions include ecl linked unrealised unearned provident dialog premiums read industries each granted using consideration recognized unallocated representing awplr provide supplementary contd retiring common john sold temporary assurance conjunction venture represented pro moving methods telephone direction proceed hotel external product cocoshell realised appeal liquid domiciled movements slow complies policyholders rubber rou bbb operation reconciliation levy borrowed rupee industry said turnover reported sector should addition except respectively registration comply meeting comprise reverse prior borrowers engineering strategic family trusts accountants disposals determined perch kandy taxable demand month assessments increment legal soysa bad behalf purpose purposes designated sscl partners inflow merchant applied resigned savings never who shareholdings street occurring authorised produce economic liquidity approach computation cover resorts present solutions social increased subsequently vehicles strategy november fort reversals ventures global otherwise when weerasinghe vasudevan unsecured exposure preference timber estimates had category past additional unfavourable vallibel acturial consumer october united top quality preparing fellow scheme amalgamation responsibility sovereign licensed tobacco doubtful excluding owned sensitivity calculated money instrument certified reports august but don high unless they nations pledged furniture about initial purchased software favourable papers relevant requires associated continued special committee grant bandaranayake repayable reclassification located units options such only undrawn slisbs hedge facility purchases comprising obsolete deutsche pte senthilverl premises pertaining senkadagala ending guarantee janashakthi real class charged valued amounted equal wht both leadership variance manufacturing refundable similar determination agreement individual age penalty quarterly customer establishment discussion pieris residencies indirect remuneration affiliate withdrawal together test adopted declared markets profitability receipt segments yield kassim recurrent suppliers model operational bonus followed according lankem amended estimated circumstances gold compared pan item retail active redeemable treasuries equities installments pension members raised iii explanatory cumulative funding sithampalam redemption certification we auditors import revalued control computer represents arisen minority categories chevron individually smb being remaining providing food square rated branches packaging court respective core situated lkb six contents dated aggregate next ownership materials hapangama renuka thereto nos changed surcharge fabric sarvodaya offs dollar ppe appropriate proposed peoples bargain exports rajaratnam almas industrial responsible until stake leisure mortgage institute projects compliant holder face necessary energy ircsl add secretary commissioner kapruka bene consistent restructuring two overview hedges cgir nci creditor fvpl second existing repurchased unrealized measurements deceased relations access main commencing asiri totaling teejay province equipments summary allocated settled clean unobservable eliminations mark kmp citizens alumex claim receiving liable machinery wise published every consultants towers facsimile rajiyah crop referring project trustee retakaful quick cinnamon cic cts lncome afs secured taken solar hydro assetline pay herath hold resolution motors cables cbsl ndb authorized contractual performing royal extraordinary summarised restated intercompany perches professional assessed eps foot comprises cards commitment observable better dues actuary ceybank falls lifetime floating fintrex cashflow composition salaries resident down conditions support prevailing rating recommended restricted singapore messrs mortality wealth previously settlements vehicle base fuad nancial course shown promotional separate slfrss functional foods sum invested pawning head upon browns lat british letter richard hospital elpitiya primary represent strength concern however shall jan publication vignarajah gunawardena regulation relationship domestic immature american repo regnis senanayake step securitization thambiayah going leased decision does electrical ravindra recovery duration variable pending personal list export peiris semi cooray later brokers ceylinco notice resort asian jat esos creasy jayasinghe point useful techniques day esop nanayakkara ranasinghe ambeon maximum arose compensation chairperson collective process relation fittings resulting enterprise bill raw while different housing collateral placement munasinghe ceramics resale miscellaneous epf mushtaq reflecting advantis participating holiday having activity drawn emoluments annum brothers meet indicators eligible instalments memorandum improvements carson cumberbatch trees euro joseph goonetilleke fire lubricants acuity bat agri sundry deputy consolidation determining computed factoring documentary andaradeniya stable denominated agriculture allotment frontier significantly maldives diesel indicated etf depreciated categorised consists known lka late overseas axiata circular com refund maturities appeals factory marine allowances bangladesh dimo refinance appearing bare maintenance radhakrishnan whether order application credits potential member reviewed distributors acceptances rambukwelle coverage conform conversion default provides articles saram senior jafferjee arudpragasam third india favour contracted lkass then exercise amendment brought view specified aitken spence erle factors described telecom solvency duty primarily mini golden dissanayake estates whose health arunodhaya deficit reduction alwis field hashim close investors ondaatjie plants withholding names judgements reflects most identifiable valuations adequate satisfied pandithage kenya developments approximately highlights accruals arunasalam hirdaramani alliance distributed status yusoof border city comb payout driven extent capitalised experience location eliya deemed continue immediate beverage repaid leverage shows states house lower enterprises totalling tangible slspc hemas hikkaduwa dipped accelerated valuer beach strong tiles amalgamated stocks galadari disposed component maharagama nuwara negombo forfeiture financials merger levies intra indicates plantation affairs entered association case dollars kumara lending immovable deffered done phantom technologies esufally warranty mather rendering palm abdulhussein stores actual care quarters sofr detailed agency full lives outcomes regulations four incorporation created maintained decreased bureau regarding mudiyanselage plus gunaratne split jinadasa negative actuaries state environment leyland abans stakeholder referred assumption projected description basel yaddehige branch filed digital centre beyond gamage numerator gunasekera ganegoda differed liyanage shared lien stewardship accommodations engaged bandara wages controlled corresponding brand recent acres internal realized division matara amarasinghe narahenpita issues realty marked data wijewardene jedb talwatte favorable realisation index collection balasuriya tower department acme translating hdfc decline ashok prosperity smart livestock structure therefore uncertainties permitted foreseeable probable utilised reflect either unlisted advanced unfavorable avenue akbar effects abishek production gardiner retired directions reconcile unidil length risks reimbursement travels specific historical tranz water opinion lines haycarb odel floor initiatives samarasinghe exponential fortress transportation litigation signed increases agricultural beruwalage hettiarachchi judgments madanayake converted acquire guidelines measuring make agent funded assumed profile ordinance tourism rodrigo teas rajagiriya relates points credited medium reversed reduced offer appliances south weerasooria along rishard carbon jayawardena malwatte improved higher free across pack unlocking empowering mature remeasurements guardian reasonable auditor underlying resources ability input assigned authority occupied kotmale complex criteria therein complied nawala sons country cents ratings brewery customs issuance address amarasekera currently mail took properly haradasa dhaman rajendram carimjee gazette mobility kpmg thousand sangani jayantha society ariyaratne diversified york maintain chamila thread prepayment modification completed discounted none mbsl revised rotunda original undertaking explained managed utilized thereafter carsons kelani weerasooriya mercantile annualized mudalige udayananda appealed senanka paper luminex ranavav code resulted paragraph holds dominion duly saving arpico perpetual osman senfin activated weerakoon abeygoonewardena daily inancial alance east janadhipathi commenced consumables generally quantitative mentioned accrual combination applies sources undiscounted considering levels anticipated proportion identified billing prof odyssey applying please siyapatha consistently swap acquisitions cashflows termination consequently employed mount still transport maskeliya loku secretaries nation jayawardana anthony lessor selliah comparison hedging policyholder introduced denominator recovered trincomalee ratmalana numbers yaseen operative assessing gooneratne materially occurred dilution citibank indirectly frequency settle exceeds printing derivatives dealing driving myanmar kariyawasan islamic cont jetwing hear resolved performed event allowable renovation comparatives estimation nearest treatment gampaha sell north outflows finished grace identical deen ratnayake generation glance exemption jointly systems normal lion principle notices contributed cwip revolving wholesale wickremasinghe info grand penalties technical plastic hospitals factories shop dharmapala reflected remain cabraal idle coconut seven ratnanather cold measure institutional lodged thilakaratne sustainable exercised anushman amotised accommodation well declined purposeful growing ceased owns mackie anuja certain deductible taking supporting park bandarawela deduction vote models utilisation jayasekara technology gautam hundred dharmadasa selected ensure wijenaike range suhada ruwan script arrc furthermore walltiles tokyo cement windforce installment ends lynear balangoda kingsbury opportunities constructions apartment australia navaratnam rathnayake dividing labour hanif returns diri savi demographic apparel mainly subtotal corrugated cartons rpty institution valley walk annexes healthcare offsetting transit consist escalation abdul users separately system awaiting derecognised best residual pursuant logistics meetings soat unadjusted objectives durga tours creation decided coupon backed give externally remained concluded monetary affiliates bought communication indika annualised chittampalam dinesh prasanna dias buhardeen subasinghe recurring mendis nayaz classes excess exceeding convertible smallholder fourth universal school entire affect authorisation cross pathirage purchasing vertical sarath wickremesinghe reference lukmanjee tennakoon thailand without award malaysia increasing glass village overall article erathna unencumbered swaps melstacorp hydropower insights farms ebitda wholly repairs permanent repos asphalts rounded brands volume call shipping entitled offered alternative cases zoysa technique true reality subramaniam harnam wickramasinghe factor adoption early straight labuan ekala schedule infrastructure calculation aruna wijeyeratne sugathadasa utilization shujeevan renewal recoveries expanded liquidation parts released consequent kurunegala contractors stamp goonewardene commerce interpretations define dewage ssbt edirisinghe jayaratne panasian identification jayanntha agents letters alpha expansion cheques confirm piyal travel valid computations beruwala kandegedara home habarana uhcl sunshine elements promissory donations jayawardhana materiality practice timing probability judgement exempt consumption replaces prepaid appreciation terminal restrictions harvested arjuna tangerine restructured brown sectors matured apartments actuarially objective regularly fitch training regulated relative karunaratne aravinda millennium divestment lipton infusions green chemanex uses alles employer ibnr ministry securitised cannot spare viii nagoya electronics bonuses katugastota rathnapura website ever textiles withdrawals consulting wijemanna cargo fonseka established riyaz macksons sustain offering bansei nawinna nalin finco formers harvest kenanga tundra dhammika saman principles processing medical officers graph swisstek successfully qualifying beer sunsuper palihakkara reaching kirula hectares sapp trinco bukit darah businesses trustees release anuragavan dairy reasonably elimination owner issuing apply certifies amerasinghe james standardized pranavan claimed inner fifty exposures defer reached constant litigations site supported telecommunication foster lane panadura participants vendor unutilised vantage fall karagoda cabral rajakariar jayah nawam braybrooke suriyabandara hallsville disallowable serendib practices homes conformity ahangama structured subdivision certificate secretarial kegalle operate electricity elevate innovate machines horizontal millions withana gunasekara expired tenure fluctuation maintaining shock kapila arachchige hearing gobinath wijesinghe ismail despite elect focus grew pound australian ravindran moratorium recycled tenor bairaha stakeholders reclassi impairement unable kotagala agro laid aggregation uncertainty carry consider pattern piliyandala indefinite millers sierra inflows beverages possible ramanan balendra livera children ramesh redeemed emfi balasingam michael airtel arise falling ebit lavinia contributes overhead century nakib volanka kulappuarachchige prassana gladstone deans prescribed needs ranaweera vauxhall subsidies strengthening bargaining shafie thoradeniya disanayake single came declaration carries bogala graphite obtaining monitoring continues ratnasabapathy invenco havelock borella chilaw tangalle securitisation unfunded macro aventura freight dynamic profiles assests versus bakers analyses senthilnathan means confirmed paye kulawardena paint priyantha channa norges canagaratna nandasiri jayasundara indemnity title providers some weerasekera announced executives derived guaranteed amrit sustainability sunil sugurta owed club rose additionally hela berhad what dispose closed world substantial cent robust brrowing leaders convenience shramadana gures repair incentives generating extension although offset whilst ascertained nominal weekly warrants culture prudent auditing flower merrill stability generate formed forfeited measures stipulated consisting affected classifications advertising battaramulla estimate person education size rohan sujeewa quater harsha though akbarally sellamuttu mackenzie darley ensuring shalsri cast doubt expectation laugfs lnterest ekanayake jayasekera unitholders consultancy ceramic aluminium mahinda email mohomed detail pussellawa trademark fentons lender sewing individuals retention thurston managers dawi distributable followings decisions submitted ijara sattar temporarily allocation gerard brito singh introduction paints newyork emmanuel rajadurai immediately implemented derecognized kaduwela show framework fractional chatoor initiated astrue originated appropriation hong minuwangoda recognises husseinally reimbursable pricing otal changing formerly functions rise allan excise asite buffer spouses thereon sezeka wanigasekara premaratne fuel currencies roce protection recreation outlook cease rocell superannuation northern center watawala western certificates momentum ramanayake lncrease reviews throughout spares cflb sandwave acknowledges definition knowledge making improvement tissa completion least budgeted receive marimuthu enhanced centres macroeconomic slfr rounding actions inflation critical neither suspense algharabally disclose responsibilities them satisfying charging incentive aforementioned lenders samarakoon station corp namal fishing expressed udeshi directive sanjay somadasa evaluated rosewood contact razik initially rwanda benedict orient divided rajahmoney sanjeev nishantha abeysiri kailasapillai nissanka looking agreed expences kmps classify restriction inappropriate authorization longer allotted installation various messers kadawatha stood become express delivery adopting reach complete gunawardana approximate among conventional janaka manufacture determinations nihal asoka network rasheed collectively vidul ranjan sujendra nill accretion liabilty ernst young discontinuing theagarajah bnym boat forex maheswaran reportable intention jansz families chacra welagedara element dilesh committed accurate priyan hiran pathirana tenant forty costa involving whereas disability ease sooriyaarachchi rooms eden gamini pietersz registrars rank majority middle notable abeysekera tables concessionary defaults pakistan walkers worldwide surgical retailing summarized scope client shaminda great britain thereof lodging forms selvanathan trend faizer yala kirimandala laboratories motion virgin ryde chemical gunatilleke cagr transparently automation confidence ancl navigating journey"
_VOCAB = {w: math.log(i + 2) + 3.0 for i, w in enumerate(VOCAB_TEXT.split())}


def ocr_enabled():
    return os.environ.get("CSE_OCR", "1").strip().lower() not in ("0", "false", "no", "off")


# ---------- which pages are images ----------

def is_image_page(page):
    """Pages whose rendered content can improve on the text layer: scans (including searchable scans),
    sparse text over vector outlines, and broken character maps. Image boxes are unrotated; compare areas only."""
    text = page.get_text("text").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    # Broken font maps can return thousands of isolated glyphs instead of words. OCR reads the rendered page,
    # rather than trying to translate that undecodable text layer into financial labels or numbers.
    if len(lines) >= 100 and sum(len(line) == 1 for line in lines) / len(lines) > 0.9:
        return True
    area = abs(page.rect.width * page.rect.height) or 1
    cover, largest = 0.0, 0.0
    for info in page.get_image_info():
        x0, y0, x1, y1 = info["bbox"]
        image_area = abs((x1 - x0) * (y1 - y0))
        cover += image_area
        largest = max(largest, image_area)
    # A searchable scan may have an inaccurate preexisting text layer. The caller only requests OCR after the
    # text parser lacks passing primary statements; the rendered image can then supply an independent reading.
    if largest / area >= MIN_IMAGE_COVER:
        return True
    if len(text) >= MIN_TEXT_CHARS:
        # Some outlined statements expose only their page number and a repeated running title (about 40 chars).
        return len(text) < 120 and len(page.get_cdrawings()) >= MIN_OUTLINE_PATHS
    if cover / area >= MIN_IMAGE_COVER:
        return True
    return len(page.get_cdrawings()) >= MIN_OUTLINE_PATHS


def image_pages(doc):
    return [i for i in range(len(doc)) if is_image_page(doc[i])]


# ---------- cleaning OCR text ----------

_DASHES = {"一", "－", "—", "–", "ー", "_", "~", "﹣", "−"}
_NUMERIC_LIKE = re.compile(r"^([(\[{]?)(-?)([\dOolI,.]+)([)\]}]?)(%?)$")
_GROUPED = re.compile(r"^\d{1,3}(?:[.,]\d{3}){2,}$")


def normalise_number(tok):
    """Repair only confusions that cannot change a correct reading: letters that look like digits inside a token that
    already has a digit, and the separators and brackets of a grouped number. S/5, B/8 and the like stay, so the token
    stays unreadable or the arithmetic refuses it."""
    m = _NUMERIC_LIKE.match(tok)
    if not m or not re.search(r"\d", m.group(3)):
        return tok
    opn, minus, core, cls, pct = m.groups()
    core = core.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1"}))
    core = re.sub(r"[,.]+$", "", core)
    core = re.sub(r",{2,}", ",", core)
    if not re.fullmatch(r"\d[\d,.]*", core or ""):
        return tok
    if _GROUPED.match(core):
        core = core.replace(".", ",")
    return ("(" if opn else "") + minus + core + (")" if cls else "") + pct


def _split_letters(run):
    """Split a glued run such as 'Plantand' using the vocabulary. All parts must be known, otherwise leave it alone."""
    low = run.lower()
    if len(run) < 4 or low in _VOCAB:
        return run
    best = [0.0] + [None] * len(low)
    back = [0] * (len(low) + 1)
    for i in range(1, len(low) + 1):
        for j in range(max(0, i - 20), i):
            cost = _VOCAB.get(low[j:i])
            if cost is not None and best[j] is not None and (best[i] is None or best[j] + cost < best[i]):
                best[i], back[i] = best[j] + cost, j
    if best[-1] is None:
        return run
    parts, i = [], len(low)
    while i > 0:
        parts.append(run[back[i]:i])
        i = back[i]
    return " ".join(reversed(parts))


def clean_line(text):
    """Text of one OCR line box, with spaces restored and safe repairs made. Returns a list of word strings."""
    t = unicodedata.normalize("NFKC", text)
    t = "".join("-" if c in _DASHES else c for c in t)
    t = re.sub(r"[　-鿿＀-￯]", " ", t)                     # the model is trained on Chinese too
    t = t.replace("‘", "'").replace("’", "'").replace("`", "'")
    t = re.sub(r"(?<=\d)\s*,\s+(?=\d{3}\b)", ",", t)                        # '1, 234'
    t = re.sub(r"(?<=\d)\s+,(?=\d{3}\b)", ",", t)                           # '1 ,234'
    t = re.sub(r"([(\[{])\s+(?=\d)", r"\1", t)                              # '( 123'
    t = re.sub(r"(?<=\d)\s+([)\]}])", r"\1", t)                             # '123 )'
    t = re.sub(r"(\d{1,2})[\"'^*]+\s*(?=[A-Za-z]{3})", r"\1 ", t)           # a superscript read as a quote: 31"March
    t = re.sub(r"(\d{2}[./-]\d{2}[./-]\d{4})(?=\d)", r"\1 ", t)             # two glued dates
    out = []
    for tok in t.split():
        tok = tok.strip("|")                                                # a table rule touching a word
        if re.fullmatch(r"[=.:;,'\"*^]*|-{3,}", tok):                        # rules and specks
            continue
        fixed = normalise_number(tok)
        if fixed != tok or re.fullmatch(r"[(\[{]?-?[\d,.]+[)\]}]?%?", tok):
            out.append(fixed)
            continue
        tok = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", tok)
        tok = re.sub(r"(?<=[A-Za-z]{2})(?=\d)", " ", tok)
        tok = re.sub(r"(?<=\d)(?=(?!(?:st|nd|rd|th)\b)[A-Za-z]{2})", " ", tok)
        tok = re.sub(r"(?<=[A-Za-z]),(?=[A-Za-z])", ", ", tok)
        tok = re.sub(r"(?<=[A-Za-z][sS]')(?=[A-Za-z]{2})", " ", tok)       # shareholders'funds
        tok = re.sub(r"[A-Za-z]+", lambda m: _split_letters(m.group(0)), tok)
        for piece in tok.split():
            out.append(normalise_number(piece))
    return out


def _char_width(c):
    if c in ",.:;'|!il":
        return 0.45
    if c in "()[]{}-":
        return 0.6
    if c.isupper() or c in "mw":
        return 1.25
    return 1.0


def split_line(x0, x1, words):
    """Share a line box's width among its words by estimated character width."""
    sizes = [sum(_char_width(c) for c in w) for w in words]
    total = sum(sizes) + 0.55 * (len(words) - 1)
    unit = (x1 - x0) / total if total else 0
    out, x = [], x0
    for w, size in zip(words, sizes):
        out.append((x, x + size * unit, w))
        x += (size + 0.55) * unit
    return out


# ---------- geometry ----------

def _skew_angle(lines):
    """Page skew in radians, from the box centres. Short boxes are often drawn level even on a tilted page, so box
    slopes cannot be used. The right angle is the one that makes the rows of centres sharpest."""
    import numpy as np
    if len(lines) < 8:
        return 0.0
    q = np.array([ln[0] for ln in lines], dtype=float)
    x, y = q[:, 0::2].mean(axis=1), q[:, 1::2].mean(axis=1)
    x = x - x.mean()
    span = y.max() - y.min() + 1
    pitch = max(2.0, float(np.median(np.abs(q[:, 7] - q[:, 1]))) / 3)

    def sharpness(angle):
        h = np.bincount(((y + x * math.tan(-angle) - y.min() + span) / pitch).astype(int))
        return float((h.astype(float) ** 2).sum())

    def best(angles):
        return max(angles, key=sharpness)

    a = best([math.radians(d / 4) for d in range(-24, 25)])                  # within 6 degrees, in steps of 0.25
    return best([a + math.radians(d / 40) for d in range(-10, 11)])          # then in steps of 0.025


def words_from_lines(entry):
    """(x0, y0, x1, y1, word, block, line, word_no) in points, straightened, plus the (y, text, score) of each number."""
    lines, f = entry["lines"], entry["pt_per_px"]
    angle = _skew_angle(lines)
    cx, cy = entry["w"] / 2, entry["h"] / 2
    ca, sa = math.cos(-angle), math.sin(-angle)
    placed = []
    for q, text, score in lines:
        xs, ys = [], []
        for i in range(0, 8, 2):
            dx, dy = q[i] - cx, q[i + 1] - cy
            xs.append(cx + dx * ca - dy * sa)
            ys.append(cy + dx * sa + dy * ca)
        placed.append((min(ys), min(xs), max(xs), max(ys), text, score))
    placed.sort(key=lambda p: ((p[0] + p[3]) / 2, p[1]))
    words = []
    for n, (y0, x0, x1, y1, text, score) in enumerate(placed):
        for k, (a, b, w) in enumerate(split_line(x0, x1, clean_line(text))):
            words.append((a * f, y0 * f, b * f, y1 * f, w, n, 0, k, float(score)))
    return words


# ---------- the engine ----------

_engine = None


def engine():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR
        n = int(os.environ.get("CSE_OCR_THREADS", "1"))
        gpu = os.environ.get("CSE_OCR_GPU", "0").strip().lower() in ("1", "true", "yes", "on")
        if gpu:
            # Needs onnxruntime-gpu with the pip CUDA/cuDNN libraries (the .venv-gpu environment).
            import onnxruntime
            onnxruntime.preload_dlls()
        _engine = RapidOCR(intra_op_num_threads=n, inter_op_num_threads=1, use_cls=False, max_side_len=FULL_LONG_SIDE + 200,
                           det_use_cuda=gpu, rec_use_cuda=gpu)
    return _engine


def render(page, long_side):
    import numpy as np
    zoom = long_side / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.stride)[:, :pix.w].copy()
    return img, zoom


def turn(img, rot):
    """rot: degrees clockwise needed to make the page upright."""
    import numpy as np
    return img if rot == 0 else np.rot90(img, k=-(rot // 90))


def wordiness(texts):
    """How many known words the recognised lines hold. Upside-down text gives almost none."""
    n = 0
    for text, score in texts:
        if score < 0.6:
            continue
        for w in " ".join(clean_line(text)).lower().split():
            w = re.sub(r"[^a-z]", "", w)
            if len(w) >= 3 and w in _VOCAB:
                n += 1
    return n


# Statement headings, matched against a short line with everything but letters removed. The heading must start the
# line (after words such as "consolidated"), so a sentence that mentions a statement does not count.
_PRE = r"^(?:the|consolidated|company|companys|group|groups|bank|banks|condensed|interim|separate|unaudited|audited|summarised|summarized|abridged|provisional|and)*"
_MID = r"(?:consolidated|condensed|interim|separate|summarised|summarized)*"
HEADS = [
    ("CF", re.compile(_PRE + r"(?:statementof" + _MID + r")?cashflows?")),
    ("SOCE", re.compile(_PRE + r"statementof" + _MID + r"(?:changesin(?:equity|shareholders|stockholders|ownersequity)|equity)")),
    ("BS", re.compile(_PRE + r"(?:statementof" + _MID + r"financialposition|balancesheet)")),
    ("IS", re.compile(_PRE + r"(?:statementof" + _MID + r"(?:profitorloss|profitandloss|profit|comprehensiveincome|income|incomeand)|(?:income|profitandloss|profitorloss|comprehensiveincome)statement)")),
]
HEAD_MAX_LETTERS = 90      # longer lines are sentences
HEAD_LINES = 12            # a heading sits among the first lines of the page
NOTES = re.compile(r"notestothe(condensed|interim|consolidated|financial|accounts)|notestofinancial|notestoandformingpart|accountingpolicies|(?:material|significant)?accountingpolicyinformation(?:tothefinancialstatements)?")


def page_kinds(texts):
    """Statement kinds headed on this page, and whether it is a page of notes. texts: top lines in reading order."""
    kinds, notes, contents = set(), False, False
    for text, _score in texts[:HEAD_LINES]:
        s = re.sub(r"[^a-z&]", "", text.lower())
        if s.startswith("contents") or s == "tableofcontents":
            contents = True
        if NOTES.search(s):
            notes = True
            continue
        if len(s) > HEAD_MAX_LETTERS:
            continue
        for code, rx in HEADS:
            if rx.search(s):
                kinds.add(code)
                break
    if len(kinds) >= 3 or contents or notes:     # a contents page or a notes page, not a statement
        return [], notes
    return sorted(kinds), notes


def _numbers(texts):
    return sum(1 for t, _ in texts if re.fullmatch(r"[(\[]?-?\d[\d,.]*[)\]]?", t.replace(" ", "")) and len(re.sub(r"\D", "", t)) >= 3)


def triage_page(page):
    """Low-resolution look at one page. Returns orientation, box count, statement headings found near the top."""
    eng = engine()
    img, _ = render(page, LOW_LONG_SIDE)
    boxes, _ = eng.text_det(eng.load_img(img))
    n = 0 if boxes is None else len(boxes)
    if n < MIN_BOXES_TEXT_PAGE:
        return dict(rot=0, boxes=n, kinds=[], notes=False, word_hits=0, texts=[])
    tall = sum(1 for b in boxes if abs(b[3][1] - b[0][1]) > 2 * abs(b[1][0] - b[0][0]))
    wide = sum(1 for b in boxes if abs(b[1][0] - b[0][0]) > 2 * abs(b[3][1] - b[0][1]))
    order = [90, 270, 0, 180] if tall > wide else [0, 180, 90, 270]
    best = None
    for rot in order:
        im = turn(img, rot)
        bgr = eng.load_img(im)
        bs = boxes if rot == 0 else eng.text_det(bgr)[0]
        if bs is None or not len(bs):
            continue
        top = [b for b in bs if max(p[1] for p in b) < 0.45 * im.shape[0]]
        top.sort(key=lambda b: b[0][1])
        top = top[:40]
        if not top:
            continue
        import numpy as np
        crops = eng.get_crop_img_list(bgr, np.array(top))
        rec, _ = eng.text_rec(crops, False)
        texts = [(r[0], float(r[1])) for r in rec]
        hits = wordiness(texts)
        if best is None or hits > best[0]:
            best = (hits, rot, texts, len(bs))
        if hits >= 3:
            break
    if best is None:
        return dict(rot=0, boxes=n, kinds=[], notes=False, word_hits=0, texts=[])
    kinds, notes = page_kinds(best[2])
    return dict(rot=best[1], boxes=best[3], kinds=kinds, notes=notes, word_hits=best[0],
                texts=[[t, round(sc, 3)] for t, sc in best[2]])


def read_page(page, rot):
    """Full-resolution OCR of one page. Line boxes are stored in pixels of the upright image."""
    img, zoom = render(page, FULL_LONG_SIDE)
    img = turn(img, rot)
    res, _ = engine()(img, use_cls=False)
    h, w = img.shape[:2]
    long_pts = max(page.rect.width, page.rect.height)
    pt_per_px = 1 / zoom if 700 <= long_pts <= 1000 else NOMINAL_LONG_SIDE / FULL_LONG_SIDE
    lines = []
    for box, text, score in res or []:
        q = [round(float(v), 1) for pt in box for v in pt]
        lines.append([q, text, round(float(score), 3)])
    return dict(rot=rot, w=w, h=h, pt_per_px=pt_per_px, lines=lines)


# ---------- cache ----------

def cache_dir():
    return pathlib.Path(os.environ.get("CSE_OCR_CACHE") or ROOT / "ocr_cache")


class Cache:
    def __init__(self, docid, path):
        self.file = cache_dir() / f"{docid}.json"
        self.size = os.path.getsize(path)
        self.data = dict(version=CACHE_VERSION, size=self.size, triage={}, full={})
        self.loaded = False
        if self.file.exists():
            try:
                d = json.loads(self.file.read_text())
                if d.get("version") == CACHE_VERSION and d.get("size") == self.size:
                    self.data, self.loaded = d, True
            except (ValueError, OSError):
                pass

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(self.data))
        os.replace(tmp, self.file)


# ---------- the wrapper ----------

class OcrPage:
    """Looks like a pymupdf page, with OCR words. Anything not handled here goes to the real page."""

    def __init__(self, page, words, entry):
        self._page = page
        self._words = words
        f = entry["pt_per_px"]
        self.rect = pymupdf.Rect(0, 0, entry["w"] * f, entry["h"] * f)
        self.rotation = 0

    def __getattr__(self, name):
        return getattr(self._page, name)

    def _lines(self):
        by = {}
        for w in self._words:
            by.setdefault(w[5], []).append(w)
        return [by[k] for k in sorted(by)]

    def get_text(self, option="text", *args, clip=None, **kw):
        words = self._words
        if clip is not None:
            r = pymupdf.Rect(clip)
            words = [w for w in words if r.x0 <= (w[0] + w[2]) / 2 <= r.x1 and r.y0 <= (w[1] + w[3]) / 2 <= r.y1]
        if option == "words":
            return [tuple(w[:8]) for w in words]
        lines = OcrPage(self._page, words, dict(pt_per_px=1, w=0, h=0))._lines()
        if option == "text":
            return "".join(" ".join(w[4] for w in ln) + "\n" for ln in lines)
        if option == "blocks":
            return [(ln[0][0], ln[0][1], ln[-1][2], ln[0][3], " ".join(w[4] for w in ln) + "\n", ln[0][5], 0) for ln in lines]
        if option in ("dict", "rawdict"):
            blocks = []
            for ln in lines:
                bbox = (ln[0][0], ln[0][1], ln[-1][2], ln[0][3])
                span = dict(text=" ".join(w[4] for w in ln), bbox=bbox, size=ln[0][3] - ln[0][1], font="ocr", flags=0, color=0, origin=(ln[0][0], ln[0][3]))
                blocks.append(dict(type=0, number=ln[0][5], bbox=bbox, lines=[dict(bbox=bbox, spans=[span], wmode=0, dir=(1.0, 0.0))]))
            return dict(width=self.rect.width, height=self.rect.height, blocks=blocks)
        return self._page.get_text(option, *args, clip=clip, **kw)


class OcrDoc:
    """Looks like a pymupdf document. Pages in self.ocr_pages answer with OCR words."""

    def __init__(self, doc, docid, path, candidates):
        self._doc = doc
        self.candidates = list(candidates)
        self.cache = Cache(docid, path)
        self.ocr_pages = {}     # page index -> words with score
        self.seconds = dict(triage=0.0, full=0.0)
        self.did_ocr = False
        self.triaged = 0
        self._triaged = set()

    def __len__(self):
        return len(self._doc)

    def __iter__(self):
        return (self[i] for i in range(len(self)))

    def __getattr__(self, name):
        return getattr(self._doc, name)

    def __getitem__(self, i):
        if isinstance(i, int) and i < 0:
            i += len(self._doc)
        page = self._doc[i]
        words = self.ocr_pages.get(i)
        if words is None:
            return page
        return OcrPage(page, words, self.cache.data["full"][str(i)])

    # -- reading --

    def triage(self, pno):
        """Low-resolution look at one page, from the cache if there. Headings are judged again from the stored text,
        so the heading rules can change without new OCR. Entries from before the text was stored are redone."""
        key = str(pno)
        store = self.cache.data["triage"]
        if "texts" not in store.get(key, {}):
            t0 = time.time()
            res = triage_page(self._doc[pno])
            res["seconds"] = round(time.time() - t0, 2)
            store[key] = res
            self.did_ocr = True
            self.cache.save()
        tri = store[key]
        if tri["texts"]:
            tri["kinds"], tri["notes"] = page_kinds([tuple(t) for t in tri["texts"]])
        # Early caches kept heading hits on notes pages, sometimes without the text needed to rejudge them.
        # Preserve the notes boundary even for those entries: a note cannot start a statement run.
        if tri.get("notes"):
            tri["kinds"] = []
        if pno not in self._triaged:
            self._triaged.add(pno)
            self.seconds["triage"] += tri.get("seconds", 0)
            self.triaged += 1
        return tri

    def read(self, pno):
        """Full OCR of one page, from the cache if it is there."""
        if pno in self.ocr_pages:
            return
        key = str(pno)
        store = self.cache.data["full"]
        if key not in store:
            rot = self.triage(pno)["rot"]
            t0 = time.time()
            entry = read_page(self._doc[pno], rot)
            entry["seconds"] = round(time.time() - t0, 2)
            store[key] = entry
            self.did_ocr = True
            self.cache.save()
        self.seconds["full"] += store[key].get("seconds", 0)
        self.ocr_pages[pno] = words_from_lines(store[key])

    # -- choosing pages --

    def locate(self, wanted):
        """Triage pages until the statements in `wanted` have been seen. Returns {page index: kinds}.

        Statements come as a run of pages just before the notes. The sweep starts part way into a long report and goes
        forward; on reaching notes before any statement it goes back from its start, since the statements are then
        earlier. It stops a few pages after everything wanted has been seen, or at the notes that follow them."""
        c, n = self.candidates, len(self.candidates)
        start = 0 if n <= 20 else int(START_FRACTION * n)
        found, seen = {}, set()

        def look(k):
            tri = self.triage(c[k])
            if tri["kinds"]:
                found[c[k]] = tri["kinds"]
                seen.update(tri["kinds"])
            return tri

        forward_found, after = False, 0
        for k in range(start, n):
            tri = look(k)
            forward_found |= bool(tri["kinds"])
            if wanted <= seen:
                after += not tri["kinds"]
                if tri["notes"] or after > AFTER_PAGES:
                    return found
            if tri["notes"]:
                break       # the statements are before the notes
        # Back from the start. If the forward pass saw statements, only the start of their run can be missing.
        quiet, got = 0, forward_found
        for k in range(start - 1, -1, -1):
            if wanted <= seen and quiet:
                break       # going back, the first statement of the run (often the income statement) is last
            tri = look(k)
            if tri["kinds"]:
                got, quiet = True, 0
            elif not tri["notes"]:
                quiet += 1
            if got and quiet > RUN_GAP_PAGES:
                break
        return found

    def read_statement_pages(self, needed):
        """Find pages headed as statements (the needed ones and the cash flow) and OCR them at full resolution with
        the pages that follow them. Returns the headings seen."""
        wanted = set(needed) | {"CF"}
        kinds_by_page = self.locate(wanted)
        seen = set(k for v in kinds_by_page.values() for k in v)
        pos = {p: i for i, p in enumerate(self.candidates)}
        for pno in sorted(kinds_by_page):
            self.read(pno)
            i = pos[pno]
            for nxt in self.candidates[i + 1:i + 1 + MAX_CONTINUATION_PAGES]:
                if nxt != self.candidates[pos[nxt] - 1] + 1:
                    break
                tri = self.triage(nxt)
                if tri["kinds"] or tri["notes"] or tri["boxes"] < MIN_BOXES_TABLE_PAGE:
                    break
                self.read(nxt)
                if sum(1 for w in self.ocr_pages[nxt] if re.search(r"\d,\d{3}|\d{4}", w[4])) < 4:
                    break
        return seen

    def read_all_table_like(self, limit=12):
        """Last resort for a short report whose headings could not be read at low resolution."""
        done = 0
        for pno in self.candidates:
            if done >= limit:
                break
            if pno in self.ocr_pages:
                continue
            if self.triage(pno)["boxes"] >= MIN_BOXES_TABLE_PAGE:
                self.read(pno)
                done += 1

    # -- reporting --

    def low_confidence_numbers(self, pages):
        """Numbers on these pages (0-based) that the model itself was unsure of, and the lowest score of any number."""
        low, lowest = 0, 1.0
        for p in pages:
            for w in self.ocr_pages.get(p, ()):
                if re.search(r"\d", w[4]):
                    lowest = min(lowest, w[8])
                    low += w[8] < LOW_CONFIDENCE
        return low, round(lowest, 3)

    def stats(self):
        return dict(image_pages=len(self.candidates), triaged_pages=self.triaged, full_pages=len(self.ocr_pages),
                    seconds_triage=round(self.seconds["triage"], 1), seconds_full=round(self.seconds["full"], 1),
                    from_cache=not self.did_ocr, page_numbers=sorted(p + 1 for p in self.ocr_pages))


# ---------- commands ----------

def _list_one(job):
    """Report what OCR one document would need, without running any."""
    import parse_report as P
    docid, ticker, path, ctx = job
    try:
        doc = pymupdf.open(path)
        chars = sum(len(doc[i].get_text("text")) for i in range(min(len(doc), 40)))
        scanned = chars < 40 * min(len(doc), 40)
        if scanned:
            cand, reason = image_pages(doc), "scanned"
        else:
            tables = P.read_tables(doc, ctx)
            needed = P.statements_wanted(tables)
            if not needed:
                return None
            cand = image_pages(doc)
            reason = "partly images: needs " + "+".join(needed)
        if not cand:
            return None if not scanned else (docid, ticker, reason + " (no image pages)", len(doc), 0, 0, 0)
        # Reports up to 20 image pages have their statements in about half of them; long ones need roughly 8 pages
        # read in full, and the sweep stops soon after the statements.
        n = len(cand)
        tri = n if n <= 20 else int(0.5 * n)
        full = min(n, 6 if n <= 20 else 8)
        return (docid, ticker, reason, len(doc), n, tri, full)
    except Exception as e:
        return (docid, ticker, f"error: {type(e).__name__}", 0, 0, 0, 0)


def cmd_list(argv):
    import argparse
    import collections
    import concurrent.futures as cf
    import sqlite3
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser(prog="ocr_words.py list")
    ap.add_argument("--reports", default=str(ROOT / "reports"))
    ap.add_argument("--db", default=str(ROOT / "db" / "cse_financials.db"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tickers")
    ap.add_argument("--out", help="write the list here as TSV instead of printing it")
    ap.add_argument("--speed", type=int, default=None, help="OCR processes to assume for the time estimate (default: --workers)")
    a = ap.parse_args(argv)
    meta = {}
    if pathlib.Path(a.db).exists():
        con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        meta = {r[0]: dict(period_end=r[1], template=r[2], fye=r[3], title=r[4], category=r[5]) for r in con.execute(
            """SELECT d.document_id, d.period_end_date, t.code, c.fiscal_year_end_month, d.title, d.category
               FROM report_document d JOIN company c USING (company_id) JOIN reporting_template t USING (template_id)""")}
        con.close()
    jobs = []
    wanted = set(a.tickers.split(",")) if a.tickers else None
    for f in sorted(pathlib.Path(a.reports).glob("*/*.pdf")):
        tk = f.parent.name
        if wanted and tk not in wanted or not f.stem.isdigit():
            continue
        docid = int(f.stem)
        jobs.append((docid, tk, str(f), dict(document_id=docid, ticker=tk, **meta.get(docid, {}))))
    rows = []
    with cf.ProcessPoolExecutor(a.workers) as ex:
        for r in ex.map(_list_one, jobs, chunksize=4):
            if r:
                rows.append(r)
    out = open(a.out, "w") if a.out else sys.stdout
    print("document_id\tticker\treason\tpages\timage_pages\test_triage_pages\test_full_pages\test_seconds", file=out)
    total_t = total_f = 0
    kinds = collections.Counter()
    for r in rows:
        secs = r[5] * EST_TRIAGE_S + r[6] * EST_FULL_S
        total_t, total_f = total_t + r[5], total_f + r[6]
        kinds[r[2].split(":")[0].split(" (")[0]] += 1
        print(*r, round(secs), sep="\t", file=out)
    if a.out:
        out.close()
    secs = total_t * EST_TRIAGE_S + total_f * EST_FULL_S
    procs = a.speed or a.workers
    print(f"# documents checked {len(jobs)}; need OCR {len(rows)}: {dict(kinds)}")
    print(f"# estimated pages: {total_t} low-resolution, {total_f} full-resolution")
    print(f"# estimated time: {secs / 3600:.1f} CPU-process hours, {secs / 3600 / procs:.1f} hours on {procs} processes (first run only; cached after that)")


def cmd_show(argv):
    path, pageno = argv[0], int(argv[1])
    doc = pymupdf.open(path)
    page = doc[pageno - 1]
    tri = triage_page(page)
    print("triage", tri)
    entry = read_page(page, tri["rot"])
    for w in words_from_lines(entry) if "--words" in argv else []:
        print(round(w[0]), round(w[1]), round(w[2]), round(w[3]), w[4], w[8])
    if "--words" not in argv:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from tokens import page_rows, text_of
        entry["seconds"] = 0
        for r in page_rows(OcrPage(page, words_from_lines(entry), entry)):
            print(round(r[0][1]), text_of(r))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        cmd_list(sys.argv[2:])
    elif len(sys.argv) > 3 and sys.argv[1] == "show":
        cmd_show(sys.argv[2:])
    else:
        print(__doc__)

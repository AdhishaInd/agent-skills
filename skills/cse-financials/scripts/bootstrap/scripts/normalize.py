"""The one place text is standardised. Loaders must use these functions, never their own.

Two spellings count as the same name only if they normalise to identical text. Everything
else stays separate and goes to review. Nothing is matched by similarity.
"""
import re
import unicodedata

# Statement headings mapped to a fixed list of section codes (also enforced by the schema).
SECTION_CODES = {
    "assets": "ASSET", "non current assets": "ASSET_NC", "current assets": "ASSET_C",
    "equity": "EQUITY", "capital and reserves": "EQUITY", "equity and liabilities": "EQUITY",
    "liabilities": "LIAB", "non current liabilities": "LIAB_NC", "current liabilities": "LIAB_C",
}


def clean(text):
    """Lowercase letters, digits and single spaces only."""
    s = unicodedata.normalize("NFKC", text or "").lower().replace("&", " and ")
    s = re.sub(r"['’‘`]", "", s)             # employees' -> employees
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bnoncurrent\b", "non current", s)
    return " ".join(s.split())


def label(text):
    """Standard form of a statement line, without 'Less:' prefixes or '(Rs.)' suffixes."""
    s = re.sub(r"^\s*(add\s*/?\s*\(?\s*less\s*\)?|less|add)\s*:\s*", "", text or "", flags=re.I)
    s = re.sub(r"\(\s*rs\.?\s*\)", " ", s, flags=re.I)
    return clean(s)


def name(text):
    """Standard form of a person, shareholder, segment or debenture name.

    Runs of single letters are joined, so 'S.B. Perera', 'S B Perera' and 'SB Perera' are one name.
    """
    out, in_initials = [], False
    for word in clean(text).split():
        single = len(word) == 1 and word.isalpha()
        if single and in_initials:
            out[-1] += word
        else:
            out.append(word)
        in_initials = single
    return " ".join(out)


def cash_flow_section(label):
    """OPERATING, INVESTING or FINANCING when a cash flow line opens that section."""
    t = clean(label)
    if re.match(r"^(cash flows? (from|used in|generated from)|net cash (flows? )?(from|used in|generated from))?\s*(operating) activit", t) or t in ("operating activities", "cash flows from operating activities"):
        return "OPERATING"
    if re.match(r"^(cash flows? (from|used in)|net cash (flows? )?(from|used in))?\s*(investing) activit", t) or t == "investing activities":
        return "INVESTING"
    if re.match(r"^(cash flows? (from|used in)|net cash (flows? )?(from|used in))?\s*(financing) activit", t) or t == "financing activities":
        return "FINANCING"
    return None


def section_code(heading):
    """Section code if this text is a statement heading, otherwise None."""
    return SECTION_CODES.get(clean(heading))


def is_expense_prefix(raw):
    """True for 'Less: x', where the figure is printed positive but is a deduction."""
    return bool(re.match(r"^\s*less\s*:", raw or "", re.I))

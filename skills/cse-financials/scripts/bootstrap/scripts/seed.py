"""Reference data: statement types, templates and the standard line-item dictionary.

Items come from the line labels in 14 sampled CSE interim reports.
Format: code, name, value_kind, is_subtotal.
"""
import pathlib
import sys

import normalize

TEMPLATES = [
    ("GENERAL", "Trading, manufacturing, services and diversified companies"),
    ("BANK", "Licensed commercial and specialised banks"),
    ("FINANCE", "Finance and leasing companies"),
    ("INSURANCE", "Insurers and insurance holding companies"),
    ("FUND", "Closed-end funds and unit trusts"),
]

STATEMENTS = [
    ("IS", "Income statement"),
    ("OCI", "Other comprehensive income"),
    ("BS", "Statement of financial position"),
    ("CF", "Cash flow statement"),
    ("SOCE", "Statement of changes in equity"),
    ("SEG", "Segment information"),
    ("KPI", "Per-share data, ratios and other reported metrics"),
]

M, P, R, C, X = "MONEY", "PER_SHARE", "PERCENT", "COUNT", "RATIO"

# (statement, template or None, [items])
ITEMS = [
    ("IS", None, [
        ("IS_REVENUE", "Revenue / turnover", M, 1), ("IS_COST_OF_SALES", "Cost of sales", M, 0),
        ("IS_GROSS_PROFIT", "Gross profit", M, 1), ("IS_OTHER_INCOME", "Other income", M, 0),
        ("IS_DISTRIBUTION_EXP", "Selling and distribution expenses", M, 0),
        ("IS_ADMIN_EXP", "Administrative expenses", M, 0), ("IS_OTHER_OPERATING_EXP", "Other operating expenses", M, 0),
        ("IS_OPERATING_PROFIT", "Operating profit", M, 1), ("IS_FINANCE_INCOME", "Finance income", M, 0),
        ("IS_FINANCE_COST", "Finance cost", M, 0), ("IS_NET_FINANCE_COST", "Net finance cost", M, 1),
        ("IS_ASSOCIATE_SHARE", "Share of profit of associates", M, 0), ("IS_PBT", "Profit before tax", M, 1),
        ("IS_TAX", "Income tax expense", M, 0), ("IS_PAT", "Profit for the period", M, 1),
        ("IS_PAT_PARENT", "Profit attributable to equity holders", M, 0),
        ("IS_PAT_NCI", "Profit attributable to non-controlling interests", M, 0),
        ("IS_EPS_BASIC", "Basic earnings per share", P, 0), ("IS_EPS_DILUTED", "Diluted earnings per share", P, 0),
        ("IS_DPS", "Dividend per share", P, 0),
    ]),
    ("IS", "BANK", [
        ("IS_GROSS_INCOME", "Gross income", M, 1), ("IS_INTEREST_INCOME", "Interest income", M, 0),
        ("IS_INTEREST_EXPENSE", "Interest expense", M, 0), ("IS_NET_INTEREST_INCOME", "Net interest income", M, 1),
        ("IS_FEE_INCOME", "Fee and commission income", M, 0), ("IS_FEE_EXPENSE", "Fee and commission expense", M, 0),
        ("IS_NET_FEE_INCOME", "Net fee and commission income", M, 1),
        ("IS_TRADING_GAINS", "Net gains/(losses) from trading", M, 0),
        ("IS_OTHER_OPERATING_INCOME", "Other operating income", M, 0), ("IS_NET_OTHER_OPERATING_INCOME", "Net other operating income", M, 1),
        ("IS_DERECOGNITION_GAINS", "Net gains/(losses) from derecognition of financial assets", M, 0),
        ("IS_TOTAL_OPERATING_INCOME", "Total operating income", M, 1),
        ("IS_IMPAIRMENT", "Impairment charges and other losses", M, 0),
        ("IS_NET_OPERATING_INCOME", "Net operating income", M, 1), ("IS_OPERATING_EXPENSES", "Total operating expenses", M, 1),
        ("IS_PERSONNEL_EXP", "Personnel expenses", M, 0), ("IS_DEPRECIATION", "Depreciation and amortisation", M, 0),
        ("IS_PROFIT_BEFORE_FST", "Operating profit before taxes on financial services", M, 1),
        ("IS_FST", "Taxes on financial services", M, 0),
        ("IS_PROFIT_AFTER_FST", "Operating profit after taxes on financial services", M, 1),
    ]),
    ("IS", "INSURANCE", [
        ("IS_GWP", "Gross written premiums", M, 0), ("IS_PREMIUM_CEDED", "Premiums ceded to reinsurers", M, 0),
        ("IS_NWP", "Net written premiums", M, 1), ("IS_UPR_CHANGE", "Net change in unearned premium reserve", M, 0),
        ("IS_NEP", "Net earned premium", M, 1), ("IS_INVESTMENT_INCOME", "Investment and other income", M, 0),
        ("IS_NET_CLAIMS", "Net insurance claims and benefits", M, 0),
        ("IS_LIFE_FUND_CHANGE", "Increase in life insurance fund", M, 0), ("IS_ACQUISITION_COST", "Acquisition cost", M, 0),
        ("IS_TOTAL_BENEFITS", "Total benefits, losses and expenses", M, 1), ("IS_NET_INCOME_INS", "Net income", M, 1),
        ("IS_NON_INSURANCE_REVENUE", "Revenue from non-insurance subsidiaries", M, 0),
        ("IS_NON_INSURANCE_COST", "Cost of sales of non-insurance subsidiaries", M, 0),
    ]),
    ("OCI", None, [
        ("OCI_REVALUATION", "Revaluation of land and buildings", M, 0), ("OCI_ACTUARIAL", "Actuarial gains/(losses)", M, 0),
        ("OCI_FAIR_VALUE", "Fair value gains/(losses) on financial assets", M, 0),
        ("OCI_FX_TRANSLATION", "Foreign currency translation differences", M, 0),
        ("OCI_CASH_FLOW_HEDGE", "Cash flow hedge movements", M, 0),
        ("OCI_TOTAL", "Other comprehensive income, net of tax", M, 1), ("OCI_TCI", "Total comprehensive income", M, 1),
        ("OCI_TCI_PARENT", "Total comprehensive income attributable to equity holders", M, 0),
        ("OCI_TCI_NCI", "Total comprehensive income attributable to non-controlling interests", M, 0),
    ]),
    ("BS", None, [
        ("BS_PPE", "Property, plant and equipment", M, 0), ("BS_PPE_AND_ROU", "Property, plant and equipment with right-of-use assets, combined", M, 0), ("BS_ROU", "Right-of-use assets", M, 0),
        ("BS_INV_PROPERTY", "Investment property", M, 0), ("BS_INTANGIBLES", "Intangible assets", M, 0),
        ("BS_GOODWILL", "Goodwill", M, 0), ("BS_SUBSIDIARIES", "Investments in subsidiaries", M, 0),
        ("BS_ASSOCIATES", "Investments in associates", M, 0), ("BS_DTA", "Deferred tax assets", M, 0),
        ("BS_OTHER_NCA", "Other non-current assets", M, 0), ("BS_TOTAL_NCA", "Total non-current assets", M, 1),
        ("BS_INVENTORIES", "Inventories", M, 0), ("BS_TRADE_RECEIVABLES", "Trade and other receivables", M, 0),
        ("BS_PREPAYMENTS", "Deposits, advances and prepayments", M, 0), ("BS_RELATED_RECEIVABLE", "Amounts due from related parties", M, 0),
        ("BS_ST_LOANS_GIVEN", "Short-term loans given", M, 0), ("BS_ST_INVESTMENTS", "Short-term investments and deposits", M, 0),
        ("BS_TAX_RECEIVABLE", "Income tax receivable", M, 0), ("BS_OTHER_ASSETS", "Other assets", M, 0),
        ("BS_CASH", "Cash and cash equivalents", M, 0), ("BS_TOTAL_CA", "Total current assets", M, 1),
        ("BS_TOTAL_ASSETS", "Total assets", M, 1),
        ("BS_STATED_CAPITAL", "Stated capital", M, 0), ("BS_REVALUATION_RES", "Revaluation reserve", M, 0),
        ("BS_RETAINED", "Retained earnings", M, 0), ("BS_OTHER_RESERVES", "Other reserves", M, 0),
        ("BS_STATUTORY_RES", "Statutory or regulatory reserve", M, 0),
        ("BS_EQUITY_PARENT", "Equity attributable to equity holders", M, 1), ("BS_NCI", "Non-controlling interests", M, 0),
        ("BS_TOTAL_EQUITY", "Total equity", M, 1),
        ("BS_LT_BORROWINGS", "Non-current borrowings", M, 0), ("BS_ST_BORROWINGS", "Current borrowings", M, 0),
        ("BS_BORROWINGS", "Interest-bearing borrowings", M, 0), ("BS_LEASE", "Lease liabilities", M, 0),
        ("BS_EMPLOYEE_BENEFIT", "Retirement benefit obligation", M, 0), ("BS_DTL", "Deferred tax liabilities", M, 0),
        ("BS_DEFERRED_INCOME", "Deferred income, not split", M, 0), ("BS_DEFERRED_INCOME_NC", "Deferred income, non-current", M, 0), ("BS_TOTAL_NCL", "Total non-current liabilities", M, 1),
        ("BS_DEFERRED_INCOME_C", "Deferred income, current", M, 0), ("BS_TRADE_PAYABLES", "Trade and other payables", M, 0), ("BS_TAX_PAYABLE", "Current tax liabilities", M, 0),
        ("BS_RELATED_PAYABLE", "Amounts due to related parties", M, 0), ("BS_OVERDRAFT", "Bank overdrafts", M, 0),
        ("BS_OTHER_LIABILITIES", "Other liabilities", M, 0), ("BS_TOTAL_CL", "Total current liabilities", M, 1),
        ("BS_TOTAL_LIABILITIES", "Total liabilities", M, 1), ("BS_TOTAL_EQUITY_LIAB", "Total equity and liabilities", M, 1),
    ]),
    ("BS", "BANK", [
        ("BS_CENTRAL_BANK", "Balances with central banks", M, 0), ("BS_BANK_PLACEMENTS", "Placements with banks", M, 0),
        ("BS_REVERSE_REPO", "Securities purchased under resale agreements", M, 0),
        ("BS_DERIV_ASSETS", "Derivative financial assets", M, 0), ("BS_FVTPL", "Financial assets at fair value through profit or loss", M, 0),
        ("BS_LOANS", "Loans and advances to customers", M, 0), ("BS_AC_DEBT", "Debt and other instruments at amortised cost", M, 0),
        ("BS_FVOCI", "Financial assets at fair value through OCI", M, 0),
        ("BS_DUE_TO_BANKS", "Due to banks", M, 0), ("BS_DERIV_LIAB", "Derivative financial liabilities", M, 0),
        ("BS_REPO", "Securities sold under repurchase agreements", M, 0), ("BS_DEPOSITS", "Due to depositors", M, 0),
        ("BS_OTHER_BORROWINGS", "Other borrowings", M, 0), ("BS_DEBENTURES", "Debt securities issued", M, 0),
        ("BS_SUBORDINATED", "Subordinated term debts", M, 0), ("BS_DUE_TO_SUBSIDIARIES", "Due to subsidiaries", M, 0),
    ]),
    ("BS", "FINANCE", [
        ("BS_LEASE_RECEIVABLES", "Lease rentals and hire purchase receivables", M, 0),
        ("BS_GOLD_LOANS", "Gold loan advances", M, 0),
    ]),
    ("BS", "INSURANCE", [
        ("BS_REINSURANCE_RECEIVABLE", "Reinsurance receivables", M, 0), ("BS_INSURANCE_RECEIVABLE", "Insurance receivables", M, 0),
        ("BS_POLICY_LOANS", "Loans to life policyholders", M, 0),
        ("BS_HTM", "Held-to-maturity financial assets", M, 0), ("BS_LOANS_RECEIVABLES", "Loans and receivables (IAS 39 category)", M, 0),
        ("BS_AFS", "Available-for-sale financial assets", M, 0), ("BS_GRATUITY_ASSET", "Employee gratuity benefit asset", M, 0), ("BS_PENSION_ASSET", "Employee pension benefit asset", M, 0), ("BS_DEFERRED_EXP", "Deferred expenses", M, 0),
        ("BS_LIFE_LIABILITY", "Life insurance contract liabilities", M, 0),
        ("BS_NONLIFE_LIABILITY", "Non-life insurance contract liabilities", M, 0),
        ("BS_UNIT_LINKED", "Unit-linked and other funds", M, 0), ("BS_REINSURANCE_PAYABLE", "Reinsurance payables", M, 0),
    ]),
    ("CF", None, [
        ("CF_PBT", "Cash flow starting point: profit before tax", M, 0), ("CF_DEPRECIATION", "Cash flow adjustment: depreciation and amortisation", M, 0),
        ("CF_CASH_GENERATED", "Cash generated from operations", M, 1), ("CF_TAX_PAID", "Income tax paid", M, 0),
        ("CF_INTEREST_PAID", "Interest paid", M, 0), ("CF_INTEREST_RECEIVED", "Interest received", M, 0),
        ("CF_OPERATING", "Net cash from operating activities", M, 1), ("CF_CAPEX", "Purchase of property, plant and equipment", M, 0),
        ("CF_DISPOSAL", "Proceeds from sale of property, plant and equipment", M, 0),
        ("CF_INVESTING", "Net cash from investing activities", M, 1), ("CF_DIVIDEND_PAID", "Dividends paid", M, 0),
        ("CF_BORROWING_PROCEEDS", "Proceeds from borrowings", M, 0), ("CF_BORROWING_REPAID", "Repayment of borrowings", M, 0),
        ("CF_LEASE_PAID", "Lease payments", M, 0), ("CF_SHARE_ISSUE", "Proceeds from share issues", M, 0),
        ("CF_FINANCING", "Net cash from financing activities", M, 1), ("CF_NET_CHANGE", "Net change in cash and cash equivalents", M, 1),
        ("CF_OPENING", "Cash and cash equivalents at start of period", M, 0), ("CF_CLOSING", "Cash and cash equivalents at end of period", M, 0),
    ]),
    ("SOCE", None, [
        ("EQ_OPENING", "Equity opening balance", M, 0), ("EQ_PROFIT", "Equity movement: profit for the period", M, 0), ("EQ_OCI", "Equity movement: other comprehensive income", M, 0),
        ("EQ_DIVIDEND", "Equity movement: dividends", M, 0), ("EQ_SHARE_ISSUE", "Issue of shares", M, 0), ("EQ_TRANSFER", "Transfers between reserves", M, 0),
        ("EQ_CLOSING", "Equity closing balance", M, 1),
        ("EQC_STATED_CAPITAL", "Stated capital (column)", M, 0), ("EQC_RETAINED", "Retained earnings (column)", M, 0),
        ("EQC_REVALUATION", "Revaluation reserve (column)", M, 0), ("EQC_OTHER", "Other reserve (column)", M, 0),
        ("EQC_NCI", "Non-controlling interests (column)", M, 0), ("EQC_TOTAL", "Total equity (column)", M, 1),
    ]),
    ("SEG", None, [
        ("SEG_REVENUE", "Segment revenue", M, 0), ("SEG_RESULT", "Segment result", M, 0), ("SEG_PBT", "Segment profit before tax", M, 0),
        ("SEG_ASSETS", "Segment assets", M, 0), ("SEG_LIABILITIES", "Segment liabilities", M, 0),
        ("SEG_CAPEX", "Segment capital expenditure", M, 0), ("SEG_DEPRECIATION", "Segment depreciation and amortisation", M, 0),
    ]),
    ("KPI", None, [
        ("KPI_NAV_PER_SHARE", "Net assets per share", P, 0), ("KPI_CONTINGENT", "Contingent liabilities", M, 0),
        ("KPI_COMMITMENTS", "Capital commitments", M, 0), ("KPI_EMPLOYEES", "Number of employees", C, 0),
        ("KPI_DEBT_EQUITY", "Debt to equity ratio", X, 0), ("KPI_INTEREST_COVER", "Interest cover", X, 0),
        ("KPI_QUICK_ASSET", "Quick asset ratio", X, 0),
    ]),
    ("KPI", "BANK", [
        ("KPI_CET1", "Common equity Tier 1 ratio", R, 0), ("KPI_TIER1", "Tier 1 capital ratio", R, 0),
        ("KPI_TOTAL_CAPITAL", "Total capital ratio", R, 0), ("KPI_LEVERAGE", "Basel III leverage ratio", R, 0),
        ("KPI_LCR", "Liquidity coverage ratio", R, 0), ("KPI_NSFR", "Net stable funding ratio", R, 0),
        ("KPI_STAGE3_GROSS", "Stage 3 loans ratio, gross", R, 0), ("KPI_STAGE3_NET", "Stage 3 loans ratio, net", R, 0),
        ("KPI_NIM", "Net interest margin", R, 0), ("KPI_ROA", "Return on assets", R, 0), ("KPI_ROE", "Return on equity", R, 0),
        ("KPI_COST_INCOME", "Cost to income ratio", R, 0), ("KPI_BRANCHES", "Number of branches", C, 0),
    ]),
    ("KPI", "FINANCE", [
        ("KPI_CORE_CAPITAL", "Core capital ratio", R, 0), ("KPI_NPL", "Non-performing loans ratio", R, 0),
    ]),
    ("KPI", "INSURANCE", [
        ("KPI_SOLVENCY", "Risk-based capital adequacy ratio", R, 0),
    ]),
]


# Approved spellings: {statement printed on: {item code: [spelling or (spelling, section)]}}.
# Taken from real reports. Matching is exact after normalize.label(), never by similarity,
# so a new spelling stays UNMAPPED until someone adds it here.
ALIASES = {
    "IS": {
        "IS_REVENUE": ["Turnover", "Revenue"], "IS_COST_OF_SALES": ["Cost of Sales"], "IS_GROSS_PROFIT": ["Gross Profit"],
        "IS_OTHER_INCOME": ["Other Income"], "IS_DISTRIBUTION_EXP": ["Marketing and Distribution Expenses"],
        "IS_ADMIN_EXP": ["Administrative Expenses"],
        "IS_OTHER_OPERATING_EXP": ["Other operating expenses", "Other Operating and Administrative Expenses"],
        "IS_OPERATING_PROFIT": ["Operating Profit/(Loss) for the Period", "Profit from Operations"],
        "IS_FINANCE_INCOME": ["Finance Income"], "IS_FINANCE_COST": ["Finance Cost", "Finance Expenses"],
        "IS_ASSOCIATE_SHARE": ["Share of Profit of Associates", "Share of profit/(loss) of associate, net of tax"],
        "IS_PBT": ["Profit Before Tax", "Profit before income tax", "Profit/(Loss) before Tax"],
        "IS_TAX": ["Income Tax Expense", "Tax Expense"],
        "IS_PAT": ["Profit for the Period", "Net Profit/(Loss) for the Period"],
        "IS_PAT_PARENT": ["Equity Holders of the Parent", "Equity holders of the Bank"],
        "IS_PAT_NCI": ["Non-Controlling Interests", "Non-controlling interest"],
        "IS_EPS_BASIC": ["Basic earnings per ordinary share"], "IS_EPS_DILUTED": ["Diluted earnings per ordinary share"],
        "IS_GROSS_INCOME": ["Gross income"], "IS_INTEREST_INCOME": ["Interest income"], "IS_INTEREST_EXPENSE": ["Interest expense"],
        "IS_NET_INTEREST_INCOME": ["Net interest income"], "IS_FEE_INCOME": ["Fee and commission income"],
        "IS_FEE_EXPENSE": ["Fee and commission expense"], "IS_NET_FEE_INCOME": ["Net fee and commission income"],
        "IS_TRADING_GAINS": ["Net gains/(losses) from trading"],
        "IS_DERECOGNITION_GAINS": ["Net gains/(losses) from derecognition of financial assets"],
        "IS_OTHER_OPERATING_INCOME": ["Other operating income"], "IS_NET_OTHER_OPERATING_INCOME": ["Net other operating income"],
        "IS_TOTAL_OPERATING_INCOME": ["Total operating income"], "IS_IMPAIRMENT": ["Impairment charges and other losses"],
        "IS_NET_OPERATING_INCOME": ["Net operating income"], "IS_OPERATING_EXPENSES": ["Operating expenses"],
        "IS_PERSONNEL_EXP": ["Personnel expenses"], "IS_DEPRECIATION": ["Depreciation and amortisation"],
        "IS_PROFIT_BEFORE_FST": ["Operating profit before taxes on financial services"], "IS_FST": ["Taxes on financial services"],
        "IS_PROFIT_AFTER_FST": ["Operating profit after taxes on financial services"],
        "IS_NET_INCOME_INS": ["Net Income"], "IS_GWP": ["Gross Written Premiums"], "IS_PREMIUM_CEDED": ["Premiums Ceded to Reinsurers"],
        "IS_NWP": ["Net Written Premiums"], "IS_UPR_CHANGE": ["Net Change in Reserve for Unearned Premium"],
        "IS_NEP": ["Net Earned Premium"], "IS_INVESTMENT_INCOME": ["Investment and Other Income"],
        "IS_NET_CLAIMS": ["Insurance Claims and Benefit (Net)"], "IS_LIFE_FUND_CHANGE": ["Increase in Life Insurance Fund"],
        "IS_ACQUISITION_COST": ["Acquisition Cost"], "IS_TOTAL_BENEFITS": ["Total Benefits, Losses and Expenses"],
        "IS_NON_INSURANCE_REVENUE": ["Revenue from Non-Insurance Subsidiaries"],
        "IS_NON_INSURANCE_COST": ["Cost of Sales of Non-Insurance Subsidiaries"],
        "OCI_TCI": ["Total Comprehensive Income"],
    },
    "BS": {
        "BS_PPE": ["Property, plant and equipment"], "BS_PPE_AND_ROU": ["Property, plant and equipment and right-of-use assets"],
        "BS_ROU": ["Right of use assets"], "BS_INV_PROPERTY": ["Investment property", "Investment properties"],
        "BS_INTANGIBLES": ["Intangible assets"], "BS_GOODWILL": ["Goodwill"],
        "BS_SUBSIDIARIES": ["Investment in Subsidiaries", "Investments in subsidiaries"], "BS_ASSOCIATES": ["Investment in Associates"],
        "BS_DTA": ["Deferred tax assets"], "BS_TOTAL_NCA": ["Total Non-Current Assets"], "BS_INVENTORIES": ["Inventories"],
        "BS_TRADE_RECEIVABLES": ["Trade and other receivables"], "BS_PREPAYMENTS": ["Deposits, advances & prepayments"],
        "BS_RELATED_RECEIVABLE": ["Amounts due from related parties"], "BS_ST_LOANS_GIVEN": ["Short term loan receivable"],
        "BS_ST_INVESTMENTS": ["Investment in short term deposits"], "BS_TAX_RECEIVABLE": ["Income Tax Receivable"],
        "BS_OTHER_ASSETS": ["Other assets"], "BS_CASH": ["Cash and cash equivalents", "Cash and cash equivalent"],
        "BS_TOTAL_CA": ["Total Current Assets"], "BS_TOTAL_ASSETS": ["Total Assets"],
        "BS_STATED_CAPITAL": ["Stated capital"], "BS_REVALUATION_RES": ["Revaluation reserves"], "BS_RETAINED": ["Retained earnings"],
        "BS_OTHER_RESERVES": ["Other reserves"], "BS_STATUTORY_RES": ["Statutory reserves", "Restricted Regulatory Reserve"],
        "BS_EQUITY_PARENT": ["Total Ordinary Shareholders\u2019 Equity", "Total equity attributable to equity holders of the Bank"],
        "BS_NCI": ["Non-Controlling Interests", "Non-Controlling Interest"], "BS_TOTAL_EQUITY": ["Total Equity"],
        "BS_LT_BORROWINGS": [("Borrowings", "LIAB_NC")], "BS_ST_BORROWINGS": [("Borrowings", "LIAB_C")],
        "BS_BORROWINGS": ["Interest Bearing Loans & Borrowings"],
        "BS_EMPLOYEE_BENEFIT": ["Retirement benefit obligation", "Employee Gratuity Benefit Liability"],
        "BS_DTL": ["Deferred tax liability", "Deferred tax liabilities"], "BS_DEFERRED_INCOME": ["Deferred Revenue"],
        "BS_DEFERRED_INCOME_NC": [("Deferred service income", "LIAB_NC")], "BS_DEFERRED_INCOME_C": [("Deferred service income", "LIAB_C")],
        "BS_TOTAL_NCL": ["Non-Current Liabilities", "Total Non-Current Liabilities"],
        "BS_TOTAL_CL": ["Current Liabilities", "Total Current Liabilities"], "BS_TRADE_PAYABLES": ["Trade and other payables"],
        "BS_TAX_PAYABLE": ["Income tax liability", "Current tax liabilities"], "BS_RELATED_PAYABLE": ["Amounts due to related parties"],
        "BS_OTHER_LIABILITIES": ["Other liabilities and provisions"], "BS_TOTAL_LIABILITIES": ["Total Liabilities"],
        "BS_TOTAL_EQUITY_LIAB": ["Total Equity and Liabilities", "Total Liabilities and Equity"],
        "BS_CENTRAL_BANK": ["Balances with Central Banks"], "BS_BANK_PLACEMENTS": ["Placements with banks"],
        "BS_REVERSE_REPO": ["Securities purchased under resale agreements"], "BS_DERIV_ASSETS": ["Derivative financial assets"],
        "BS_FVTPL": ["Financial assets recognised through profit or loss \u2013 measured at fair value", "Financial Assets at Fair Value through Profit or Loss"],
        "BS_LOANS": ["Financial assets at amortised cost \u2013 Loans and advances to other customers"],
        "BS_AC_DEBT": ["Financial assets at amortised cost \u2013 Debt and other financial instruments"],
        "BS_FVOCI": ["Financial assets measured at fair value through other comprehensive income"],
        "BS_DUE_TO_BANKS": ["Due to banks"], "BS_DERIV_LIAB": ["Derivative financial liabilities"],
        "BS_REPO": ["Securities sold under repurchase agreements"],
        "BS_DEPOSITS": ["Financial liabilities at amortised cost \u2013 due to depositors"],
        "BS_OTHER_BORROWINGS": ["Financial liabilities at amortised cost \u2013 other borrowings"],
        "BS_SUBORDINATED": ["Subordinated liabilities"], "BS_DUE_TO_SUBSIDIARIES": ["Due to subsidiaries"],
        "BS_REINSURANCE_RECEIVABLE": ["Reinsurance Receivables"], "BS_INSURANCE_RECEIVABLE": ["Insurance Receivables/Trade Debtors"],
        "BS_POLICY_LOANS": ["Loans to Life Policyholders"], "BS_DEFERRED_EXP": ["Deferred Expenses"],
        "BS_HTM": ["Held to Maturity Financial Assets"], "BS_LOANS_RECEIVABLES": ["Loans and Receivables"],
        "BS_AFS": ["Available-for-Sale Financial Assets"], "BS_GRATUITY_ASSET": ["Employee Gratuity Benefit Asset"],
        "BS_PENSION_ASSET": ["Employee Pension Benefit Asset"], "BS_LIFE_LIABILITY": ["Life Insurance Contract Liabilities"],
        "BS_NONLIFE_LIABILITY": ["Non Life Insurance Contract Liabilities"], "BS_UNIT_LINKED": ["Unit Linked Fund & Other Funds -Life"],
        "BS_REINSURANCE_PAYABLE": ["Reinsurance Payables"],
        "KPI_CONTINGENT": ["Contingent Liabilities and Commitments"], "KPI_NAV_PER_SHARE": ["Net Assets Value per Ordinary Share"],
    },
}


# Approved announcement categories, exact match after normalize.clean(). Anything else appears in
# v_unclassified_action_announcements for a decision.
KIND_MAP = {
    "CASH_DIVIDEND": ["dividend announcement", "cash dividend", "cash dividend dates to be notified", "dividend announcement dates",
        "dividend announcement amended dates", "dividend announcement amended", "dividend announcements",
        "dividend announcement amended payment date", "dividend announcement with amended dates",
        "dividend announcements interim and final", "cash and scrip dividend", "cash and scrip dividend announcement",
        "cash and scrip dividend dates", "cash and scrip dividend announcement dates", "dividend announcements cash and scrip"],
    "SCRIP_DIVIDEND": ["scrip dividend", "scrip dividend dates", "scrip dividend notification on the listing of shares",
        "notification on the listing of shares scrip dividend", "further announcement re scrip dividend", "scrip dividend announcement dates",
        "scrip dividend announcement", "notification of listing of shares of scrip dividend", "scrip dividend further announcement",
        "cash and scrip dividend", "cash and scrip dividend announcement", "cash and scrip dividend dates",
        "cash and scrip dividend announcement dates", "dividend announcements cash and scrip"],
    "SUB_DIVISION": ["sub division of shares", "sub division of shares dates", "sub division", "sub division of shares circular to shareholders",
        "sub division of shares and adjustment to warrants", "rights issue and sub division of shares",
        "reduction of stated capital and sub division of shares", "subdivision private placement and reduction of stated capital"],
    "CONSOLIDATION": ["consolidation of shares"],
    "CAPITALISATION": ["capitalization of reserves", "capitalisation of reserves", "capitalization of reserves dates",
        "notification on the listing of shares capitalization of reserves", "capitalization of reserves notification on the listing of shares",
        "capitalization of reserves notification"],
    "RIGHTS_ISSUE": ["rights issue", "rights issue dates", "rights issue notification on the listing of shares",
        "notification on the listing of shares rights issue", "further announcement re rights issue", "rights issue of shares",
        "rights issue amended dates", "rights issue dates amended", "rights issue and related party transactions",
        "rights issue and sub division of shares", "announcement of rights issue and warrants", "rights issue of unlisted ordinary shares"],
    "REPURCHASE": ["repurchase of shares", "notification on repurchase of shares", "repurchase of shares and dividend announcement"],
    "CAPITAL_REDUCTION": ["reduction of stated capital", "reduction of stated capital and sub division of shares",
        "subdivision private placement and reduction of stated capital"],
    "PRIVATE_PLACEMENT": ["issue of shares by private placement", "private placement", "private placement of ordinary shares notification on the listing of shares",
        "notification on the listing of shares private placement", "issue of shares by way of a private placement", "private placement of shares",
        "subdivision private placement and reduction of stated capital"],
    "NAME_CHANGE": ["change of company name", "company name change", "change of name", "change of name of the company", "name change"],
    "WATCH_LIST_IN": ["watch list transferred in", "watch list transfer in"],
    "WATCH_LIST_OUT": ["watch list transferred out", "watch list transfer out"],
    "SUSPENDED": ["enforcement action in terms of cse listing rules notification re trading suspension", "trading suspended",
        "notification re trading suspension"],
    "SUSPENSION_LIFTED": ["lifting of trading suspension", "trading suspension lifted"],
    "DELISTED": ["delisting of the ordinary shares of asiri central hospitals plc",
        "de listing of the ordinary shares of equity one plc from the official list of the colombo stock exch",
        "delisting of securities of kalpitiya beach resort plc", "delisting of shares from the official list of the colombo stock exchange"],
    "BOARD_TRANSFER": ["transfer from the main board to the diri savi board", "transfer to the main board", "transfer to the diri savi board",
        "transfer from main board to the diri savi board"],
}


# Second pass over the review queue, 2026-11-02. Proposals, circulars and meetings stay out on purpose.
_BOTH = ["amended cash and scrip dividend dates", "announcement re cash and scrip dividend", "cash and scrip dividend announcements",
         "cash and scrip dividends", "cash and scrip dividends announcement", "dividend announcements cash and scrip cdb", "further announcement re cash and scrip dividend"]
_RIGHTS_SPLIT = ["rights issue and sub division of shares dates", "rights issue sub division", "rights issue sub division and other corporate disclosures",
                 "sub division of shares and rights issue of shares", "subdivision of shares capitalization of reserves rights issue of shares",
                 "subdivision of shares capitalization of reserves rights issue of shares dates"]
_MORE = {
    "CASH_DIVIDEND": _BOTH + ["amended dividend announcement", "amended dividend announcement amended dates", "amended dividend announcement financial year",
        "ceylon hospitals plc durdans dividend announcement", "dividend announcement amended financial year", "dividend announcement ammended dates",
        "dividend announcement final and final", "dividend announcement on the enhanced capital post the rights issue", "dividend announcements amended dates",
        "dividend dates", "dividend dates amended", "final dividend for the financial year ended 31 12 2011", "first and final dividend", "interim dividend",
        "capitalization of reserves and dividend"],
    "SCRIP_DIVIDEND": _BOTH + ["annual general meeting and scrip dividend dates", "national development bank plc scrip dividend", "scrip dividend 2012",
        "scrip dividend 2016 notification on the listing of shares", "scrip dividend amended", "scrip dividend notification", "seylan bank scrip dividend dates"],
    "CAPITALISATION": ["capitalisation of reserves dates", "capitalisation of reserves notification on the listing of shares", "capitalization of reserves amended dates",
        "capitalization of reserves amended proportion", "capitalization of reserves and dividend", "capitalization of reserves and sub division of shares",
        "capitalization of reserves dates voting and non voting", "capitalization of reserves notification on listing of shares", "capitalization of reserves voting and non voting",
        "further announcement re capitalization of reserves", "issue of shares by way of capitalization of reserves", "rights issue and capitalization of reserves",
        "subdivision of shares capitalization of reserves rights issue of shares", "subdivision of shares capitalization of reserves rights issue of shares dates"],
    "SUB_DIVISION": _RIGHTS_SPLIT + ["capitalization of reserves and sub division of shares", "further announcement re sub division of shares",
        "sub division of shares subsequent to the rights issue", "subdivision of ordinary shares and adjustment to warrants"],
    "CONSOLIDATION": ["consolidation of shares and rights issue", "consolidation of shares and rights issue dates", "further announcement re repurchase of shares and consolidation of shares",
        "repurchase of shares and consolidation of shares", "repurchase of shares followed by a consolidation of shares"],
    "RIGHTS_ISSUE": _RIGHTS_SPLIT + ["browns beach hotels further announcement re rights issue", "consolidation of shares and rights issue", "consolidation of shares and rights issue dates",
        "corporate disclosure re rights issue", "further announcement re rights issue of shares", "notification re rights issue", "private placement and rights issue",
        "private placement and rights issue of shares", "private placement and rights issue of shares dates", "rights isssue", "rights isssue notification on the listing of shares",
        "rights issue amended dates voting and non voting", "rights issue and capitalization of reserves", "rights issue cfi", "rights issue change of date of acceptance and payment",
        "rights issue cit", "rights issue dates voting and non voting", "rights issue kfp", "rights issue notification on the listings of shares",
        "rights issue of ordinary non voting covertible shares", "rights issue of ordinary shares", "rights issue of shares 2012", "rights issue oversubscribed",
        "rights issue tranche 1 notification on the listing of shares", "rights warrant issue"],
    "REPURCHASE": ["ceylon leather products plc repurchase of shares", "disclosure re share repurchase by ndb capital holdings plc", "repurchase of shares agm",
        "repurchase of shares and consolidation of shares", "repurchase of shares followed by a consolidation of shares", "further announcement re repurchase of shares and consolidation of shares",
        "repurchase of shares notification on repurchase of shares", "repurchase of shares notification on the repurchase of shares", "notification on the repurchase of shares", "share repurchase"],
    "PRIVATE_PLACEMENT": ["further announcement re private placement", "further announcement re private placement of shares", "notification on the listing of shares private placement of ordinary shares",
        "notification on the listing of shares private placement of ordinary voting shares", "private placement and rights issue", "private placement and rights issue of shares",
        "private placement and rights issue of shares dates", "private placement of ordinary voting shares notification on the listing of shares",
        "private placement of shares notification on the listing of shares", "share swap by way of a private placement"],
    "NAME_CHANGE": ["change of the company name", "name change of the company"],
    "WATCH_LIST_IN": ["anilana hotels and properties plc watch list transferred in"],
    "WATCH_LIST_OUT": ["watchlist transferred out"],
    "SUSPENDED": ["ctce n0000 trading suspended", "metropolitan resource holdings trading suspended", "mori n0000 and mori x0000 trading suspended", "pdl n0000 trading suspension",
        "sfs n0000 trading suspended", "trading suspension", "cse notification and company announcement re suspension of trading",
        "suspension of trading of securities of swarnamahal financial services plc", "sec directive trading suspension of the shares of touchwood investments plc"],
    "SUSPENSION_LIFTED": ["lanka cement plc lifting of trading suspension", "notification on the lifting of trading suspension of brac lanka finance plc",
        "notification on the lifting of trading suspension of kotmale holdings plc", "notification on the lifting of trading suspension of trade finance and investments plc",
        "radiant gems international plc trading suspension lifted amended", "lifting of the suspension on trading of the shares of distilleries company of sri lanka plc"],
}
for _k, _v in _MORE.items():
    KIND_MAP[_k] = KIND_MAP[_k] + [c for c in _v if c not in KIND_MAP[_k]]


def apply(con):
    con.executemany("INSERT INTO reporting_template(code,name) VALUES (?,?)", TEMPLATES)
    con.executemany("INSERT INTO statement_type(code,name) VALUES (?,?)", STATEMENTS)
    st = dict(con.execute("SELECT code, statement_type_id FROM statement_type"))
    tp = dict(con.execute("SELECT code, template_id FROM reporting_template"))
    order, seen_names = 0, {}
    for stmt, tmpl, items in ITEMS:
        for code, name, kind, sub in items:
            key = normalize.clean(name)
            if key in seen_names:
                raise ValueError(f"line items {seen_names[key]} and {code} have the same name: {name}")
            seen_names[key] = code
            order += 10
            con.execute(
                "INSERT INTO line_item(code,name,statement_type_id,template_id,value_kind,is_subtotal,display_order)"
                " VALUES (?,?,?,?,?,?,?)",
                (code, name, st[stmt], tp.get(tmpl), kind, sub, order),
            )
    items_by_code = dict(con.execute("SELECT code, line_item_id FROM line_item"))
    for stmt, by_code in ALIASES.items():
        for code, spellings in by_code.items():
            for spelling in spellings:
                text, section = spelling if isinstance(spelling, tuple) else (spelling, "ANY")
                con.execute("INSERT INTO label_alias(statement_type_id,section,normalized_label,line_item_id) VALUES (?,?,?,?)",
                            (st[stmt], section, normalize.label(text), items_by_code[code]))
    # Reviewed label approvals from full loads, kept in reviewed/label_aliases.py
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "reviewed"))
    import label_aliases as LA
    for stmt, code, name, kind, sub in LA.NEW_ITEMS:
        key = normalize.clean(name)
        if key in seen_names:
            raise ValueError(f"line items {seen_names[key]} and {code} have the same name: {name}")
        seen_names[key] = code
        order += 10
        con.execute("INSERT INTO line_item(code,name,statement_type_id,value_kind,is_subtotal,display_order) VALUES (?,?,?,?,?,?)",
                    (code, name, st[stmt], kind, sub, order))
    items_by_code = dict(con.execute("SELECT code, line_item_id FROM line_item"))
    existing = {(a, b, c_): d for a, b, c_, d in con.execute("SELECT statement_type_id, section, normalized_label, line_item_id FROM label_alias")}
    for stmt, by_code in LA.ALIASES.items():
        for code, spellings in by_code.items():
            for spelling in spellings:
                text, section = spelling if isinstance(spelling, tuple) else (spelling, "ANY")
                key = (st[stmt], section, normalize.label(text))
                if key in existing:
                    if existing[key] != items_by_code[code]:
                        raise ValueError(f"{text!r} already approved for another item")
                    continue
                con.execute("INSERT INTO label_alias(statement_type_id,section,normalized_label,line_item_id) VALUES (?,?,?,?)",
                            (st[stmt], section, key[2], items_by_code[code]))
                existing[key] = items_by_code[code]
    for kind, categories in KIND_MAP.items():
        for category in categories:
            con.execute("INSERT INTO announcement_kind_map(normalized_category,kind) VALUES (?,?)", (normalize.clean(category), kind))

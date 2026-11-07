-- CSE financial database schema (SQLite 3.45+; run with PRAGMA foreign_keys = ON).
--
-- Money is stored in whole rupees in `value`, whatever scale the report used.
-- Each figure keeps its source document, page and scale so it can be traced.
--
-- Naming rules, enforced here rather than left to loaders:
--   * Text columns called normalized_* may only hold lowercase letters, digits and single
--     spaces, so 'Total Assets' and 'TOTAL  ASSETS' can only be one row.
--   * A standard line item has one name. Other spellings live in label_alias, where each
--     spelling points to exactly one item. Matching is exact; unknown labels stay UNMAPPED.
--   * One document cannot report two values for one item, period and scope.
-- Composite foreign keys that include company_id stop a figure being attached
-- to another company's document, period or label.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- reference
CREATE TABLE sector (
    sector_id        INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    cse_index_code   TEXT
);

-- Statement layout family. Banks, insurers, finance companies and funds do not
-- report the same lines as trading companies.
CREATE TABLE reporting_template (
    template_id      INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL
);

CREATE TABLE statement_type (
    statement_type_id INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL
);

-- ---------------------------------------------------------------- companies
CREATE TABLE company (
    company_id       INTEGER PRIMARY KEY,          -- CSE securityId; shared by voting and non-voting classes
    ticker           TEXT NOT NULL UNIQUE,         -- e.g. COMB
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    sector_id        INTEGER REFERENCES sector(sector_id),
    sector_source    TEXT CHECK (sector_source IN ('OFFICIAL_INDEX','COMPANY_PROFILE')),
    -- Set when CSE gave one legal entity a new id, e.g. debentures first and shares later.
    successor_company_id INTEGER REFERENCES company(company_id),
    cse_sector_raw   TEXT,                         -- CSE free text before standardising
    template_id      INTEGER NOT NULL REFERENCES reporting_template(template_id),
    board_type       TEXT,
    listing_status   TEXT NOT NULL CHECK (listing_status IN ('LISTED','DELISTED')),
    trading_status   TEXT,                         -- CSE's current flag, e.g. TRADING_SUSPENDED
    established_year INTEGER,
    fiscal_year_end_month INTEGER CHECK (fiscal_year_end_month BETWEEN 1 AND 12),
    registered_office TEXT,
    phone            TEXT,
    fax              TEXT,
    email            TEXT,
    website          TEXT,
    secretaries      TEXT,
    auditors         TEXT,
    business_summary TEXT,
    fetched_at       TEXT NOT NULL
);

CREATE TABLE security (
    security_id      INTEGER PRIMARY KEY,          -- CSE reqSymbolInfo.id
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    symbol           TEXT NOT NULL UNIQUE,         -- e.g. COMB.X0000
    isin             TEXT UNIQUE,
    share_class      TEXT NOT NULL
        CHECK (share_class IN ('VOTING','NON_VOTING','UNIT','RIGHTS','PREFERENCE','WARRANT','OTHER')),
    listing_status   TEXT NOT NULL CHECK (listing_status IN ('LISTED','DELISTED')),
    par_value        NUMERIC,
    issue_date       TEXT,
    quantity_issued  INTEGER,
    UNIQUE (company_id, security_id)
);

-- One row per exact name. CSE issues a new director id per directorship, so the id
-- cannot identify a person and lives on company_officer instead.
CREATE TABLE person (
    person_id        INTEGER PRIMARY KEY,
    full_name        TEXT NOT NULL,
    normalized_name  TEXT NOT NULL UNIQUE
        CHECK (normalized_name <> '' AND normalized_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_name NOT LIKE '%  %')
);

CREATE TABLE company_officer (
    officer_id       INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    person_id        INTEGER NOT NULL REFERENCES person(person_id),
    cse_director_id  INTEGER UNIQUE,
    designation      TEXT,
    is_executive     INTEGER CHECK (is_executive IN (0,1)),
    is_independent   INTEGER CHECK (is_independent IN (0,1)),
    as_of_date       TEXT NOT NULL,
    UNIQUE (company_id, person_id, as_of_date)
);

-- ------------------------------------------------------- documents & periods
CREATE TABLE report_document (
    document_id      INTEGER PRIMARY KEY,          -- CSE report id
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    category         TEXT NOT NULL CHECK (category IN ('INTERIM','ANNUAL','OTHER')),
    title            TEXT NOT NULL,
    source_url       TEXT NOT NULL UNIQUE,
    period_end_date  TEXT                          -- parsed from the title; NULL if the title has no date
        CHECK (period_end_date IS NULL OR date(period_end_date) IS period_end_date),
    cse_manual_date  TEXT,                         -- raw CSE date, sometimes a filing date or an error
    uploaded_at      TEXT,
    authorized_at    TEXT,
    local_path       TEXT,
    sha256           TEXT,
    page_count       INTEGER,
    extraction_status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (extraction_status IN ('PENDING','DOWNLOADED','EXTRACTED','PARTIAL','FAILED','SKIPPED')),
    extractor        TEXT,
    UNIQUE (company_id, document_id),
    UNIQUE (company_id, sha256)                    -- the same file cannot be loaded under two ids
);
CREATE INDEX ix_document_company_date ON report_document(company_id, category, period_end_date);

-- A balance-sheet date is an INSTANT; an income or cash-flow period is a DURATION.
CREATE TABLE reporting_period (
    period_id        INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    period_kind      TEXT NOT NULL CHECK (period_kind IN ('INSTANT','DURATION')),
    start_date       TEXT,
    end_date         TEXT NOT NULL,
    months           INTEGER,
    fiscal_year      INTEGER,                      -- calendar year in which the fiscal year ends
    fiscal_quarter   INTEGER CHECK (fiscal_quarter BETWEEN 1 AND 4),
    -- IS rather than =, because a bad date gives NULL and CHECK lets NULL through.
    CHECK (date(end_date) IS end_date),
    CHECK ((period_kind = 'INSTANT' AND start_date IS NULL AND months IS NULL)
        OR (period_kind = 'DURATION' AND months > 0
            -- starts on the 1st and months agrees with the dates, so a period has only one form
            AND date(start_date, 'start of month') IS start_date
            AND date(start_date, '+' || months || ' months', '-1 day') IS end_date)),
    UNIQUE (company_id, period_id)
);
CREATE UNIQUE INDEX ux_period ON reporting_period(company_id, period_kind, COALESCE(start_date,''), end_date);

-- -------------------------------------------------- line-item dictionary
-- Standard line items. template_id NULL means the item applies to every template.
CREATE TABLE line_item (
    line_item_id     INTEGER PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    statement_type_id INTEGER NOT NULL REFERENCES statement_type(statement_type_id),
    template_id      INTEGER REFERENCES reporting_template(template_id),
    parent_line_item_id INTEGER REFERENCES line_item(line_item_id),
    value_kind       TEXT NOT NULL DEFAULT 'MONEY'
        CHECK (value_kind IN ('MONEY','PER_SHARE','PERCENT','COUNT','RATIO')),
    is_subtotal      INTEGER NOT NULL DEFAULT 0 CHECK (is_subtotal IN (0,1)),
    display_order    INTEGER NOT NULL
);

-- The approved list of spellings. Each spelling, on a given statement, has one meaning.
-- section 'ANY' applies under every heading. A specific section is used only where the same
-- words mean different things, e.g. 'Borrowings' under current or non-current liabilities.
-- statement_type_id is the statement the line is printed on; the item it points to can sit in
-- another statement, e.g. net assets per share printed on a balance sheet is a KPI.
CREATE TABLE label_alias (
    alias_id         INTEGER PRIMARY KEY,
    statement_type_id INTEGER NOT NULL REFERENCES statement_type(statement_type_id),
    section          TEXT NOT NULL DEFAULT 'ANY'
        CHECK (section IN ('ANY','NONE','ASSET','ASSET_NC','ASSET_C','EQUITY','LIAB','LIAB_NC','LIAB_C','OPERATING','INVESTING','FINANCING')),
    normalized_label TEXT NOT NULL
        CHECK (normalized_label <> '' AND normalized_label NOT GLOB '*[^a-z0-9 ]*' AND normalized_label NOT LIKE '%  %'),
    line_item_id     INTEGER NOT NULL REFERENCES line_item(line_item_id),
    UNIQUE (statement_type_id, section, normalized_label)
);

-- A label as a company wrote it. raw_label keeps the first spelling seen. normalized_label is
-- what identifies it, so changes of case or punctuation between reports reuse the same row.
-- Section stays NONE unless the alias needs it, so a heading change cannot split a label.
CREATE TABLE reported_label (
    label_id         INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    statement_type_id INTEGER NOT NULL REFERENCES statement_type(statement_type_id),
    section          TEXT NOT NULL DEFAULT 'NONE'
        CHECK (section IN ('NONE','ASSET','ASSET_NC','ASSET_C','EQUITY','LIAB','LIAB_NC','LIAB_C','OPERATING','INVESTING','FINANCING')),
    raw_label        TEXT NOT NULL,
    normalized_label TEXT NOT NULL
        CHECK (normalized_label <> '' AND normalized_label NOT GLOB '*[^a-z0-9 ]*' AND normalized_label NOT LIKE '%  %'),
    line_item_id     INTEGER REFERENCES line_item(line_item_id),
    mapping_method   TEXT NOT NULL DEFAULT 'UNMAPPED'
        CHECK (mapping_method IN ('ALIAS','MANUAL','UNMAPPED')),
    -- Companies show expenses differently: '(1,567,932)' or 'Less: Interest expense 91,955'.
    -- value x sign_factor gives the standard sign, with income positive and expenses negative.
    sign_factor      INTEGER NOT NULL DEFAULT 1 CHECK (sign_factor IN (1,-1)),
    CHECK ((line_item_id IS NULL) = (mapping_method = 'UNMAPPED')),
    UNIQUE (company_id, statement_type_id, section, normalized_label),
    UNIQUE (company_id, label_id)
);

-- ------------------------------------------------------------ financial facts
CREATE TABLE financial_fact (
    fact_id          INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL,
    document_id      INTEGER NOT NULL,
    period_id        INTEGER NOT NULL,
    label_id         INTEGER NOT NULL,
    entity_scope     TEXT NOT NULL CHECK (entity_scope IN ('GROUP','COMPANY')),
    value            NUMERIC NOT NULL,
    unit_scale       INTEGER NOT NULL DEFAULT 1,   -- reported x unit_scale = value
    currency         TEXT NOT NULL DEFAULT 'LKR',
    audit_status     TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK (audit_status IN ('AUDITED','UNAUDITED','UNKNOWN')),
    is_restated      INTEGER NOT NULL DEFAULT 0 CHECK (is_restated IN (0,1)),
    page_no          INTEGER,
    FOREIGN KEY (company_id, document_id) REFERENCES report_document(company_id, document_id),
    FOREIGN KEY (company_id, period_id)   REFERENCES reporting_period(company_id, period_id),
    FOREIGN KEY (company_id, label_id)    REFERENCES reported_label(company_id, label_id),
    UNIQUE (document_id, period_id, entity_scope, label_id)
);
CREATE INDEX ix_fact_label  ON financial_fact(label_id);
CREATE INDEX ix_fact_period ON financial_fact(period_id);
CREATE INDEX ix_fact_company_scope_period ON financial_fact(company_id, entity_scope, period_id);

-- Statement of changes in equity is a matrix: movement rows by reserve columns.
CREATE TABLE equity_movement_fact (
    equity_fact_id   INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL,
    document_id      INTEGER NOT NULL,
    period_id        INTEGER NOT NULL,
    movement_label_id  INTEGER NOT NULL,           -- row, e.g. Dividends paid
    component_label_id INTEGER NOT NULL,           -- column, e.g. Retained earnings
    entity_scope     TEXT NOT NULL CHECK (entity_scope IN ('GROUP','COMPANY')),
    value            NUMERIC NOT NULL,
    unit_scale       INTEGER NOT NULL DEFAULT 1,
    page_no          INTEGER,
    FOREIGN KEY (company_id, document_id) REFERENCES report_document(company_id, document_id),
    FOREIGN KEY (company_id, period_id)   REFERENCES reporting_period(company_id, period_id),
    FOREIGN KEY (company_id, movement_label_id)  REFERENCES reported_label(company_id, label_id),
    FOREIGN KEY (company_id, component_label_id) REFERENCES reported_label(company_id, label_id),
    UNIQUE (document_id, period_id, entity_scope, movement_label_id, component_label_id)
);

CREATE TABLE segment (
    segment_id       INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL
        CHECK (normalized_name <> '' AND normalized_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_name NOT LIKE '%  %'),
    segment_kind     TEXT NOT NULL DEFAULT 'BUSINESS' CHECK (segment_kind IN ('BUSINESS','GEOGRAPHIC','OTHER')),
    UNIQUE (company_id, normalized_name, segment_kind),
    UNIQUE (company_id, segment_id)
);

CREATE TABLE segment_fact (
    segment_fact_id  INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL,
    document_id      INTEGER NOT NULL,
    period_id        INTEGER NOT NULL,
    segment_id       INTEGER NOT NULL,
    label_id         INTEGER NOT NULL,             -- e.g. Segment revenue, Segment assets
    entity_scope     TEXT NOT NULL CHECK (entity_scope IN ('GROUP','COMPANY')),
    value            NUMERIC NOT NULL,
    unit_scale       INTEGER NOT NULL DEFAULT 1,
    page_no          INTEGER,
    FOREIGN KEY (company_id, document_id) REFERENCES report_document(company_id, document_id),
    FOREIGN KEY (company_id, period_id)   REFERENCES reporting_period(company_id, period_id),
    FOREIGN KEY (company_id, segment_id)  REFERENCES segment(company_id, segment_id),
    FOREIGN KEY (company_id, label_id)    REFERENCES reported_label(company_id, label_id),
    UNIQUE (document_id, period_id, entity_scope, segment_id, label_id)
);

-- --------------------------------------------------- ownership & market data
-- CSE-required share information from interim reports, per share class.
CREATE TABLE security_disclosure (
    disclosure_id    INTEGER PRIMARY KEY,
    document_id      INTEGER NOT NULL REFERENCES report_document(document_id),
    security_id      INTEGER NOT NULL REFERENCES security(security_id),
    as_of_date       TEXT NOT NULL,
    shares_outstanding INTEGER,
    price_high       NUMERIC,
    price_low        NUMERIC,
    price_last       NUMERIC,
    public_holding_pct NUMERIC,
    public_shareholder_count INTEGER,
    float_adjusted_market_cap NUMERIC,
    float_compliance_option TEXT,
    UNIQUE (document_id, security_id, as_of_date)
);

CREATE TABLE shareholder (
    shareholder_id   INTEGER PRIMARY KEY,
    normalized_name  TEXT NOT NULL UNIQUE
        CHECK (normalized_name <> '' AND normalized_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_name NOT LIKE '%  %'),
    display_name     TEXT NOT NULL,
    holder_type      TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (holder_type IN ('INDIVIDUAL','INSTITUTION','UNKNOWN'))
);

CREATE TABLE shareholding (
    document_id      INTEGER NOT NULL REFERENCES report_document(document_id),
    security_id      INTEGER NOT NULL REFERENCES security(security_id),
    as_of_date       TEXT NOT NULL,
    rank_no          INTEGER NOT NULL,             -- ranks can tie, so not part of the key
    shareholder_id   INTEGER NOT NULL REFERENCES shareholder(shareholder_id),
    shares           INTEGER NOT NULL,
    pct              NUMERIC,
    PRIMARY KEY (document_id, security_id, as_of_date, shareholder_id)
);
CREATE INDEX ix_shareholding_holder ON shareholding(shareholder_id);

CREATE TABLE director_holding (
    document_id      INTEGER NOT NULL REFERENCES report_document(document_id),
    security_id      INTEGER NOT NULL REFERENCES security(security_id),
    person_id        INTEGER NOT NULL REFERENCES person(person_id),
    as_of_date       TEXT NOT NULL,
    shares           INTEGER NOT NULL,
    PRIMARY KEY (document_id, security_id, person_id, as_of_date)
);

CREATE TABLE debenture (
    debenture_id     INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    name             TEXT NOT NULL,
    normalized_name  TEXT NOT NULL
        CHECK (normalized_name <> '' AND normalized_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_name NOT LIKE '%  %'),
    coupon_rate      NUMERIC,
    interest_frequency TEXT,
    allotment_date   TEXT,
    maturity_date    TEXT,
    UNIQUE (company_id, normalized_name)
);

CREATE TABLE debenture_disclosure (
    document_id      INTEGER NOT NULL REFERENCES report_document(document_id),
    debenture_id     INTEGER NOT NULL REFERENCES debenture(debenture_id),
    as_of_date       TEXT NOT NULL,
    price_high       NUMERIC,
    price_low        NUMERIC,
    price_last       NUMERIC,
    interest_yield   NUMERIC,
    yield_to_maturity NUMERIC,
    comparable_gov_yield NUMERIC,
    PRIMARY KEY (document_id, debenture_id, as_of_date)
);

-- --------------------------------------------- announcements & corporate actions
-- Every CSE announcement, as published. CSE has two id systems that overlap, so an id
-- only means something together with its format.
CREATE TABLE announcement (
    announcement_pk  INTEGER PRIMARY KEY,
    cse_format       TEXT NOT NULL CHECK (cse_format IN ('NEW','OLD')),
    cse_announcement_id INTEGER NOT NULL,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    category_raw     TEXT NOT NULL,
    normalized_category TEXT NOT NULL
        CHECK (normalized_category NOT GLOB '*[^a-z0-9 ]*' AND normalized_category NOT LIKE '%  %'),
    announced_on     TEXT CHECK (announced_on IS NULL OR date(announced_on) IS announced_on),
    detail_status    TEXT NOT NULL DEFAULT 'NOT_FETCHED'
        CHECK (detail_status IN ('NOT_FETCHED','FETCHED','NO_DETAIL','COMPANY_MISMATCH')),
    cse_detail_type  TEXT,
    remarks          TEXT,
    file_url         TEXT,
    UNIQUE (cse_format, cse_announcement_id)
);
CREATE INDEX ix_announcement_company ON announcement(company_id, announced_on);
CREATE INDEX ix_announcement_category ON announcement(normalized_category);

-- The approved list of what each announcement category means. Exact match only; one
-- category can mean two things, e.g. 'cash and scrip dividend'. Categories not listed here
-- stay as plain announcements.
CREATE TABLE announcement_kind_map (
    normalized_category TEXT NOT NULL
        CHECK (normalized_category NOT GLOB '*[^a-z0-9 ]*' AND normalized_category NOT LIKE '%  %'),
    kind             TEXT NOT NULL CHECK (kind IN (
        'CASH_DIVIDEND','SCRIP_DIVIDEND','SUB_DIVISION','CONSOLIDATION','CAPITALISATION','RIGHTS_ISSUE',
        'REPURCHASE','CAPITAL_REDUCTION','PRIVATE_PLACEMENT','NAME_CHANGE',
        'WATCH_LIST_IN','WATCH_LIST_OUT','SUSPENDED','SUSPENSION_LIFTED','DELISTED','BOARD_TRANSFER')),
    PRIMARY KEY (normalized_category, kind)
);

-- One row per event and share class. Several announcements usually describe one event
-- (initial notice, dates, listing of the new shares); they are linked below.
-- adjustment_factor: multiply a share count from before ex/effective date by this to compare
-- it with later counts, and divide per-share figures by it. NULL when the ratio is unknown.
CREATE TABLE corporate_action (
    action_id        INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL,
    security_id      INTEGER NOT NULL,
    action_type      TEXT NOT NULL CHECK (action_type IN (
        'CASH_DIVIDEND','SCRIP_DIVIDEND','SUB_DIVISION','CONSOLIDATION','CAPITALISATION','RIGHTS_ISSUE',
        'REPURCHASE','CAPITAL_REDUCTION','PRIVATE_PLACEMENT')),
    announced_on     TEXT CHECK (announced_on IS NULL OR date(announced_on) IS announced_on),
    dividend_stage   TEXT CHECK (dividend_stage IN ('INTERIM','FINAL','FIRST_AND_FINAL','OTHER')),
    financial_year   TEXT,
    per_share        NUMERIC,
    ratio_text       TEXT,
    shares_before    INTEGER,
    shares_after     INTEGER,
    shares_issued    INTEGER,
    issue_price      NUMERIC,
    adjustment_factor NUMERIC CHECK (adjustment_factor IS NULL OR adjustment_factor > 0),
    record_date      TEXT CHECK (record_date IS NULL OR date(record_date) IS record_date),
    ex_date          TEXT CHECK (ex_date IS NULL OR date(ex_date) IS ex_date),
    effective_date   TEXT CHECK (effective_date IS NULL OR date(effective_date) IS effective_date),
    payment_date     TEXT CHECK (payment_date IS NULL OR date(payment_date) IS payment_date),
    -- STRUCTURED: CSE fields. BODY_TEXT: parsed from CSE's text. SCAN_REVIEWED: read from a scanned notice.
    -- INFERRED: not stated for this share class, copied from the other class by a tested rule.
    detail_level     TEXT NOT NULL CHECK (detail_level IN ('STRUCTURED','BODY_TEXT','SCAN_REVIEWED','INFERRED','TITLE_ONLY')),
    FOREIGN KEY (company_id, security_id) REFERENCES security(company_id, security_id)
);
-- The same event cannot be recorded twice once its ex-date is known.
CREATE UNIQUE INDEX ux_action_ex_date ON corporate_action(security_id, action_type, ex_date, COALESCE(per_share, -1))
    WHERE ex_date IS NOT NULL;
CREATE INDEX ix_action_security ON corporate_action(security_id, action_type, announced_on);

CREATE TABLE corporate_action_announcement (
    action_id        INTEGER NOT NULL REFERENCES corporate_action(action_id),
    announcement_pk  INTEGER NOT NULL REFERENCES announcement(announcement_pk),
    PRIMARY KEY (action_id, announcement_pk)
);

CREATE TABLE company_name_change (
    name_change_id   INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    old_name         TEXT NOT NULL,
    new_name         TEXT NOT NULL,
    normalized_old_name TEXT NOT NULL
        CHECK (normalized_old_name <> '' AND normalized_old_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_old_name NOT LIKE '%  %'),
    normalized_new_name TEXT NOT NULL
        CHECK (normalized_new_name <> '' AND normalized_new_name NOT GLOB '*[^a-z0-9 ]*' AND normalized_new_name NOT LIKE '%  %'),
    effective_date   TEXT CHECK (effective_date IS NULL OR date(effective_date) IS effective_date),
    source           TEXT NOT NULL DEFAULT 'CSE_STRUCTURED' CHECK (source IN ('CSE_STRUCTURED','SCAN_REVIEWED')),
    announcement_pk  INTEGER NOT NULL REFERENCES announcement(announcement_pk),
    CHECK (normalized_old_name <> normalized_new_name),
    UNIQUE (company_id, normalized_old_name, normalized_new_name)
);

CREATE TABLE listing_event (
    listing_event_id INTEGER PRIMARY KEY,
    company_id       INTEGER NOT NULL REFERENCES company(company_id),
    event_type       TEXT NOT NULL CHECK (event_type IN
        ('WATCH_LIST_IN','WATCH_LIST_OUT','SUSPENDED','SUSPENSION_LIFTED','DELISTED','BOARD_TRANSFER')),
    effective_date   TEXT CHECK (effective_date IS NULL OR date(effective_date) IS effective_date),
    date_basis       TEXT NOT NULL CHECK (date_basis IN ('STATED','ANNOUNCEMENT')),
    reason           TEXT,
    announcement_pk  INTEGER NOT NULL REFERENCES announcement(announcement_pk),
    UNIQUE (company_id, event_type, effective_date)
);

-- ---------------------------------------------------------------- triggers
-- Rules a UNIQUE constraint cannot express because they look through label -> line_item.

-- An alias section of ANY cannot coexist with a specific section for the same words.
CREATE TRIGGER trg_alias_no_overlap BEFORE INSERT ON label_alias
WHEN EXISTS (SELECT 1 FROM label_alias a
             WHERE a.statement_type_id = NEW.statement_type_id
               AND a.normalized_label = NEW.normalized_label
               AND (a.section = 'ANY' OR NEW.section = 'ANY'))
BEGIN SELECT RAISE(ABORT, 'alias overlaps an existing alias for the same words'); END;

-- A label can only map to an item in its own statement.
CREATE TRIGGER trg_label_statement_ins BEFORE INSERT ON reported_label
WHEN NEW.line_item_id IS NOT NULL AND NEW.statement_type_id <>
     (SELECT statement_type_id FROM line_item WHERE line_item_id = NEW.line_item_id)
BEGIN SELECT RAISE(ABORT, 'label and line item belong to different statements'); END;

CREATE TRIGGER trg_label_statement_upd BEFORE UPDATE OF line_item_id, statement_type_id ON reported_label
WHEN NEW.line_item_id IS NOT NULL AND NEW.statement_type_id <>
     (SELECT statement_type_id FROM line_item WHERE line_item_id = NEW.line_item_id)
BEGIN SELECT RAISE(ABORT, 'label and line item belong to different statements'); END;

-- One document cannot give two values for one item, period and scope, even through two labels.
CREATE TRIGGER trg_fact_one_per_item BEFORE INSERT ON financial_fact
WHEN (SELECT line_item_id FROM reported_label WHERE label_id = NEW.label_id) IS NOT NULL
 AND EXISTS (SELECT 1 FROM financial_fact f
             JOIN reported_label r  ON r.label_id = f.label_id
             JOIN reported_label n  ON n.label_id = NEW.label_id
             WHERE f.document_id = NEW.document_id AND f.period_id = NEW.period_id
               AND f.entity_scope = NEW.entity_scope AND r.line_item_id = n.line_item_id)
BEGIN SELECT RAISE(ABORT, 'this document already has a value for this line item, period and scope'); END;

-- Re-mapping a label cannot create that same duplicate after the fact.
CREATE TRIGGER trg_label_remap_no_collision BEFORE UPDATE OF line_item_id ON reported_label
WHEN NEW.line_item_id IS NOT NULL AND EXISTS (
    SELECT 1 FROM financial_fact a
    JOIN financial_fact b ON b.document_id = a.document_id AND b.period_id = a.period_id
                         AND b.entity_scope = a.entity_scope AND b.label_id <> a.label_id
    JOIN reported_label r ON r.label_id = b.label_id
    WHERE a.label_id = NEW.label_id AND r.line_item_id = NEW.line_item_id)
BEGIN SELECT RAISE(ABORT, 're-mapping would give a document two values for one line item'); END;

-- Each fact table only accepts labels from its own statements.
CREATE TRIGGER trg_fact_statement BEFORE INSERT ON financial_fact
WHEN (SELECT s.code FROM reported_label l JOIN statement_type s USING (statement_type_id)
      WHERE l.label_id = NEW.label_id) IN ('SOCE','SEG')
BEGIN SELECT RAISE(ABORT, 'equity and segment figures belong in their own tables'); END;

CREATE TRIGGER trg_equity_statement BEFORE INSERT ON equity_movement_fact
WHEN EXISTS (SELECT 1 FROM reported_label l JOIN statement_type s USING (statement_type_id)
             WHERE l.label_id IN (NEW.movement_label_id, NEW.component_label_id) AND s.code <> 'SOCE')
BEGIN SELECT RAISE(ABORT, 'equity figures need labels from the equity statement'); END;

CREATE TRIGGER trg_segment_statement BEFORE INSERT ON segment_fact
WHEN (SELECT s.code FROM reported_label l JOIN statement_type s USING (statement_type_id)
      WHERE l.label_id = NEW.label_id) <> 'SEG'
BEGIN SELECT RAISE(ABORT, 'segment figures need labels from the segment statement'); END;

-- ------------------------------------------------------------------ views
-- One row per figure with standard names attached. A figure reported in several
-- documents appears once per document.
CREATE VIEW v_fact AS
SELECT f.fact_id, c.ticker, c.name AS company, f.entity_scope,
       p.period_kind, p.start_date, p.end_date, p.months,
       st.code AS statement, rl.section, rl.raw_label, rl.normalized_label,
       li.code AS line_item_code, li.name AS line_item,
       f.value, f.value * rl.sign_factor AS standard_value, f.currency, f.audit_status, f.is_restated,
       d.document_id, d.title AS document, d.uploaded_at, f.page_no
FROM financial_fact f
JOIN company c            ON c.company_id = f.company_id
JOIN reporting_period p   ON p.period_id = f.period_id
JOIN reported_label rl    ON rl.label_id = f.label_id
JOIN statement_type st    ON st.statement_type_id = rl.statement_type_id
JOIN report_document d    ON d.document_id = f.document_id
LEFT JOIN line_item li    ON li.line_item_id = rl.line_item_id;

-- For each figure, only the value from the most recently uploaded document, so restated
-- comparatives replace the originals. Mapped figures are matched on the standard item, so a
-- label reworded between reports still counts as the same figure.
CREATE VIEW v_fact_latest AS
SELECT * FROM (
    SELECT v.*, ROW_NUMBER() OVER (
        PARTITION BY ticker, entity_scope, period_kind, start_date, end_date, statement,
                     COALESCE(line_item_code, section || '|' || normalized_label)
        ORDER BY uploaded_at DESC, document_id DESC) AS rn
    FROM v_fact v
) WHERE rn = 1;

-- Announcements that look like an action or status change but have no approved meaning yet.
-- The keyword search only builds this list; it never decides what a category means.
CREATE VIEW v_unclassified_action_announcements AS
SELECT a.normalized_category, COUNT(*) AS announcements, MIN(a.announced_on) AS first_seen, MAX(a.announced_on) AS last_seen
FROM announcement a
WHERE NOT EXISTS (SELECT 1 FROM announcement_kind_map m WHERE m.normalized_category = a.normalized_category)
  AND (a.normalized_category LIKE '%dividend%' OR a.normalized_category LIKE '%sub division%'
    OR a.normalized_category LIKE '%subdivision%' OR a.normalized_category LIKE '%split%'
    OR a.normalized_category LIKE '%consolidation%' OR a.normalized_category LIKE '%capitali%'
    OR a.normalized_category LIKE '%rights%' OR a.normalized_category LIKE '%repurchase%'
    OR a.normalized_category LIKE '%reduction of%' OR a.normalized_category LIKE '%private placement%'
    OR a.normalized_category LIKE '%name%' OR a.normalized_category LIKE '%watch%'
    OR a.normalized_category LIKE '%suspen%' OR a.normalized_category LIKE '%delist%'
    OR a.normalized_category LIKE '%de list%')
GROUP BY 1 ORDER BY announcements DESC;

-- Current status of every company, with the last sign of activity for those without a delisting date.
CREATE VIEW v_company_listing AS
SELECT c.ticker, c.name, c.listing_status, c.trading_status, c.board_type,
       (SELECT MAX(e.effective_date) FROM listing_event e WHERE e.company_id = c.company_id AND e.event_type = 'DELISTED') AS delisted_on,
       c.listing_status = 'LISTED' AND COALESCE((SELECT e.event_type FROM listing_event e WHERE e.company_id = c.company_id
         AND e.event_type LIKE 'WATCH%' ORDER BY e.effective_date DESC LIMIT 1) = 'WATCH_LIST_IN', 0) AS on_watch_list,
       (SELECT MAX(a.announced_on) FROM announcement a WHERE a.company_id = c.company_id) AS last_announcement,
       (SELECT MAX(d.period_end_date) FROM report_document d WHERE d.company_id = c.company_id) AS last_report_period
FROM company c;

-- Same amount within 60 days but a different ex-date. Usually two real dividends, sometimes a
-- re-announcement. Shown for review because merging them automatically could lose a real payment.
CREATE VIEW v_possible_duplicate_actions AS
SELECT c.ticker, a.action_type, a.per_share, a.announced_on AS first_announced, a.ex_date AS first_ex_date,
       b.announced_on AS second_announced, b.ex_date AS second_ex_date
FROM corporate_action a
JOIN corporate_action b ON a.security_id = b.security_id AND a.action_type = b.action_type AND a.action_id < b.action_id
     AND a.per_share = b.per_share AND ABS(julianday(a.announced_on) - julianday(b.announced_on)) < 60
JOIN company c ON c.company_id = a.company_id;

-- Scanned 2012-2019 notices whose values have not been read: split ratios and names.
CREATE VIEW v_actions_missing_values AS
SELECT c.ticker, ca.action_type, ca.announced_on, an.category_raw, an.file_url
FROM corporate_action ca
JOIN company c USING (company_id)
JOIN corporate_action_announcement l USING (action_id)
JOIN announcement an USING (announcement_pk)
WHERE ca.action_type IN ('SUB_DIVISION','CONSOLIDATION','CAPITALISATION','SCRIP_DIVIDEND') AND ca.adjustment_factor IS NULL
UNION ALL
SELECT c.ticker, 'NAME_CHANGE', an.announced_on, an.category_raw, an.file_url
FROM announcement an
JOIN company c USING (company_id)
JOIN announcement_kind_map m ON m.normalized_category = an.normalized_category AND m.kind = 'NAME_CHANGE'
WHERE NOT EXISTS (SELECT 1 FROM company_name_change n WHERE n.announcement_pk = an.announcement_pk);

-- One figure reported differently by two reports. Small differences are usually audit adjustments to provisional
-- figures; large ones can be a misread period, scope or unit and need review.
CREATE VIEW v_fact_disagreements AS
SELECT ticker, entity_scope, period_kind, start_date, end_date, line_item_code,
       COUNT(DISTINCT document_id) AS documents, MIN(value) AS low, MAX(value) AS high,
       CASE WHEN MIN(ABS(value)) > 0 THEN MAX(ABS(value)) / MIN(ABS(value)) END AS ratio
FROM v_fact WHERE line_item_code IS NOT NULL
GROUP BY ticker, entity_scope, period_kind, start_date, end_date, line_item_code
HAVING COUNT(DISTINCT ROUND(value)) > 1;

-- The review queue: labels waiting for a decision. Add an alias to approve one.
CREATE VIEW v_unmapped_labels AS
SELECT rl.normalized_label, st.code AS statement, rl.section,
       COUNT(DISTINCT rl.company_id) AS companies, COUNT(f.fact_id) AS figures,
       MIN(rl.raw_label) AS example
FROM reported_label rl
JOIN statement_type st USING (statement_type_id)
LEFT JOIN financial_fact f ON f.label_id = rl.label_id
WHERE rl.line_item_id IS NULL
GROUP BY 1, 2, 3
ORDER BY companies DESC, figures DESC;

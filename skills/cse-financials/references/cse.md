# CSE reference

## Contents
1. API
2. Report documents
3. Companies and securities
4. Reading CSE statements
5. Things that cost time

## 1. API

- POST, form-encoded, to `https://www.cse.lk/api/<endpoint>`, with headers `Origin: https://www.cse.lk` and a generic
  `User-Agent` (never personal details). Most endpoints take `symbol` (e.g. `JKH.N0000`).
- Per symbol: `financials` (report lists: `infoQuarterlyData`, `infoAnnualData`, `infoOtherData`, each with
  `fileText` title and `path`), `companyProfile`, `companyInfoSummery` (sic), `getAnnouncementByCompany`.
- Lists: `allSectors`, `listBySector` (`sectorId`; official sector membership - overrides the free-text profile
  sector), `tradeSummary`, `approvedAnnouncement`, boards `main_boards`, `secondBoard`, `default_board`,
  `empower_boards`, `divi_siri_board`.
- GET: `deListedEntities`, `allSecurityCode`, `cntSecurity`.
- Unlisted endpoints: search the site's JavaScript for `apiService.post(`.
- Announcements have two overlapping id systems. New: `getAnnouncementById` (`announcementId`), then
  `getGeneralAnnouncementById`. Old: `announcementById` (`id`). The wrong endpoint silently returns another
  company's record - always check the company in the response.
- `load_master.py` caches every response as `raw_api/<endpoint>_<SYMBOL>.json`; delete a file to refetch it.

## 2. Report documents

- PDF URL: `https://cdn.cse.lk/` + `path`; a path without the `cmt/` prefix needs it added, otherwise 403.
- `manualDate` is unreliable (filing dates, 1970, typos): period ends come from titles (`load_master.py`
  `period_end_from_title`, `annual_end_from_title` with the company's fiscal month). About 4% of interim titles give
  no date; those are downloaded when uploaded inside the run's window (`--undated-since`).
- `document_id` is the CSE report id; category ANNUAL / INTERIM / OTHER from the list it came from.
- Identical PDFs filed twice: the downloader keeps the first and marks the other SKIPPED (sha256 per company).

## 3. Companies and securities

- Voting (`.N0000`) and non-voting (`.X0000`) classes share one `securityId` and the same reports: reports belong to
  the company, not the security.
- CSE sometimes gives one legal entity a new id (e.g. debentures first, shares later): successions are listed in
  `reviewed/scan_readings.py` (`SUCCESSOR`), as are reporting-template overrides (bank / finance / insurance /
  fund / general).
- Director ids are per directorship, not per person: people are keyed on the exact normalised name.
- Old (2012-2019) name changes and many split ratios exist only in scanned PDFs: OCR to find the passage, then read
  the cropped image; reviewed values go in `reviewed/scan_readings.py`.

## 4. Reading CSE statements

- Units: "Rs.'000" = 1000; "Rs. Mn", "Rs. Mns", "LKR Mn" = 1,000,000; a bare "Rs." header = full rupees; "Rs. Bn"
  = 1,000,000,000. A page note ("all amounts in Sri Lanka Rupees thousands") applies to every table on the page.
- Currency LKR. USD functional-currency reporters (e.g. MGT): currency USD, values as printed.
- Banks: columns "Bank" and "Group" -> COMPANY and GROUP. Expenses often printed unsigned under "Less:"; "Debt
  capital" / "Perpetual bonds" sit between liabilities and equity and count as liabilities.
- Finance and leasing companies: VAT on financial services sits between operating profit and income tax; some
  print only "Profit before income tax and VAT on financial services" (the checker uses it when no other PBT exists).
- Insurers: life fund / policyholder fund balance sheets beside the company's: transcribe the company's.
- Unit trusts and funds (e.g. CAL funds): "net assets attributable to unitholders" stands where equity is.
- 25th-of-month closers (Union Chemicals): BS at the printed date, IS durations at month end.
- Interims: the prior year-end column is AUDITED only if the header says so.

## 5. Things that cost time

- pdfplumber splits some CSE tables into single characters (ABAN); pymupdf/pypdf read them.
- Many older filings are scans with a junk OCR text layer, not flagged as scanned: they need an OCR or vision pass.
- Errata filings usually carry one corrected statement (no BS): record "errata, no balance sheet" rather than
  searching. Twenty-largest-shareholder lists and notices of meeting are filed under ANNUAL.
- Keep download concurrency modest; failed fetches are listed in `<out_dir>/download_report.json` - rerun the
  same command to retry them (finished files are skipped).

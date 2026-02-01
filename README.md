# FCC IPES Market Intelligence Pipeline

Extract, structure, and AI-enrich FCC IPES (Interconnected VoIP Provider) numbering authorization applications into actionable market intelligence.

**Output:** 200 IPES companies with enriched profiles including activity status, industry segment, and market position.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run pipeline (phases execute sequentially)
python -m src.extract      # 1. Fetch from FCC API
python -m src.filter       # 2. Filter to IPES applications
python -m src.structure    # 3. Dedupe into companies
python -m src.download_docs # 4. Download documents
python -m src.extract_text # 5. Extract text from PDFs
python -m src.enrich       # 6. AI enrichment
```

---

## How It Works

### Phase 1: Extraction

**Problem:** The FCC ECFS API doesn't have a clean "IPES applications" filter. Different applications use different description formats.

**Solution:** Two-query union strategy:
1. `"Numbering Authorization Application"` → 959 filings (standard format)
2. `52.15(g)` → 2,347 filings (catches edge cases)

Deduplicated by `id_submission` → **2,364 unique filings**

**Why two queries?** Testing showed no single query catches everything:
- Query 1 catches standard applications + INBOX-52.15 staging filings
- Query 2 catches rare formats (HDC Alpha/Beta/etc., Stratus Networks)

### Phase 2: Filtering

**Problem:** The 2,364 filings include noise (COVID Telehealth, copper retirement notices, Section 214 transfers).

**Solution:** Keep filings matching ANY of:
- Proceedings description contains `"interconnected voip numbering"` OR `"voip numbering authorization application"` OR `"authorization to obtain numbering resources"`
- Document filename contains `"voip numbering"`

**Result:** 896 IPES-related filings (240 APPLICATIONs + supplements/notices)

### Phase 3: Structuring

**Problem:** Same company files multiple times (initial app, supplements, amendments). Data is filing-centric but the question is company-centric.

**Solution:**
1. Extract company name from proceedings description using regex (`Filed By (.+?) Pursuant`)
2. Normalize names (lowercase, strip suffixes like LLC/Inc/Corp)
3. Group filings by normalized name
4. Keep original variations as `name_variations[]`

**Result:** 200 unique IPES companies

**Edge case:** 34 records had person names (attorneys/officers) instead of company names. The actual company name often appears in `proceeding_types`. Fixed via post-processing regex extraction.

### Phase 4: Document Downloads

**Problem:** FCC document server is finicky. Standard HTTP/2 requests fail.

**Solution:** Specific request settings discovered through testing:
- Force HTTP/1.1
- TLS 1.2
- User-Agent: `PostmanRuntime/7.47.1`
- Cookie: `lmao=1`

**Result:** 512 documents downloaded (492 PDF, 18 DOCX, 2 DOC), 620 MB total

### Phase 5: AI Enrichment

**Strategy:** Maximize free data before expensive API calls.

| Step | Action | API Calls | Coverage |
|------|--------|-----------|----------|
| 1 | Parse FCC docs (regex) | 0 | 188 companies with address/phone/personnel |
| 2 | Compute filing signals | 0 | 200 companies |
| 3 | Web search (DuckDuckGo) | 200 | Background info for all |
| 4 | LLM synthesis (Claude) | 200 | Final enrichment |

**Why this order?** FCC applications contain structured sections (address, key personnel, founding dates). Parsing these first provides better LLM context than web search alone. Web search works well for famous companies (8x8, Vonage) but returns nothing for obscure ones.

### Post-Enrichment Improvements

Three additional data quality passes (no LLM calls):

1. **Fix person names** → 15 company names extracted from `proceeding_types` where filer was an attorney
2. **Clean key personnel** → Filtered noise entries (734 → 109 valid names)
3. **Infer market position** → Rules-based inference reduced "Unknown" from 50% → 29%

---

## Schema Design

### Company Record (Primary Output)

| Field | Type | Why |
|-------|------|-----|
| `company_name` | string | Primary identifier |
| `company_name_normalized` | string | For deduplication |
| `docket_numbers` | string[] | Links to FCC proceedings |
| `first_filing_date` | date | Market entry timing |
| `documents[]` | object[] | Download URLs for PDFs |
| `filings[]` | object[] | All related submissions |

### Enrichment Fields (Required by Assignment)

| Field | Type | Notes |
|-------|------|-------|
| `is_active` | bool | LLM-determined from evidence |
| `activity_signal` | string | Must cite sources |
| `industry_segment` | string | UCaaS/CCaaS/CPaaS/Carrier/etc. |
| `product_summary` | string | 1-2 sentences |
| `market_position` | string | Enterprise/Mid-Market/SMB/Startup/Unknown |

### Data Quality Fields

| Field | Type | Why |
|-------|------|-----|
| `enrichment_confidence` | High/Med/Low | Transparency on evidence quality |
| `market_position_source` | llm/rules/undetermined | Provenance tracking |
| `filing_signals` | object | Activity indicators (filing count, recency) |
| `parsed_*` | various | Contact data extracted from FCC docs |

**Schema philosophy:** Every field serves a purpose. `enrichment_confidence` distinguishes well-known companies (8x8, Bandwidth) from obscure ones. `market_position_source` documents whether the value came from LLM analysis, rules inference, or couldn't be determined.

---

## Assumptions

1. **Coverage window:** ~2016/17 to present. Section 52.15(g) was introduced then; earlier filings use different formats.
2. **Company = applicant:** If multiple entities file under one docket, they're treated as one company.
3. **Active = operating:** Companies with recent filings or web presence are "active"; those with only old filings and no web trace are "inactive."
4. **Person filers:** When an individual files an application, the actual company usually appears in `proceeding_types`. If not, marked as `filer_type: "individual"`.

---

## Verification

### Extraction Accuracy

- **Two-query union:** Tested individually, found gaps in each, combined catches all
- **Filter precision:** Manually reviewed ~50 rejected filings — confirmed noise (COVID programs, Section 214 transfers)
- **240 APPLICATION filings** matches expected range from FCC docket counts

### Enrichment Accuracy

**Spot checks on known companies:**

| Company | is_active | industry_segment | market_position | Verified? |
|---------|-----------|------------------|-----------------|-----------|
| 8x8, Inc. | true | UCaaS | SMB | Correct |
| Bandwidth, Inc. | true | CPaaS | Enterprise | Correct |
| Twilio International | true | CPaaS | Enterprise | Correct |
| Vonage Holdings | false | UCaaS | Enterprise | Correct (acquired by Ericsson 2022) |

**Confidence distribution:**
- High: 54 companies (multiple confirming signals)
- Medium: 87 companies (some signals, incomplete)
- Low: 59 companies (FCC data only)

### Document Parsing

- 507/512 documents matched (99%)
- 5 unmatched due to filename encoding edge cases
- All 200 companies have at least one document from related filings

---

## Output Files

```
data/
├── raw/
│   ├── filings_raw.jsonl          # 2,364 raw API responses
│   └── extraction_meta.json       # Query stats
├── processed/
│   ├── filings_filtered.jsonl     # 896 IPES filings
│   ├── companies.json             # 200 deduped companies (pre-enrichment)
│   ├── companies_enriched.json    # Final enriched output
│   ├── companies_enriched.csv     # Flat CSV export
│   └── enrichment_logs/           # 400 prompt/response pairs

documents/
├── original/                      # 512 downloaded files (620 MB)
└── text/                          # Extracted text from PDFs
```

---

## Development Process

1. **Planning:** Iterated on PRD with ChatGPT to identify edge cases and API quirks
2. **Execution:** Used Cursor plan mode to implement phase-by-phase
3. **Testing:** Small samples first (10 companies), validated outputs, then scaled
4. **Refinement:** Created post-processing scripts after reviewing initial enrichment quality

Each phase produces a shippable artifact. If time ran out, earlier phases would still be complete.

---

## Limitations

- No coverage before ~2016 (different filing format)
- Contact data coverage: 68% have addresses, 60% have phones, 42% have emails
- Market position undetermined for 29% of companies (obscure entities with minimal web presence)
- Some companies may have rebranded/merged since their FCC filing

---

## Tools Used

- **API:** FCC ECFS Public API (`publicapi.fcc.gov/ecfs/filings`)
- **Web Search:** DuckDuckGo via `ddgs` package (no API key needed)
- **LLM:** Claude Sonnet via Anthropic API
- **PDF Text:** PyMuPDF (`fitz`)
- **HTTP:** `httpx` with HTTP/1.1 forced

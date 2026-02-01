# FCC IPES Market Intelligence Pipeline

Extract, structure, and AI-enrich FCC IPES (Interconnected VoIP Provider) numbering authorization applications into actionable market intelligence.

**Output:** 200 IPES companies with enriched profiles including activity status, industry segment, and market position.

---

## Overview

This pipeline transforms raw FCC filings into a structured company database in 6 steps:

```
FCC API → 2,364 filings → Filter to 896 IPES → Dedupe to 200 companies → Download 512 docs → AI enrich
```

**The core challenge:** The FCC doesn't have a clean "IPES companies" dataset. Applications are scattered across thousands of filings with inconsistent formats, duplicate submissions, and noise from unrelated proceedings.

**The solution:** A multi-phase pipeline that progressively filters, structures, and enriches the data:

1. **Extract** — Query FCC API with two search strategies to catch all IPES filings
2. **Filter** — Remove noise (COVID programs, Section 214 transfers) using keyword matching
3. **Structure** — Group filings by company, deduplicate by normalized name
4. **Download** — Fetch 512 PDF/DOCX application documents from FCC servers
5. **Parse** — Extract contact info, personnel, and dates from document text (free data)
6. **Enrich** — Web search + LLM synthesis to determine activity status, industry, and market position

**Key insight:** FCC applications themselves contain valuable structured data (addresses, key personnel, founding dates). Parsing these *before* calling the LLM provides better context and reduces reliance on web search, which fails for obscure companies.

---

## Quick Start

```bash
pip install -r requirements.txt

python -m src.extract       # 1. Fetch from FCC API
python -m src.filter        # 2. Filter to IPES applications
python -m src.structure     # 3. Dedupe into companies
python -m src.download_docs # 4. Download documents
python -m src.extract_text  # 5. Extract text from PDFs
python -m src.enrich        # 6. AI enrichment
```

---

## How It Works

### Phase 1: Extraction

**Problem:** No single FCC API query catches all IPES applications — different filings use different description formats.

**Solution:** Union of two queries, deduplicated by `id_submission`:
- `"Numbering Authorization Application"` → 959 filings (standard format)
- `52.15(g)` → 2,347 filings (catches edge cases like HDC, Stratus)

**Result:** 2,364 unique filings

### Phase 2: Filtering

**Problem:** Raw filings include noise (COVID Telehealth, copper retirement, Section 214 transfers).

**Solution:** Keep filings where description OR document filename contains IPES-related keywords (`"interconnected voip numbering"`, `"voip numbering authorization"`, etc.)

**Result:** 896 IPES filings (240 APPLICATIONs + supplements)

### Phase 3: Structuring

**Problem:** Same company files multiple times (initial app, supplements, amendments).

**Solution:** Extract company name via regex (`Filed By (.+?) Pursuant`), normalize (lowercase, strip LLC/Inc), group by normalized name.

**Result:** 200 unique companies

### Phase 4: Document Downloads

**Problem:** FCC document server rejects standard HTTP requests.

**Solution:** Force HTTP/1.1, TLS 1.2, specific User-Agent (`PostmanRuntime/7.47.1`).

**Result:** 512 documents (492 PDF, 18 DOCX, 2 DOC), 620 MB

### Phase 5: AI Enrichment

**Strategy:** Maximize free data extraction before expensive API calls.

| Step | Action | API Calls | Coverage |
|------|--------|-----------|----------|
| 1 | Parse FCC docs (regex) | 0 | 188 companies with address/phone/personnel |
| 2 | Compute filing signals | 0 | 200 companies |
| 3 | Web search (DuckDuckGo) | 200 | Background info |
| 4 | LLM synthesis (Claude) | 200 | Final enrichment |

### Post-Enrichment Cleanup

Three additional passes (no LLM calls):
1. **Fix person names** — Extract real company names from `proceeding_types` for 15 attorney-filed records
2. **Clean key personnel** — Filter noise entries (734 → 109 valid names)
3. **Infer market position** — Rules-based inference reduced "Unknown" from 50% → 29%

---

## Schema

### Core Fields
| Field | Description |
|-------|-------------|
| `company_name` | Primary identifier |
| `docket_numbers[]` | FCC proceeding references |
| `first_filing_date` | Market entry timing |
| `documents[]` | Downloaded application files |

### Enrichment Fields (Assignment Required)
| Field | Description |
|-------|-------------|
| `is_active` | Boolean — still operating? |
| `activity_signal` | Evidence supporting determination |
| `industry_segment` | UCaaS / CCaaS / CPaaS / Carrier / etc. |
| `product_summary` | 1-2 sentence description |
| `market_position` | Enterprise / Mid-Market / SMB / Startup / Unknown |

### Quality Tracking
| Field | Description |
|-------|-------------|
| `enrichment_confidence` | High / Medium / Low |
| `market_position_source` | `llm` / `rules` / `undetermined` |
| `parsed_*` | Contact data extracted from FCC docs |

---

## Assumptions

1. **Coverage:** ~2016/17 to present (Section 52.15(g) was introduced then)
2. **Company = applicant:** Multiple entities under one docket treated as one company
3. **Active = operating:** Recent filings or web presence → active; only old filings + no web trace → inactive
4. **Person filers:** When an individual files, the company usually appears in `proceeding_types`

---

## Verification

### Extraction
- Two-query union tested individually — each missed filings the other caught
- Manually reviewed ~50 rejected filings — confirmed noise
- 240 APPLICATIONs matches expected range from FCC docket counts

### Enrichment Spot Checks
| Company | is_active | industry_segment | market_position | Correct? |
|---------|-----------|------------------|-----------------|----------|
| 8x8, Inc. | true | UCaaS | SMB | Yes |
| Bandwidth, Inc. | true | CPaaS | Enterprise | Yes |
| Twilio International | true | CPaaS | Enterprise | Yes |
| Vonage Holdings | false | UCaaS | Enterprise | Yes (acquired 2022) |

### Confidence Distribution
- High: 54 companies (multiple confirming signals)
- Medium: 87 companies (some signals)
- Low: 59 companies (FCC data only)

---

## Output Files

```
data/
├── raw/
│   ├── filings_raw.jsonl          # 2,364 raw API responses
│   └── extraction_meta.json       # Query stats
├── processed/
│   ├── filings_filtered.jsonl     # 896 IPES filings
│   ├── companies.json             # 200 companies (pre-enrichment)
│   ├── companies_enriched.json    # Final enriched output
│   └── companies_enriched.csv     # Flat CSV export

documents/
├── original/                      # 512 downloaded files (620 MB)
└── text/                          # Extracted text from PDFs

PRD.md                             # Implementation plan (Claude Code)
PROCESS_LOG.md                     # Decision reasoning log
ENRICHMENT_IMPROVEMENT.md          # Post-enrichment fix plan
```

---

## Development Process

1. **Planning** — Created PRD using Claude Code plan mode
2. **Execution** — Implemented phase-by-phase, iterating on the plan between phases to test effectiveness
3. **Testing** — Small samples first (10 companies), validated outputs, then scaled
4. **Refinement** — Analyzed enrichment results, created improvement plan, applied post-processing fixes

Each phase produces a standalone artifact — if time ran out, earlier phases would still be complete.

### Documentation

| File | Purpose |
|------|---------|
| [PRD.md](./PRD.md) | Implementation plan created with Claude Code plan mode. Executed phase-by-phase with iteration between phases to validate approach. |
| [PROCESS_LOG.md](./PROCESS_LOG.md) | Decision log tracking the reasoning behind each design choice — why two queries, why this filter, why this schema, etc. |
| [ENRICHMENT_IMPROVEMENT.md](./ENRICHMENT_IMPROVEMENT.md) | Follow-up plan created with Claude Code to fix data quality issues discovered after initial enrichment. |

---

## Limitations

- No coverage before ~2016 (different filing format)
- Contact data: 68% addresses, 60% phones, 42% emails
- Market position undetermined for 29% of companies (obscure entities)
- Some companies may have rebranded/merged since filing

---

## Tools

- **API:** FCC ECFS Public API
- **Web Search:** DuckDuckGo (`ddgs` package)
- **LLM:** Claude Sonnet (Anthropic API)
- **PDF:** PyMuPDF (`fitz`)
- **HTTP:** `httpx` with HTTP/1.1

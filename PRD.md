## PRD: FCC ECFS IPES Market Intelligence Pipeline

**Project:** Sent Growth Engineer Take-Home Assessment
**Owner:** Julian
**Constraint:** ≤ 4 hours total (ship something complete + explainable)
**Goal:** Produce a near-complete census of IPES (Interconnected VoIP Provider) numbering authorization applications under **47 CFR §52.15(g)**, structure into clean company records, and enrich each company with LLM-powered market intel. 

---

# 1) Problem & Why It Matters

The FCC ECFS database contains filings for IPES numbering authorization applications. This is effectively a high-signal list of legitimate CPaaS / VoIP ecosystem players (competitors/partners). Your job is to extract, structure, and enrich this dataset into something Sent can act on. 

---

# 2) Success Criteria

### Extraction Success

* Capture **all filings that are IPES numbering authorization applications** under §52.15(g) (near-complete since ~2016/17). 
* For each relevant filing, capture:

  * company/applicant name
  * docket number
  * filing date
  * submission type (“APPLICATION”, “SUPPLEMENT”, etc.)
  * document URL(s) + filename(s)
  * any available filer/contact/attorney info
  * any metadata in the API response 
* Produce a folder of downloaded filing submissions (PDF/Word, or converted to markdown). 

### Structuring Success

* Deduplicate into **one primary record per company**
* Link related filings (supplements, public notices, etc.)
* Export as JSON and/or CSV 

### Enrichment Success

For each company record:

* `is_active` (boolean)
* `activity_signal` (evidence)
* `industry_segment`
* `product_summary`
* `market_position` 

### Deliverables Success

Ship:

1. Code repo / process explainer
2. Raw dataset (pre-enrichment)
3. Documents folder (downloads)
4. Enriched dataset 

---

# 3) Key Design Decisions

## 3.1 Data source: ECFS Public API (no UI scraping)

**Decision:** Use `https://publicapi.fcc.gov/ecfs/filings` as the primary retrieval mechanism.
**Why:** Fast, structured JSON, deterministic pagination.
**Implementation reality (from your sample):**

* Response key is **`"filing"`** (list) plus `"aggregations"`.
* Each filing includes:

  * `id_submission`
  * `submissiontype.description`
  * `proceedings[]` (contains docket name & bureau code, plus a description that includes the applicant)
  * `documents[]` with `src` URLs and `filename`
    This matches your live response and is the source of truth.

## 3.2 “Company name” extraction

**Decision:** Extract canonical applicant/company primarily from `proceedings[].description` (e.g., “...Filed By ULEC, LLC...”), not `filers[]`.
**Why:** `filers[]` can be a person/attorney; proceedings description reliably contains the applicant in these cases.

## 3.3 What counts as an “application”

**Decision:** Define the “application record” per `(docket, company)` as the earliest filing where `submissiontype.description == "APPLICATION"`.
**Why:** Matches the assignment’s “applications” focus, while still preserving related filings for context/status. 

## 3.4 Application status

**Decision:** Compute an interpretable `application_status` using docket-level signals:

* If later filings in same docket include “Granted / Denied / Dismissed / Withdrawn” in proceeding descriptions or document filenames/text, reflect that.
* Else “Pending/Unknown”.
  **Why:** ECFS metadata alone may not reflect “final” status; using docket timeline is more accurate and explainable.

## 3.5 Document downloads

**Decision:** Download **all primary submission documents** for each relevant filing.
**Critical implementation detail:** The `documents[].src` field is a *viewer* URL (e.g., `/ecfs/document/{id}/{seq}`), NOT the download URL.
- **Download URL pattern:** `https://www.fcc.gov/ecfs/documents/{id_submission}/{seq}` (note: plural "documents")
- Extract `id_submission` from the filing and `seq` from the document index (1-based)
**Required request settings:**
- Force HTTP/1.1 (`--http1.1` or `http2=False`)
- TLS 1.2 (`--tlsv1.2`)
- User-Agent header (e.g., `PostmanRuntime/7.47.1`)
- Accept: `*/*`
- Follow redirects
**Risk/mitigation:** FCC endpoint is flaky with HTTP/2; the above settings resolve this. Add retry with exponential backoff.

ex (download might only work with these exact headers). curl -L --tlsv1.2 --http1.1 \
  -A 'PostmanRuntime/7.47.1' \
  -H 'Accept: */*' \                                    
  -H 'Connection: keep-alive' \
  -H 'Cookie: lmao=1' \
  --compressed \
  -o /tmp/fcc.pdf \
  -v \
  'https://www.fcc.gov/ecfs/documents/1012774818450/1'

## 3.6 Enrichment methodology: evidence-pack + LLM structured output

**Decision:** Use an LLM to fill enrichment fields **based on an evidence pack** containing:

* FCC signals (docket description, dates, doc filenames, optionally extracted PDF text)
* optional lightweight web snippets (homepage + LinkedIn/press snippets) if time permits
  **Why:** Keeps hallucinations down; makes `activity_signal` defensible.

## 3.7 LLM Access

**Decision:** Use Vercel AI Gateway as the simplest path to model calls (provided key). 
**Security:** Never commit keys. Use env vars.

---

# 4) Data Model

You’ll maintain two primary datasets: **filings** (raw) and **companies** (deduped).

## 4.1 Raw Filing (normalized from API)

Fields (minimum viable):

* `id_submission` (string)
* `date_received` (ISO datetime)
* `date_disseminated` (ISO datetime, if exists)
* `submission_type` (from `submissiontype.description`)
* `docket` (constructed as `"{bureau_code} {name}"` from proceedings)
* `proceedings_description` (string)
* `company_extracted` (string; from proceedings desc parsing)
* `filers` (raw list)
* `documents` (list of `{filename, src}`)
* `viewingstatus` / `filingstatus` (optional)
* `raw` (optional: raw JSON blob for audit/debug)

## 4.2 Company (deduped primary entity)

* `company_id` (normalized hash)
* `name` (canonical)
* `aliases[]`
* `dockets[]`
* `first_filing_date`
* `latest_filing_date`
* `application_filings[]` (subset where submission_type == “APPLICATION”)
* `related_filings[]` (supplements, notices, etc.)
* `primary_document_urls[]` (from application filing docs)
* `contact_names[]` (from filers/authors when present)
* `application_status` (computed)

## 4.3 Enriched fields (extend Company)

* `is_active` (bool | null if unknown)
* `activity_signal` (string, must cite evidence)
* `industry_segment` (enum-ish string)
* `product_summary` (1–2 sentences)
* `market_position` (Enterprise/Mid-Market/SMB/Startup/Unknown)
* `enrichment_confidence` (High/Med/Low)
* `enrichment_sources[]` (URLs or identifiers used)

---

# 5) Pipeline Phases You Can Complete Incrementally

This is designed so each phase produces a shippable artifact. If you run out of time, you still have a coherent submission.

---

## Phase 0 — Repo skeleton + config (10–15 min)

**Outputs:**

* `README.md` with approach + how to run
* `.env.example`
* folder structure

**Folder structure**

```
fcc-ipes/
  src/
    extract.py
    filter.py
    structure.py
    download_docs.py
    enrich.py
    schemas.py
    utils.py
  data/
    raw/
    processed/
  documents/
    original/
    text/
  README.md
  requirements.txt
```

**Config via env vars**

* `FCC_API_KEY` (optional but recommended for higher rate limits)
* `AI_GATEWAY_API_KEY` — provided key in .env (not used)
* `MODEL` (default: `gpt-4o-mini` or `claude-3-haiku` for speed/cost balance; ANTHROPIC_API_KEY in .env)

**Vercel AI Gateway usage:**
- Base URL: `https://api.vercel.ai/v1`
- Auth header: `Authorization: Bearer {VERCEL_AI_GATEWAY_API_KEY}`
- Compatible with OpenAI SDK format
- Docs: https://vercel.com/docs/ai-gateway

---

## Phase 1 — Extraction from ECFS API (45–60 min)

**Goal:** Produce `data/raw/filings_raw.jsonl` with near-complete recall.

**Implementation details**

* **Two-query union** (ensures complete coverage of all IPES applications):
  ```
  Query 1: q="Numbering Authorization Application"  (~959 filings)
  Query 2: q=52.15(g)                               (~2347 filings)
  ```
  * Deduplicate by `id_submission` after fetching both
  * Query 1 captures standard IPES format + INBOX-52.15 staging docket
  * Query 2 captures edge cases with different proceeding description formats

* **API key:** Pass as header `X-Api-Key: {FCC_API_KEY}` (required)

* **Pagination:**
  * use `limit=25` (safe default) + `offset`
  * stop when `filing[]` is empty or offset exceeds total

* Save raw responses for traceability.

**Why two queries are needed:**
Some IPES applications have non-standard proceeding descriptions:
1. `"Interconnected VoIP Numbering Authorization Application Filed By {COMPANY}..."` — standard (Query 1)
2. `"VoIP Numbering Authorization Application (Fee Required)"` — INBOX-52.15 staging (Query 1)
3. `"In the Matter of {COMPANY}"` — HDC Alpha/Beta/etc. (Query 2 only)
4. `"In the Matter of {COMPANY} For Authorization to Obtain Numbering Resources..."` — Stratus, Assurance (Query 2 only)

**Outputs**

* `data/raw/filings_raw.jsonl` (one API filing object per line, deduplicated)
* `data/raw/extraction_meta.json` (queries used, timestamp, total count)

---

## Phase 2 — Filtering to IPES applications (30–45 min)

**Goal:** Drop noise and keep IPES-relevant filings only.

**Why filtering is needed:**
The API `q=` parameter matches terms anywhere in a filing (document text, comments, metadata). While the "Numbering Authorization Application" query is precise, client-side filtering ensures we keep only true IPES filings.

**Filtering rule (single source of truth):**
Keep a filing if it matches ANY of these conditions (all case-insensitive):

**Condition A - Proceedings description contains:**
```
"interconnected voip numbering"
```
OR
```
"voip numbering authorization application"
```
OR
```
"authorization to obtain numbering resources"
```

**Condition B - Document filename contains:**
```
"voip numbering"
```

**Note:** Case-insensitivity is required because some filings have uppercase text.
Condition B catches edge cases where proceedings description is generic (e.g., "In the Matter of HDC Alpha, LLC").

**Four proceeding description formats exist:**
1. **Standard IPES format (WC XX-XXX dockets):**
   ```
   "Interconnected VoIP Numbering Authorization Application Filed By {COMPANY}
    Pursuant To Section 52.15(g)(3) of the Commission's Rules"
   ```

2. **Staging/inbox format (INBOX-52.15 docket):**
   ```
   "VoIP Numbering Authorization Application (Fee Required)"
   ```
   Note: Company name must be extracted from filers[] or document content.

3. **"In the Matter of" format (older filings):**
   ```
   "In the Matter of {COMPANY} For Authorization to Obtain Numbering Resources
    Pursuant to Section 52.15(g) of The Commission's Rules"
   ```

4. **Generic format (rare):**
   ```
   "In the Matter of {COMPANY}"  or  "MISCELLANEOUS"
   ```
   Note: IPES identified by document filename containing "VoIP Numbering".

**Expected yield after filtering (verified):**
| Submission Type | Count | Notes |
|-----------------|-------|-------|
| APPLICATION | **240** | 218 standard + 13 INBOX-52.15 + 9 edge cases |
| PUBLIC NOTICE | ~290 | |
| SUPPLEMENT | ~110 | |
| COMMENT | ~60 | |
| AMENDMENT | ~35 | |
| LETTER | ~40 | |
| WITHDRAWAL | ~22 | |
| OTHER | ~20 | |
| NOTICE OF EXPARTE | ~10 | |
| misc (EXHIBIT, PETITION, etc.) | ~40 | |
| **Total** | **~860-900** | |

**Edge case APPLICATIONs captured by two-query approach (8 additional companies):**
- Stratus Networks (19-306)
- HDC Alpha/Beta/Gamma/Delta/Epsilon (19-313 to 19-317)
- Assurance Telecom (19-335)
- Simwood (INBOX-1.41)

**Noise removed by filter:**
- Section 214 transfer applications
- COVID Telehealth program applications
- General numbering policy filings
- Copper retirement network change notices

**Outputs**

* `data/processed/filings_filtered.jsonl`

---

## Phase 3 — Structuring + dedup into companies (45–60 min)

**Goal:** Produce `companies.json` + `raw_filings.csv` for easy review.

**Key step: company extraction**

* **For standard IPES format** (proceedings description contains "Filed By"):
  * Parse applicant from `proceedings[].description` using regex:
    * primary: `Filed By (.+?) Pursuant`
    * fallback: `Filed By (.+?)(?:$|,|\.)`

* **For INBOX-52.15 format** (proceedings description is "VoIP Numbering Authorization Application"):
  * Extract from `filers[].name` (first non-bureau filer)
  * Fallback: extract from document filename if available

* Construct docket: `"{bureau_code} {name}"` (e.g., "WC 25-226" or "INBOX-52.15")

**Dedup strategy**

* Group by normalized company name using this algorithm:
  1. Lowercase
  2. Strip legal suffixes: `LLC`, `Inc`, `Corp`, `Corporation`, `Ltd`, `LP`, `LLP`, `Co`, `Company`, `Holdings`, `Group`
  3. Remove punctuation (commas, periods, hyphens)
  4. Collapse multiple whitespace to single space
  5. Strip leading/trailing whitespace
  * Example: `"ULEC, LLC"` → `"ulec"`, `"Bandwidth.com, Inc."` → `"bandwidthcom"`
* Keep original names as aliases
* Link all filings and dockets

**Status**

* Compute `application_status` per company:

  * If any related filing has `submissiontype.description` == ORDER / PUBLIC NOTICE and the proceedings description includes “Granted”/“Denied”/“Dismissed”/“Withdrawn”, map to status.
  * Else “Unknown/Pending”

**Outputs**

* `data/processed/companies.json`
* `data/processed/companies.csv`
* `data/processed/filings_flat.csv`

---

## Phase 4 — Document downloads + text extraction (30–60 min)

**Goal:** Populate `documents/original/` with all primary docs.

**Download requirements**

* For each filing, download each `documents[].src` to:

  * `documents/original/{id_submission}_{idx}_{filename}`
* Use HTTP/1.1 (avoid curl-like HTTP/2 weirdness) + retry/backoff.
* Concurrency: 5–10.

* Extract text from PDFs into `documents/text/*.txt` for enrichment evidence.

**Outputs**

* `documents/original/*`
* `documents/text/*`

---

## Phase 5 — AI enrichment

**Goal:** Produce `data/processed/companies_enriched.json/csv` with high-quality market intelligence.

**Model:** Claude Sonnet (via Anthropic API, key in `.env` as `ANTHROPIC_API_KEY`)
- Sonnet provides optimal balance of reasoning quality and cost for ~200 companies
- Structured output via tool_use for reliable JSON parsing

### Research Findings (tested on sample companies)

| Source | Effectiveness | Notes |
|--------|--------------|-------|
| **FCC Document Text** | Very High | 138/507 docs have standard FCC format with parseable sections |
| **Filing Metadata** | High | 98/200 companies have multiple filings (activity signal) |
| **Web Search (well-known)** | Excellent | Rich profiles for 8x8, Vonage, etc. |
| **Web Search (mid-tier)** | Good | ZoomInfo/LinkedIn profiles available |
| **Web Search (obscure)** | Poor | Often nothing or negative news only |

### Enrichment Pipeline (4 steps)

**Step 1: Document Text Parsing (no API calls)**

Parse FCC application documents using regex to extract:
- Company address, phone, email from § 52.15(g)(3)(i)(A) section
- Key personnel (CEO, President, CFO) from § 52.15(g)(3)(i)(F) section
- Founding date if mentioned ("founded in", "established", "since YYYY")
- Service area descriptions
- Business descriptions and carrier partners

Implementation: Regex patterns targeting standard FCC application format.
Coverage: ~70% of companies have parseable standard-format applications.

**Step 2: Filing Signals (no API calls)**

Derive activity indicators from existing `companies.json` metadata:
- `total_filing_count > 1` → likely still active
- `latest_filing_date` within 2 years → likely active
- Has SUPPLEMENT filings → ongoing business relationship
- Multiple docket numbers → expanded operations

**Step 3: Web Search (DuckDuckGo via `ddgs` package)**

For each company, one search query: `"{company_name}" VoIP telecommunications`

```python
from ddgs import DDGS
results = DDGS().text(f'"{company_name}" VoIP telecommunications', max_results=5)
```

Extract from results:
- Company website exists? (active signal)
- Recent news mentions
- Business profiles (D&B, ZoomInfo)
- Acquisition or funding news

Implementation notes:
- `pip install ddgs` (no API key required)
- Add 1-second delay between requests to avoid rate limits
- ~3-4 minutes for all 200 companies

**Step 4: LLM Synthesis (Claude Sonnet API)**

Pass all gathered evidence to Claude with structured output schema:

```python
enrichment_schema = {
    "is_active": bool,           # Is company currently operating?
    "activity_signal": str,      # Evidence supporting determination (cite sources)
    "industry_segment": str,     # UCaaS | CCaaS | CPaaS | Carrier | Reseller | Enterprise IT | Other
    "product_summary": str,      # 1-2 sentence description
    "market_position": str,      # Enterprise | Mid-Market | SMB | Startup | Unknown
    "enrichment_confidence": str, # High | Medium | Low
    "enrichment_sources": list   # URLs/identifiers used
}
```

Evidence pack structure:
```python
evidence_pack = {
    "company_name": str,
    "aliases": list,
    "fcc_filing": {
        "first_filing_date": str,
        "latest_filing_date": str,
        "total_filings": int,
        "docket_numbers": list,
        "proceeding_types": list
    },
    "parsed_from_docs": {
        "address": str | None,
        "phone": str | None,
        "key_personnel": list,
        "founding_date": str | None,
        "service_description": str | None
    },
    "web_search_snippets": list,
    "doc_text_excerpts": list  # First 2000 chars of each doc
}
```

**Prompt contract:**
- Ground all assessments in provided evidence
- Cite specific sources in `activity_signal`
- Use "Unknown" when evidence is insufficient (don't hallucinate)
- `enrichment_confidence` reflects evidence quality:
  - High = multiple confirming signals (web + docs + recent filings)
  - Medium = some signals but incomplete
  - Low = FCC data only, no external confirmation

**Implementation:**
- Batch document parsing first (fast, no API)
- Then parallel web searches (5 concurrent)
- Then parallel LLM calls (5 concurrent)
- Cache results by `company_name_normalized` (skip already-enriched)
- Store raw prompts/responses in `data/processed/enrichment_logs/`
- Retry with backoff on API errors

**Outputs**

* `data/processed/companies_enriched.json`
* `data/processed/companies_enriched.csv`
* `data/processed/enrichment_logs/` (prompts + responses for audit trail)

### Post-Enrichment Improvements

After initial LLM enrichment, additional data quality improvements are documented in **[ENRICHMENT_IMPROVEMENT.md](./ENRICHMENT_IMPROVEMENT.md)**:
- Fix individual filer names (21 records with person names instead of company names)
- Clean key personnel noise (45% of entries are parsing artifacts)
- Infer market position from filing signals (reduce 50% "Unknown" rate)
- Optional targeted re-enrichment for low-confidence records

---

# 6) Non-Goals

* Perfect historical coverage before 2016 (note limitations in README)
* Full attorney/contact extraction from PDFs
* Deep competitive analysis (pricing, customer lists, etc.)

---

# 7) Risks & Mitigations

### Risk: API search recall misses some applicants

**Mitigation:** Use multiple queries + keep everything with proceeding descriptions matching the IPES phrasing; store what queries were used.

### Risk: Company name extraction fails for weird phrasing

**Mitigation:** Store raw proceedings description; fallback to filers; mark Unknown.

### Risk: Document downloads flaky (HTTP/2 errors)

**Mitigation:** Use Python httpx with `http2=False`, retries + backoff, and store failed downloads list.

### Risk: LLM hallucination

**Mitigation:** Evidence-pack architecture (FCC data + parsed doc fields + web search). Prompt requires citing sources. "Unknown" is valid. Confidence field reflects evidence quality (High/Medium/Low based on signal diversity). All prompts/responses logged for audit.

### Risk: Web search returns no results for obscure companies

**Mitigation:** Web search is supplementary, not required. Document parsing + filing metadata provide baseline enrichment even with zero web results. These companies get `enrichment_confidence: "Low"` but still get populated fields from FCC data.

---

# 8) Deliverables Checklist

1. **Repo + explainer**

   * README: approach, design decisions, limitations, how to run
   * notable assumptions (coverage window, parsing heuristics) 
2. **Raw dataset**

   * `filings_raw.jsonl` (pre-filter or post-filter, but clearly labeled) 
3. **Documents folder**

   * `documents/original/` (downloaded files) 
4. **Enriched dataset**

   * `companies_enriched.json` + `.csv` 

---

# 9) Phase-by-Phase “Done” Definitions

* **Done Phase 1:** you can answer “how many filings did we pull and from which queries?”
* **Done Phase 2:** you can show “these are IPES-related filings; noise removed”
* **Done Phase 3:** you have a deduped company list with dockets + docs linked
* **Done Phase 4:** all linked submission docs downloaded (or a clearly logged failure list)
* **Done Phase 5:** enriched dataset with all fields populated; document parsing extracts available structured fields; web search logged; LLM synthesis with confidence ratings (High/Medium/Low) per company

---

If you want, I can also give you:

* the exact regex patterns + normalization function tuned for your sample phrasing (“Filed By ULEC, LLC…”),
* and a minimal `main.py` orchestration order so you can run `python -m src.main extract && ...` without thinking.

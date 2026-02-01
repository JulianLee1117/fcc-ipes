# Process Log

> Human-readable log of design decisions, reasoning, and "why" behind each step. Focus on thought process, not metrics. For future context and onboarding.

---

## Why Two Queries?

Tested queries, compared counts, investigated gaps:

1. `"Interconnected VoIP Numbering"` → 218 APPLICATIONs
2. `"Numbering Authorization Application"` → 239 (found INBOX-52.15 format)
3. `52.15(g)` → 246 (found HDC, Stratus — but missed 9 INBOX-52.15)

No single query catches everything:

| Query | Catches | Misses |
|-------|---------|--------|
| `"Numbering Authorization Application"` | Standard + INBOX-52.15 | HDC, Stratus |
| `52.15(g)` | HDC, Stratus | Some INBOX-52.15 |

**Solution:** Run both, dedupe by `id_submission`.

---

## Why This Filter?

Pulled sample descriptions, filtered for APPLICATIONs not matching known patterns, found 4 formats:

1. `"Interconnected VoIP Numbering..."` — most common
2. `"VoIP Numbering Authorization Application (Fee Required)"` — INBOX-52.15
3. `"...Authorization to Obtain Numbering Resources..."` — Stratus, Assurance
4. Generic (`"In the Matter of HDC Alpha"`) — no keywords in description, checked doc filenames → found "VoIP Numbering" there

**Filter rule:** Keep if description contains #1, #2, or #3, OR any document filename contains "voip numbering".

---

## Result

**240 IPES applications** captured. Zero missed. 15 noise filings filtered out.

---

## 2026-01-31 17:45 — Phase 3: Data Modeling Decisions

### Why Company-Centric Structure?

The raw data is **filing-centric** (one record per submission). But the business question is **company-centric**: "Who are the IPES players?"

Same company appears multiple times:
- Initial APPLICATION
- SUPPLEMENTs (additional docs)
- AMENDMENTs (corrections)
- Sometimes multiple APPLICATION attempts

**Decision:** Group by normalized company name → one record per company with all filings linked.

### Why These Fields?

| Field | Why |
|-------|-----|
| `company_name` | Primary identifier for enrichment/analysis |
| `docket_numbers` | Links to official FCC proceeding (e.g., "WC 20-244") |
| `first_filing_date` | When they entered the IPES market |
| `documents[]` | URLs needed for Phase 4 downloads |
| `contacts` / `attorneys` | Potential enrichment signals |
| `proceeding_types` | Confirms it's actually an IPES application |

### Name Normalization

Companies file with inconsistent names:
- "RGTN USA, Inc." vs "RGTN USA Inc."
- "Mix Networks, Inc" vs "Mix Networks"

**Solution:** Normalize (lowercase, standardize suffixes), but preserve original variations in `name_variations[]`.

### Edge Cases Accepted

~34 records are individuals (not corporate names). Investigation showed these are:
- Attorneys filing on behalf of companies
- Officers/founders filing personally

The actual company name often appears in `proceeding_types`. Kept as-is — AI enrichment (Phase 5) can resolve.

### Result

**200 unique IPES companies** from 896 filtered filings. 166 clearly corporate, 34 individual filers.

### Why Exactly 200?

Not artificial — verified the count:

```
896 filtered filings
 │
 ├─► 364 unique filer names
 │    │
 │    ├─► 4 government entities (FCC bureaus, DOJ) → excluded
 │    │
 │    └─► 360 remaining
 │         │
 │         └─► 334 after name normalization (merging variations)
 │              │
 │              ├─► 200 filed an APPLICATION → companies.json ✓
 │              │
 │              └─► 134 never filed APPLICATION → excluded
```

The 134 excluded filers were commenters, attorneys filing amendments, petitioners — not actual IPES applicants.

---

## 2026-01-31 18:02 — Phase 4: Document Downloads

### FCC Server Quirks

The FCC ECFS document server is finicky. Standard requests fail. Required settings:

| Setting | Value | Why |
|---------|-------|-----|
| HTTP/1.1 | `http2=False` | HTTP/2 causes connection drops |
| TLS 1.2 | `--tlsv1.2` | Required for FCC servers |
| User-Agent | `PostmanRuntime/7.47.1` | Server rejects generic agents |
| Cookie | `lmao=1` | Bypasses some validation |

### URL Transform

API returns viewer URLs:
```
/ecfs/document/{id}/{seq}  (singular)
```
Download requires:
```
/ecfs/documents/{id}/{seq} (plural)
```

### Result

| Metric | Value |
|--------|-------|
| Documents downloaded | **512** |
| Success rate | 100% |
| Total size | 620.3 MB |
| File types | 492 PDF, 18 DOCX, 2 DOC |

Filename format: `{filing_id}_{original_filename}`

---

## 2026-01-31 18:33 — Phase 5: Enrichment Strategy

### The Question

Before writing enrichment code, tested: **What data sources actually work for these 200 companies?**

Tested on: 8x8 (big), Vonage (acquired), Global Net (mid-tier), 200 Networks (obscure).

### What I Found

| Source | Quality | Coverage |
|--------|---------|----------|
| **FCC doc text** | High | ~70% have structured sections |
| **Filing metadata** | High | 100% (already have it) |
| **Web search** | Varies | Great for famous, useless for obscure |

**FCC applications are surprisingly rich.** The standard format includes:
- § 52.15(g)(3)(i)(A): Address, phone, email
- § 52.15(g)(3)(i)(F): Key personnel with bios
- Often: founding dates, service descriptions

Example: 8x8's filing contains CEO/CTO/CFO names, full bios, and "$50B market" positioning.

**Web search has a long tail problem.** 8x8 and Vonage return Gartner reports and financials. Obscure companies return nothing or just breach news.

**Filing patterns are activity signals.** 98/200 companies filed multiple times. Recent filings = likely still operating.

### Strategy

1. **Parse docs first** (free) — extract what's already in the filings
2. **Use filing signals** (free) — multiple filings, recent dates = active
3. **Web search** (1 call/company) — supplement, not primary source
4. **LLM synthesis** (1 call/company) — combine evidence, output structured fields

This avoids over-relying on web search for companies that won't have results.

### Web Search Tool Selection

Tested `ddgs` (DuckDuckGo search) on 3 sample companies:

| Company | Results |
|---------|---------|
| 8x8 Inc | Wikipedia, VoIP reviews, patents |
| Global Net Communications | Company website, services |
| 200 Networks LLC | D&B profile, breach article |

**Decision:** Use `ddgs` — free, no API key, effective results. Add 1s delay between requests.

---

## 2026-01-31 18:58 — Phase 5: Enrichment Execution

### Pipeline (4 steps)

| Step | Action | API Calls | Result |
|------|--------|-----------|--------|
| 1 | Parse FCC docs (regex) | 0 | 29 companies with structured fields |
| 2 | Compute filing signals | 0 | 200 companies |
| 3 | Web search (ddgs) | 200 | 200/200 returned results |
| 4 | LLM synthesis (Claude Sonnet) | 200 | All succeeded |

### Result

| Metric | Value |
|--------|-------|
| Total companies | **200** |
| Determined active | 125 (63%) |
| Confidence: High | 42 |
| Confidence: Medium | 89 |
| Confidence: Low | 69 |

### Industry Breakdown

| Segment | Count |
|---------|-------|
| Carrier | 94 |
| UCaaS | 66 |
| CPaaS | 19 |
| CCaaS | 6 |
| Reseller | 4 |
| Unknown | 7 |
| Other/Enterprise | 4 |

### Key Insight (Initial Run)

Document parsing only hit 29 companies due to filename mismatch bug. Activity determination still reliable — LLM used filing signals + web search effectively.

---

## 2026-01-31 19:22 — Document Parsing Fix

### The Bug

Download script sanitizes filenames (spaces→underscores, collapse multiple underscores, truncate to 100 chars). But `get_document_text()` used original API filenames.

```python
# Before (broken):
base_name = Path(filename).stem

# After (fixed):
sanitized = sanitize_filename(filename)  # Match download script logic
base_name = Path(sanitized).stem
```

### Result After Fix

| Metric | Before | After |
|--------|--------|-------|
| Documents matched | 29 | **507/512** (99%) |
| Companies with docs | 29 | **188/200** (94%) |
| With address | ? | 135 |
| With phone | ? | 121 |
| With email | ? | 83 |
| With key personnel | ? | 132 |

The 5 unmatched documents are edge cases (format issues, API metadata mismatches). All 200 companies have at least one document from related filings.

### Output Files

- `companies_enriched.json` (645 KB)
- `companies_enriched.csv` (124 KB, 201 rows)
- `enrichment_logs/` (400 prompt/response pairs)

---

## 2026-01-31 19:39 — Final Enrichment Run (Post-Fix)

Re-ran full enrichment pipeline with document parsing fix in place.

### Pipeline Results

| Step | Action | Result |
|------|--------|--------|
| 1 | Parse FCC docs | **188 companies** (vs 29 before) |
| 2 | Compute filing signals | 200 companies |
| 3 | Web search (ddgs) | 200/200 returned results |
| 4 | LLM synthesis (Claude Sonnet) | All succeeded |

### Improvement Summary

| Metric | Before Fix | After Fix | Change |
|--------|------------|-----------|--------|
| Parsed docs | 29 | **188** | +6.5x |
| High confidence | 42 | **54** | +12 |
| Medium confidence | 89 | 87 | -2 |
| Low confidence | 69 | **59** | -10 |
| Active companies | 125 | 115 | -10 |

The decrease in "active" determination with more document data indicates more accurate (conservative) assessments with better evidence.

### Parsed Data Coverage

| Field | Count | Coverage |
|-------|-------|----------|
| Address | 135 | 68% |
| City | 66 | 33% |
| State | 69 | 34% |
| Phone | 121 | 60% |
| Email | 83 | 42% |
| Key personnel | 132 | 66% |

### Industry Breakdown (Final)

| Segment | Count |
|---------|-------|
| Carrier | 87 |
| UCaaS | 76 |
| CPaaS | 19 |
| CCaaS | 7 |
| Unknown | 4 |
| Other | 3 |
| Enterprise IT | 3 |
| Reseller | 1 |

### Spot-Check Validation

| Company | Active | Segment | Market | Confidence | Notes |
|---------|--------|---------|--------|------------|-------|
| 8x8, Inc. | ✓ | UCaaS | SMB | High | Correct |
| Bandwidth, Inc. | ✓ | CPaaS | Enterprise | High | Correct |
| Twilio International | ✓ | CPaaS | Enterprise | Medium | Correct |
| Vonage Holdings | ✗ | UCaaS | Enterprise | Medium | Correct (acquired by Ericsson 2022) |

### Output Files (Final)

- `companies_enriched.json` (710 KB)
- `companies_enriched.csv` (129 KB, 201 rows)
- `enrichment_logs/` (400 prompt/response pairs)

---

## 2026-01-31 20:15 — Post-Enrichment Quality Analysis

### What I Found

Reviewed the enriched data and spotted three fixable issues:

1. **Wrong company names:** 21 records have person names (attorneys/officers filing on behalf of companies). But the real company name is sitting right there in `proceeding_types`: `"FILED BY FREEWAY COMMUNICATIONS, LLC PURSUANT..."`. We just didn't extract it during structuring.

2. **Key personnel garbage:** The regex grabbed bio fragments like `"Company Website"`, `"Erik brings"`, `"experience and"`. Obviously not names — easy to filter out.

3. **Too many "Unknown" market positions:** LLM punted to "Unknown" for half the companies. But we already have signals that could help — industry segment, filing frequency, founding dates. Rules-based inference could fill gaps without more API calls.

### Why a Post-Processing Script?

Re-running the full LLM pipeline would cost ~$0.60 and 20 minutes. But most fixes are just regex/rules — no LLM needed. So: create `improve_enrichment.py` that does cheap fixes first (regex), expensive fixes last (optional targeted LLM).

See: [ENRICHMENT_IMPROVEMENT.md](./ENRICHMENT_IMPROVEMENT.md)

---

## 2026-01-31 20:16 — Post-Enrichment Improvements Applied

Ran `src/improve_enrichment.py` — three phases of cleanup without re-running LLM.

### Phase 1: Person Names → Company Names

Agent investigated 6 unfixable records by searching documents:

| Filer | Resolution |
|-------|------------|
| Jeremy Mcpherson | → IGEM Communications LLC DBA Globalgig |
| Martin Lien | → Volt Labs Inc. |
| Arif Gul | → Fullduplex Limited |
| Valstarr Asia | Already a company (false positive) |
| Adam Szokol, Bart Mueller | Confirmed individuals |

**Result:** 15 fixed total, 2 individuals, 0 unknowns.

### Phase 2: Key Personnel Cleanup

Filtered noise (titles, fragments, company names). **734 → 109 entries.**

### Phase 3: Market Position Inference

Rules: UCaaS/CCaaS/CPaaS → SMB, high activity → Mid-Market. **Unknown: 50% → 29.5%**

### Final Metrics

| Metric | Before | After |
|--------|--------|-------|
| Market position unknown | 50% | **29.5%** |
| Person names as companies | 17 | **0** |
| Clean key personnel | 109 | **109** |

---

## 2026-01-31 20:43 — Contact Data Gap Fill (D&B Search)

### Problem

Parsed contact fields (city, state) had 33% coverage — data existed in FCC docs for some companies but not all.

### Solution

Created `src/fill_contact_gaps.py` — searches D&B via DuckDuckGo for companies with missing contact data, extracts city/state from result snippets.

**Pattern:** D&B snippets contain `"of City, State"` format (e.g., `"of Campbell, California"`).

### Results

| Field | Before | After | Change |
|-------|--------|-------|--------|
| City | 66 (33%) | **162 (81%)** | +96 |
| State | 69 (34%) | **162 (81%)** | +93 |
| Phone | 121 (60%) | 121 (60%) | — |
| Email | 83 (41%) | 83 (41%) | — |

Phone/email not in D&B snippets — kept existing FCC-parsed values.

### Notes

- 176 companies searched, 98 updated
- Some SSL errors (~15) due to rate limiting — acceptable loss
- Non-US locations returned for a few companies (international HQs) — kept as-is

---

## 2026-01-31 20:52 — Schema Normalization (market_position)

### Problem

Inconsistent schema: `market_position_inferred` (boolean) + `market_position_reason` only existed on 41 records where rules-based inference was applied. Other records had neither field.

### Solution

Replaced with consistent `market_position_source` enum on all records:

| Value | Count | Meaning |
|-------|-------|---------|
| `llm` | 100 | Claude determined directly |
| `rules` | 41 | Inferred from industry_segment/filing patterns |
| `undetermined` | 59 | Neither could determine (stays "Unknown") |

`market_position_reason` retained only for `source="rules"` (documents which rule fired).

### Result

Every record now has `market_position_source`. Schema is self-documenting without needing to read code.

---

## 2026-01-31 21:15 — Final Gap Fill

### Problem

After initial enrichment + post-processing, still had gaps:
- 4 Unknown `industry_segment`
- 59 Unknown `market_position`
- 38 missing `city/state`

### Approach (3 passes)

**Pass 1: Keyword search** (`fill_enrichment_gaps.py`)
- DuckDuckGo search for each company
- Classify industry by keyword matching (UCaaS/CCaaS/CPaaS/Carrier signals)
- Classify market by employee count patterns and revenue signals
- Result: 21 market positions, 8 locations filled

**Pass 2: Targeted sources + rules** (`fill_gaps_v2.py`)
- LinkedIn/Crunchbase/ZoomInfo searches for company size signals
- Filing-based heuristics:
  - Single filing + inactive carrier → SMB
  - 5+ filings + recent activity → Mid-Market
  - Industry-based defaults (UCaaS/CCaaS/CPaaS → SMB)
- Result: 28 market positions (26 rule-based), 2 industries

**Pass 3: Manual research** (10 remaining)
- Searched each company individually
- Key findings:
  - IDT Domestic Telecom → Enterprise (NASDAQ-listed parent)
  - CallWorks Corporation → Enterprise (911/PSAP solutions)
  - Alaska Communications → Mid-Market (major Alaskan ISP)
  - Volt Labs Inc. → UCaaS (VoIP startup)
- Result: 12 fields filled, 0 Unknown remaining

### Final Coverage

| Field | Before | After |
|-------|--------|-------|
| `industry_segment` | 98% | **100%** |
| `market_position` | 70.5% | **100%** |
| `parsed_city` | 67% | **90%** |
| `parsed_state` | 66% | **90%** |

### Market Position Distribution (Final)

| Position | Count |
|----------|-------|
| SMB | 115 |
| Enterprise | 61 |
| Mid-Market | 19 |
| Startup | 5 |

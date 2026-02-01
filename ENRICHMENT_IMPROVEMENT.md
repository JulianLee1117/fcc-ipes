# Enrichment Improvement Plan

> Post-processing improvements to enhance data quality after initial LLM enrichment.

---

## Current State Analysis (Validated via Testing)

| Metric | Value | Impact |
|--------|-------|--------|
| Market position unknown | **100/200 (50%)** | High - key intelligence gap |
| Key personnel noise | **552/734 (75%)** | High - worse than estimated |
| Low confidence | **59/200 (29%)** | Medium - credibility |
| Individual filers (regex-fixable) | **12** | High - wrong company names |
| Individual filers (need agent) | **6** | Medium - no pattern to extract |
| Missing contact data | 32-58% | Low - nice to have |

---

## Improvements (Priority Order)

### Phase 1: Fix Individual Filers (Regex + Optional Agent)

**Problem:** 18 records have person names instead of company names:
- `"(Melvin) Lee Reeves"` → actual company: `"FREEWAY COMMUNICATIONS, LLC"`
- `"Andrew Metcalfe"` → actual company: `"RED SPECTRUM COMMUNICATIONS, LLC"`

**Solution A - Regex (12 records):**
1. For each company where `proceeding_types` contains `"Filed By ... Pursuant"` (case-insensitive)
2. Extract actual company name via regex
3. Update `company_name` field, move original to `filer_name`

**Pattern (improved - case insensitive):**
```python
r'(?i)filed\s+by\s+([^,]+?(?:,?\s*(?:LLC|INC|CORP|L\.?L\.?C\.?|INC\.?|CORP\.?|CORPORATION|COMPANY|CO\.?))?)[\s,]+pursuant'
```

**Solution B - Agent Search (6 records):**
For records without extractable company name:
- `Adam Szokol`, `Arif Gul`, `Bart Mueller`, `Jeremy Mcpherson`, `Martin Lien`, `Valstarr Asia`
- Option: Use Claude Code agent to search documents/web for company association
- Or: Mark as `filer_type: "individual"` if truly personal filings

**Expected Result:** 18 person names → 12 fixed via regex, 6 flagged for review

---

### Phase 2: Clean Key Personnel Noise (Regex)

**Problem:** 75% of parsed_key_personnel entries are noise (worse than estimated):
- `"Company Website"`, `"Erik brings"`, `"experience and"`, `"Chief Operating Officer"`
- Also includes company names, partial phrases, titles without names

**Solution:** Post-process to filter - keep only entries that:
1. Have 2-4 words (typical "First Last" or "First Middle Last" pattern)
2. Start with uppercase letter
3. Don't contain noise keywords:
   - Position words: `"chief"`, `"officer"`, `"president"`, `"director"`, `"ceo"`, `"cto"`, `"coo"`
   - Fragment words: `"company"`, `"website"`, `"experience"`, `"brings"`, `"has"`, `"was"`, `"and"`, `"the"`, `"from"`, `"its"`
   - Generic: `"contact name"`, `"see exhibit"`, `"of vm"`, `"strategic"`, `"technical"`
4. Don't contain company indicators: `"llc"`, `"inc"`, `"corp"`, `"communications"`, `"networks"`
5. Deduplicate by normalized name

**Expected Result:** 75% noise → ~17% clean personnel (98 unique names)

---

### Phase 3: Market Position Inference (Rules-Based)

**Problem:** 50% have `Unknown` market_position even after LLM

**Solution:** Rules-based inference from other signals (tested - 41 inferences):

| Priority | Condition | Inferred Position | Test Count |
|----------|-----------|------------------|------------|
| 1 | `industry_segment == "Enterprise IT"` | `"Enterprise"` | 0 |
| 2 | `parsed_founding_date >= 2022` | `"Startup"` | 0 |
| 3 | `filing_signals.total_filings > 5` AND `recent_activity == true` | `"Mid-Market"` | 1 |
| 4 | `industry_segment in ["UCaaS", "CCaaS", "CPaaS"]` | `"SMB"` | 40 |
| - | `is_active == false` | Keep `"Unknown"` | - |

**Expected Result:** 50% unknown → ~30% unknown (41 inferred)

---

### Phase 4: Re-enrich Low-Confidence Records (Optional, LLM)

**Problem:** 59 records (29%) have `Low` confidence, mostly missing market_position

**Solution:** Targeted LLM pass for low-confidence records only:
1. Enhanced prompt specifically requesting market_position determination
2. Include additional context from proceeding_types
3. Update only those 59 records

**Cost:** ~$0.15 (59 calls × $0.003/call)

**Note:** This phase is optional. Phases 1-3 may resolve enough issues.

---

## Implementation

**Script:** `src/improve_enrichment.py`

```python
# Usage:
# python -m src.improve_enrichment [--skip-llm]
#
# Phases:
# 1. Fix individual filers (regex)
# 2. Clean key_personnel noise (regex)
# 3. Apply market_position rules (no API)
# 4. Optionally re-enrich low-confidence via LLM (--skip-llm to disable)
```

---

## Expected Outcome (Validated)

| Metric | Before | After |
|--------|--------|-------|
| Individual filer names | 18 | **6** (12 fixed, 6 flagged) |
| Key personnel noise | 75% | **~17% clean** (98 unique names) |
| Market position unknown | 50% | **~30%** (41 inferred) |
| Low confidence | 29% | **~20%** (post-rules) |

---

## Files Modified

- `src/improve_enrichment.py` — new post-processing script
- `data/processed/companies_enriched.json` — updated output
- `data/processed/companies_enriched.csv` — regenerated
- `PROCESS_LOG.md` — document improvements

---

## Verification

1. Re-run gap analysis after improvements
2. Spot-check fixed individual filers
3. Verify key_personnel cleaned
4. Confirm market_position improvements

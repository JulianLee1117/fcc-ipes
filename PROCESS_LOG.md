# Process Log

> Running log of design decisions and reasoning. For future context.

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

---

## 2026-02-01 02:02 — Phase 4: Document Downloads

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

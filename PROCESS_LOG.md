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

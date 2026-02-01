"""
Post-processing improvements for enriched company data.

Usage:
    python -m src.improve_enrichment [--dry-run] [--verbose]

Phases:
    1. Fix individual filers (regex extraction from proceeding_types)
    2. Clean key_personnel noise (filter to real person names)
    3. Apply market_position rules (no API)
"""

import json
import re
import csv
import argparse
from pathlib import Path


INPUT_FILE = Path("data/processed/companies_enriched.json")
OUTPUT_JSON = Path("data/processed/companies_enriched.json")
OUTPUT_CSV = Path("data/processed/companies_enriched.csv")


# Manual fixes from agent investigation (records without extractable pattern)
MANUAL_COMPANY_FIXES = {
    "Jeremy Mcpherson": "IGEM Communications LLC DBA Globalgig",
    "Martin Lien": "Volt Labs Inc.",
    "Arif Gul": "Fullduplex Limited",
}

# Records that are actually companies (false positives in person detection)
NOT_PERSON_NAMES = {"Valstarr Asia", "True IP Solutions"}

# Confirmed individual filers (no company association)
INDIVIDUAL_FILERS = {"Adam Szokol", "Bart Mueller"}


# Phase 1: Regex pattern for extracting company names from proceeding_types
COMPANY_EXTRACT_PATTERN = re.compile(
    r'filed\s+by\s+([^,]+?(?:,?\s*(?:LLC|INC|CORP|L\.?L\.?C\.?|INC\.?|CORP\.?|CORPORATION|COMPANY|CO\.?))?)[\s,]+pursuant',
    re.IGNORECASE
)


def looks_like_person_name(name: str) -> bool:
    """Check if a company_name looks like a person's name rather than a company."""
    if not name:
        return False

    company_indicators = [
        'llc', 'inc', 'corp', 'ltd', 'company', 'co.', 'technologies',
        'communications', 'networks', 'services', 'tel', 'voip', 'solutions',
        'wireless', 'telecom', 'broadband', 'digital', 'media'
    ]
    name_lower = name.lower()

    # Has company suffix -> not a person
    if any(ind in name_lower for ind in company_indicators):
        return False

    # Check if looks like "First Last" pattern
    words = name.split()
    if len(words) >= 2 and len(words) <= 4:
        # No digits in a person's name
        if any(c.isdigit() for c in name):
            return False
        # Words should be capitalized (strip parentheses for check)
        def first_alpha_upper(w):
            stripped = w.strip("()")
            return stripped and stripped[0].isupper()
        if all(first_alpha_upper(w) for w in words if len(w) > 1):
            return True

    return False


def extract_company_from_proceeding(proceeding_types: list) -> str | None:
    """Extract company name from proceeding_types if present."""
    for pt in proceeding_types:
        match = COMPANY_EXTRACT_PATTERN.search(pt)
        if match:
            return match.group(1).strip()
    return None


def phase1_fix_individual_filers(data: list, verbose: bool = False) -> dict:
    """Fix records where company_name is a person's name."""
    stats = {"fixed": 0, "flagged": 0, "skipped": 0, "individual": 0}

    for company in data:
        name = company["company_name"]

        # Skip names that are actually companies (false positives)
        if name in NOT_PERSON_NAMES:
            stats["skipped"] += 1
            continue

        # Check manual fixes first
        if name in MANUAL_COMPANY_FIXES:
            old_name = name
            new_name = MANUAL_COMPANY_FIXES[name]
            company["filer_name"] = old_name
            company["company_name"] = new_name
            company["company_name_normalized"] = new_name.lower().replace(",", "").replace(".", "").strip()
            stats["fixed"] += 1
            if verbose:
                print(f"  FIXED (manual): '{old_name}' -> '{new_name}'")
            continue

        # Mark confirmed individual filers
        if name in INDIVIDUAL_FILERS:
            company["filer_type"] = "individual"
            stats["individual"] += 1
            if verbose:
                print(f"  INDIVIDUAL: '{name}'")
            continue

        # Check if looks like a person name
        if not looks_like_person_name(name):
            stats["skipped"] += 1
            continue

        # Try regex extraction from proceeding_types
        extracted = extract_company_from_proceeding(company.get("proceeding_types", []))

        if extracted:
            old_name = name
            company["filer_name"] = old_name
            company["company_name"] = extracted
            company["company_name_normalized"] = extracted.lower().replace(",", "").replace(".", "").strip()
            stats["fixed"] += 1
            if verbose:
                print(f"  FIXED (regex): '{old_name}' -> '{extracted}'")
        else:
            company["filer_type"] = "individual_or_unknown"
            stats["flagged"] += 1
            if verbose:
                print(f"  FLAGGED: '{name}' (no pattern found)")

    return stats


# Phase 2: Noise keywords for key_personnel filtering
PERSONNEL_NOISE_WORDS = [
    'company', 'website', 'experience', 'brings', 'chief', 'officer',
    'president', 'director', 'ceo', 'cto', 'coo', 'cfo', 'and', 'the',
    'see exhibit', 'of vm', 'since', 'has', 'was', 'from', 'its',
    'contact name', 'strategic', 'technical', 'management', 'operations',
    'executive', 'senior', 'vice', 'provide', 'business', 'address'
]

COMPANY_INDICATORS = [
    'llc', 'inc', 'corp', 'communications', 'networks', 'solutions',
    'technologies', 'telecom', 'services', 'wireless'
]


def is_valid_person_name(name: str) -> bool:
    """Check if a key_personnel name looks like a real person's name."""
    if not name or len(name.strip()) < 3:
        return False

    name = name.strip()
    name_lower = name.lower()

    # Reject noise keywords
    if any(kw in name_lower for kw in PERSONNEL_NOISE_WORDS):
        return False

    # Reject company names
    if any(ci in name_lower for ci in COMPANY_INDICATORS):
        return False

    # Check word count (typical names are 2-4 words)
    words = [w for w in name.split() if w]
    if len(words) < 2 or len(words) > 4:
        return False

    # First character should be uppercase (names are capitalized)
    if not name[0].isupper():
        return False

    # Check for newlines/special chars (parsing artifacts)
    if '\n' in name or '\t' in name:
        return False

    return True


def phase2_clean_personnel(data: list, verbose: bool = False) -> dict:
    """Clean key_personnel to remove noise entries."""
    stats = {"total_before": 0, "total_after": 0, "companies_cleaned": 0}

    for company in data:
        personnel = company.get("parsed_key_personnel", [])
        if not personnel:
            continue

        stats["total_before"] += len(personnel)

        # Filter to valid names and deduplicate
        seen_names = set()
        cleaned = []

        for p in personnel:
            name = p.get("name", "")
            if is_valid_person_name(name):
                name_norm = name.lower().strip()
                if name_norm not in seen_names:
                    seen_names.add(name_norm)
                    cleaned.append(p)

        if len(cleaned) != len(personnel):
            company["parsed_key_personnel"] = cleaned
            stats["companies_cleaned"] += 1

            if verbose:
                print(f"  {company['company_name'][:30]}: {len(personnel)} -> {len(cleaned)}")

        stats["total_after"] += len(cleaned)

    return stats


def phase3_infer_market_position(data: list, verbose: bool = False) -> dict:
    """Infer market_position from other signals for Unknown records."""
    stats = {"inferred": 0, "skipped": 0}

    for company in data:
        if company.get("market_position") != "Unknown":
            stats["skipped"] += 1
            continue

        new_pos = None
        reason = ""

        # Rule 1: Enterprise IT -> Enterprise
        if company.get("industry_segment") == "Enterprise IT":
            new_pos = "Enterprise"
            reason = "industry_segment=Enterprise IT"

        # Rule 2: Recent founding -> Startup
        if not new_pos and company.get("parsed_founding_date"):
            try:
                year = int(str(company["parsed_founding_date"])[:4])
                if year >= 2022:
                    new_pos = "Startup"
                    reason = f"founded {year}"
            except (ValueError, TypeError):
                pass

        # Rule 3: High filing activity -> Mid-Market
        fs = company.get("filing_signals", {})
        if not new_pos and fs.get("total_filings", 0) > 5 and fs.get("recent_activity"):
            new_pos = "Mid-Market"
            reason = f"total_filings={fs['total_filings']}, recent_activity"

        # Rule 4: UCaaS/CCaaS/CPaaS -> SMB
        if not new_pos and company.get("industry_segment") in ["UCaaS", "CCaaS", "CPaaS"]:
            new_pos = "SMB"
            reason = f"industry_segment={company['industry_segment']}"

        # Apply inference
        if new_pos:
            company["market_position"] = new_pos
            company["market_position_inferred"] = True
            company["market_position_reason"] = reason
            stats["inferred"] += 1

            if verbose:
                print(f"  {company['company_name'][:35]:35} -> {new_pos} ({reason})")
        else:
            stats["skipped"] += 1

    return stats


def save_csv(data: list, output_path: Path):
    """Save data as flattened CSV."""
    if not data:
        return

    # Flatten nested structures for CSV
    flat_records = []
    for company in data:
        flat = {
            "company_name": company.get("company_name"),
            "company_name_normalized": company.get("company_name_normalized"),
            "dba_name": company.get("dba_name"),
            "filer_name": company.get("filer_name"),
            "filer_type": company.get("filer_type"),
            "first_filing_date": company.get("first_filing_date"),
            "latest_filing_date": company.get("latest_filing_date"),
            "total_filing_count": company.get("total_filing_count"),
            "application_count": company.get("application_count"),
            "docket_numbers": "; ".join(company.get("docket_numbers", [])),
            "is_active": company.get("is_active"),
            "activity_signal": company.get("activity_signal"),
            "industry_segment": company.get("industry_segment"),
            "product_summary": company.get("product_summary"),
            "market_position": company.get("market_position"),
            "market_position_inferred": company.get("market_position_inferred", False),
            "enrichment_confidence": company.get("enrichment_confidence"),
            "parsed_address": company.get("parsed_address"),
            "parsed_city": company.get("parsed_city"),
            "parsed_state": company.get("parsed_state"),
            "parsed_phone": company.get("parsed_phone"),
            "parsed_email": company.get("parsed_email"),
            "parsed_founding_date": company.get("parsed_founding_date"),
            "key_personnel_count": len(company.get("parsed_key_personnel", [])),
        }
        flat_records.append(flat)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=flat_records[0].keys())
        writer.writeheader()
        writer.writerows(flat_records)


def main():
    parser = argparse.ArgumentParser(description="Post-process enriched company data")
    parser.add_argument("--dry-run", action="store_true", help="Don't save changes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed changes")
    args = parser.parse_args()

    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} companies\n")

    # Phase 1
    print("=== Phase 1: Fix Individual Filers ===")
    stats1 = phase1_fix_individual_filers(data, verbose=args.verbose)
    print(f"  Fixed: {stats1['fixed']}, Individual: {stats1.get('individual', 0)}, Flagged: {stats1['flagged']}, Skipped: {stats1['skipped']}\n")

    # Phase 2
    print("=== Phase 2: Clean Key Personnel ===")
    stats2 = phase2_clean_personnel(data, verbose=args.verbose)
    print(f"  Personnel: {stats2['total_before']} -> {stats2['total_after']} ({stats2['companies_cleaned']} companies cleaned)\n")

    # Phase 3
    print("=== Phase 3: Infer Market Position ===")
    stats3 = phase3_infer_market_position(data, verbose=args.verbose)
    print(f"  Inferred: {stats3['inferred']}, Skipped: {stats3['skipped']}\n")

    # Save results
    if args.dry_run:
        print("DRY RUN - not saving changes")
    else:
        print(f"Saving to {OUTPUT_JSON}...")
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Saving to {OUTPUT_CSV}...")
        save_csv(data, OUTPUT_CSV)

        print("Done!")

    # Summary
    print("\n=== Summary ===")
    print(f"Phase 1: {stats1['fixed']} filer names fixed, {stats1.get('individual', 0)} confirmed individual, {stats1['flagged']} flagged")
    print(f"Phase 2: {stats2['total_before'] - stats2['total_after']} noise entries removed ({stats2['total_after']} clean)")
    print(f"Phase 3: {stats3['inferred']} market positions inferred")


if __name__ == "__main__":
    main()

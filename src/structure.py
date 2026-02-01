"""
Phase 3: Structure filtered filings into company records.

Groups filings by company (normalized name), establishes primary records,
and links all related filings to each company.
"""

import json
import re
from collections import defaultdict
from pathlib import Path


def normalize_company_name(name: str) -> str:
    """
    Normalize company name for deduplication.

    Handles:
    - Case normalization
    - Punctuation variations (Inc. vs Inc, LLC vs L.L.C.)
    - Trailing punctuation
    - Common suffixes
    """
    if not name:
        return ""

    # Lowercase
    normalized = name.lower().strip()

    # Remove common suffixes variations for matching
    # But keep a simplified version
    suffixes = [
        (r'\s*,?\s*l\.?l\.?c\.?$', ' llc'),
        (r'\s*,?\s*inc\.?$', ' inc'),
        (r'\s*,?\s*corp\.?$', ' corp'),
        (r'\s*,?\s*l\.?l\.?p\.?$', ' llp'),
        (r'\s*,?\s*l\.?p\.?$', ' lp'),
        (r'\s*,?\s*ltd\.?$', ' ltd'),
        (r'\s*,?\s*co\.?$', ' co'),
        (r'\s*,?\s*p\.?l\.?l\.?c\.?$', ' pllc'),
    ]

    for pattern, replacement in suffixes:
        normalized = re.sub(pattern, replacement, normalized)

    # Remove extra whitespace
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # Remove trailing comma/period
    normalized = normalized.rstrip('.,')

    return normalized


def extract_dba_name(name: str) -> tuple[str, str | None]:
    """
    Extract d/b/a (doing business as) name if present.
    Returns (primary_name, dba_name or None).
    """
    # Common patterns: "Company d/b/a Brand", "Company dba Brand"
    dba_patterns = [
        r'^(.+?)\s+d/?b/?a\s+(.+)$',
        r'^(.+?)\s+doing\s+business\s+as\s+(.+)$',
    ]

    for pattern in dba_patterns:
        match = re.match(pattern, name, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()

    return name, None


def is_government_entity(name: str) -> bool:
    """Check if filer is a government entity (should be excluded from companies)."""
    govt_keywords = [
        'wireline competition bureau',
        'federal communications commission',
        'fcc',
        'u.s. department',
        'department of justice',
    ]
    name_lower = name.lower()
    return any(kw in name_lower for kw in govt_keywords)


def structure_companies(input_file: Path, output_file: Path) -> dict:
    """
    Structure filtered filings into company records.

    Returns metadata about the structuring.
    """

    # Group filings by normalized company name
    company_filings = defaultdict(list)
    name_variations = defaultdict(set)

    # Track stats
    total_filings = 0
    excluded_govt = 0
    excluded_no_filer = 0

    with open(input_file) as f:
        for line in f:
            filing = json.loads(line)
            total_filings += 1

            filers = filing.get('filers', [])
            if not filers:
                excluded_no_filer += 1
                continue

            # Use first filer as primary
            filer_name = filers[0].get('name', '').strip()
            if not filer_name:
                excluded_no_filer += 1
                continue

            # Exclude government entities
            if is_government_entity(filer_name):
                excluded_govt += 1
                continue

            # Normalize for grouping
            normalized = normalize_company_name(filer_name)

            # Track original name variations
            name_variations[normalized].add(filer_name)

            # Add filing to company
            company_filings[normalized].append(filing)

    # Build company records
    companies = []

    for normalized_name, filings in company_filings.items():
        # Separate filing types
        applications = [f for f in filings
                       if f.get('submissiontype', {}).get('description') == 'APPLICATION']
        other_filings = [f for f in filings
                        if f.get('submissiontype', {}).get('description') != 'APPLICATION']

        # Skip if no APPLICATION (not an actual IPES applicant)
        if not applications:
            continue

        # Sort by date
        applications.sort(key=lambda x: x.get('date_received', ''))
        other_filings.sort(key=lambda x: x.get('date_received', ''))

        # Primary application is the first one
        primary_app = applications[0]

        # Collect all docket numbers
        dockets = set()
        for f in filings:
            for p in f.get('proceedings', []):
                docket = p.get('name', '')
                if docket and docket not in ['INBOX-52.15', 'INBOX-1.41']:
                    dockets.add(docket)

        # Collect all documents
        documents = []
        for f in filings:
            for doc in f.get('documents', []):
                documents.append({
                    'filename': doc.get('filename', ''),
                    'url': doc.get('src', ''),
                    'filing_id': f.get('id_submission'),
                    'filing_type': f.get('submissiontype', {}).get('description'),
                    'filing_date': f.get('date_received', '')[:10],
                })

        # Collect contacts (authors)
        contacts = set()
        for f in filings:
            for author in f.get('authors', []):
                name = author.get('name', '').strip()
                if name:
                    contacts.add(name)

        # Collect attorneys (law firms)
        attorneys = set()
        for f in filings:
            for firm in f.get('lawfirms', []):
                name = firm.get('name', '').strip()
                if name:
                    attorneys.add(name)

        # Get proceeding descriptions (for context about application type)
        proceeding_types = set()
        for f in filings:
            for p in f.get('proceedings', []):
                desc = p.get('description', '')
                if desc:
                    proceeding_types.add(desc)

        # Determine primary name (prefer most formal/complete variation)
        variations = list(name_variations[normalized_name])
        # Sort by length descending, then alphabetically to get most complete name
        variations.sort(key=lambda x: (-len(x), x))
        primary_name = variations[0] if variations else normalized_name

        # Extract d/b/a if present
        base_name, dba_name = extract_dba_name(primary_name)

        # Build filing summaries
        filing_summaries = []
        for f in filings:
            filing_summaries.append({
                'id': f.get('id_submission'),
                'type': f.get('submissiontype', {}).get('description'),
                'date': f.get('date_received', '')[:10],
                'status': f.get('filingstatus', {}).get('description'),
            })
        filing_summaries.sort(key=lambda x: x['date'])

        company = {
            'company_name': primary_name,
            'company_name_normalized': normalized_name,
            'dba_name': dba_name,
            'name_variations': sorted(variations),
            'docket_numbers': sorted(dockets),
            'first_filing_date': applications[0].get('date_received', '')[:10],
            'latest_filing_date': filings[-1].get('date_received', '')[:10] if filings else None,
            'application_count': len(applications),
            'total_filing_count': len(filings),
            'filings': filing_summaries,
            'documents': documents,
            'contacts': sorted(contacts),
            'attorneys': sorted(attorneys),
            'proceeding_types': sorted(proceeding_types),
        }

        companies.append(company)

    # Sort companies by name
    companies.sort(key=lambda x: x['company_name_normalized'])

    # Save to JSON
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(companies, f, indent=2)

    # Calculate stats
    stats = {
        'input_file': str(input_file),
        'output_file': str(output_file),
        'total_filings': total_filings,
        'excluded_govt': excluded_govt,
        'excluded_no_filer': excluded_no_filer,
        'unique_companies': len(companies),
        'companies_with_multiple_apps': sum(1 for c in companies if c['application_count'] > 1),
        'total_documents': sum(len(c['documents']) for c in companies),
    }

    return stats


def main():
    input_file = Path(__file__).parent.parent / 'data' / 'processed' / 'filings_filtered.jsonl'
    output_file = Path(__file__).parent.parent / 'data' / 'processed' / 'companies.json'

    stats = structure_companies(input_file, output_file)

    print('=== Structuring Complete ===')
    print(f"Input:  {stats['total_filings']} filtered filings")
    print(f"Output: {stats['unique_companies']} unique IPES companies")
    print(f"\nExcluded:")
    print(f"  Government entities: {stats['excluded_govt']}")
    print(f"  No filer name: {stats['excluded_no_filer']}")
    print(f"\nCompanies with multiple applications: {stats['companies_with_multiple_apps']}")
    print(f"Total documents linked: {stats['total_documents']}")
    print(f"\nSaved to: {stats['output_file']}")


if __name__ == '__main__':
    main()

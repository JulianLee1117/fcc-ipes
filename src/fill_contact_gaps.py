"""
Fill missing contact data (city, state, phone, email) using D&B web search.

Usage:
    python -m src.fill_contact_gaps [--dry-run] [--limit N]
"""

import json
import re
import time
import argparse
from pathlib import Path
from ddgs import DDGS

INPUT_FILE = Path("data/processed/companies_enriched.json")
OUTPUT_FILE = Path("data/processed/companies_enriched.json")

# Extraction patterns
LOCATION_PATTERN = re.compile(r'of ([A-Z][a-zA-Z\s\.]+),\s*([A-Z][a-zA-Z]+|\w{2})[\.\s]')
PHONE_PATTERN = re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

# State abbreviation mapping
STATE_ABBREVS = {
    'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA',
    'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'Florida': 'FL', 'Georgia': 'GA',
    'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA',
    'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD',
    'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS',
    'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH',
    'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC',
    'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA',
    'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN',
    'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA',
    'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY', 'District of Columbia': 'DC'
}


def normalize_state(state: str) -> str:
    """Convert state name to abbreviation if needed."""
    if len(state) == 2:
        return state.upper()
    return STATE_ABBREVS.get(state.title(), state)


def extract_from_snippet(body: str) -> dict:
    """Extract city, state, phone, email from D&B snippet."""
    result = {}

    # Location: "of City, State"
    loc_match = LOCATION_PATTERN.search(body)
    if loc_match:
        result['city'] = loc_match.group(1).strip()
        result['state'] = normalize_state(loc_match.group(2).strip())

    # Phone
    phone_match = PHONE_PATTERN.search(body)
    if phone_match:
        result['phone'] = phone_match.group(0)

    # Email
    email_match = EMAIL_PATTERN.search(body)
    if email_match:
        email = email_match.group(0)
        # Filter out generic emails
        if not any(x in email.lower() for x in ['example.com', 'dnb.com', 'dun']):
            result['email'] = email

    return result


def search_company(name: str) -> dict:
    """Search D&B for company contact info."""
    # Clean company name for search
    clean_name = name.split(',')[0].strip()  # Remove "Inc, Person Name" suffixes
    query = f'"{clean_name}" site:dnb.com'

    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=2))
            if results:
                # Combine snippets for more data
                combined = ' '.join(r.get('body', '') for r in results)
                return extract_from_snippet(combined)
    except Exception as e:
        print(f"  Error searching {clean_name}: {e}")

    return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help="Don't save changes")
    parser.add_argument('--limit', type=int, default=None, help="Limit companies to process")
    args = parser.parse_args()

    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)

    # Find companies with missing contact data (prioritize LLC/Inc/Corp)
    candidates = []
    for c in data:
        missing_fields = []
        if not c.get('parsed_city'):
            missing_fields.append('city')
        if not c.get('parsed_state'):
            missing_fields.append('state')
        if not c.get('parsed_phone'):
            missing_fields.append('phone')
        if not c.get('parsed_email'):
            missing_fields.append('email')

        if missing_fields:
            # Prioritize companies with corporate suffixes (more likely in D&B)
            name = c.get('company_name', '')
            has_suffix = any(x in name.upper() for x in ['LLC', 'INC', 'CORP', 'LTD'])
            candidates.append((c, missing_fields, has_suffix))

    # Sort: corporate suffixes first
    candidates.sort(key=lambda x: (not x[2], x[0].get('company_name', '')))

    if args.limit:
        candidates = candidates[:args.limit]

    print(f"Found {len(candidates)} companies with missing contact data\n")

    stats = {'city': 0, 'state': 0, 'phone': 0, 'email': 0, 'searched': 0, 'updated': 0}

    for i, (company, missing, _) in enumerate(candidates):
        name = company['company_name']
        print(f"[{i+1}/{len(candidates)}] {name[:50]}...")

        result = search_company(name)
        stats['searched'] += 1

        updated = False
        if result.get('city') and 'city' in missing:
            company['parsed_city'] = result['city']
            company['parsed_city_source'] = 'dnb_search'
            stats['city'] += 1
            updated = True

        if result.get('state') and 'state' in missing:
            company['parsed_state'] = result['state']
            company['parsed_state_source'] = 'dnb_search'
            stats['state'] += 1
            updated = True

        if result.get('phone') and 'phone' in missing:
            company['parsed_phone'] = result['phone']
            company['parsed_phone_source'] = 'dnb_search'
            stats['phone'] += 1
            updated = True

        if result.get('email') and 'email' in missing:
            company['parsed_email'] = result['email']
            company['parsed_email_source'] = 'dnb_search'
            stats['email'] += 1
            updated = True

        if updated:
            stats['updated'] += 1
            print(f"  ✓ Found: {result}")
        else:
            print(f"  ✗ No data")

        time.sleep(1.2)  # Rate limiting

    print(f"\n=== Results ===")
    print(f"Searched: {stats['searched']}")
    print(f"Updated: {stats['updated']}")
    print(f"Cities filled: {stats['city']}")
    print(f"States filled: {stats['state']}")
    print(f"Phones filled: {stats['phone']}")
    print(f"Emails filled: {stats['email']}")

    if args.dry_run:
        print("\nDRY RUN - not saving")
    else:
        print(f"\nSaving to {OUTPUT_FILE}...")
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("Done!")

    return stats


if __name__ == "__main__":
    main()

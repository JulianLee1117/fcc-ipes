"""
Fill null/Unknown gaps in enrichment data via web search.

Targets: industry_segment, market_position, contact info
"""

import json
import time
import re
from pathlib import Path
from ddgs import DDGS

INPUT_FILE = Path("data/processed/companies_enriched.json")
OUTPUT_FILE = Path("data/processed/companies_enriched.json")

# Industry classification keywords
INDUSTRY_KEYWORDS = {
    "UCaaS": ["unified communications", "ucaas", "business phone", "cloud pbx", "voip phone system", "team collaboration"],
    "CCaaS": ["contact center", "ccaas", "call center", "customer service platform", "ivr"],
    "CPaaS": ["cpaas", "communication api", "sms api", "voice api", "programmable", "developer platform"],
    "Carrier": ["wholesale", "clec", "ilec", "carrier services", "interconnection", "switch", "tandem", "origination", "termination"],
    "Reseller": ["reseller", "resale", "white label", "partner program"],
}

# Market position signals
MARKET_SIGNALS = {
    "Enterprise": ["fortune 500", "enterprise", "large business", "global", "multinational", "thousands of employees"],
    "Mid-Market": ["mid-market", "mid-size", "growing business", "regional", "hundreds of employees"],
    "SMB": ["small business", "smb", "startup friendly", "affordable", "soho", "freelancer"],
    "Startup": ["seed funding", "series a", "founded 202", "founded 2019", "early stage", "beta"],
}

def search_company(name: str) -> str:
    """Search for company info, return combined snippets."""
    clean_name = re.sub(r'\s*,?\s*(LLC|Inc\.?|Corp\.?|L\.?L\.?C\.?).*$', '', name, flags=re.IGNORECASE).strip()
    query = f'"{clean_name}" company'

    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=5))
            if results:
                return ' '.join(r.get('body', '') + ' ' + r.get('title', '') for r in results)
    except Exception as e:
        print(f"  Search error: {e}")
    return ""

def classify_industry(text: str) -> str | None:
    """Classify industry based on search text."""
    text_lower = text.lower()
    scores = {}

    for industry, keywords in INDUSTRY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[industry] = score

    if scores:
        return max(scores, key=scores.get)
    return None

def classify_market_position(text: str, industry: str, is_active: bool) -> str | None:
    """Classify market position based on search text and other signals."""
    text_lower = text.lower()

    # Direct keyword matches
    for position, keywords in MARKET_SIGNALS.items():
        if any(kw in text_lower for kw in keywords):
            return position

    # Heuristics based on industry
    if industry in ["UCaaS", "CCaaS", "CPaaS"]:
        return "SMB"  # Most UCaaS/CCaaS/CPaaS target SMB

    if not is_active:
        return None  # Can't determine for inactive companies without signals

    return None

def extract_location(text: str) -> tuple[str | None, str | None]:
    """Extract city, state from search results."""
    # Pattern: "of City, State" or "based in City, State" or "City, ST"
    patterns = [
        r'(?:of|in|based in|located in|headquarters in)\s+([A-Z][a-zA-Z\s\.]+),\s*([A-Z]{2})\b',
        r'([A-Z][a-zA-Z]+),\s*([A-Z]{2})\s+(?:\d{5}|United States)',
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, None

def main():
    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)

    # Find companies needing updates
    needs_industry = [c for c in data if c.get('industry_segment') in [None, 'Unknown']]
    needs_market = [c for c in data if c.get('market_position') in [None, 'Unknown']]
    needs_location = [c for c in data if not c.get('parsed_city') or not c.get('parsed_state')]

    # Combine into unique set
    to_search = {}
    for c in needs_industry + needs_market + needs_location:
        to_search[c['company_name']] = c

    print(f"Companies needing updates: {len(to_search)}")
    print(f"  - Unknown industry: {len(needs_industry)}")
    print(f"  - Unknown market_position: {len(needs_market)}")
    print(f"  - Missing location: {len(needs_location)}")

    stats = {'industry': 0, 'market': 0, 'city': 0, 'state': 0, 'searched': 0}

    for i, (name, company) in enumerate(to_search.items()):
        print(f"\n[{i+1}/{len(to_search)}] {name[:50]}...")

        text = search_company(name)
        stats['searched'] += 1

        if not text:
            print("  No results")
            time.sleep(1)
            continue

        # Fill industry if needed
        if company.get('industry_segment') in [None, 'Unknown']:
            industry = classify_industry(text)
            if industry:
                company['industry_segment'] = industry
                company['industry_segment_source'] = 'gap_fill_search'
                stats['industry'] += 1
                print(f"  → industry: {industry}")

        # Fill market position if needed
        if company.get('market_position') in [None, 'Unknown']:
            market = classify_market_position(
                text,
                company.get('industry_segment', ''),
                company.get('is_active', False)
            )
            if market:
                company['market_position'] = market
                company['market_position_source'] = 'gap_fill_search'
                stats['market'] += 1
                print(f"  → market: {market}")

        # Fill location if needed
        if not company.get('parsed_city') or not company.get('parsed_state'):
            city, state = extract_location(text)
            if city and not company.get('parsed_city'):
                company['parsed_city'] = city
                company['parsed_city_source'] = 'gap_fill_search'
                stats['city'] += 1
                print(f"  → city: {city}")
            if state and not company.get('parsed_state'):
                company['parsed_state'] = state
                company['parsed_state_source'] = 'gap_fill_search'
                stats['state'] += 1
                print(f"  → state: {state}")

        time.sleep(1.2)  # Rate limiting

    # Save
    print(f"\n\nSaving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("\n=== Results ===")
    print(f"Searched: {stats['searched']}")
    print(f"Industry filled: {stats['industry']}")
    print(f"Market position filled: {stats['market']}")
    print(f"Cities filled: {stats['city']}")
    print(f"States filled: {stats['state']}")

    # Final counts
    remaining_industry = sum(1 for c in data if c.get('industry_segment') in [None, 'Unknown'])
    remaining_market = sum(1 for c in data if c.get('market_position') in [None, 'Unknown'])
    print(f"\nRemaining Unknown industry: {remaining_industry}")
    print(f"Remaining Unknown market_position: {remaining_market}")

if __name__ == "__main__":
    main()

"""
Fill remaining enrichment gaps using targeted searches and stronger heuristics.
Different approach from fill_contact_gaps.py - uses LinkedIn/Crunchbase searches
and filing-based rules.
"""

import json
import time
import re
from pathlib import Path
from ddgs import DDGS

INPUT_FILE = Path("data/processed/companies_enriched.json")
OUTPUT_FILE = Path("data/processed/companies_enriched.json")

def search_linkedin(name: str) -> str:
    """Search LinkedIn for company info."""
    clean = re.sub(r'\s*,?\s*(LLC|Inc\.?|Corp\.?|L\.?L\.?C\.?).*$', '', name, flags=re.IGNORECASE).strip()
    query = f'"{clean}" site:linkedin.com/company'
    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=3))
            return ' '.join(r.get('body', '') + ' ' + r.get('title', '') for r in results)
    except:
        return ""

def search_crunchbase(name: str) -> str:
    """Search Crunchbase for company info."""
    clean = re.sub(r'\s*,?\s*(LLC|Inc\.?|Corp\.?|L\.?L\.?C\.?).*$', '', name, flags=re.IGNORECASE).strip()
    query = f'"{clean}" site:crunchbase.com'
    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=3))
            return ' '.join(r.get('body', '') + ' ' + r.get('title', '') for r in results)
    except:
        return ""

def search_zoominfo(name: str) -> str:
    """Search ZoomInfo for company size info."""
    clean = re.sub(r'\s*,?\s*(LLC|Inc\.?|Corp\.?|L\.?L\.?C\.?).*$', '', name, flags=re.IGNORECASE).strip()
    query = f'"{clean}" site:zoominfo.com'
    try:
        with DDGS() as ddg:
            results = list(ddg.text(query, max_results=2))
            return ' '.join(r.get('body', '') + ' ' + r.get('title', '') for r in results)
    except:
        return ""

def infer_market_from_text(text: str) -> str | None:
    """Infer market position from search results."""
    text_lower = text.lower()

    # Employee count patterns
    emp_patterns = [
        (r'(\d+,?\d*)\s*(?:employees|staff|workers)', 'employees'),
        (r'(\d+)-(\d+)\s*employees', 'range'),
        (r'company size[:\s]+(\d+)', 'size'),
    ]

    for pattern, ptype in emp_patterns:
        match = re.search(pattern, text_lower)
        if match:
            if ptype == 'range':
                count = int(match.group(2).replace(',', ''))
            else:
                count = int(match.group(1).replace(',', ''))

            if count >= 1000:
                return "Enterprise"
            elif count >= 100:
                return "Mid-Market"
            elif count >= 10:
                return "SMB"
            else:
                return "Startup"

    # Revenue patterns
    rev_patterns = [
        (r'\$(\d+)\s*(?:billion|B)\s*(?:revenue)?', 'billion'),
        (r'\$(\d+)\s*(?:million|M)\s*(?:revenue)?', 'million'),
    ]

    for pattern, scale in rev_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount = int(match.group(1))
            if scale == 'billion' or (scale == 'million' and amount > 100):
                return "Enterprise"
            elif scale == 'million' and amount > 10:
                return "Mid-Market"
            else:
                return "SMB"

    # Keyword signals
    if any(x in text_lower for x in ['fortune 500', 'enterprise', 'global leader', 'multinational']):
        return "Enterprise"
    if any(x in text_lower for x in ['mid-market', 'regional', 'growing']):
        return "Mid-Market"
    if any(x in text_lower for x in ['small business', 'smb', 'startup', 'founded 202']):
        return "SMB"

    return None

def infer_industry_from_text(text: str) -> str | None:
    """Infer industry segment from search results."""
    text_lower = text.lower()

    scores = {
        "UCaaS": sum(1 for kw in ['unified communications', 'ucaas', 'cloud pbx', 'voip phone', 'business phone', 'collaboration'] if kw in text_lower),
        "CCaaS": sum(1 for kw in ['contact center', 'call center', 'ccaas', 'customer service', 'ivr'] if kw in text_lower),
        "CPaaS": sum(1 for kw in ['api', 'cpaas', 'developer', 'programmable', 'sms api', 'voice api'] if kw in text_lower),
        "Carrier": sum(1 for kw in ['wholesale', 'carrier', 'clec', 'interconnect', 'switch', 'termination', 'origination'] if kw in text_lower),
    }

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return None

def apply_filing_rules(company: dict) -> str | None:
    """Infer market position from filing patterns."""
    fs = company.get('filing_signals', {})
    total = fs.get('total_filings', 0)
    recent = fs.get('recent_activity', False)
    industry = company.get('industry_segment', '')
    is_active = company.get('is_active', False)

    # High filing activity suggests established player
    if total >= 5 and recent:
        return "Mid-Market"

    # Single filing + inactive = likely failed startup or small carrier
    if total == 1 and not is_active:
        if industry == 'Carrier':
            return "SMB"  # Small regional carrier
        return "Startup"  # Failed startup

    # Active carriers with few filings = regional/SMB
    if industry == 'Carrier' and is_active and total <= 2:
        return "SMB"

    # Inactive carriers with moderate filings = was mid-market
    if industry == 'Carrier' and not is_active and total >= 3:
        return "Mid-Market"

    return None

def main():
    print(f"Loading {INPUT_FILE}...")
    with open(INPUT_FILE) as f:
        data = json.load(f)

    # Find remaining unknowns
    unknowns = [c for c in data if c.get('market_position') == 'Unknown' or c.get('industry_segment') == 'Unknown']
    print(f"Found {len(unknowns)} companies with Unknown values\n")

    stats = {'market': 0, 'industry': 0, 'rule_based': 0}

    for i, company in enumerate(unknowns):
        name = company['company_name']
        print(f"[{i+1}/{len(unknowns)}] {name[:50]}...")

        needs_market = company.get('market_position') == 'Unknown'
        needs_industry = company.get('industry_segment') == 'Unknown'

        # Try filing-based rules first (no API calls)
        if needs_market:
            rule_market = apply_filing_rules(company)
            if rule_market:
                company['market_position'] = rule_market
                company['market_position_source'] = 'filing_rules'
                stats['market'] += 1
                stats['rule_based'] += 1
                print(f"  → market (rule): {rule_market}")
                needs_market = False

        # Search if still need info
        if needs_market or needs_industry:
            all_text = ""

            # Try LinkedIn first
            linkedin = search_linkedin(name)
            if linkedin:
                all_text += linkedin + " "
                time.sleep(0.8)

            # Try Crunchbase
            crunchbase = search_crunchbase(name)
            if crunchbase:
                all_text += crunchbase + " "
                time.sleep(0.8)

            # Try ZoomInfo for employee counts
            if needs_market:
                zoominfo = search_zoominfo(name)
                if zoominfo:
                    all_text += zoominfo + " "
                    time.sleep(0.8)

            if all_text:
                if needs_market:
                    market = infer_market_from_text(all_text)
                    if market:
                        company['market_position'] = market
                        company['market_position_source'] = 'gap_fill_v2'
                        stats['market'] += 1
                        print(f"  → market (search): {market}")

                if needs_industry:
                    industry = infer_industry_from_text(all_text)
                    if industry:
                        company['industry_segment'] = industry
                        company['industry_segment_source'] = 'gap_fill_v2'
                        stats['industry'] += 1
                        print(f"  → industry (search): {industry}")

        time.sleep(0.5)

    # Save
    print(f"\n\nSaving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # Final stats
    remaining_market = sum(1 for c in data if c.get('market_position') == 'Unknown')
    remaining_industry = sum(1 for c in data if c.get('industry_segment') == 'Unknown')

    print("\n=== Results ===")
    print(f"Market positions filled: {stats['market']} ({stats['rule_based']} rule-based)")
    print(f"Industries filled: {stats['industry']}")
    print(f"\nRemaining Unknown market_position: {remaining_market}")
    print(f"Remaining Unknown industry: {remaining_industry}")

if __name__ == "__main__":
    main()

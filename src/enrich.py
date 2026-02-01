"""
Phase 5: AI-powered enrichment of company records.

Pipeline:
1. Parse document text (regex, no API)
2. Extract filing signals (from existing data, no API)
3. Web search (DuckDuckGo via ddgs, no API key)
4. LLM synthesis (Claude Sonnet via Anthropic API)
"""

import json
import os
import re
import time
import csv
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Step 1: Document Text Parsing
# ============================================================================

def parse_fcc_document(text: str) -> dict:
    """
    Extract structured fields from FCC application document text.
    Targets standard § 52.15(g)(3)(i) format.
    """
    result = {
        "address": None,
        "city": None,
        "state": None,
        "zip_code": None,
        "phone": None,
        "email": None,
        "key_personnel": [],
        "founding_date": None,
        "service_description": None,
    }

    if not text:
        return result

    # Address extraction - look for patterns after § 52.15(g)(3)(i)(A) section
    # Pattern: Name: ... Address: ... City: ... State: ... ZIP:
    address_match = re.search(
        r'Address:\s*(.+?)(?:\n|City:|$)',
        text, re.IGNORECASE | re.DOTALL
    )
    if address_match:
        result["address"] = address_match.group(1).strip()

    city_match = re.search(r'City:\s*(\w+)', text, re.IGNORECASE)
    if city_match:
        result["city"] = city_match.group(1).strip()

    state_match = re.search(r'State:\s*(\w{2})', text, re.IGNORECASE)
    if state_match:
        result["state"] = state_match.group(1).strip().upper()

    zip_match = re.search(r'ZIP\s*(?:Code)?:\s*(\d{5}(?:-\d{4})?)', text, re.IGNORECASE)
    if zip_match:
        result["zip_code"] = zip_match.group(1).strip()

    # Phone extraction
    phone_match = re.search(r'Telephone:\s*([\d\-\.\(\)\s]+)', text, re.IGNORECASE)
    if phone_match:
        phone = re.sub(r'[^\d]', '', phone_match.group(1))
        if len(phone) >= 10:
            result["phone"] = phone[:10]  # Normalize to 10 digits

    # Email extraction
    email_match = re.search(r'Email:\s*([\w\.\-]+@[\w\.\-]+\.\w+)', text, re.IGNORECASE)
    if email_match:
        result["email"] = email_match.group(1).strip()

    # Key personnel extraction - look for titles like President, CEO, CFO, CTO
    personnel_patterns = [
        r'(?:Name:|Contact:)\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?),?\s*(President|CEO|CFO|CTO|COO|Chief\s+\w+\s+Officer)',
        r'(President|CEO|CFO|CTO|COO|Chief\s+\w+\s+Officer)[:\s]+([A-Z][a-z]+\s+[A-Z][a-z]+)',
        r'([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:is|as|serves as)\s+(?:the\s+)?(President|CEO|CFO|CTO)',
    ]

    for pattern in personnel_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            groups = match.groups()
            if len(groups) >= 2:
                name = groups[0].strip() if not groups[0].upper() in ['PRESIDENT', 'CEO', 'CFO', 'CTO', 'COO'] else groups[1].strip()
                title = groups[1].strip() if groups[0].upper() not in ['PRESIDENT', 'CEO', 'CFO', 'CTO', 'COO'] else groups[0].strip()
                if name and title and len(name) > 3:
                    result["key_personnel"].append({"name": name, "title": title})

    # Founding date extraction
    founding_patterns = [
        r'(?:founded|established|incorporated|formed)\s+(?:in\s+)?(\d{4})',
        r'since\s+(\d{4})',
        r'(?:founded|established|incorporated|formed)\s+(?:in\s+)?([A-Za-z]+\s+\d{4})',
    ]

    for pattern in founding_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["founding_date"] = match.group(1)
            break

    # Service description - extract text around "interconnected VoIP" mentions
    voip_match = re.search(
        r'(?:provides?|offers?|delivers?)[^.]*(?:interconnected\s+VoIP|VoIP\s+services?)[^.]*\.',
        text, re.IGNORECASE
    )
    if voip_match:
        result["service_description"] = voip_match.group(0).strip()

    return result


def sanitize_filename(filename: str) -> str:
    """
    Match the sanitization logic from download_docs.py exactly.
    This ensures we can find text files by their expected names.
    """
    # Replace problematic characters with underscore
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Collapse multiple underscores/spaces into single underscore
    filename = re.sub(r'[_\s]+', '_', filename)
    # Truncate to 100 chars (matching download script)
    if len(filename) > 100:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:95] + ('.' + ext if ext else '')
    return filename


def get_document_text(company: dict, text_dir: Path) -> str:
    """Get concatenated text from all documents for a company."""
    texts = []

    for doc in company.get("documents", []):
        filing_id = doc.get("filing_id", "")
        filename = doc.get("filename", "")

        if not filing_id or not filename:
            continue

        # Build expected text filename using same sanitization as download script
        sanitized = sanitize_filename(filename)
        base_name = Path(sanitized).stem
        text_filename = f"{filing_id}_{base_name}.txt"
        text_path = text_dir / text_filename

        if text_path.exists():
            try:
                with open(text_path, encoding='utf-8', errors='ignore') as f:
                    texts.append(f.read())
            except Exception:
                pass

    return "\n\n---\n\n".join(texts)


# ============================================================================
# Step 2: Filing Signals
# ============================================================================

def compute_filing_signals(company: dict) -> dict:
    """Derive activity indicators from filing metadata."""
    signals = {
        "total_filings": company.get("total_filing_count", 0),
        "application_count": company.get("application_count", 0),
        "has_multiple_filings": company.get("total_filing_count", 0) > 1,
        "has_supplements": False,
        "has_amendments": False,
        "docket_count": len(company.get("docket_numbers", [])),
        "first_filing_date": company.get("first_filing_date"),
        "latest_filing_date": company.get("latest_filing_date"),
        "years_active": None,
        "recent_activity": False,  # Filing within last 2 years
    }

    # Check filing types
    for filing in company.get("filings", []):
        ftype = filing.get("type", "").upper()
        if ftype == "SUPPLEMENT":
            signals["has_supplements"] = True
        elif ftype == "AMENDMENT":
            signals["has_amendments"] = True

    # Calculate years active
    if signals["first_filing_date"] and signals["latest_filing_date"]:
        try:
            first = datetime.strptime(signals["first_filing_date"], "%Y-%m-%d")
            latest = datetime.strptime(signals["latest_filing_date"], "%Y-%m-%d")
            signals["years_active"] = round((latest - first).days / 365, 1)

            # Recent activity = filing within last 2 years
            today = datetime.now()
            signals["recent_activity"] = (today - latest).days < 730
        except ValueError:
            pass

    return signals


# ============================================================================
# Step 3: Web Search (DuckDuckGo)
# ============================================================================

def web_search(company_name: str, max_results: int = 5) -> list[dict]:
    """
    Search for company info via DuckDuckGo.
    Returns list of {title, href, body} dicts.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        print("Warning: ddgs not installed. Run: pip install ddgs")
        return []

    query = f'"{company_name}" VoIP telecommunications'

    try:
        results = DDGS().text(query, max_results=max_results)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", "")
            }
            for r in results
        ] if results else []
    except Exception as e:
        print(f"  Web search error for {company_name}: {e}")
        return []


def batch_web_search(companies: list[dict], delay: float = 1.0) -> dict:
    """
    Run web searches for all companies with rate limiting.
    Returns dict mapping company_name_normalized -> search results.
    """
    results = {}
    total = len(companies)

    print(f"\nRunning web searches for {total} companies...")

    for i, company in enumerate(companies, 1):
        name = company.get("company_name", "")
        normalized = company.get("company_name_normalized", "")

        if i % 20 == 0:
            print(f"  Progress: {i}/{total}")

        results[normalized] = web_search(name)

        if i < total:
            time.sleep(delay)

    return results


# ============================================================================
# Step 4: LLM Synthesis (Anthropic Claude)
# ============================================================================

ENRICHMENT_SCHEMA = {
    "name": "enrichment_result",
    "description": "Structured enrichment data for an IPES company",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_active": {
                "type": "boolean",
                "description": "Is the company currently operating? Base on evidence."
            },
            "activity_signal": {
                "type": "string",
                "description": "Evidence supporting the is_active determination. Cite specific sources."
            },
            "industry_segment": {
                "type": "string",
                "enum": ["UCaaS", "CCaaS", "CPaaS", "Carrier", "Reseller", "Enterprise IT", "Other", "Unknown"],
                "description": "Primary industry segment"
            },
            "product_summary": {
                "type": "string",
                "description": "1-2 sentence description of what the company does"
            },
            "market_position": {
                "type": "string",
                "enum": ["Enterprise", "Mid-Market", "SMB", "Startup", "Unknown"],
                "description": "Target market segment"
            },
            "enrichment_confidence": {
                "type": "string",
                "enum": ["High", "Medium", "Low"],
                "description": "Confidence in enrichment quality based on evidence diversity"
            }
        },
        "required": ["is_active", "activity_signal", "industry_segment", "product_summary", "market_position", "enrichment_confidence"]
    }
}


def build_evidence_pack(company: dict, parsed_docs: dict, filing_signals: dict, web_results: list) -> dict:
    """Build evidence pack for LLM synthesis."""
    return {
        "company_name": company.get("company_name"),
        "aliases": company.get("name_variations", []),
        "fcc_filing": {
            "first_filing_date": filing_signals.get("first_filing_date"),
            "latest_filing_date": filing_signals.get("latest_filing_date"),
            "total_filings": filing_signals.get("total_filings"),
            "docket_numbers": company.get("docket_numbers", []),
            "proceeding_types": company.get("proceeding_types", []),
            "has_supplements": filing_signals.get("has_supplements"),
            "recent_activity": filing_signals.get("recent_activity"),
        },
        "parsed_from_docs": parsed_docs,
        "web_search_results": web_results[:5] if web_results else [],
    }


def build_prompt(evidence_pack: dict) -> str:
    """Build the prompt for LLM enrichment."""
    return f"""You are analyzing an IPES (Interconnected VoIP Provider) company that filed for numbering authorization with the FCC.

Based ONLY on the evidence provided below, determine:
1. Whether the company is likely still active
2. Their industry segment (UCaaS, CCaaS, CPaaS, Carrier, Reseller, Enterprise IT, or Other)
3. A brief product summary
4. Their market position (Enterprise, Mid-Market, SMB, Startup, or Unknown)
5. Your confidence level based on evidence quality

EVIDENCE PACK:
{json.dumps(evidence_pack, indent=2, default=str)}

RULES:
- Ground ALL assessments in the provided evidence
- Cite specific sources in activity_signal (e.g., "Recent FCC filing (2024)", "Company website found via search")
- Use "Unknown" when evidence is insufficient - DO NOT hallucinate
- Confidence levels:
  - High = Multiple confirming signals (recent web presence + recent filings + company details)
  - Medium = Some signals but incomplete picture
  - Low = FCC data only, no external confirmation

Call the enrichment_result function with your analysis."""


def enrich_with_llm(evidence_pack: dict, client, logs_dir: Path) -> dict:
    """Call Claude API to synthesize enrichment."""
    prompt = build_prompt(evidence_pack)
    company_name = evidence_pack.get("company_name", "unknown")

    # Save prompt
    safe_name = re.sub(r'[^\w\-]', '_', company_name)[:50]
    prompt_file = logs_dir / f"{safe_name}_prompt.txt"
    with open(prompt_file, 'w') as f:
        f.write(prompt)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            tools=[ENRICHMENT_SCHEMA],
            tool_choice={"type": "tool", "name": "enrichment_result"},
            messages=[{"role": "user", "content": prompt}]
        )

        # Save response
        response_file = logs_dir / f"{safe_name}_response.json"
        with open(response_file, 'w') as f:
            json.dump(response.model_dump(), f, indent=2, default=str)

        # Extract tool use result
        for block in response.content:
            if block.type == "tool_use" and block.name == "enrichment_result":
                return block.input

        return {"error": "No tool use in response"}

    except Exception as e:
        error_file = logs_dir / f"{safe_name}_error.txt"
        with open(error_file, 'w') as f:
            f.write(str(e))
        return {"error": str(e)}


def batch_llm_enrichment(
    companies: list[dict],
    parsed_docs: dict,
    filing_signals: dict,
    web_results: dict,
    logs_dir: Path,
    max_workers: int = 5
) -> dict:
    """Run LLM enrichment for all companies."""
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in environment")

    client = anthropic.Anthropic(api_key=api_key)
    results = {}
    total = len(companies)

    print(f"\nRunning LLM enrichment for {total} companies...")
    logs_dir.mkdir(parents=True, exist_ok=True)

    def enrich_one(company: dict) -> tuple[str, dict]:
        normalized = company.get("company_name_normalized", "")
        evidence = build_evidence_pack(
            company,
            parsed_docs.get(normalized, {}),
            filing_signals.get(normalized, {}),
            web_results.get(normalized, [])
        )
        result = enrich_with_llm(evidence, client, logs_dir)
        return normalized, result

    completed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(enrich_one, c): c for c in companies}

        for future in as_completed(futures):
            normalized, result = future.result()
            results[normalized] = result
            completed += 1
            if completed % 20 == 0:
                print(f"  Progress: {completed}/{total}")

    return results


# ============================================================================
# Main Pipeline
# ============================================================================

def run_enrichment(
    companies_file: Path,
    text_dir: Path,
    output_json: Path,
    output_csv: Path,
    logs_dir: Path
) -> dict:
    """Run the full enrichment pipeline."""

    # Load companies
    print("Loading companies...")
    with open(companies_file) as f:
        companies = json.load(f)
    print(f"  Loaded {len(companies)} companies")

    # Step 1: Parse documents
    print("\nStep 1: Parsing document text...")
    parsed_docs = {}
    for company in companies:
        normalized = company.get("company_name_normalized", "")
        doc_text = get_document_text(company, text_dir)
        if doc_text:
            parsed_docs[normalized] = parse_fcc_document(doc_text)
    print(f"  Parsed docs for {len(parsed_docs)} companies")

    # Step 2: Compute filing signals
    print("\nStep 2: Computing filing signals...")
    filing_signals = {}
    for company in companies:
        normalized = company.get("company_name_normalized", "")
        filing_signals[normalized] = compute_filing_signals(company)
    print(f"  Computed signals for {len(filing_signals)} companies")

    # Step 3: Web search
    print("\nStep 3: Running web searches...")
    web_results = batch_web_search(companies, delay=1.0)
    companies_with_results = sum(1 for v in web_results.values() if v)
    print(f"  Found results for {companies_with_results}/{len(companies)} companies")

    # Step 4: LLM enrichment
    print("\nStep 4: Running LLM enrichment...")
    llm_results = batch_llm_enrichment(
        companies, parsed_docs, filing_signals, web_results, logs_dir
    )

    # Merge results
    print("\nMerging results...")
    enriched = []
    for company in companies:
        normalized = company.get("company_name_normalized", "")
        llm_data = llm_results.get(normalized, {})

        enriched_company = {
            **company,
            "is_active": llm_data.get("is_active"),
            "activity_signal": llm_data.get("activity_signal"),
            "industry_segment": llm_data.get("industry_segment"),
            "product_summary": llm_data.get("product_summary"),
            "market_position": llm_data.get("market_position"),
            "enrichment_confidence": llm_data.get("enrichment_confidence"),
            "enrichment_sources": [],
            "parsed_address": parsed_docs.get(normalized, {}).get("address"),
            "parsed_city": parsed_docs.get(normalized, {}).get("city"),
            "parsed_state": parsed_docs.get(normalized, {}).get("state"),
            "parsed_phone": parsed_docs.get(normalized, {}).get("phone"),
            "parsed_email": parsed_docs.get(normalized, {}).get("email"),
            "parsed_founding_date": parsed_docs.get(normalized, {}).get("founding_date"),
            "parsed_key_personnel": parsed_docs.get(normalized, {}).get("key_personnel", []),
            "filing_signals": filing_signals.get(normalized, {}),
        }

        # Build enrichment sources list
        sources = []
        if parsed_docs.get(normalized):
            sources.append("fcc_documents")
        if filing_signals.get(normalized, {}).get("total_filings", 0) > 0:
            sources.append("fcc_filings")
        if web_results.get(normalized):
            sources.extend([r.get("url") for r in web_results.get(normalized, [])[:3] if r.get("url")])
        enriched_company["enrichment_sources"] = sources

        enriched.append(enriched_company)

    # Save JSON
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, 'w') as f:
        json.dump(enriched, f, indent=2, default=str)
    print(f"\nSaved: {output_json}")

    # Save CSV
    csv_fields = [
        "company_name", "company_name_normalized", "dba_name",
        "is_active", "activity_signal", "industry_segment",
        "product_summary", "market_position", "enrichment_confidence",
        "first_filing_date", "latest_filing_date", "total_filing_count",
        "parsed_state", "parsed_city", "parsed_phone", "parsed_email",
        "parsed_founding_date"
    ]

    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()
        for company in enriched:
            row = {k: company.get(k) for k in csv_fields}
            # Flatten nested fields
            row["total_filing_count"] = company.get("total_filing_count")
            writer.writerow(row)
    print(f"Saved: {output_csv}")

    # Stats
    stats = {
        "total_companies": len(enriched),
        "with_parsed_docs": len(parsed_docs),
        "with_web_results": companies_with_results,
        "enrichment_confidence": {
            "High": sum(1 for c in enriched if c.get("enrichment_confidence") == "High"),
            "Medium": sum(1 for c in enriched if c.get("enrichment_confidence") == "Medium"),
            "Low": sum(1 for c in enriched if c.get("enrichment_confidence") == "Low"),
        },
        "active_companies": sum(1 for c in enriched if c.get("is_active") is True),
        "industry_segments": {},
    }

    for company in enriched:
        seg = company.get("industry_segment", "Unknown")
        stats["industry_segments"][seg] = stats["industry_segments"].get(seg, 0) + 1

    return stats


def main():
    base = Path(__file__).parent.parent

    stats = run_enrichment(
        companies_file=base / "data" / "processed" / "companies.json",
        text_dir=base / "documents" / "text",
        output_json=base / "data" / "processed" / "companies_enriched.json",
        output_csv=base / "data" / "processed" / "companies_enriched.csv",
        logs_dir=base / "data" / "processed" / "enrichment_logs"
    )

    print("\n" + "=" * 50)
    print("ENRICHMENT COMPLETE")
    print("=" * 50)
    print(f"Total companies: {stats['total_companies']}")
    print(f"With parsed docs: {stats['with_parsed_docs']}")
    print(f"With web results: {stats['with_web_results']}")
    print(f"\nActive companies: {stats['active_companies']}")
    print(f"\nConfidence distribution:")
    for level, count in stats['enrichment_confidence'].items():
        print(f"  {level}: {count}")
    print(f"\nIndustry segments:")
    for seg, count in sorted(stats['industry_segments'].items(), key=lambda x: -x[1]):
        print(f"  {seg}: {count}")


if __name__ == "__main__":
    main()

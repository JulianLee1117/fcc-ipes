"""
Phase 1: Extract filings from FCC ECFS API

Two-query union approach:
- Query 1: "Numbering Authorization Application" (standard IPES + INBOX-52.15)
- Query 2: 52.15(g) (edge cases like HDC, Stratus)

Deduplicates by id_submission.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

API_BASE = "https://publicapi.fcc.gov/ecfs/filings"
LIMIT = 25


def get_api_key() -> str:
    key = os.environ.get("FCC_API_KEY")
    if not key:
        raise ValueError("FCC_API_KEY environment variable not set")
    return key


def fetch_page(query: str, offset: int, api_key: str) -> dict:
    """Fetch a single page from the ECFS API."""
    params = {
        "q": query,
        "limit": LIMIT,
        "offset": offset,
        "sort": "date_received,DESC",
    }
    url = f"{API_BASE}?{urlencode(params)}"
    headers = {"X-Api-Key": api_key}

    for attempt in range(3):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def fetch_all_filings(query: str, api_key: str) -> list[dict]:
    """Fetch all filings for a query with pagination."""
    filings = []
    offset = 0
    total = None

    while True:
        print(f"  Fetching offset={offset}...")
        data = fetch_page(query, offset, api_key)

        batch = data.get("filings", data.get("filing", []))
        if not batch:
            break

        filings.extend(batch)

        # Get total from aggregations on first request
        if total is None:
            aggs = data.get("aggregations", {})
            total = aggs.get("total", {}).get("value", "unknown")
            print(f"  Total filings for query: {total}")

        offset += LIMIT

        # Rate limiting
        time.sleep(0.5)

        # Safety check
        if offset > 5000:
            print("  Warning: reached 5000 offset limit")
            break

    return filings


def extract_filings(output_dir: Path) -> dict:
    """
    Run both queries, deduplicate, and save results.

    Returns metadata about the extraction.
    """
    api_key = get_api_key()

    queries = [
        '"Numbering Authorization Application"',
        '52.15(g)',
    ]

    all_filings = {}
    query_stats = []

    for query in queries:
        print(f"\nFetching: {query}")
        filings = fetch_all_filings(query, api_key)

        count_before = len(all_filings)
        for f in filings:
            submission_id = f.get("id_submission")
            if submission_id and submission_id not in all_filings:
                all_filings[submission_id] = f
        count_after = len(all_filings)

        new_count = count_after - count_before
        query_stats.append({
            "query": query,
            "fetched": len(filings),
            "new_unique": new_count,
        })
        print(f"  Fetched {len(filings)}, {new_count} new unique")

    # Save to JSONL
    output_file = output_dir / "filings_raw.jsonl"
    with open(output_file, "w") as f:
        for filing in all_filings.values():
            f.write(json.dumps(filing) + "\n")

    print(f"\nSaved {len(all_filings)} unique filings to {output_file}")

    # Metadata
    meta = {
        "extraction_time": datetime.utcnow().isoformat() + "Z",
        "queries": query_stats,
        "total_unique_filings": len(all_filings),
        "output_file": str(output_file),
    }

    meta_file = output_dir / "extraction_meta.json"
    with open(meta_file, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"Saved metadata to {meta_file}")

    return meta


def main():
    from dotenv import load_dotenv
    load_dotenv()

    output_dir = Path(__file__).parent.parent / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = extract_filings(output_dir)

    print("\n=== Extraction Complete ===")
    print(f"Total unique filings: {meta['total_unique_filings']}")
    for q in meta["queries"]:
        print(f"  {q['query']}: {q['fetched']} fetched, {q['new_unique']} new")


if __name__ == "__main__":
    main()

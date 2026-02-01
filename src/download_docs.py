"""
Phase 4: Download all documents from IPES filings.

Downloads documents from FCC ECFS to documents/original/.
Handles FCC's quirky server requirements (HTTP/1.1, specific headers).
"""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

# FCC server requirements (from PRD section 3.5)
# Must match exact curl command that works:
# curl -L --tlsv1.2 --http1.1 -A 'PostmanRuntime/7.47.1' -H 'Accept: */*' -H 'Connection: keep-alive' -H 'Cookie: lmao=1' --compressed
HEADERS = {
    "User-Agent": "PostmanRuntime/7.47.1",
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Cookie": "lmao=1",
    "Accept-Encoding": "gzip, deflate",
}

# Concurrency and retry settings
MAX_CONCURRENT = 8
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 3, 10]  # seconds
TIMEOUT = 60.0


def transform_url(viewer_url: str) -> str:
    """
    Transform viewer URL to download URL.

    /ecfs/document/{id}/{seq} -> /ecfs/documents/{id}/{seq}
    (singular to plural)
    """
    return viewer_url.replace("/ecfs/document/", "/ecfs/documents/")


def sanitize_filename(filename: str) -> str:
    """Remove/replace characters that are problematic in filenames."""
    # Replace problematic characters
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Collapse multiple underscores/spaces
    filename = re.sub(r'[_\s]+', '_', filename)
    # Limit length
    if len(filename) > 100:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:95] + ('.' + ext if ext else '')
    return filename


async def download_document(
    client: httpx.AsyncClient,
    doc: dict,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Download a single document with retries.

    Returns result dict with status info.
    """
    viewer_url = doc["url"]
    download_url = transform_url(viewer_url)
    filename = sanitize_filename(doc["filename"])
    filing_id = doc["filing_id"]

    # Build output filename: {filing_id}_{filename}
    output_filename = f"{filing_id}_{filename}"
    output_path = output_dir / output_filename

    # Skip if already downloaded
    if output_path.exists() and output_path.stat().st_size > 0:
        return {
            "url": viewer_url,
            "filename": output_filename,
            "status": "skipped",
            "message": "already exists",
        }

    result = {
        "url": viewer_url,
        "download_url": download_url,
        "filename": output_filename,
        "status": "failed",
        "message": None,
    }

    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(
                    download_url,
                    follow_redirects=True,
                    timeout=TIMEOUT,
                )

                if response.status_code == 200:
                    # Verify we got actual content (not an error page)
                    content = response.content
                    content_type = response.headers.get("content-type", "")

                    # Check for HTML error pages
                    if "text/html" in content_type and len(content) < 5000:
                        if b"error" in content.lower() or b"not found" in content.lower():
                            result["message"] = "HTML error page returned"
                            continue

                    # Save the file
                    output_path.write_bytes(content)
                    result["status"] = "success"
                    result["size"] = len(content)
                    result["content_type"] = content_type
                    return result

                elif response.status_code == 404:
                    result["message"] = "404 Not Found"
                    break  # Don't retry 404s

                else:
                    result["message"] = f"HTTP {response.status_code}"

            except httpx.TimeoutException:
                result["message"] = "Timeout"
            except httpx.RequestError as e:
                result["message"] = f"Request error: {type(e).__name__}"
            except Exception as e:
                result["message"] = f"Error: {str(e)}"

            # Wait before retry
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF[attempt])

    return result


async def download_all(companies_file: Path, output_dir: Path) -> dict:
    """
    Download all documents from companies.json.

    Returns stats about the download process.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load companies and extract all documents
    with open(companies_file) as f:
        companies = json.load(f)

    # Collect unique documents (by URL)
    docs_by_url = {}
    for company in companies:
        for doc in company.get("documents", []):
            url = doc.get("url")
            if url and url not in docs_by_url:
                docs_by_url[url] = doc

    docs = list(docs_by_url.values())
    print(f"Found {len(docs)} unique documents to download")

    # Create async client with HTTP/1.1 (required by FCC)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async with httpx.AsyncClient(
        headers=HEADERS,
        http2=False,  # Force HTTP/1.1
        verify=True,
    ) as client:
        # Download all documents
        tasks = [
            download_document(client, doc, output_dir, semaphore)
            for doc in docs
        ]

        results = []
        completed = 0

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result)
            completed += 1

            # Progress indicator
            if completed % 25 == 0 or completed == len(tasks):
                success = sum(1 for r in results if r["status"] == "success")
                skipped = sum(1 for r in results if r["status"] == "skipped")
                failed = sum(1 for r in results if r["status"] == "failed")
                print(f"  Progress: {completed}/{len(tasks)} "
                      f"(success: {success}, skipped: {skipped}, failed: {failed})")

    # Calculate stats
    stats = {
        "total_documents": len(docs),
        "success": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total_bytes": sum(r.get("size", 0) for r in results if r["status"] == "success"),
    }

    # Save failed downloads for debugging
    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        failed_file = output_dir.parent / "failed_downloads.json"
        with open(failed_file, "w") as f:
            json.dump(failed, f, indent=2)
        stats["failed_log"] = str(failed_file)

    return stats


def main():
    companies_file = Path(__file__).parent.parent / "data" / "processed" / "companies.json"
    output_dir = Path(__file__).parent.parent / "documents" / "original"

    print("=== Phase 4: Document Downloads ===")
    print(f"Source: {companies_file}")
    print(f"Output: {output_dir}")
    print()

    stats = asyncio.run(download_all(companies_file, output_dir))

    print()
    print("=== Download Complete ===")
    print(f"Total documents: {stats['total_documents']}")
    print(f"Successfully downloaded: {stats['success']}")
    print(f"Skipped (already exist): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    print(f"Total size: {stats['total_bytes'] / 1024 / 1024:.1f} MB")

    if stats.get("failed_log"):
        print(f"\nFailed downloads logged to: {stats['failed_log']}")


if __name__ == "__main__":
    main()

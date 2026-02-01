"""
Phase 4.5: Extract text from downloaded documents.

Extracts text from PDFs and DOCX files in documents/original/.
Saves plain text files to documents/text/.
"""

import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# PDF extraction
import pdfplumber

# DOCX extraction
from docx import Document as DocxDocument


def extract_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pdfplumber."""
    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        return f"[ERROR extracting PDF: {e}]"

    return "\n\n".join(text_parts)


def extract_docx(docx_path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        doc = DocxDocument(docx_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        return f"[ERROR extracting DOCX: {e}]"


def extract_doc(doc_path: Path) -> str:
    """Extract text from legacy DOC files using antiword."""
    import subprocess
    try:
        result = subprocess.run(
            ["antiword", str(doc_path)],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return result.stdout
        return f"[ERROR extracting DOC: {result.stderr}]"
    except FileNotFoundError:
        return "[ERROR: antiword not installed - skipping DOC file]"
    except Exception as e:
        return f"[ERROR extracting DOC: {e}]"


def process_file(input_path: Path, output_dir: Path) -> dict:
    """Process a single file and extract text."""
    suffix = input_path.suffix.lower()
    output_path = output_dir / (input_path.stem + ".txt")

    # Skip if already extracted
    if output_path.exists() and output_path.stat().st_size > 0:
        return {
            "file": input_path.name,
            "status": "skipped",
            "message": "already exists"
        }

    # Extract based on file type
    if suffix == ".pdf":
        text = extract_pdf(input_path)
    elif suffix == ".docx":
        text = extract_docx(input_path)
    elif suffix == ".doc":
        text = extract_doc(input_path)
    else:
        return {
            "file": input_path.name,
            "status": "skipped",
            "message": f"unsupported format: {suffix}"
        }

    # Check for errors
    if text.startswith("[ERROR"):
        return {
            "file": input_path.name,
            "status": "failed",
            "message": text
        }

    # Save extracted text
    output_path.write_text(text, encoding="utf-8")

    return {
        "file": input_path.name,
        "status": "success",
        "output": output_path.name,
        "chars": len(text),
        "words": len(text.split())
    }


def extract_all(input_dir: Path, output_dir: Path, max_workers: int = 4) -> dict:
    """Extract text from all documents in input_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect files to process
    files = []
    for ext in ["*.pdf", "*.docx", "*.doc"]:
        files.extend(input_dir.glob(ext))

    print(f"Found {len(files)} documents to process")

    results = []
    completed = 0

    # Process files (use ProcessPoolExecutor for CPU-bound PDF extraction)
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_file, f, output_dir): f
            for f in files
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1

            if completed % 50 == 0 or completed == len(files):
                success = sum(1 for r in results if r["status"] == "success")
                skipped = sum(1 for r in results if r["status"] == "skipped")
                failed = sum(1 for r in results if r["status"] == "failed")
                print(f"  Progress: {completed}/{len(files)} "
                      f"(success: {success}, skipped: {skipped}, failed: {failed})")

    # Calculate stats
    stats = {
        "total_files": len(files),
        "success": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "failed"),
        "total_chars": sum(r.get("chars", 0) for r in results),
        "total_words": sum(r.get("words", 0) for r in results),
    }

    # Log failures
    failed = [r for r in results if r["status"] == "failed"]
    if failed:
        failed_file = output_dir.parent / "failed_extractions.json"
        with open(failed_file, "w") as f:
            json.dump(failed, f, indent=2)
        stats["failed_log"] = str(failed_file)

    return stats


def main():
    input_dir = Path(__file__).parent.parent / "documents" / "original"
    output_dir = Path(__file__).parent.parent / "documents" / "text"

    print("=== Phase 4.5: Text Extraction ===")
    print(f"Source: {input_dir}")
    print(f"Output: {output_dir}")
    print()

    stats = extract_all(input_dir, output_dir)

    print()
    print("=== Extraction Complete ===")
    print(f"Total files: {stats['total_files']}")
    print(f"Successfully extracted: {stats['success']}")
    print(f"Skipped (already exist): {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    print(f"Total characters: {stats['total_chars']:,}")
    print(f"Total words: {stats['total_words']:,}")

    if stats.get("failed_log"):
        print(f"\nFailed extractions logged to: {stats['failed_log']}")


if __name__ == "__main__":
    main()

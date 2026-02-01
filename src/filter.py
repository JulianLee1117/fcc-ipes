"""
Phase 2: Filter raw filings to IPES-relevant only.

Filtering rule (case-insensitive):
Keep if proceedings description contains:
  - "interconnected voip numbering"
  - "voip numbering authorization application"
  - "authorization to obtain numbering resources"
OR if any document filename contains:
  - "voip numbering"
"""

import json
from pathlib import Path


def is_ipes_filing(filing: dict) -> bool:
    """Check if filing matches IPES filter criteria."""

    # Check proceedings descriptions
    proceedings = filing.get("proceedings", [])
    for proc in proceedings:
        desc = (proc.get("description") or "").lower()
        if "interconnected voip numbering" in desc:
            return True
        if "voip numbering authorization application" in desc:
            return True
        if "authorization to obtain numbering resources" in desc:
            return True

    # Check document filenames
    documents = filing.get("documents", [])
    for doc in documents:
        filename = (doc.get("filename") or "").lower()
        if "voip numbering" in filename:
            return True

    return False


def filter_filings(input_file: Path, output_file: Path) -> dict:
    """Filter raw filings and save IPES-relevant ones."""

    kept = []
    dropped = 0
    type_counts = {}

    with open(input_file) as f:
        for line in f:
            filing = json.loads(line)

            if is_ipes_filing(filing):
                kept.append(filing)
                st = filing.get("submissiontype", {}).get("description", "UNKNOWN")
                type_counts[st] = type_counts.get(st, 0) + 1
            else:
                dropped += 1

    # Save filtered filings
    with open(output_file, "w") as f:
        for filing in kept:
            f.write(json.dumps(filing) + "\n")

    stats = {
        "input_file": str(input_file),
        "output_file": str(output_file),
        "total_input": len(kept) + dropped,
        "kept": len(kept),
        "dropped": dropped,
        "by_submission_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
    }

    return stats


def main():
    input_file = Path(__file__).parent.parent / "data" / "raw" / "filings_raw.jsonl"
    output_file = Path(__file__).parent.parent / "data" / "processed" / "filings_filtered.jsonl"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    stats = filter_filings(input_file, output_file)

    print("=== Filtering Complete ===")
    print(f"Input:   {stats['total_input']} filings")
    print(f"Kept:    {stats['kept']} IPES-relevant")
    print(f"Dropped: {stats['dropped']} noise")
    print("\nBy submission type:")
    for st, count in stats["by_submission_type"].items():
        print(f"  {count:4d} {st}")


if __name__ == "__main__":
    main()

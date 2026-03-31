"""Write redaction mapping tables (.txt and .csv)."""

import csv
from datetime import datetime
from pathlib import Path

from .tokenizer import TokenMap


def write_map_txt(token_map: TokenMap, output_dir: Path, source_dir: str) -> Path:
    """Write human-readable mapping table.

    Args:
        token_map: The token mapping.
        output_dir: Directory to write the file.
        source_dir: Original source directory path (for display).

    Returns:
        Path to the written file.
    """
    path = output_dir / "redaction_map.txt"
    mappings = token_map.get_all_mappings()

    with open(path, "w", encoding="utf-8") as f:
        f.write("TaxShield Redaction Map\n")
        f.write("Keep this file safe. Do not send to third parties.\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Source: {source_dir}\n")
        f.write("\n")
        f.write(f"{'Token':<20} {'Original'}\n")
        f.write(f"{'─' * 20} {'─' * 40}\n")

        for m in mappings:
            line = f"{m['token']:<20} {m['original']}"
            if m['note']:
                line += f"  ({m['note']})"
            f.write(line + "\n")

    return path


def write_map_csv(token_map: TokenMap, output_dir: Path) -> Path:
    """Write machine-readable mapping table for TaxReveal.

    Args:
        token_map: The token mapping.
        output_dir: Directory to write the file.

    Returns:
        Path to the written file.
    """
    path = output_dir / "redaction_map.csv"
    mappings = token_map.get_all_mappings()

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["token", "original", "note"])
        writer.writeheader()
        writer.writerows(mappings)

    return path

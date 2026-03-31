"""Main redaction orchestrator."""

import fitz
from pathlib import Path

from .pii_detector import PIIMatch
from .pdf_processor import (
    detect_pii_on_page,
    apply_redactions_to_pdf,
    identify_form_type,
)
from .tokenizer import TokenMap
from .map_writer import write_map_txt, write_map_csv


SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def is_supported_file(path: Path) -> bool:
    """Check if a file is a supported format using magic bytes, with extension fallback."""
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header[:4] == b"%PDF":
            return True
        if header[:3] == b"\xff\xd8\xff":  # JPEG
            return True
        if header[:4] == b"\x89PNG":  # PNG
            return True
    except (OSError, IOError):
        pass

    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def get_file_type(path: Path) -> str:
    """Determine file type from magic bytes.

    Returns:
        "pdf", "image", or "unknown".
    """
    try:
        with open(path, "rb") as f:
            header = f.read(8)
        if header[:4] == b"%PDF":
            return "pdf"
        if header[:3] == b"\xff\xd8\xff" or header[:4] == b"\x89PNG":
            return "image"
    except (OSError, IOError):
        pass

    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in {".jpg", ".jpeg", ".png"}:
        return "image"
    return "unknown"


def collect_files(paths: list[str]) -> list[Path]:
    """Collect all supported files from the given paths.

    Args:
        paths: List of file paths or directory paths.

    Returns:
        List of Path objects for supported files.
    """
    files = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and is_supported_file(child):
                    # Skip files in the redacted/ subdirectory
                    if child.parent.name != "redacted":
                        files.append(child)
        elif path.is_file() and is_supported_file(path):
            files.append(path)
        else:
            raise FileNotFoundError(f"File not found or unsupported format: {p}")
    return files


def determine_output_dir(files: list[Path], explicit_output: str | None) -> Path:
    """Determine the output directory based on input files.

    Args:
        files: List of input file paths.
        explicit_output: Explicitly specified output directory, or None.

    Returns:
        Path to the output directory.
    """
    if explicit_output:
        return Path(explicit_output)

    parents = {f.parent for f in files}
    if len(parents) == 1:
        return parents.pop() / "redacted"
    else:
        raise ValueError(
            "Input files are in different directories. "
            "Please use --output to specify an output directory."
        )


def redact_pdf(
    input_path: Path,
    output_path: Path,
    token_map: TokenMap,
    preview: bool = False,
) -> list[PIIMatch]:
    """Redact a single PDF file.

    Args:
        input_path: Path to the input PDF.
        output_path: Path for the redacted output PDF.
        token_map: Shared token map across all files.
        preview: If True, only detect PII without applying redactions.

    Returns:
        List of all PIIMatch objects found.
    """
    doc = fitz.open(str(input_path))
    form_type = identify_form_type(doc)

    all_matches: dict[int, list[PIIMatch]] = {}
    all_matches_flat: list[PIIMatch] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_matches = detect_pii_on_page(page, page_num, token_map)
        all_matches[page_num] = page_matches
        all_matches_flat.extend(page_matches)

    doc.close()

    if not preview:
        apply_redactions_to_pdf(str(input_path), str(output_path), all_matches)

    return all_matches_flat


def redact_image(
    input_path: Path,
    output_path: Path,
    token_map: TokenMap,
    preview: bool = False,
) -> list[PIIMatch]:
    """Redact an image file (JPG/PNG).

    MVP: Convert to PDF first, then process as PDF.
    Future: OCR + direct image manipulation.

    Args:
        input_path: Path to the input image.
        output_path: Path for the redacted output PDF.
        token_map: Shared token map.
        preview: If True, only detect PII.

    Returns:
        List of all PIIMatch objects found.
    """
    # Convert image to PDF using PyMuPDF
    img_doc = fitz.open()
    img = fitz.open(str(input_path))

    # For image files, create a PDF page from the image
    if input_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        img_doc = fitz.open()
        img_page = img_doc.new_page(width=img[0].rect.width, height=img[0].rect.height)
        img_page.insert_image(img_page.rect, filename=str(input_path))

        # Save temporary PDF
        temp_pdf = output_path.with_suffix(".tmp.pdf")
        img_doc.save(str(temp_pdf))
        img_doc.close()
        img.close()

        # Now process the temporary PDF
        matches = redact_pdf(temp_pdf, output_path, token_map, preview)

        # Clean up temp file
        if temp_pdf.exists():
            temp_pdf.unlink()

        return matches

    img.close()
    img_doc.close()
    return []


def run_redaction(
    input_paths: list[str],
    output_dir: str | None = None,
    preview: bool = False,
) -> dict:
    """Main entry point for redaction.

    Args:
        input_paths: List of file/directory paths to process.
        output_dir: Optional explicit output directory.
        preview: If True, only detect and report PII without redacting.

    Returns:
        Dict with keys: files_processed, total_pii_found, output_dir, mappings.
    """
    files = collect_files(input_paths)
    if not files:
        return {"files_processed": 0, "total_pii_found": 0, "output_dir": None, "mappings": []}

    out_dir = determine_output_dir(files, output_dir)

    if not preview:
        out_dir.mkdir(parents=True, exist_ok=True)

    token_map = TokenMap()
    total_pii = 0
    files_processed = 0
    all_file_results = []

    for file_path in files:
        file_type = get_file_type(file_path)
        output_name = file_path.stem + "_redacted.pdf"
        output_path = out_dir / output_name

        if file_type == "pdf":
            matches = redact_pdf(file_path, output_path, token_map, preview)
        elif file_type == "image":
            matches = redact_image(file_path, output_path, token_map, preview)
        else:
            continue

        total_pii += len(matches)
        files_processed += 1
        all_file_results.append({
            "file": str(file_path),
            "output": str(output_path) if not preview else None,
            "pii_count": len(matches),
            "pii_items": matches,
        })

    # Write mapping tables
    if not preview and token_map.get_all_mappings():
        source_dir = str(files[0].parent)
        write_map_txt(token_map, out_dir, source_dir)
        write_map_csv(token_map, out_dir)

    return {
        "files_processed": files_processed,
        "total_pii_found": total_pii,
        "output_dir": str(out_dir) if not preview else None,
        "mappings": token_map.get_all_mappings(),
        "file_results": all_file_results,
    }

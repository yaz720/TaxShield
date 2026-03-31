"""PDF processing: read text, detect PII, apply redactions."""

import re
import fitz  # PyMuPDF

from .pii_detector import (
    PIIMatch,
    SSN_PATTERN,
    EIN_PATTERN,
    format_ssn_replacement,
    format_ein_replacement,
    format_phone_replacement,
)
from .tokenizer import TokenMap

# Strict phone pattern: requires parentheses or dot/dash separators
# Matches: (831)726-6633, 831-726-6633, 831.726.6633
# Does NOT match: bare digit sequences like 4746222715
PHONE_STRICT_PATTERN = re.compile(
    r'\(\d{3}\)\s*\d{3}[.-]\d{4}'   # (xxx)xxx-xxxx or (xxx) xxx-xxxx
    r'|\d{3}[.-]\d{3}[.-]\d{4}'     # xxx-xxx-xxxx or xxx.xxx.xxxx
)


def extract_text_blocks(page: fitz.Page) -> list[dict]:
    """Extract text blocks with position info from a PDF page.

    Returns:
        List of dicts with keys: text, rect (fitz.Rect), block_no.
    """
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    result = []
    for block in blocks:
        if block["type"] != 0:  # skip image blocks
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    result.append({
                        "text": text,
                        "rect": fitz.Rect(span["bbox"]),
                        "font_size": span["size"],
                        "font_name": span["font"],
                    })
    return result


def _find_text_rects(page: fitz.Page, text: str) -> list[fitz.Rect]:
    """Find all occurrences of exact text on a page and return their rects."""
    results = page.search_for(text, quads=False)
    return results if results else []


def detect_pii_on_page(
    page: fitz.Page,
    page_num: int,
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect all PII on a single PDF page.

    Uses text extraction + regex to find PII, then locates their positions
    on the page for redaction.

    Args:
        page: The PDF page.
        page_num: 0-based page number.
        token_map: Token map for name tokenization.

    Returns:
        List of PIIMatch objects.
    """
    matches = []
    seen_texts = set()  # avoid duplicate detections

    # Extract text blocks with position info for precise matching
    blocks = extract_text_blocks(page)

    for block in blocks:
        text = block["text"]

        # --- SSN detection ---
        for ssn_match in SSN_PATTERN.finditer(text):
            ssn_text = ssn_match.group()
            if ("ssn", ssn_text) not in seen_texts:
                seen_texts.add(("ssn", ssn_text))
                rects = _find_text_rects(page, ssn_text)
                for rect in rects:
                    matches.append(PIIMatch(
                        pii_type="ssn",
                        original_text=ssn_text,
                        replacement=format_ssn_replacement(ssn_match),
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="high",
                    ))

        # --- EIN detection ---
        for ein_match in EIN_PATTERN.finditer(text):
            ein_text = ein_match.group()
            # Skip if it matches SSN format (SSN is XX-XX-XXXX, EIN is XX-XXXXXXX)
            if SSN_PATTERN.search(ein_text):
                continue
            # EIN is exactly 2 digits, separator, 7 digits
            parts = re.split(r'[- ]', ein_text)
            if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 7:
                if ("ein", ein_text) not in seen_texts:
                    seen_texts.add(("ein", ein_text))
                    rects = _find_text_rects(page, ein_text)
                    for rect in rects:
                        matches.append(PIIMatch(
                            pii_type="ein",
                            original_text=ein_text,
                            replacement=format_ein_replacement(ein_match),
                            page_num=page_num,
                            rect=tuple(rect),
                            confidence="high",
                        ))

        # --- Phone detection (strict: must have parentheses or dashes) ---
        for phone_match in PHONE_STRICT_PATTERN.finditer(text):
            phone_text = phone_match.group()
            if ("phone", phone_text) not in seen_texts:
                seen_texts.add(("phone", phone_text))
                rects = _find_text_rects(page, phone_text)
                for rect in rects:
                    matches.append(PIIMatch(
                        pii_type="phone",
                        original_text=phone_text,
                        replacement=format_phone_replacement(phone_match),
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="high",
                    ))

    return matches


def detect_names_by_position(
    page: fitz.Page,
    page_num: int,
    token_map: TokenMap,
    form_type: str,
) -> list[PIIMatch]:
    """Detect names based on their position relative to known form labels.

    This uses the fact that tax forms have fixed layouts - names appear
    in predictable locations relative to labels like "Your first name".

    Args:
        page: The PDF page.
        page_num: 0-based page number.
        token_map: Token map for name tokenization.
        form_type: e.g., "1040", "w2", "8615".

    Returns:
        List of PIIMatch objects for detected names.
    """
    matches = []
    blocks = extract_text_blocks(page)

    if form_type == "1040" and page_num == 0:
        matches.extend(_detect_1040_page1_names(page, page_num, blocks, token_map))
    elif form_type == "w2":
        matches.extend(_detect_w2_names(page, page_num, blocks, token_map))
    elif form_type == "8615":
        matches.extend(_detect_8615_names(page, page_num, blocks, token_map))

    return matches


def _detect_1040_page1_names(
    page: fitz.Page,
    page_num: int,
    blocks: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect names on 1040 page 1 by finding text near name labels."""
    matches = []

    # Find the "Your first name and middle initial" label
    for i, block in enumerate(blocks):
        text_lower = block["text"].lower()

        # Taxpayer name - appears after "your first name" label
        if "your first name" in text_lower:
            # The actual name is typically in the next text block(s) at similar y position
            name_rect = block["rect"]
            # Look for text blocks that are below this label and in the name field area
            for j in range(i + 1, min(i + 10, len(blocks))):
                candidate = blocks[j]
                # Name should be below the label, within reasonable distance
                if (candidate["rect"].y0 > name_rect.y0 and
                        candidate["rect"].y0 < name_rect.y1 + 30):
                    name_text = candidate["text"].strip()
                    if name_text and not _is_form_label(name_text):
                        token = token_map.get_or_create_token(name_text, "Taxpayer")
                        matches.append(PIIMatch(
                            pii_type="name",
                            original_text=name_text,
                            replacement=token,
                            page_num=page_num,
                            rect=tuple(candidate["rect"]),
                            confidence="medium",
                        ))
                        break

        # Address detection
        if "home address" in text_lower:
            name_rect = block["rect"]
            for j in range(i + 1, min(i + 10, len(blocks))):
                candidate = blocks[j]
                if (candidate["rect"].y0 > name_rect.y0 and
                        candidate["rect"].y0 < name_rect.y1 + 30):
                    addr_text = candidate["text"].strip()
                    if addr_text and not _is_form_label(addr_text):
                        # Replace address but keep state if detectable
                        replacement = _redact_address(addr_text)
                        matches.append(PIIMatch(
                            pii_type="address",
                            original_text=addr_text,
                            replacement=replacement,
                            page_num=page_num,
                            rect=tuple(candidate["rect"]),
                            confidence="medium",
                        ))
                        break

    return matches


def _detect_w2_names(
    page: fitz.Page,
    page_num: int,
    blocks: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect names on W-2 form."""
    matches = []
    for i, block in enumerate(blocks):
        text_lower = block["text"].lower()
        if "employer" in text_lower and "name" in text_lower:
            for j in range(i + 1, min(i + 5, len(blocks))):
                candidate = blocks[j]
                name_text = candidate["text"].strip()
                if name_text and not _is_form_label(name_text):
                    token = token_map.get_or_create_token(name_text, "Employer")
                    matches.append(PIIMatch(
                        pii_type="employer_name",
                        original_text=name_text,
                        replacement=token,
                        page_num=page_num,
                        rect=tuple(candidate["rect"]),
                        confidence="medium",
                    ))
                    break
    return matches


def _detect_8615_names(
    page: fitz.Page,
    page_num: int,
    blocks: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect parent name on Form 8615."""
    matches = []
    for i, block in enumerate(blocks):
        text_lower = block["text"].lower()
        if "parent" in text_lower and "name" in text_lower:
            for j in range(i + 1, min(i + 5, len(blocks))):
                candidate = blocks[j]
                name_text = candidate["text"].strip()
                if name_text and not _is_form_label(name_text):
                    token = token_map.get_or_create_token(name_text, "Parent")
                    matches.append(PIIMatch(
                        pii_type="parent_name",
                        original_text=name_text,
                        replacement=token,
                        page_num=page_num,
                        rect=tuple(candidate["rect"]),
                        confidence="medium",
                    ))
                    break
    return matches


def _is_form_label(text: str) -> bool:
    """Check if text is likely a form label rather than user data."""
    label_keywords = [
        "first name", "last name", "middle initial", "address",
        "city", "state", "zip", "social security", "ein",
        "employer", "employee", "form", "schedule", "see instructions",
        "check", "box", "line", "attach", "department", "treasury",
        "internal revenue", "omb no",
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in label_keywords)


def _redact_address(address: str) -> str:
    """Redact address but try to preserve state abbreviation.

    e.g., '3038 McKinley Dr, Santa Clara, CA 95051'
       -> 'XXXX XXXXXXXX XX, XXXXX XXXXX, CA XXXXX'
    """
    import re
    # Try to find a 2-letter state abbreviation
    state_match = re.search(r'\b([A-Z]{2})\b', address)
    state = state_match.group(1) if state_match else ""

    # Replace each word with X's of the same length, except state
    words = address.split()
    redacted_words = []
    state_found = False
    for word in words:
        # Preserve commas and other punctuation at word boundaries
        clean_word = word.strip(",.")
        trailing = word[len(clean_word):]

        if clean_word == state and not state_found:
            redacted_words.append(word)
            state_found = True
        else:
            redacted_words.append("X" * len(clean_word) + trailing)

    return " ".join(redacted_words)


def apply_redactions_to_pdf(
    input_path: str,
    output_path: str,
    all_matches: dict[int, list[PIIMatch]],
) -> None:
    """Apply all redactions to a PDF and save.

    Uses PyMuPDF's permanent redaction API - text is deleted from
    the PDF text layer, not just visually covered.

    Args:
        input_path: Path to the original PDF.
        output_path: Path to save the redacted PDF.
        all_matches: Dict of page_num -> list of PIIMatch.
    """
    doc = fitz.open(input_path)

    for page_num, matches in all_matches.items():
        page = doc[page_num]
        for match in matches:
            rect = fitz.Rect(match.rect)
            # Add redaction annotation - this marks the area for deletion
            page.add_redact_annot(
                rect,
                text=match.replacement,
                fontsize=8,
                align=fitz.TEXT_ALIGN_LEFT,
                fill=(1, 1, 1),  # white background
                text_color=(0, 0, 0),  # black text
            )
        # Apply all redactions on this page - permanently deletes original text
        page.apply_redactions()

    # Clean metadata
    doc.scrub()
    doc.set_metadata({})

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


def identify_form_type(doc: fitz.Document) -> str:
    """Try to identify what type of tax form this PDF is.

    Returns:
        Form type string: "1040", "w2", "schedule_d", "8615", "8949", "8995",
        "1099_div", "1099_b", "1099_int", "1098", "1099_r", or "unknown".
    """
    first_pages_text = ""
    for i in range(min(2, len(doc))):
        first_pages_text += doc[i].get_text().lower()

    if "form 1040" in first_pages_text or "u.s. individual income tax return" in first_pages_text:
        return "1040"
    elif "w-2" in first_pages_text and "wage and tax statement" in first_pages_text:
        return "w2"
    elif "schedule d" in first_pages_text and "capital gains" in first_pages_text:
        return "schedule_d"
    elif "form 8615" in first_pages_text:
        return "8615"
    elif "form 8949" in first_pages_text:
        return "8949"
    elif "form 8995" in first_pages_text:
        return "8995"
    elif "1099-div" in first_pages_text:
        return "1099_div"
    elif "1099-b" in first_pages_text:
        return "1099_b"
    elif "1099-int" in first_pages_text:
        return "1099_int"
    elif "1098" in first_pages_text and "mortgage" in first_pages_text:
        return "1098"
    elif "1099-r" in first_pages_text:
        return "1099_r"
    else:
        return "unknown"

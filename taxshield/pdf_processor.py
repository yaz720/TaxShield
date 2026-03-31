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
PHONE_STRICT_PATTERN = re.compile(
    r'\(\d{3}\)\s*\d{3}[.-]\d{4}'
    r'|\d{3}[.-]\d{3}[.-]\d{4}'
)

# Known form labels that identify nearby PII fields
# (label_substring, pii_type, token_role)
LABEL_TO_PII = {
    "your first name": ("name", "Taxpayer"),
    "last name": ("name", None),
    "spouse's first name": ("name", "Spouse"),
    "home address": ("address", None),
    "city, town": ("address", None),
    "parent's name": ("name", "Parent"),
    "employer's name": ("name", "Employer"),
    "employee's name": ("name", None),
    "preparer's name": ("preparer", None),
    "preparer's signature": ("preparer", None),
    "firm's name": ("preparer", None),
    "firm's address": ("preparer", None),
    "firm's ein": ("preparer", None),
    "phone no": ("preparer", None),
    "email address": ("preparer", None),
    "ptin": ("preparer", None),
}

# Date pattern for birth dates: MM/DD/YYYY or MM-DD-YYYY
DATE_PATTERN = re.compile(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})')

# Labels near which dates should be treated as birth dates (partial redact)
BIRTH_DATE_LABELS = {
    "date of birth", "born before", "born", "dob",
    "birth date", "birthdate",
}

# Labels near which dates are transaction dates (preserve as-is)
TRANSACTION_DATE_LABELS = {
    "date acquired", "date sold", "date disposed",
    "date of death", "created", "rev ",
}

# Fonts used for user-entered data in TurboTax PDFs
USER_DATA_FONTS = {"Courier", "courier"}


def _is_user_data_font(font_name: str) -> bool:
    """Check if a font is used for user-entered data (not form labels)."""
    return any(uf in font_name for uf in USER_DATA_FONTS)


def _is_numeric_or_amount(text: str) -> bool:
    """Check if text is a number or dollar amount (should be preserved)."""
    cleaned = text.replace(",", "").replace(".", "").replace("$", "").replace(" ", "")
    return cleaned.isdigit() or cleaned == "" or text in {"X", "x"}


def extract_text_spans(page: fitz.Page) -> list[dict]:
    """Extract all text spans with font info from a PDF page."""
    blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    spans = []
    for block in blocks:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    spans.append({
                        "text": text,
                        "rect": fitz.Rect(span["bbox"]),
                        "font": span["font"],
                        "size": span["size"],
                        "is_user_data": _is_user_data_font(span["font"]),
                    })
    return spans


def _find_label_context(
    spans: list[dict],
    span_idx: int,
    label_spans: list[dict],
) -> str | None:
    """Find the nearest form label above/at the same line as a user-data span.

    Uses y-coordinate proximity, not span index order, because TurboTax PDFs
    often put all labels before all user data in the span list.

    Args:
        spans: All spans on the page.
        span_idx: Index of the user-data span.
        label_spans: Pre-filtered list of label (non-user-data) spans.

    Returns the label key if found, or None.
    """
    target = spans[span_idx]
    target_x = target["rect"].x0
    target_y = target["rect"].y0

    best_label = None
    best_distance = float("inf")

    for label in label_spans:
        label_y = label["rect"].y0
        label_x = label["rect"].x0

        # Label must be above or at same line (within 15 pts)
        y_diff = target_y - label_y
        if y_diff < -5:  # label is below target
            continue
        if y_diff > 20:  # label is too far above
            continue

        # Prefer labels on the same horizontal side (left half vs right half)
        x_dist = abs(target_x - label_x)

        # Combined distance (y more important than x)
        distance = y_diff * 10 + x_dist

        label_text = label["text"].lower()
        for label_key in LABEL_TO_PII:
            if label_key in label_text:
                if distance < best_distance:
                    best_distance = distance
                    best_label = label_key

    return best_label


def detect_pii_on_page(
    page: fitz.Page,
    page_num: int,
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect all PII on a single PDF page using regex + font + position."""
    matches = []
    seen = set()

    spans = extract_text_spans(page)
    label_spans = [s for s in spans if not s["is_user_data"]]

    for idx, span in enumerate(spans):
        text = span["text"]
        rect = span["rect"]

        # --- Regex-based: SSN ---
        for ssn_match in SSN_PATTERN.finditer(text):
            ssn_text = ssn_match.group()
            key = ("ssn", ssn_text, page_num)
            if key not in seen:
                seen.add(key)
                for r in page.search_for(ssn_text, quads=False):
                    matches.append(PIIMatch(
                        pii_type="ssn",
                        original_text=ssn_text,
                        replacement=format_ssn_replacement(ssn_match),
                        page_num=page_num,
                        rect=tuple(r),
                        confidence="high",
                    ))

        # --- Regex-based: EIN (2-7 digit format) ---
        for ein_match in EIN_PATTERN.finditer(text):
            ein_text = ein_match.group()
            parts = re.split(r'[- ]', ein_text)
            if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 7:
                if SSN_PATTERN.search(ein_text):
                    continue
                key = ("ein", ein_text, page_num)
                if key not in seen:
                    seen.add(key)
                    for r in page.search_for(ein_text, quads=False):
                        matches.append(PIIMatch(
                            pii_type="ein",
                            original_text=ein_text,
                            replacement=format_ein_replacement(ein_match),
                            page_num=page_num,
                            rect=tuple(r),
                            confidence="high",
                        ))

        # --- Regex-based: Phone ---
        for phone_match in PHONE_STRICT_PATTERN.finditer(text):
            phone_text = phone_match.group()
            key = ("phone", phone_text, page_num)
            if key not in seen:
                seen.add(key)
                for r in page.search_for(phone_text, quads=False):
                    matches.append(PIIMatch(
                        pii_type="phone",
                        original_text=phone_text,
                        replacement=format_phone_replacement(phone_match),
                        page_num=page_num,
                        rect=tuple(r),
                        confidence="high",
                    ))

        # --- Date detection: birth dates get partial redaction ---
        if span["is_user_data"]:
            for date_match in DATE_PATTERN.finditer(text):
                date_text = date_match.group()
                # Skip if this is part of an SSN (SSN: XXX-XX-XXXX)
                if SSN_PATTERN.search(text):
                    continue
                # Validate date: month 1-12, day 1-31
                month_val = int(date_match.group(1))
                day_val = int(date_match.group(2))
                if month_val < 1 or month_val > 12 or day_val < 1 or day_val > 31:
                    continue
                # Check if this date is near a birth-date label
                is_birth_date = _is_near_label_set(
                    label_spans, rect, BIRTH_DATE_LABELS
                )
                # Check if it's a transaction date (preserve)
                is_transaction_date = _is_near_label_set(
                    label_spans, rect, TRANSACTION_DATE_LABELS
                )

                if is_birth_date and not is_transaction_date:
                    month = date_match.group(1)
                    year = date_match.group(3)
                    sep = "/" if "/" in date_text else "-"
                    replacement = f"{month}{sep}XX{sep}{year}"
                    key = ("birth_date", date_text, page_num)
                    if key not in seen:
                        seen.add(key)
                        for r in page.search_for(date_text, quads=False):
                            matches.append(PIIMatch(
                                pii_type="birth_date",
                                original_text=date_text,
                                replacement=replacement,
                                page_num=page_num,
                                rect=tuple(r),
                                confidence="high",
                            ))

        # --- Font + Position based: names, addresses, preparer info ---
        if span["is_user_data"] and not _is_numeric_or_amount(text):
            label = _find_label_context(spans, idx, label_spans)
            if label is None:
                # Also check if this span is in the preparer area (y > 700 on 1040 page 2)
                if rect.y0 > 700 and _is_in_preparer_area(label_spans, rect):
                    label = "preparer's name"  # treat as preparer info
                else:
                    continue

            pii_type, token_role = LABEL_TO_PII[label]

            if pii_type == "name" and token_role:
                replacement = token_map.get_or_create_token(text, token_role)
                key = ("name", text, page_num, round(rect.y0))
                if key not in seen:
                    seen.add(key)
                    matches.append(PIIMatch(
                        pii_type="name",
                        original_text=text,
                        replacement=replacement,
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="high",
                    ))
            elif pii_type == "name" and token_role is None:
                existing = token_map.lookup_token(text)
                replacement = existing if existing else "X" * len(text)
                key = ("name", text, page_num, round(rect.y0))
                if key not in seen:
                    seen.add(key)
                    matches.append(PIIMatch(
                        pii_type="name",
                        original_text=text,
                        replacement=replacement,
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="medium",
                    ))
            elif pii_type == "address":
                replacement = _redact_address(text)
                key = ("address", text, page_num, round(rect.y0))
                if key not in seen:
                    seen.add(key)
                    matches.append(PIIMatch(
                        pii_type="address",
                        original_text=text,
                        replacement=replacement,
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="high",
                    ))
            elif pii_type == "preparer":
                replacement = "X" * min(len(text), 10)
                key = ("preparer", text, page_num, round(rect.y0))
                if key not in seen:
                    seen.add(key)
                    matches.append(PIIMatch(
                        pii_type="preparer",
                        original_text=text,
                        replacement=replacement,
                        page_num=page_num,
                        rect=tuple(rect),
                        confidence="high",
                    ))

    return matches


def _is_near_label_set(
    label_spans: list[dict],
    target_rect: fitz.Rect,
    label_keywords: set[str],
) -> bool:
    """Check if a target rect is near any label containing the given keywords."""
    for label in label_spans:
        y_diff = abs(target_rect.y0 - label["rect"].y0)
        if y_diff > 30:
            continue
        label_text = label["text"].lower()
        for keyword in label_keywords:
            if keyword in label_text:
                return True
    return False


def _is_in_preparer_area(label_spans: list[dict], target_rect: fitz.Rect) -> bool:
    """Check if a rect is in the Paid Preparer area of the form."""
    for label in label_spans:
        label_text = label["text"].lower()
        if ("preparer" in label_text or "firm" in label_text or "ptin" in label_text):
            y_diff = abs(target_rect.y0 - label["rect"].y0)
            if y_diff < 20:
                return True
    return False


def _redact_address(address: str) -> str:
    """Redact address but preserve state abbreviation."""
    state_match = re.search(r'\b([A-Z]{2})\b', address)
    state = state_match.group(1) if state_match else ""

    words = address.split()
    redacted = []
    state_kept = False
    for word in words:
        clean = word.strip(",.")
        trailing = word[len(clean):]
        if clean == state and not state_kept:
            redacted.append(word)
            state_kept = True
        else:
            redacted.append("X" * len(clean) + trailing)
    return " ".join(redacted)


def apply_redactions_to_pdf(
    input_path: str,
    output_path: str,
    all_matches: dict[int, list[PIIMatch]],
) -> None:
    """Apply permanent redactions to a PDF.

    Uses PyMuPDF's redaction API which permanently deletes text
    from the PDF text layer (not just visual overlay).
    """
    doc = fitz.open(input_path)

    for page_num, matches in all_matches.items():
        page = doc[page_num]
        for match in matches:
            rect = fitz.Rect(match.rect)
            # Expand rect slightly to ensure full coverage
            rect = rect + (-1, -1, 1, 1)
            page.add_redact_annot(
                rect,
                text=match.replacement,
                fontsize=8,
                align=fitz.TEXT_ALIGN_LEFT,
                fill=(1, 1, 1),
                text_color=(0, 0, 0),
            )
        page.apply_redactions()

    # Clean metadata
    doc.scrub()
    doc.set_metadata({})

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()


def identify_form_type(doc: fitz.Document) -> str:
    """Identify tax form type from PDF content."""
    text = ""
    for i in range(min(2, len(doc))):
        text += doc[i].get_text().lower()

    if "form 1040" in text or "u.s. individual income tax return" in text:
        return "1040"
    elif "w-2" in text and "wage and tax statement" in text:
        return "w2"
    elif "schedule d" in text and "capital gains" in text:
        return "schedule_d"
    elif "form 8615" in text:
        return "8615"
    elif "form 8949" in text:
        return "8949"
    elif "form 8995" in text:
        return "8995"
    elif "1099-div" in text:
        return "1099_div"
    elif "1099-b" in text:
        return "1099_b"
    elif "1099-int" in text:
        return "1099_int"
    elif "1098" in text and "mortgage" in text:
        return "1098"
    elif "1099-r" in text:
        return "1099_r"
    return "unknown"

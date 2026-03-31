"""Tax form specific PII detection logic.

Contains layout-aware detection for each tax form type.
These are not generic rules - they are specific to IRS form layouts.
"""

import fitz

from .pii_detector import PIIMatch
from .tokenizer import TokenMap


def _find_user_data_near_label(
    spans: list[dict],
    label_text: str,
    max_y_distance: float = 20,
    same_x_range: bool = False,
    label_x_range: tuple | None = None,
) -> list[dict]:
    """Find user-data spans near a specific label.

    Args:
        spans: All text spans on the page.
        label_text: Label text to search for (case-insensitive).
        max_y_distance: Max vertical distance from label to user data.
        same_x_range: If True, only match user data in similar x range as label.
        label_x_range: If provided, only look for labels in this x range.

    Returns:
        List of user-data spans found near the label.
    """
    label_text_lower = label_text.lower()
    results = []

    # Find the label
    label_span = None
    for s in spans:
        if s["is_user_data"]:
            continue
        if label_x_range:
            if s["rect"].x0 < label_x_range[0] or s["rect"].x0 > label_x_range[1]:
                continue
        if label_text_lower in s["text"].lower():
            label_span = s
            break

    if label_span is None:
        return results

    label_y = label_span["rect"].y0
    label_x0 = label_span["rect"].x0
    label_x1 = label_span["rect"].x1

    # Find user data below/at this label
    for s in spans:
        if not s["is_user_data"]:
            continue
        y_diff = s["rect"].y0 - label_y
        if y_diff < -2 or y_diff > max_y_distance:
            continue
        if same_x_range:
            # Must overlap horizontally with label area
            if s["rect"].x1 < label_x0 - 50 or s["rect"].x0 > label_x1 + 200:
                continue
        results.append(s)

    return results


def detect_1040_page1_pii(
    page: fitz.Page,
    page_num: int,
    spans: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect PII on 1040 page 1 using form-specific layout knowledge.

    Handles:
    - Taxpayer name (first + last → combined token)
    - Spouse name (first + last → combined token)
    - SSN (3 separate spans → combined, redact each)
    - Address (street, city, state, zip)
    """
    matches = []

    # === Taxpayer Name ===
    # First name is in x range 0-250 (left side of name area)
    first_name_all = _find_user_data_near_label(
        spans, "your first name", max_y_distance=18, label_x_range=(0, 200)
    )
    first_name_spans = [s for s in first_name_all if s["rect"].x0 < 250 and not s["text"].strip().isdigit()]

    # Last name is in x range 250-450 (right side of name area)
    last_name_all = _find_user_data_near_label(
        spans, "last name", max_y_distance=18, label_x_range=(200, 350)
    )
    last_name_data = [s for s in last_name_all if 200 < s["rect"].x0 < 450 and not s["text"].strip().isdigit()]

    # Filter last name to only those on the taxpayer row (similar y to first name)
    taxpayer_last = last_name_data
    if first_name_spans:
        taxpayer_last = [s for s in last_name_data
                         if abs(s["rect"].y0 - first_name_spans[0]["rect"].y0) < 5]

    if first_name_spans or taxpayer_last:
        first_text = first_name_spans[0]["text"].strip() if first_name_spans else ""
        last_text = taxpayer_last[0]["text"].strip() if taxpayer_last else ""

        # Combine into full name and create ONE token FIRST
        full_name = f"{first_text} {last_text}".strip()
        token = token_map.get_or_create_token(full_name, "Taxpayer")

        # Register all name variants to map to the SAME token for global search
        for variant in [first_text, last_text, full_name]:
            if variant:
                token_map._name_to_token[token_map._normalize(variant)] = token
        # Also register without middle initial (e.g., "Luna" without "H")
        if " " in first_text:
            first_only = first_text.split()[0]
            token_map._name_to_token[token_map._normalize(first_only)] = token
            token_map._name_to_token[token_map._normalize(f"{first_only} {last_text}")] = token

        # Redact first name field
        if first_name_spans:
            matches.append(PIIMatch(
                pii_type="name",
                original_text=first_text,
                replacement=token,
                page_num=page_num,
                rect=tuple(first_name_spans[0]["rect"]),
                confidence="high",
            ))

        # Redact last name field
        if taxpayer_last:
            matches.append(PIIMatch(
                pii_type="name",
                original_text=last_text,
                replacement=token,
                page_num=page_num,
                rect=tuple(taxpayer_last[0]["rect"]),
                confidence="high",
            ))

    # === Spouse Name ===
    spouse_first = _find_user_data_near_label(
        spans, "spouse's first name", max_y_distance=18, label_x_range=(0, 250)
    )
    if spouse_first:
        # Find spouse last name on the same row
        spouse_last = [s for s in last_name_data
                       if abs(s["rect"].y0 - spouse_first[0]["rect"].y0) < 5]

        first_text = spouse_first[0]["text"].strip()
        last_text = spouse_last[0]["text"].strip() if spouse_last else ""
        full_name = f"{first_text} {last_text}".strip()
        token = token_map.get_or_create_token(full_name, "Spouse")

        if last_text:
            token_map._name_to_token[token_map._normalize(last_text)] = token
            token_map._name_to_token[token_map._normalize(first_text)] = token
            first_only = first_text.split()[0] if " " in first_text else first_text
            token_map._name_to_token[token_map._normalize(first_only)] = token
            token_map._name_to_token[token_map._normalize(f"{first_only} {last_text}")] = token

        matches.append(PIIMatch(
            pii_type="name",
            original_text=first_text,
            replacement=token,
            page_num=page_num,
            rect=tuple(spouse_first[0]["rect"]),
            confidence="high",
        ))
        if spouse_last:
            matches.append(PIIMatch(
                pii_type="name",
                original_text=last_text,
                replacement=token,
                page_num=page_num,
                rect=tuple(spouse_last[0]["rect"]),
                confidence="high",
            ))

    # === SSN (split into 3 spans) ===
    ssn_matches = _detect_split_ssn(
        spans, "your social security number", page_num, label_x_range=(400, 580)
    )
    matches.extend(ssn_matches)

    # Spouse SSN
    spouse_ssn = _detect_split_ssn(
        spans, "spouse's social security number", page_num, label_x_range=(400, 580)
    )
    matches.extend(spouse_ssn)

    # === Address ===
    addr_spans = _find_user_data_near_label(
        spans, "home address", max_y_distance=18, label_x_range=(0, 300)
    )
    for s in addr_spans:
        text = s["text"].strip()
        if text:
            matches.append(PIIMatch(
                pii_type="address",
                original_text=text,
                replacement="X" * len(text),
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    # City (but NOT State - State is preserved)
    city_spans = _find_user_data_near_label(
        spans, "city, town", max_y_distance=18, label_x_range=(0, 330)
    )
    for s in city_spans:
        text = s["text"].strip()
        # Skip 2-letter state abbreviation (e.g., "CA") and data in State field area (x > 330)
        if len(text) == 2 and text.isalpha() and text.isupper():
            continue
        if s["rect"].x0 > 320:  # State and ZIP fields are to the right
            continue
        if text:
            matches.append(PIIMatch(
                pii_type="address",
                original_text=text,
                replacement="X" * len(text),
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    # ZIP code
    zip_spans = _find_user_data_near_label(
        spans, "zip code", max_y_distance=18, label_x_range=(350, 470)
    )
    for s in zip_spans:
        text = s["text"].strip()
        if text:
            matches.append(PIIMatch(
                pii_type="address",
                original_text=text,
                replacement="X" * len(text),
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    # State is explicitly NOT redacted (preserved for tax purposes)

    return matches


def _detect_split_ssn(
    spans: list[dict],
    label_text: str,
    page_num: int,
    label_x_range: tuple | None = None,
) -> list[PIIMatch]:
    """Detect SSN that is split into 3 separate numeric spans (3-2-4 digits).

    On 1040, SSN appears as three separate fields: 619 | 71 | 2727
    """
    matches = []

    # Find the SSN label
    label_span = None
    for s in spans:
        if s["is_user_data"]:
            continue
        if label_x_range:
            if s["rect"].x0 < label_x_range[0] or s["rect"].x0 > label_x_range[1]:
                continue
        if label_text.lower() in s["text"].lower():
            label_span = s
            break

    if label_span is None:
        return matches

    label_y = label_span["rect"].y0

    # Find numeric user-data spans near the label (within 18 pts below)
    numeric_spans = []
    for s in spans:
        if not s["is_user_data"]:
            continue
        y_diff = s["rect"].y0 - label_y
        if y_diff < -2 or y_diff > 18:
            continue
        text = s["text"].strip()
        if text.isdigit() and len(text) in (2, 3, 4):
            numeric_spans.append(s)

    # Sort by x position
    numeric_spans.sort(key=lambda s: s["rect"].x0)

    # Look for 3-2-4 pattern
    if len(numeric_spans) >= 3:
        for i in range(len(numeric_spans) - 2):
            a, b, c = numeric_spans[i], numeric_spans[i + 1], numeric_spans[i + 2]
            if (len(a["text"].strip()) == 3 and
                    len(b["text"].strip()) == 2 and
                    len(c["text"].strip()) == 4):
                # Found SSN pattern
                matches.append(PIIMatch(
                    pii_type="ssn",
                    original_text=a["text"].strip(),
                    replacement="XXX",
                    page_num=page_num,
                    rect=tuple(a["rect"]),
                    confidence="high",
                ))
                matches.append(PIIMatch(
                    pii_type="ssn",
                    original_text=b["text"].strip(),
                    replacement="XX",
                    page_num=page_num,
                    rect=tuple(b["rect"]),
                    confidence="high",
                ))
                matches.append(PIIMatch(
                    pii_type="ssn",
                    original_text=c["text"].strip(),
                    replacement="XXXX",
                    page_num=page_num,
                    rect=tuple(c["rect"]),
                    confidence="high",
                ))
                break

    return matches


def detect_1040_page2_pii(
    page: fitz.Page,
    page_num: int,
    spans: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect PII on 1040 page 2 (signature, preparer area)."""
    matches = []

    # Preparer area: firm name, phone, etc.
    preparer_labels = ["preparer's name", "firm's name", "firm's address", "ptin", "firm's ein"]
    for label in preparer_labels:
        data_spans = _find_user_data_near_label(spans, label, max_y_distance=15)
        for s in data_spans:
            text = s["text"].strip()
            if text:
                matches.append(PIIMatch(
                    pii_type="preparer",
                    original_text=text,
                    replacement="X" * min(len(text), 10),
                    page_num=page_num,
                    rect=tuple(s["rect"]),
                    confidence="high",
                ))

    # Phone number near "Phone no." label
    phone_spans = _find_user_data_near_label(spans, "phone no", max_y_distance=15)
    for s in phone_spans:
        text = s["text"].strip()
        if text:
            matches.append(PIIMatch(
                pii_type="phone",
                original_text=text,
                replacement="(XXX) XXX-XXXX",
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    # Email
    email_spans = _find_user_data_near_label(spans, "email address", max_y_distance=15)
    for s in email_spans:
        text = s["text"].strip()
        if text:
            matches.append(PIIMatch(
                pii_type="email",
                original_text=text,
                replacement="X" * min(len(text), 10),
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    return matches


def detect_form_8615_pii(
    page: fitz.Page,
    page_num: int,
    spans: list[dict],
    token_map: TokenMap,
) -> list[PIIMatch]:
    """Detect PII on Form 8615 (Kiddie Tax) - parent name and SSN."""
    matches = []

    # Parent name
    parent_spans = _find_user_data_near_label(
        spans, "parent's name", max_y_distance=18
    )
    for s in parent_spans:
        text = s["text"].strip()
        if text and len(text) > 1:
            token = token_map.get_or_create_token(text, "Parent")
            matches.append(PIIMatch(
                pii_type="name",
                original_text=text,
                replacement=token,
                page_num=page_num,
                rect=tuple(s["rect"]),
                confidence="high",
            ))

    # Parent SSN (split)
    parent_ssn = _detect_split_ssn(
        spans, "parent's social security number", page_num
    )
    matches.extend(parent_ssn)

    # Child SSN (split)
    child_ssn = _detect_split_ssn(
        spans, "child's social security number", page_num
    )
    matches.extend(child_ssn)

    return matches

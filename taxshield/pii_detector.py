"""PII detection using regex patterns and position rules for US tax forms."""

import re
from dataclasses import dataclass


@dataclass
class PIIMatch:
    """A detected PII item with location and redaction info."""
    pii_type: str          # e.g., "ssn", "ein", "phone", "name", "address"
    original_text: str     # the original text found
    replacement: str       # what to replace it with
    page_num: int          # 0-based page number
    rect: tuple            # (x0, y0, x1, y1) bounding box
    confidence: str        # "high", "medium", "low"


# Regex patterns for fixed-format PII
SSN_PATTERN = re.compile(r'\b\d{3}[- ]\d{2}[- ]\d{4}\b')
EIN_PATTERN = re.compile(r'\b\d{2}[- ]\d{7}\b')
PHONE_PATTERN = re.compile(
    r'\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b'
)
ROUTING_PATTERN = re.compile(r'\b\d{9}\b')  # 9-digit routing number
ACCOUNT_PATTERN = re.compile(r'\b\d{8,17}\b')  # bank account 8-17 digits
DATE_PATTERN = re.compile(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b')


def detect_ssn(text: str) -> list[re.Match]:
    return list(SSN_PATTERN.finditer(text))


def detect_ein(text: str) -> list[re.Match]:
    return list(EIN_PATTERN.finditer(text))


def detect_phone(text: str) -> list[re.Match]:
    return list(PHONE_PATTERN.finditer(text))


def detect_date(text: str) -> list[re.Match]:
    return list(DATE_PATTERN.finditer(text))


def format_ssn_replacement(match: re.Match) -> str:
    """Replace SSN with XXX-XX-XXXX, preserving separator style."""
    original = match.group()
    sep = '-' if '-' in original else ' ' if ' ' in original else '-'
    return f"XXX{sep}XX{sep}XXXX"


def format_ein_replacement(match: re.Match) -> str:
    """Replace EIN with XX-XXXXXXX, preserving separator style."""
    original = match.group()
    sep = '-' if '-' in original else ' ' if ' ' in original else '-'
    return f"XX{sep}XXXXXXX"


def format_phone_replacement(match: re.Match) -> str:
    """Replace phone with (XXX) XXX-XXXX."""
    return "(XXX) XXX-XXXX"


def format_date_partial(match: re.Match) -> str:
    """Keep month and year, replace day with XX. e.g., 05/15/2008 -> 05/XX/2008."""
    month = match.group(1)
    year = match.group(3)
    sep = '/' if '/' in match.group() else '-'
    return f"{month}{sep}XX{sep}{year}"


# Position-based field labels for 1040 form
# These labels help identify PII by the text that appears near them
FORM_1040_NAME_LABELS = [
    "your first name and middle initial",
    "last name",
    "spouse's first name",
    "if joint return",
]

FORM_1040_ADDRESS_LABELS = [
    "home address",
    "city, town or post office",
    "apt. no",
    "zip code",
]

FORM_1040_SSN_LABELS = [
    "your social security number",
    "spouse's social security number",
    "social security number",
]

W2_NAME_LABELS = [
    "employee's first name",
    "employer's name",
    "employee's name",
]

W2_ADDRESS_LABELS = [
    "employee's address",
    "employer's address",
]

FORM_8615_PARENT_LABELS = [
    "parent's name",
    "parent's social security number",
]

PREPARER_LABELS = [
    "preparer's name",
    "preparer's signature",
    "firm's name",
    "firm's address",
    "ptin",
    "firm's ein",
    "phone no",
]

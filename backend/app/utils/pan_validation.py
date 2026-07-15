"""
Problem: PAN is alphanumeric (ABCPK1234R) but users speak it letter by letter.
  User says:  "A B C P K 1 2 3 4 R"
  Deepgram returns: "A B C P K 1 2 3 4 R"  or  "ABCPK 1234 R"
  We need: "ABCPK1234R"

PAN format: 5 letters + 4 digits + 1 letter (always 10 characters)
  Example: ABCPK1234R
  Regex:   ^[A-Z]{5}[0-9]{4}[A-Z]{1}$

Used in:
  - VERIFY_PAN state: normalize what user spoke → validate format → DB lookup
"""

import re

# Maps spoken letters/numbers Deepgram might spell out or confuse
# Adding common Deepgram mishears for letters when spoken individually
SPOKEN_TO_CHAR = {
    # digits
    "zero" : "0", "oh": "0",
    "one"  : "1",
    "two"  : "2",
    "three": "3",
    "four" : "4",
    "five" : "5",
    "six"  : "6",
    "seven": "7",
    "eight": "8",
    "nine" : "9",
}

PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")


def normalize_pan(text: str) -> str:
    """
    Normalizes a spoken PAN transcript into the standard 10-character format.

    Steps:
      1. Uppercase everything
      2. Replace spoken digit words with actual digits
      3. Remove all spaces and non-alphanumeric characters
      4. Return the cleaned string (caller then validates with is_valid_pan)

    Examples:
        normalize_pan("A B C P K 1 2 3 4 R")   → "ABCPK1234R"
        normalize_pan("abcpk 1234 r")            → "ABCPK1234R"
        normalize_pan("A B C P K one two three four R") → "ABCPK1234R"
    """
    text = text.upper().strip()

    # Replace spoken digit words (uppercased now, so match uppercase)
    for word, char in SPOKEN_TO_CHAR.items():
        text = re.sub(rf"\b{word.upper()}\b", char, text)

    # Remove spaces and anything that isn't a letter or digit
    text = re.sub(r"[^A-Z0-9]", "", text)

    return text


def is_valid_pan(pan: str) -> bool:
    """
    Returns True if the string matches the PAN format exactly.
    Call this AFTER normalize_pan.

    Examples:
        is_valid_pan("ABCPK1234R")  → True
        is_valid_pan("ABCPK123")    → False  (too short)
        is_valid_pan("abcpk1234r")  → False  (lowercase — normalize first)
        is_valid_pan("ABCPK1234RX") → False  (too long)
    """
    return bool(PAN_REGEX.match(pan))


def extract_pan(text: str) -> str | None:
    """
    Convenience function — normalize + validate in one call.
    Returns the clean PAN string if valid, None if the transcript
    doesn't contain a valid PAN.

    This is what the state machine actually calls.

    Examples:
        extract_pan("A B C P K 1 2 3 4 R")  → "ABCPK1234R"
        extract_pan("I don't know my PAN")   → None
    """
    normalized = normalize_pan(text)
    if is_valid_pan(normalized):
        return normalized
    return None
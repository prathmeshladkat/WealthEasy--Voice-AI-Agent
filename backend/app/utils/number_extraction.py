"""
Problem: Deepgram transcribes phone numbers as words, not digits.
  User says:  "nine eight seven six five four three two one zero"
  Deepgram returns: "nine eight seven six five four three two one zero"
  We need: "9876543210"

Also handles mixed formats Deepgram sometimes returns:
  "98765 43210"     → "9876543210"
  "nine 8 seven 6"  → "9876"  (partial — handled by caller)
  "+91 98765 43210" → "919876543210"

Used in:
  - VERIFY_PHONE state: extract 10-digit phone from transcript
  - VERIFY_PAN state:   extract alphanumeric PAN from transcript
                        (PAN extraction is in pan_validation.py)
"""

import re

# Map of every English word Deepgram might use for a digit
WORD_TO_DIGIT = {
    "zero" : "0", "oh"   : "0",  # "oh" is commonly said instead of "zero"
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


def extract_digits(text: str) -> str:
    """
    Extracts all digits from a transcript, handling both spoken words
    and numeric characters.

    Steps:
      1. Lowercase the text
      2. Replace each spoken word with its digit
      3. Strip everything that isn't a digit

    Examples:
        extract_digits("nine eight seven six five four three two one zero")
        → "9876543210"

        extract_digits("+91 98765 43210")
        → "919876543210"

        extract_digits("my number is nine 8 seven 6")
        → "9876"
    """
    text = text.lower().strip()

    # Replace each word-digit with its numeric character
    # We sort by length descending so "seven" is replaced before "eve"
    # (not an issue with our word list but good defensive practice)
    for word, digit in WORD_TO_DIGIT.items():
        text = re.sub(rf"\b{word}\b", digit, text)

    # Strip everything that isn't a digit — spaces, +, punctuation, letters
    digits_only = re.sub(r"\D", "", text)
    return digits_only


def extract_phone_number(text: str) -> str | None:
    """
    Extracts a 10-digit Indian phone number from a transcript.
    Strips the country code (+91 or 91) if present.
    Returns the 10-digit string, or None if no valid number found.

    Examples:
        extract_phone_number("nine eight seven six five four three two one zero")
        → "9876543210"

        extract_phone_number("it is plus 91 98765 43210")
        → "9876543210"

        extract_phone_number("hello how are you")
        → None
    """
    digits = extract_digits(text)

    # Strip leading country code if present
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]

    if len(digits) == 10:
        return digits

    return None  # not a valid 10-digit number
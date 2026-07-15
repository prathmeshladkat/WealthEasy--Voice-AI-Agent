"""
Quick sanity check for number_extraction and pan_validation utils.
Run from backend/: python test_utils.py
"""

from app.utils.number_extraction import extract_digits, extract_phone_number
from app.utils.pan_validation import normalize_pan, is_valid_pan, extract_pan

print("=" * 50)
print("NUMBER EXTRACTION TESTS")
print("=" * 50)

# extract_digits
print(extract_digits("nine eight seven six five four three two one zero"))  # 9876543210
print(extract_digits("+91 98765 43210"))                                    # 919876543210
print(extract_digits("my number is nine 8 seven 6"))                        # 9876

print()

# extract_phone_number
print(extract_phone_number("nine eight seven six five four three two one zero"))  # 9876543210
print(extract_phone_number("plus 91 98765 43210"))                                # 9876543210
print(extract_phone_number("hello how are you"))                                  # None

print()
print("=" * 50)
print("PAN VALIDATION TESTS")
print("=" * 50)

# normalize_pan
print(normalize_pan("A B C P K 1 2 3 4 R"))                    # ABCPK1234R
print(normalize_pan("abcpk 1234 r"))                            # ABCPK1234R
print(normalize_pan("A B C P K one two three four R"))          # ABCPK1234R

print()

# is_valid_pan
print(is_valid_pan("ABCPK1234R"))   # True
print(is_valid_pan("ABCPK123"))     # False
print(is_valid_pan("ABCPK1234RX"))  # False

print()

# extract_pan — the one the state machine actually calls
print(extract_pan("A B C P K 1 2 3 4 R"))       # ABCPK1234R
print(extract_pan("I don't know my PAN"))         # None
print(extract_pan("B C D E F 5 6 7 8 S"))        # BCDEF5678S  ← Priya's PAN
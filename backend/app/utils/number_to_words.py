"""
app/utils/number_to_words.py — deterministic number → spoken words conversion.

Why this exists:
  We confirmed in production logs that the LLM (llama-3.1-8b-instant) can
  correctly receive a tool result containing {"monthly_amount": 5000.0, ...}
  and still SPEAK it back as "fifty thousand rupees" instead of "five
  thousand rupees" — the underlying data was always correct, only the final
  free-form "convert this number to natural language" step was unreliable.

  Small/fast models are measurably weaker at exactly this task, especially
  converting into the Indian lakh/crore numbering system rather than the
  Western thousand/million system they see more of in training data.

  The fix: never ask the LLM to do this conversion at all. We do it here,
  deterministically, and hand the LLM a ready-made phrase to relay verbatim.
  A template function either produces the exact right words or raises —
  there's no "close enough" failure mode like free-form generation has.

Usage:
    from app.utils.number_to_words import format_rupees_spoken, format_number_spoken

    format_rupees_spoken(5000)        -> "five thousand rupees"
    format_rupees_spoken(2522880)     -> "twenty five lakh twenty two thousand eight hundred eighty rupees"
    format_rupees_spoken(0)           -> "zero rupees"
    format_number_spoken(15)          -> "fifteen"
    format_number_spoken(12.5)        -> "twelve point five"
"""

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
]


def _two_digit_words(n: int) -> str:
    """n is 0-99."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return _TENS[tens]
    return f"{_TENS[tens]} {_ONES[ones]}"


def _three_digit_words(n: int) -> str:
    """n is 0-999."""
    if n < 100:
        return _two_digit_words(n)
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return f"{_ONES[hundreds]} hundred"
    return f"{_ONES[hundreds]} hundred {_two_digit_words(rest)}"


def _int_to_words_indian(n: int) -> str:
    """
    Converts a non-negative integer into words using the Indian numbering
    system (crore = 10,000,000 / lakh = 100,000 / thousand = 1,000),
    which is how amounts are naturally spoken in Indian English — this is
    NOT the same grouping as the Western "million/billion" system.
    """
    if n == 0:
        return "zero"

    parts = []

    crore, n = divmod(n, 10_000_000)
    if crore:
        parts.append(f"{_int_to_words_indian(crore)} crore")

    lakh, n = divmod(n, 100_000)
    if lakh:
        parts.append(f"{_two_digit_words(lakh) if lakh < 100 else _int_to_words_indian(lakh)} lakh")

    thousand, n = divmod(n, 1_000)
    if thousand:
        parts.append(f"{_two_digit_words(thousand) if thousand < 100 else _int_to_words_indian(thousand)} thousand")

    if n:
        parts.append(_three_digit_words(n))

    return " ".join(parts)


def format_number_spoken(value: float | int) -> str:
    """
    Generic number → words, no unit/suffix. Rounds to 2 decimal places;
    a fractional part (if any) is spoken as "point <digit> <digit>...".
    Use this for things like years, percentages (caller adds "percent"),
    counts, etc. — anything that isn't a rupee amount.
    """
    is_negative = value < 0
    value = abs(value)

    whole = int(value)
    frac = round(value - whole, 2)

    words = _int_to_words_indian(whole)

    if frac > 0:
        frac_str = f"{frac:.2f}".split(".")[1].rstrip("0") or "0"
        frac_words = " ".join(_ONES[int(d)] for d in frac_str)
        words = f"{words} point {frac_words}"

    return f"negative {words}" if is_negative else words


def format_rupees_spoken(amount: float | int) -> str:
    """
    Formats a rupee amount as spoken words, rounded to the nearest whole
    rupee (paise aren't meaningful to speak aloud on a voice call).

    format_rupees_spoken(5000)     -> "five thousand rupees"
    format_rupees_spoken(2522880)  -> "twenty five lakh twenty two thousand eight hundred eighty rupees"
    """
    rounded = round(amount)
    words = _int_to_words_indian(abs(rounded))
    prefix = "negative " if rounded < 0 else ""
    return f"{prefix}{words} rupees"
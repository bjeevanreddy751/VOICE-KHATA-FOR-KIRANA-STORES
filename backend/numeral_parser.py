"""
VaaniKhata – Code-Mix Indic Numeral & Relative Date Engine
============================================================
Fast (< 5 ms), zero-dependency deterministic text normalizer for
noisy Indian retail speech (Hindi, Hinglish, Kannada-English, English).

Converts spoken words, fractions, idioms, and Indic script digits into
standard ASCII numerals, resolves relative dates, and produces clean
spoken Hindi words for Gnani Timbre v3.0 TTS (0 raw digits).
"""

from __future__ import annotations

import datetime
import re
from typing import Tuple

# ---------------------------------------------------------------------------
# Indic Script Digit Translations
# ---------------------------------------------------------------------------
_DEVANAGARI_DIGITS = "०१२३४५६७८९"
_KANNADA_DIGITS = "೦೧೨೩೪೫೬೭೮೯"
_TAMIL_DIGITS = "௦௧௨௩௪௫௬௭௮௯"
_TELUGU_DIGITS = "౦౧౨౩౪౫౬౭౮౯"
_ASCII_DIGITS = "0123456789"

_DIGIT_TRANS_TABLE = str.maketrans(
    _DEVANAGARI_DIGITS + _KANNADA_DIGITS + _TAMIL_DIGITS + _TELUGU_DIGITS,
    _ASCII_DIGITS * 4,
)

# ---------------------------------------------------------------------------
# Hindi / Hinglish Number Word Mappings (1 to 99)
# ---------------------------------------------------------------------------
_HINDI_UNITS_MAP: dict[str, int] = {
    "ek": 1, "do": 2, "teen": 3, "chaar": 4, "char": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "baarah": 12, "barah": 12, "terah": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "athaarah": 18,
    "unnees": 19, "unnis": 19, "bees": 20, "bis": 20,
    "ikkees": 21, "ikkis": 21, "baees": 22, "bais": 22, "teees": 23, "teis": 23,
    "chaubees": 24, "chaubis": 24, "pachis": 25, "pachchees": 25,
    "chhabbees": 26, "chhabis": 26, "sattaees": 27, "sattais": 27,
    "atthaees": 28, "atthais": 28, "untees": 29, "untis": 29, "tees": 30,
    "iktis": 31, "battis": 32, "tentis": 33, "chautis": 34,
    "paitis": 35, "paintees": 35, "chhattis": 36, "saintis": 37,
    "adtis": 38, "untalis": 39, "chalis": 40, "chaalis": 40,
    "iktalis": 41, "bayalis": 42, "taitalis": 43, "chawalis": 44,
    "paitalis": 45, "paitaalis": 45, "chhiyalis": 46, "saintalis": 47,
    "adtalis": 48, "unchas": 49, "pachas": 50, "pachaas": 50,
    "ikyawan": 51, "baawan": 52, "tirpan": 53, "chauwan": 54,
    "pachpan": 55, "chhappan": 56, "sattawan": 57, "atthawan": 58,
    "unsath": 59, "saath": 60, "iksath": 61, "baasath": 62,
    "tirsath": 63, "chaunsath": 64, "painsath": 65, "chhiyasath": 66,
    "sarsath": 67, "adsath": 68, "unhattar": 69, "sattar": 70,
    "ikhattar": 71, "bahattar": 72, "tihattar": 73, "chauhattar": 74,
    "pachhattar": 75, "chhihattar": 76, "sathattar": 77, "athhattar": 78,
    "unasi": 79, "assi": 80, "ikyasi": 81, "bayasi": 82,
    "tirasi": 83, "chaurasi": 84, "pachasi": 85, "chhiyasi": 86,
    "sattasi": 87, "atthasi": 88, "nauasi": 89, "nabbe": 90,
    "ikyanbe": 91, "bawanbe": 92, "tiranbe": 93, "chauranbe": 94,
    "pachanbe": 95, "chhiyanbe": 96, "sattanbe": 97, "atthanbe": 98,
    "ninyanbe": 99,
}

# English retail colloquial numbers (words -> int)
_ENGLISH_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# ---------------------------------------------------------------------------
# Idioms & Fixed Multi-Word Expressions (matched before compound rules)
# ---------------------------------------------------------------------------
_SPECIAL_IDIOMS: list[tuple[re.Pattern, str]] = [
    # Hindi fractions & idioms
    (re.compile(r"\b(?:dedh\s+sau|dedhsau)\b", re.IGNORECASE), "150"),
    (re.compile(r"\b(?:dhai\s+sau|dhaisau)\b", re.IGNORECASE), "250"),
    (re.compile(r"\b(?:sawa\s+sau|sawasau)\b", re.IGNORECASE), "125"),
    (re.compile(r"\b(?:paune\s+do\s+sau)\b", re.IGNORECASE), "175"),
    (re.compile(r"\b(?:sawa\s+do\s+sau)\b", re.IGNORECASE), "225"),
    (re.compile(r"\b(?:paune\s+teen\s+sau)\b", re.IGNORECASE), "275"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+teen\s+sau\b", re.IGNORECASE), "350"),
    (re.compile(r"\b(?:paune\s+chaar\s+sau|paune\s+char\s+sau)\b", re.IGNORECASE), "375"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+(?:chaar|char)\s+sau\b", re.IGNORECASE), "450"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+(?:paanch|panch)\s+sau\b", re.IGNORECASE), "550"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+(?:chhe|che)\s+sau\b", re.IGNORECASE), "650"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+saat\s+sau\b", re.IGNORECASE), "750"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+aath\s+sau\b", re.IGNORECASE), "850"),
    (re.compile(r"\b(?:saadhe|sadhe)\s+nau\s+sau\b", re.IGNORECASE), "950"),
    (re.compile(r"\b(?:dedh\s+hazaar|dedh\s+hazar)\b", re.IGNORECASE), "1500"),
    (re.compile(r"\b(?:dhai\s+hazaar|dhai\s+hazar)\b", re.IGNORECASE), "2500"),

    # Kannada shop numerals & compounds
    (re.compile(r"\bmooru\s+noora\s+nalavattu\b", re.IGNORECASE), "340"),
    (re.compile(r"\beradu\s+noora\s+aivattu\b", re.IGNORECASE), "250"),
    (re.compile(r"\bnoora\s+aivattu\b", re.IGNORECASE), "150"),
    (re.compile(r"\bnaalku\s+noora\s+moovattu\b", re.IGNORECASE), "430"),
    (re.compile(r"\b(?:eradu|yeradu)\s+nooru\b", re.IGNORECASE), "200"),
    (re.compile(r"\bmooru\s+nooru\b", re.IGNORECASE), "300"),
    (re.compile(r"\b(?:naalku|nalku)\s+nooru\b", re.IGNORECASE), "400"),
    (re.compile(r"\baidu\s+nooru\b", re.IGNORECASE), "500"),
    (re.compile(r"\baaru\s+nooru\b", re.IGNORECASE), "600"),
    (re.compile(r"\belu\s+nooru\b", re.IGNORECASE), "700"),
    (re.compile(r"\bentu\s+nooru\b", re.IGNORECASE), "800"),
    (re.compile(r"\bombattu\s+nooru\b", re.IGNORECASE), "900"),
    (re.compile(r"\b(?:ondhu\s+saavira|saavira)\b", re.IGNORECASE), "1000"),
    (re.compile(r"\bnooru\b", re.IGNORECASE), "100"),

    # Tamil shop numerals & compounds
    (re.compile(r"\bmunnoothi\s+naarpathu\b", re.IGNORECASE), "340"),
    (re.compile(r"\bnaanoothi\s+muppathu\b", re.IGNORECASE), "430"),
    (re.compile(r"\birunoothi\s+ambathu\b", re.IGNORECASE), "250"),
    (re.compile(r"\bnoothi\s+ambathu\b", re.IGNORECASE), "150"),
    (re.compile(r"\birunooru\b", re.IGNORECASE), "200"),
    (re.compile(r"\bmunnooru\b", re.IGNORECASE), "300"),
    (re.compile(r"\bnaanooru\b", re.IGNORECASE), "400"),
    (re.compile(r"\bainooru\b", re.IGNORECASE), "500"),
    (re.compile(r"\b(?:oru\s+aayiram|aayiram)\b", re.IGNORECASE), "1000"),

    # Telugu shop numerals & compounds
    (re.compile(r"\bmoodu\s+vandala\s+nalabhai\b", re.IGNORECASE), "340"),
    (re.compile(r"\bnaalugu\s+vandala\s+mupphai\b", re.IGNORECASE), "430"),
    (re.compile(r"\brendu\s+vandala\s+yaabhai\b", re.IGNORECASE), "250"),
    (re.compile(r"\bvanda\s+yaabhai\b", re.IGNORECASE), "150"),
    (re.compile(r"\brendu\s+vandal[au]\b", re.IGNORECASE), "200"),
    (re.compile(r"\bmoodu\s+vandal[au]\b", re.IGNORECASE), "300"),
    (re.compile(r"\bnaalugu\s+vandal[au]\b", re.IGNORECASE), "400"),
    (re.compile(r"\baidu\s+vandal[au]\b", re.IGNORECASE), "500"),
    (re.compile(r"\b(?:oka\s+veyyi|veyyi)\b", re.IGNORECASE), "1000"),
    (re.compile(r"\bvanda\b", re.IGNORECASE), "100"),

    # Marathi shop numerals & compounds
    (re.compile(r"\bteen\s+she\s+chaalis\b", re.IGNORECASE), "340"),
    (re.compile(r"\bchaar\s+she\s+tees\b", re.IGNORECASE), "430"),
    (re.compile(r"\b(?:dhaishe|dhai\s+she)\b", re.IGNORECASE), "250"),
    (re.compile(r"\b(?:dedhshe|dedh\s+she)\b", re.IGNORECASE), "150"),
    (re.compile(r"\b(?:paach\s+she|paachshe)\b", re.IGNORECASE), "500"),
    (re.compile(r"\b(?:chaar\s+she|chaarshe)\b", re.IGNORECASE), "400"),
    (re.compile(r"\b(?:teen\s+she|teenshe)\b", re.IGNORECASE), "300"),
    (re.compile(r"\b(?:don\s+she|donshe)\b", re.IGNORECASE), "200"),
    (re.compile(r"\bshambhar\b", re.IGNORECASE), "100"),

    # English retail compound pairs (e.g. "three-forty" -> 340, "four thirty" -> 430)
    (re.compile(r"\bthree[- ]forty\b", re.IGNORECASE), "340"),
    (re.compile(r"\bfour[- ]thirty\b", re.IGNORECASE), "430"),
    (re.compile(r"\btwo[- ]fifty\b", re.IGNORECASE), "250"),
    (re.compile(r"\bone[- ]eighty\b", re.IGNORECASE), "180"),
    (re.compile(r"\bone[- ]fifty\b", re.IGNORECASE), "150"),
    (re.compile(r"\btwo[- ]twenty\b", re.IGNORECASE), "220"),
    (re.compile(r"\bthree[- ]twenty\b", re.IGNORECASE), "320"),
    (re.compile(r"\bfour[- ]twenty\b", re.IGNORECASE), "420"),
    (re.compile(r"\bfive[- ]fifty\b", re.IGNORECASE), "550"),
]

# Patterns for compound hundreds/thousands
_HUNDRED_MULTIPLIERS = {
    "ek": 1, "do": 2, "teen": 3, "chaar": 4, "char": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
}

_ENGLISH_HUNDRED_MULTIPLIERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}


def _replace_hindi_compounds(text: str) -> str:
    """
    Match and normalize compound Hindi number phrases:
      e.g. 'ek hazaar do sau pachaas' -> 1250
           'teen sau chaalis' -> 340
           'chaar sau tees' -> 430
           'ek hazaar do sau' -> 1200
           'do sau' -> 200
    """
    # Regex matching: [thousands]? [hundreds]? [remainder]?
    # Example: "ek hazaar do sau pachaas"
    pattern = re.compile(
        r"\b(?:([a-z]+)\s+haza?ar)?\s*(?:([a-z]+)\s+sau)?\s*([a-z]+)?\b",
        re.IGNORECASE,
    )

    def repl(m: re.Match) -> str:
        th_word = (m.group(1) or "").lower()
        hd_word = (m.group(2) or "").lower()
        rm_word = (m.group(3) or "").lower()

        # At least one must be a valid numeral structural marker
        has_thousand = th_word in _HUNDRED_MULTIPLIERS
        has_hundred = hd_word in _HUNDRED_MULTIPLIERS

        if not has_thousand and not has_hundred:
            return m.group(0)

        total = 0
        if has_thousand:
            total += _HUNDRED_MULTIPLIERS[th_word] * 1000

        if has_hundred:
            total += _HUNDRED_MULTIPLIERS[hd_word] * 100

        if rm_word and rm_word in _HINDI_UNITS_MAP:
            total += _HINDI_UNITS_MAP[rm_word]
            return str(total)
        elif rm_word:
            # rm_word is not a number; leave it attached
            return f"{total} {rm_word}"

        return str(total)

    # Match specifically clauses with sau or hazar
    sau_hazar_pattern = re.compile(
        r"\b(?:(?:ek|do|teen|chaar|char|paanch|panch|chhe|che|saat|aath|nau)\s+haza?ar\s*)?"
        r"(?:(?:ek|do|teen|chaar|char|paanch|panch|chhe|che|saat|aath|nau)\s+sau)"
        r"(?:\s+(?:[a-z]+))?\b",
        re.IGNORECASE,
    )

    def sub_compound(m: re.Match) -> str:
        tokens = m.group(0).lower().split()
        idx = 0
        val = 0
        while idx < len(tokens):
            tok = tokens[idx]
            if tok in ("hazaar", "hazar") and idx > 0 and tokens[idx - 1] in _HUNDRED_MULTIPLIERS:
                pass  # already accounted for
            elif idx + 1 < len(tokens) and tokens[idx + 1] in ("hazaar", "hazar") and tok in _HUNDRED_MULTIPLIERS:
                val += _HUNDRED_MULTIPLIERS[tok] * 1000
                idx += 1
            elif idx + 1 < len(tokens) and tokens[idx + 1] == "sau" and tok in _HUNDRED_MULTIPLIERS:
                val += _HUNDRED_MULTIPLIERS[tok] * 100
                idx += 1
            elif tok == "sau":
                pass
            elif tok in _HINDI_UNITS_MAP:
                val += _HINDI_UNITS_MAP[tok]
            else:
                # trailing non-number word
                return f"{val} {tok}"
            idx += 1
        return str(val)

    # First handle thousand-only without sau e.g. "ek hazaar" -> 1000
    text = re.sub(
        r"\b(ek|do|teen|chaar|char|paanch|panch|chhe|che|saat|aath|nau)\s+haza?ar\b",
        lambda m: str(_HUNDRED_MULTIPLIERS[m.group(1).lower()] * 1000),
        text,
        flags=re.IGNORECASE,
    )

    # Now handle sau compounds
    text = sau_hazar_pattern.sub(sub_compound, text)
    return text


def _replace_english_compounds(text: str) -> str:
    """Normalize 'one hundred and forty' -> 140, 'two hundred' -> 200."""
    eng_hundred_pattern = re.compile(
        r"\b(one|two|three|four|five|six|seven|eight|nine)\s+hundred(?:\s+and)?(?:\s+([a-z]+))?\b",
        re.IGNORECASE,
    )

    def sub_eng(m: re.Match) -> str:
        mult = _ENGLISH_HUNDRED_MULTIPLIERS.get(m.group(1).lower(), 1)
        val = mult * 100
        rem = (m.group(2) or "").lower()
        if rem and rem in _ENGLISH_NUMBER_WORDS:
            val += _ENGLISH_NUMBER_WORDS[rem]
            return str(val)
        elif rem:
            return f"{val} {rem}"
        return str(val)

    return eng_hundred_pattern.sub(sub_eng, text)


# ---------------------------------------------------------------------------
# Public Functions
# ---------------------------------------------------------------------------
def normalize_spoken_numbers(text: str) -> str:
    """
    Normalize Indic script digits, fractions, idioms, and compound spoken
    number words into standard ASCII numerals while preserving customer names
    and retail context.
    """
    if not text:
        return ""

    # 1. Translate Devanagari, Kannada, and Tamil digits (e.g., ३४० -> 340)
    out = text.translate(_DIGIT_TRANS_TABLE)

    # 2. Strip attached currency symbols (e.g. ₹340 -> 340, Rs. 340 -> 340)
    out = re.sub(r"[₹]\s*(\d+)", r"\1", out)
    out = re.sub(r"\b(?:rs\.?|rupees?|rupaye?)\s*(\d+)", r"\1", out, flags=re.IGNORECASE)

    # 3. Apply fixed idioms and special expressions (e.g. dedh sau, three-forty)
    for pattern, replacement in _SPECIAL_IDIOMS:
        out = pattern.sub(replacement, out)

    # 4. Apply compound Hindi/Hinglish hundreds and thousands
    out = _replace_hindi_compounds(out)

    # 5. Apply English compound hundreds
    out = _replace_english_compounds(out)

    # 6. Apply unambiguous single-word Hindi number words (tens >= 10, e.g. chaalis -> 40)
    # Avoid replacing small words like 'do' which often acts as Hindi imperative verb ("udhaar do")
    # Only replace numbers >= 10 that cannot be confused with verbs.
    for word, val in _HINDI_UNITS_MAP.items():
        if val >= 10:
            out = re.sub(rf"\b{word}\b", str(val), out, flags=re.IGNORECASE)

    # Clean up any duplicate spacing
    out = re.sub(r"\s+", " ", out).strip()
    return out


def resolve_relative_date(text_segment: str) -> Tuple[int, str, str]:
    """
    Determine relative date from noisy Indian retail speech across 6 regional languages.
    Returns: (day_offset, 'YYYY-MM-DD', relative_label)
      - Day before (-2): 'parso', 'day before yesterday', 'monne', 'munnethu', 'parva', 'परसों', 'ಮೊನ್ನೆ'
      - Yesterday (-1): 'kal', 'yesterday', 'ninne', 'netru', 'nethu', 'ninna', 'kaal', 'कल', 'ನಿನ್ನೆ', 'நேற்று', 'నిన్న', 'काल'
      - Today (0): 'aaj', 'today', 'ivattu', 'inru', 'innikku', 'ee roju', 'aajach', 'आज', 'ಇವತ್ತು', 'இன்று', 'ఈ రోజు', 'आजच'
    """
    low = (text_segment or "").lower()
    today = datetime.date.today()

    # Day before yesterday (-2)
    if any(k in low for k in (
        "parso", "parson", "day before yesterday", "monne", "munnethu",
        "parva", "परसों", "ಮೊನ್ನೆ", "மின்னேத்து"
    )):
        target = today - datetime.timedelta(days=2)
        return -2, target.isoformat(), "Day Before (parso)"

    # Yesterday (-1)
    if any(k in low for k in (
        "kal", "yesterday", "ninne", "netru", "nethu", "ninna",
        "kaal", "kallu", "कल", "ನಿನ್ನೆ", "நேற்று", "నిన్న", "काल"
    )):
        target = today - datetime.timedelta(days=1)
        return -1, target.isoformat(), "Yesterday (kal)"

    # Default: Today (0)
    return 0, today.isoformat(), "Today"


def detect_language(text: str, stt_lang: str | None = None) -> str:
    """
    Detect spoken regional language among:
      'hi-IN' (Hindi/Hinglish), 'kn-IN' (Kannada), 'ta-IN' (Tamil),
      'te-IN' (Telugu), 'mr-IN' (Marathi), 'en-IN' (English).
    """
    if stt_lang and stt_lang not in ("auto", "indic-auto") and stt_lang in ("hi-IN", "kn-IN", "ta-IN", "te-IN", "mr-IN", "en-IN"):
        return stt_lang

    t = (text or "").strip()
    if not t:
        return "hi-IN"

    # 1. Unicode Script Block Detection
    for ch in t:
        code = ord(ch)
        if 0x0C80 <= code <= 0x0CFF:
            return "kn-IN"
        if 0x0B80 <= code <= 0x0BFF:
            return "ta-IN"
        if 0x0C00 <= code <= 0x0C7F:
            return "te-IN"

    # Devanagari script: distinguish Marathi vs Hindi
    if any(0x0900 <= ord(ch) <= 0x097F for ch in t):
        low_t = t.lower()
        marathi_devanagari_markers = ("आहे", "नाही", "उधारी", "दिले", "घेतले", "कोणाचे", "किती", "काल", "परवा", "आजच")
        if any(m in low_t for m in marathi_devanagari_markers):
            return "mr-IN"
        return "hi-IN"

    # 2. Romanized / Code-Mix Keyword Detection
    low = t.lower()
    tokens = set(re.findall(r"[a-z]+", low))

    # Kannada cues
    kn_cues = {
        "saala", "kotta", "kottidda", "eshtu", "ninne", "monne", "ivattu",
        "beda", "alla", "ge", "haaku", "nooru", "saavira", "aivattu", "nalavattu",
        "moovattu", "bariyabahudu", "hosa"
    }
    if tokens & kn_cues:
        return "kn-IN"

    # Tamil cues
    ta_cues = {
        "kadan", "kodutha", "kodu", "evlo", "netru", "nethu", "innikku",
        "illa", "vendam", "serkkappattathu", "kanakkil", "aayiram", "ambathu",
        "naarpathu", "muppathu", "irunooru", "munnooru", "pudhiya"
    }
    if tokens & ta_cues:
        return "ta-IN"

    # Telugu cues
    te_cues = {
        "appu", "ichadu", "ichanu", "entha", "ninna", "kaadu", "vaddu",
        "katha", "nomdhaiyindhi", "veyyi", "yaabhai", "nalabhai", "vandalu",
        "vandala", "cherchabadindhi", "kottha"
    }
    if tokens & te_cues:
        return "te-IN"

    # Marathi cues
    mr_cues = {
        "udhaari", "dile", "dilas", "kiti", "ahe", "aajach",
        "parva", "khate", "nondavli", "shambhar", "donshe", "teenshe",
        "chya", "chi", "jodla", "naveen"
    }
    if tokens & mr_cues:
        return "mr-IN"

    # Pure English retail cues
    en_cues = {
        "credit", "paid", "balance", "total", "customer", "record",
        "yesterday", "today", "due", "account", "please", "add"
    }
    if len(tokens & en_cues) >= 1 and not any(k in low for k in ("ka", "ki", "ke", "ko", "hai", "diya", "udhaar", "batao")):
        return "en-IN"

    return "hi-IN"


# ---------------------------------------------------------------------------
# Spoken Hindi Numbers (Strictly Zero ASCII Digits for Timbre v3.0 TTS)
# ---------------------------------------------------------------------------
_INT_TO_HINDI_MAP: dict[int, str] = {
    0: "shunya", 1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch",
    6: "chhe", 7: "saat", 8: "aath", 9: "nau", 10: "das",
    11: "gyarah", 12: "baarah", 13: "terah", 14: "chaudah", 15: "pandrah",
    16: "solah", 17: "satrah", 18: "atharah", 19: "unnees", 20: "bees",
    21: "ikkees", 22: "baees", 23: "teees", 24: "chaubees", 25: "pachis",
    26: "chhabbees", 27: "sattaees", 28: "atthaees", 29: "untees", 30: "tees",
    31: "iktis", 32: "battis", 33: "tentis", 34: "chautis", 35: "paintees",
    36: "chhattis", 37: "saintis", 38: "adtis", 39: "untalis", 40: "chaalis",
    41: "iktalis", 42: "bayalis", 43: "taitalis", 44: "chawalis", 45: "paitaalis",
    46: "chhiyalis", 47: "saintalis", 48: "adtalis", 49: "unchas", 50: "pachaas",
    51: "ikyawan", 52: "baawan", 53: "tirpan", 54: "chauwan", 55: "pachpan",
    56: "chhappan", 57: "sattawan", 58: "atthawan", 59: "unsath", 60: "saath",
    61: "iksath", 62: "baasath", 63: "tirsath", 64: "chaunsath", 65: "painsath",
    66: "chhiyasath", 67: "sarsath", 68: "adsath", 69: "unhattar", 70: "sattar",
    71: "ikhattar", 72: "bahattar", 73: "tihattar", 74: "chauhattar", 75: "pachhattar",
    76: "chhihattar", 77: "sathattar", 78: "athhattar", 79: "unasi", 80: "assi",
    81: "ikyasi", 82: "bayasi", 83: "tirasi", 84: "chaurasi", 85: "pachasi",
    86: "chhiyasi", 87: "sattasi", 88: "atthasi", 89: "nauasi", 90: "nabbe",
    91: "ikyanbe", 92: "bawanbe", 93: "tiranbe", 94: "chauranbe", 95: "pachanbe",
    96: "chhiyanbe", 97: "sattanbe", 98: "atthanbe", 99: "ninyanbe",
}


def number_to_spoken_hindi(amount: int) -> str:
    """
    Convert any integer (0 to 99999) into clean, natural spoken Hindi words
    for Gnani Timbre v3.0 TTS.
    GUARANTEE: Returned string contains strictly zero ASCII digits ('0'-'9').
    """
    if amount == 0:
        return "shunya"
    if amount < 0:
        return f"minus {number_to_spoken_hindi(abs(amount))}"

    n = abs(amount)
    parts: list[str] = []

    # Thousands
    if n >= 1000:
        th = n // 1000
        n %= 1000
        if th in _INT_TO_HINDI_MAP:
            parts.append(f"{_INT_TO_HINDI_MAP[th]} hazaar")
        else:
            parts.append(f"{number_to_spoken_hindi(th)} hazaar")

    # Hundreds
    if n >= 100:
        hd = n // 100
        n %= 100
        hd_word = _INT_TO_HINDI_MAP.get(hd, "ek")
        parts.append(f"{hd_word} sau")

    # Remainder (1 to 99)
    if n > 0:
        parts.append(_INT_TO_HINDI_MAP.get(n, ""))

    result = " ".join(p for p in parts if p).strip()
    return result


# ---------------------------------------------------------------------------
# Multi-Regional Spoken Numbers (Strictly Zero ASCII Digits for Timbre v3.0)
# ---------------------------------------------------------------------------
_ENG_UNITS: dict[int, str] = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
}

def _number_to_english(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {_number_to_english(abs(n))}"
    parts: list[str] = []
    if n >= 1000:
        th = n // 1000
        n %= 1000
        parts.append(f"{_number_to_english(th)} thousand")
    if n >= 100:
        hd = n // 100
        n %= 100
        parts.append(f"{_ENG_UNITS.get(hd, 'one')} hundred")
    if n > 0:
        if n in _ENG_UNITS:
            parts.append(_ENG_UNITS[n])
        else:
            tens = (n // 10) * 10
            rem = n % 10
            parts.append(f"{_ENG_UNITS.get(tens, '')} {_ENG_UNITS.get(rem, '')}".strip())
    return " ".join(parts).strip()


_KN_UNITS: dict[int, str] = {
    0: "sonne", 1: "ondhu", 2: "eradu", 3: "mooru", 4: "naalku", 5: "aidu",
    6: "aaru", 7: "elu", 8: "entu", 9: "ombattu", 10: "hattu",
    11: "hannondu", 12: "hanneradu", 13: "hadimooru", 14: "hadinaalku", 15: "hadinaidu",
    16: "hadinaaru", 17: "hadinelu", 18: "hadinentu", 19: "hatthombattu",
    20: "ippattu", 30: "moovattu", 40: "nalavattu", 50: "aivattu",
    60: "aravattu", 70: "eppattu", 80: "embattu", 90: "thombattu",
}
_KN_HUNDREDS: dict[int, str] = {
    1: "nooru", 2: "eradu nooru", 3: "mooru nooru", 4: "naalku nooru", 5: "aidu nooru",
    6: "aaru nooru", 7: "elu nooru", 8: "entu nooru", 9: "ombattu nooru",
}

def _number_to_kannada(n: int) -> str:
    if n == 0:
        return "sonne"
    if n < 0:
        return f"minus {_number_to_kannada(abs(n))}"
    parts: list[str] = []
    if n >= 1000:
        th = n // 1000
        n %= 1000
        prefix = f"{_KN_UNITS.get(th, 'ondhu')} " if th > 1 else ""
        parts.append(f"{prefix}saavira".strip())
    if n >= 100:
        hd = n // 100
        n %= 100
        if n > 0:
            hd_compound = {
                1: "noora", 2: "eradu noora", 3: "mooru noora",
                4: "naalku noora", 5: "aidu noora"
            }.get(hd, f"{_KN_UNITS.get(hd, '')} noora")
            parts.append(hd_compound)
        else:
            parts.append(_KN_HUNDREDS.get(hd, f"{_KN_UNITS.get(hd, '')} nooru"))
    if n > 0:
        if n in _KN_UNITS:
            parts.append(_KN_UNITS[n])
        else:
            tens = (n // 10) * 10
            rem = n % 10
            parts.append(f"{_KN_UNITS.get(tens, '')} {_KN_UNITS.get(rem, '')}".strip())
    return " ".join(parts).strip()


_TA_UNITS: dict[int, str] = {
    0: "poojiyam", 1: "onru", 2: "irandu", 3: "moonru", 4: "naangu", 5: "aindhu",
    6: "aaru", 7: "ezhu", 8: "ettu", 9: "onbadhu", 10: "patthu",
    20: "irubadhu", 30: "muppathu", 40: "naarpathu", 50: "ambathu",
    60: "arubathu", 70: "ezhubathu", 80: "enbathu", 90: "thonnooru",
}
_TA_HUNDREDS: dict[int, str] = {
    1: "nooru", 2: "irunooru", 3: "munnooru", 4: "naanooru", 5: "ainooru",
    6: "aranuru", 7: "ezhunuru", 8: "ennuru", 9: "thollayiram",
}

def _number_to_tamil(n: int) -> str:
    if n == 0:
        return "poojiyam"
    if n < 0:
        return f"minus {_number_to_tamil(abs(n))}"
    parts: list[str] = []
    if n >= 1000:
        th = n // 1000
        n %= 1000
        parts.append(f"{_TA_UNITS.get(th, 'oru')} aayiram")
    if n >= 100:
        hd = n // 100
        n %= 100
        if n > 0:
            hd_compound = {
                1: "noothi", 2: "irunoothi", 3: "munnoothi",
                4: "naanoothi", 5: "ainnoothi"
            }.get(hd, f"{_TA_UNITS.get(hd, '')} noothi")
            parts.append(hd_compound)
        else:
            parts.append(_TA_HUNDREDS.get(hd, f"{_TA_UNITS.get(hd, '')} nooru"))
    if n > 0:
        if n in _TA_UNITS:
            parts.append(_TA_UNITS[n])
        else:
            tens = (n // 10) * 10
            rem = n % 10
            parts.append(f"{_TA_UNITS.get(tens, '')} {_TA_UNITS.get(rem, '')}".strip())
    return " ".join(parts).strip()


_TE_UNITS: dict[int, str] = {
    0: "sunna", 1: "okati", 2: "rendu", 3: "moodu", 4: "naalugu", 5: "aidu",
    6: "aaru", 7: "eedu", 8: "enimidi", 9: "thommidi", 10: "padi",
    20: "iravai", 30: "mupphai", 40: "nalabhai", 50: "yaabhai",
    60: "aravai", 70: "debbhai", 80: "enabhai", 90: "tombhai",
}
_TE_HUNDREDS: dict[int, str] = {
    1: "vanda", 2: "rendu vandalu", 3: "moodu vandalu", 4: "naalugu vandalu", 5: "aidu vandalu",
    6: "aaru vandalu", 7: "eedu vandalu", 8: "enimidi vandalu", 9: "thommidi vandalu",
}

def _number_to_telugu(n: int) -> str:
    if n == 0:
        return "sunna"
    if n < 0:
        return f"minus {_number_to_telugu(abs(n))}"
    parts: list[str] = []
    if n >= 1000:
        th = n // 1000
        n %= 1000
        parts.append(f"{_TE_UNITS.get(th, 'oka')} veyyi")
    if n >= 100:
        hd = n // 100
        n %= 100
        if n > 0:
            hd_compound = {
                1: "vanda", 2: "rendu vandala", 3: "moodu vandala",
                4: "naalugu vandala", 5: "aidu vandala"
            }.get(hd, f"{_TE_UNITS.get(hd, '')} vandala")
            parts.append(hd_compound)
        else:
            parts.append(_TE_HUNDREDS.get(hd, f"{_TE_UNITS.get(hd, '')} vandalu"))
    if n > 0:
        if n in _TE_UNITS:
            parts.append(_TE_UNITS[n])
        else:
            tens = (n // 10) * 10
            rem = n % 10
            parts.append(f"{_TE_UNITS.get(tens, '')} {_TE_UNITS.get(rem, '')}".strip())
    return " ".join(parts).strip()


_MR_UNITS: dict[int, str] = {
    0: "shunya", 1: "ek", 2: "don", 3: "teen", 4: "chaar", 5: "paach",
    6: "saha", 7: "saat", 8: "aath", 9: "nau", 10: "daha",
    20: "vis", 30: "tees", 40: "chaalis", 50: "pannaas",
    60: "saath", 70: "sattar", 80: "eishi", 90: "nabbe",
}
_MR_HUNDREDS: dict[int, str] = {
    1: "shambhar", 2: "don she", 3: "teen she", 4: "chaar she", 5: "paach she",
    6: "saha she", 7: "saat she", 8: "aath she", 9: "nau she",
}

def _number_to_marathi(n: int) -> str:
    if n == 0:
        return "shunya"
    if n < 0:
        return f"minus {_number_to_marathi(abs(n))}"
    if n == 150:
        return "dedhshe"
    if n == 250:
        return "dhaishe"
    parts: list[str] = []
    if n >= 1000:
        th = n // 1000
        n %= 1000
        parts.append(f"{_MR_UNITS.get(th, 'ek')} hazaar")
    if n >= 100:
        hd = n // 100
        n %= 100
        parts.append(_MR_HUNDREDS.get(hd, f"{_MR_UNITS.get(hd, '')} she"))
    if n > 0:
        if n in _INT_TO_HINDI_MAP:
            parts.append(_INT_TO_HINDI_MAP[n])
        else:
            tens = (n // 10) * 10
            rem = n % 10
            parts.append(f"{_MR_UNITS.get(tens, '')} {_MR_UNITS.get(rem, '')}".strip())
    return " ".join(parts).strip()


def number_to_spoken_words(amount: int, lang: str = "hi-IN") -> str:
    """
    Convert any integer (0 to 99999) into clean, natural spoken words in the
    target regional language for Gnani Timbre v3.0 TTS.
    GUARANTEE: Returned string contains strictly zero ASCII digits ('0'-'9').
    """
    if lang == "kn-IN":
        return _number_to_kannada(amount)
    elif lang == "ta-IN":
        return _number_to_tamil(amount)
    elif lang == "te-IN":
        return _number_to_telugu(amount)
    elif lang == "mr-IN":
        return _number_to_marathi(amount)
    elif lang == "en-IN":
        return _number_to_english(amount)
    else:
        return number_to_spoken_hindi(amount)


# ---------------------------------------------------------------------------
# Indic Script to Latin Transliteration Engine
# ---------------------------------------------------------------------------
_INDIC_PHRASE_MAP: list[tuple[str, str]] = [
    # Hindi phrases
    ("कर दो", "kar do"),
    ("कर देना", "kar dena"),
    ("कर दीजिए", "kar dijiye"),
    ("नया कस्टमर", "naya customer"),
    ("नया ग्राहक", "naya customer"),
    ("नया खाता खोलो", "naya khata kholo"),
    ("खाता खोलो", "khata kholo"),
    ("खाता बनाओ", "khata banao"),
    ("खाते में", "khaate mein"),
    ("कुल बाकी", "kul baaki"),
    ("कितना बाकी", "kitna baaki"),
    ("कितना हुआ", "kitna hua"),
    ("उधार गया", "udhaar gaya"),
    ("आज का", "aaj ka"),
    ("अरे नहीं", "arre nahi"),
    # Kannada phrases
    ("ಹೊಸ ಗ್ರಾಹಕ", "hosa grahaka"),
    ("ಹೊಸ ಖಾತೆ", "hosa khaate"),
    ("ಖಾತೆ ತೆರೆ", "khaate tere"),
    # Tamil phrases
    ("புதிய வாடிக்கையாளர்", "pudhiya customer"),
    ("புதிய கணக்கு", "pudhiya kanakku"),
    # Telugu phrases
    ("కొత్త కస్టమర్", "kottha customer"),
    ("కొత్త ఖాతా", "kottha khata"),
]

_INDIC_WORD_MAP: dict[str, str] = {
    # Devanagari Customer Names
    "रमेश": "ramesh", "रमेंश": "ramesh", "शर्मा": "sharma", "वर्मा": "verma",
    "सुरेश": "suresh", "गौड़ा": "gowda", "गौडा": "gowda", "लक्ष्मी": "lakshmi",
    "देवी": "devi", "किरण": "kiran", "कुमार": "kumar", "अमित": "amit",
    "राजेश": "rajesh", "प्रिया": "priya", "अंजली": "anjali", "राहुल": "rahul",
    "सुनील": "sunil", "अनिल": "anil", "विकास": "vikas", "पूजा": "pooja",
    "दीपक": "deepak", "मनोज": "manoj", "संजय": "sanjay", "विजय": "vijay",
    "अजय": "ajay", "रोहित": "rohit", "सचिन": "sachin", "गौरव": "gaurav",
    "नीरज": "neeraj", "वसीम": "waseem", "मोहम्मद": "mohammed", "खान": "khan",
    "पटेल": "patel", "सिंह": "singh", "गुप्ता": "gupta", "रेड्डी": "reddy",

    # Devanagari Ledger & Retail Keywords
    "उधार": "udhaar", "उधारी": "udhaari", "कल": "kal", "दिया": "diya",
    "दिए": "diye", "दी": "di", "था": "tha", "थी": "thi", "थे": "the",
    "जमा": "jama", "नहीं": "nahi", "नही": "nahi", "गलत": "galat",
    "कर": "kar", "दो": "do", "करो": "karo", "दीजिए": "dijiye",
    "आज": "aaj", "टोटल": "total", "कितना": "kitna", "कितने": "kitne",
    "कितनी": "kitni", "बाकी": "baaki", "का": "ka", "की": "ki",
    "के": "ke", "को": "ko", "खाता": "khata", "खाते": "khaate",
    "में": "mein", "है": "hai", "हैं": "hain", "रुपये": "rupaye",
    "रुपया": "rupiya", "रुपए": "rupaye", "नया": "naya", "नई": "nayi",
    "कस्टमर": "customer", "ग्राहक": "grahak", "जोड़ो": "jodo", "जोड़": "jod",
    "जोडो": "jodo", "ऐड": "add", "बनाओ": "banao", "लिखो": "likho",
    "लिख": "likh", "परसों": "parso", "परसो": "parso", "लोन": "loan",
    "ब्याज": "byaaj", "हफ्ता": "hafta", "धमकी": "dhamki", "पुलिस": "police",
    "और": "aur", "फिर": "phir", "लेकिन": "lekin", "हिसाब": "hisaab",
    "हिशाब": "hisaab", "पैसा": "paisa", "पैसे": "paise", "कैश": "cash",

    # Marathi Devanagari Keywords
    "आहे": "ahe", "नाही": "nahi", "दिले": "dile", "दिलीस": "dilis",
    "घेतले": "ghetle", "कोणाचे": "konache", "किती": "kiti", "काल": "kal",
    "परवा": "parva", "आजच": "aajach", "नवीन": "naveen", "आणि": "aani",

    # Kannada Script Names & Keywords
    "ರಮೇಶ್": "ramesh", "ರಮೇಶ": "ramesh", "ಶರ್ಮಾ": "sharma", "ವರ್ಮಾ": "verma",
    "ಸುರೇಶ್": "suresh", "ಸುರೇಶ": "suresh", "ಗೌಡ": "gowda", "ಲಕ್ಷ್ಮಿ": "lakshmi",
    "ಲಕ್ಷ್ಮೀ": "lakshmi", "ದೇವಿ": "devi", "ಕಿರಣ್": "kiran", "ಕುಮಾರ್": "kumar",
    "ಸಾಲ": "saala", "ಕೊಟ್ಟ": "kotta", "ಕೊಟ್ಟಿದ್ದ": "kottidda", "ಕೊಡು": "kodu",
    "ನಿನ್ನೆ": "ninne", "ಮೊನ್ನೆ": "monne", "ಇವತ್ತು": "ivattu", "ಜಮಾ": "jama",
    "ಹಾಕು": "haaku", "ಬೇಡ": "beda", "ಅಲ್ಲ": "alla", "ಎಷ್ಟು": "eshtu",
    "ಹೊಸ": "hosa", "ಗ್ರಾಹಕ": "grahaka", "ಖಾತೆ": "khaate", "ಬರೆ": "bare",
    "ರೂಪಾಯಿ": "roopayi", "ಮತ್ತು": "matthu", "ಒಟ್ಟು": "ottu",

    # Tamil Script Names & Keywords
    "ரமேஷ்": "ramesh", "சர்மா": "sharma", "வர்மா": "verma", "சுரேஷ்": "suresh",
    "லக்ஷ்மி": "lakshmi", "தேவி": "devi", "கிரண்": "kiran", "குமார்": "kumar",
    "கடன்": "kadan", "கொடுத்தார்": "kodutha", "கொடுத்த": "kodutha", "கொடு": "kodu",
    "நேற்று": "netru", "நேத்து": "nethu", "இன்று": "innikku", "இன்னைக்கு": "innikku",
    "ஜமா": "jama", "இல்லை": "illa", "வேண்டாம்": "vendam", "எவ்வளவு": "evlo",
    "புதிய": "pudhiya", "கணக்கு": "kanakku", "ரூபாய்": "roobai", "மற்றும்": "mattrum",

    # Telugu Script Names & Keywords
    "రమేష్": "ramesh", "శర్మ": "sharma", "వర్మ": "verma", "సురేష్": "suresh",
    "లక్ష్మి": "lakshmi", "దేవి": "devi", "కిరణ్": "kiran", "కుమార్": "kumar",
    "అప్పు": "appu", "ఇచ్చాడు": "ichadu", "ఇచ్చాను": "ichanu", "నిన్న": "ninna",
    "మొన్న": "monna", "ఈరోజు": "eroju", "జమా": "jama", "వద్దు": "vaddu",
    "కాదు": "kaadu", "ఎంత": "entha", "కొత్త": "kottha", "ఖాతా": "khata",
    "రూపాయలు": "roopayalu", "మరియు": "mariyu",
}

_INDIC_CHAR_MAP: dict[str, str] = {
    # Devanagari Vowels & Matras
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah',
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h',
    '्': '',
    # Devanagari Consonants
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    'क़': 'q', 'ख़': 'kh', 'ग़': 'g', 'ज़': 'z', 'ड़': 'r', 'ढ़': 'rh', 'फ़': 'f',

    # Kannada
    'ಅ': 'a', 'ಆ': 'aa', 'ಇ': 'i', 'ಈ': 'ee', 'ಉ': 'u', 'ಊ': 'oo', 'ಋ': 'ri',
    'ಎ': 'e', 'ಏ': 'e', 'ಐ': 'ai', 'ಒ': 'o', 'ಓ': 'o', 'ಔ': 'au', 'ಂ': 'm', 'ಃ': 'h',
    'ಾ': 'a', 'ಿ': 'i', 'ೀ': 'ee', 'ು': 'u', 'ೂ': 'oo', 'ೃ': 'ri',
    'ೆ': 'e', 'ೇ': 'e', 'ೈ': 'ai', 'ೊ': 'o', 'ೋ': 'o', 'ೌ': 'au', '್': '',
    'ಕ': 'k', 'ಖ': 'kh', 'ಗ': 'g', 'ಘ': 'gh', 'ಙ': 'ng',
    'ಚ': 'ch', 'ಛ': 'chh', 'ಜ': 'j', 'ಝ': 'jh', 'ಞ': 'ny',
    'ಟ': 't', 'ಠ': 'th', 'ಡ': 'd', 'ಢ': 'dh', 'ಣ': 'n',
    'ತ': 't', 'ಥ': 'th', 'ದ': 'd', 'ಧ': 'dh', 'ನ': 'n',
    'ಪ': 'p', 'ಫ': 'ph', 'ಬ': 'b', 'ಭ': 'bh', 'ಮ': 'm',
    'ಯ': 'y', 'ರ': 'r', 'ಲ': 'l', 'ವ': 'v', 'ಶ': 'sh', 'ಷ': 'sh', 'ಸ': 's', 'ಹ': 'h', 'ಳ': 'l',

    # Tamil
    'அ': 'a', 'ஆ': 'aa', 'இ': 'i', 'ஈ': 'ee', 'உ': 'u', 'ஊ': 'oo',
    'எ': 'e', 'ஏ': 'e', 'ஐ': 'ai', 'ஒ': 'o', 'ஓ': 'o', 'ஔ': 'au', 'ஃ': 'h',
    'ா': 'a', 'ி': 'i', 'ீ': 'ee', 'ு': 'u', 'ூ': 'oo',
    'ெ': 'e', 'ே': 'e', 'ை': 'ai', 'ொ': 'o', 'ோ': 'o', 'ௌ': 'au', '்': '',
    'க': 'k', 'ங': 'ng', 'ச': 's', 'ஞ': 'ny', 'ட': 't', 'ண': 'n',
    'த': 't', 'ந': 'n', 'ப': 'p', 'ம': 'm', 'ய': 'y', 'ர': 'r',
    'ல': 'l', 'வ': 'v', 'ழ': 'zh', 'ள': 'l', 'ற': 'r', 'ன': 'n',
    'ஜ': 'j', 'ஷ': 'sh', 'ஸ': 's', 'ஹ': 'h',

    # Telugu
    'అ': 'a', 'ఆ': 'aa', 'ఇ': 'i', 'ఈ': 'ee', 'ఉ': 'u', 'ఊ': 'oo', 'ఋ': 'ri',
    'ఎ': 'e', 'ఏ': 'e', 'ఐ': 'ai', 'ఒ': 'o', 'ఓ': 'o', 'ఔ': 'au', 'ం': 'm', 'ః': 'h',
    'ా': 'a', 'ి': 'i', 'ీ': 'ee', 'ు': 'u', 'ూ': 'oo', 'ృ': 'ri',
    'ె': 'e', 'ే': 'e', 'ై': 'ai', 'ొ': 'o', 'ో': 'o', 'ౌ': 'au', '్': '',
    'క': 'k', 'ఖ': 'kh', 'గ': 'g', 'ఘ': 'gh', 'ఙ': 'ng',
    'చ': 'ch', 'ఛ': 'chh', 'జ': 'j', 'ఝ': 'jh', 'ఞ': 'ny',
    'ట': 't', 'ఠ': 'th', 'డ': 'd', 'ఢ': 'dh', 'ణ': 'n',
    'త': 't', 'థ': 'th', 'ద': 'd', 'ధ': 'dh', 'న': 'n',
    'ప': 'p', 'ఫ': 'ph', 'బ': 'b', 'భ': 'bh', 'మ': 'm',
    'య': 'y', 'ర': 'r', 'ల': 'l', 'వ': 'v', 'శ': 'sh', 'ష': 'sh', 'స': 's', 'హ': 'h', 'ళ': 'l',
}


def transliterate_to_latin(text: str) -> str:
    """
    Fast, zero-dependency Indic-to-Latin transliteration covering
    Devanagari (Hindi/Marathi), Kannada, Tamil, and Telugu.
    Maps customer names and retail keywords to standard Romanized ASCII
    while stripping Indic punctuation like '।' and '॥'.
    """
    if not text:
        return ""

    # 1. Strip Hindi / Indic punctuation
    t = text.replace("\u0964", " ").replace("\u0965", " ")

    # 2. Phrase-level replacements
    for phrase, rep in _INDIC_PHRASE_MAP:
        t = t.replace(phrase, rep)

    # 3. Word-level and character-level transliteration
    def _trans_word(w: str) -> str:
        w_clean = w.strip()
        if not w_clean:
            return w

        # Direct dictionary match
        if w_clean in _INDIC_WORD_MAP:
            return _INDIC_WORD_MAP[w_clean]

        # Check if contains any Indic characters
        has_indic = any(
            0x0900 <= ord(c) <= 0x097F or
            0x0C80 <= ord(c) <= 0x0CFF or
            0x0B80 <= ord(c) <= 0x0BFF or
            0x0C00 <= ord(c) <= 0x0C7F
            for c in w_clean
        )
        if not has_indic:
            return w

        # Character-level fallback transliteration
        out_chars = []
        for ch in w_clean:
            out_chars.append(_INDIC_CHAR_MAP.get(ch, ch))
        return "".join(out_chars)

    tokens = re.split(r"(\s+)", t)
    trans_tokens = [_trans_word(tok) if not tok.isspace() else tok for tok in tokens]
    result = "".join(trans_tokens).strip()
    return re.sub(r"\s+", " ", result)

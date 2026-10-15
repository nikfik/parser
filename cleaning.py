"""Funkcje czyszczące dane. Czyste funkcje (bez I/O) - łatwe do testowania.

Żadna z nich nie rzuca wyjątku dla "brudnych" danych: brak lub śmieć zamieniają
się w ``None`` (pusta wartość), a nie w błąd przerywający parser.
"""
from __future__ import annotations

import html
import re
import warnings
from datetime import date, timedelta

from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

# Teksty, które serwis wstawia zamiast brakującej wartości ("Not available" itd.).
PLACEHOLDERS = {
    "not available", "unknown", "untitled", "uncategorized", "date unknown",
    "price unavailable", "summary unavailable", "no additional text available.",
    "no additional text available", "n/a", "-", "",
}

# Stałe, przybliżone kursy do PLN - tylko po to, by porównywać ceny w jednej walucie.
# To założenie analityczne, nie dane rynkowe.
PLN_RATES = {"PLN": 1.0, "EUR": 4.25, "USD": 3.85, "GBP": 5.00, "CZK": 0.17, "JPY": 0.026}

_CODE_RE = re.compile(r"(EUR|GBP|USD|JPY|CZK|PLN)", re.I)
_SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD", "¥": "JPY", "kč": "CZK", "zł": "PLN", "zl": "PLN"}

MONTHS = {
    "jan": 1, "january": 1, "styczeń": 1, "stycznia": 1,
    "feb": 2, "february": 2, "luty": 2, "lutego": 2,
    "mar": 3, "march": 3, "marzec": 3, "marca": 3,
    "apr": 4, "april": 4, "kwiecień": 4, "kwietnia": 4,
    "may": 5, "maj": 5, "maja": 5,
    "jun": 6, "june": 6, "czerwiec": 6, "czerwca": 6,
    "jul": 7, "july": 7, "lipiec": 7, "lipca": 7,
    "aug": 8, "august": 8, "sierpień": 8, "sierpnia": 8,
    "sep": 9, "sept": 9, "september": 9, "wrzesień": 9, "września": 9,
    "oct": 10, "october": 10, "październik": 10, "października": 10,
    "nov": 11, "november": 11, "listopad": 11, "listopada": 11,
    "dec": 12, "december": 12, "grudzień": 12, "grudnia": 12,
}


def clean_text(value) -> str | None:
    """Usuwa znaczniki HTML, dekoduje encje (&nbsp; &oacute; &#39; ...), normalizuje spacje.

    Zwraca None dla pustych tekstów i placeholderów typu "Not available".
    """
    if value is None:
        return None
    text = str(value)
    if "<" in text or "&" in text:
        text = BeautifulSoup(text, "html.parser").get_text()
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace(" ", " ").replace("​", "")
    text = re.sub(r"\s+", " ", text).strip()
    if text.lower() in PLACEHOLDERS:
        return None
    return text


def _to_number(num: str) -> float | None:
    """Zamienia "1,299.00" / "1.299,00" / "1299,5" na float (heurystyka separatorów)."""
    negative = num.startswith("-")
    num = num.replace("-", "").strip(".,")
    if not num or not any(ch.isdigit() for ch in num):
        return None
    if "," in num and "." in num:
        decimal = "," if num.rfind(",") > num.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        num = num.replace(thousands, "").replace(decimal, ".")
    elif "," in num:
        parts = num.split(",")
        num = num.replace(",", "") if len(parts) > 2 or len(parts[-1]) == 3 else num.replace(",", ".")
    elif "." in num:
        parts = num.split(".")
        if len(parts) > 2 or (len(parts[-1]) == 3 and 0 < len(parts[0]) <= 3 and parts[0] != "0"):
            num = num.replace(".", "")
    try:
        value = float(num)
    except ValueError:
        return None
    return -value if negative else value


def parse_price(raw) -> tuple[float | None, str | None]:
    """"€2,380.41" / "2,275.62 £" / "Kč1,307.15" / "1106.86 GBP" / "1 299,00 zł" -> (liczba, kod waluty)."""
    if raw is None:
        return None, None
    s = str(raw).replace("\xa0", " ").replace(" ", " ").strip()
    if not s:
        return None, None
    currency = None
    code = _CODE_RE.search(s)
    if code:
        currency = code.group(1).upper()
    else:
        low = s.lower()
        for symbol, iso in _SYMBOLS.items():
            if symbol in low:
                currency = iso
                break
    number = re.sub(r"[^\d,.\-]", "", s)
    return _to_number(number), currency


def to_pln(value: float | None, currency: str | None) -> float | None:
    if value is None or currency not in PLN_RATES:
        return None
    return round(value * PLN_RATES[currency], 2)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_date(raw, ref: date | None = None) -> tuple[str | None, str]:
    """Ujednolica daty do ISO (YYYY-MM-DD). Zwraca (data, jakość).

    jakość: exact | ambiguous (np. 03/04/2025 - dd/mm czy mm/dd) | relative | missing | invalid
    """
    ref = ref or date.today()
    s = clean_text(raw)
    if s is None:
        return None, "missing"
    s = s.lower()

    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        d = _safe_date(int(m[1]), int(m[2]), int(m[3]))
        return (d.isoformat(), "exact") if d else (None, "invalid")

    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        d = _safe_date(int(m[3]), int(m[2]), int(m[1]))
        return (d.isoformat(), "exact") if d else (None, "invalid")

    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        dmy, mdy = _safe_date(year, b, a), _safe_date(year, a, b)
        if dmy and not mdy:
            return dmy.isoformat(), "exact"
        if mdy and not dmy:
            return mdy.isoformat(), "exact"
        if dmy and mdy:
            if dmy == mdy:
                return dmy.isoformat(), "exact"
            # dwuznaczne: preferujemy dd/mm, chyba że wychodzi data z przyszłości
            chosen = dmy if dmy <= ref or mdy > ref else mdy
            return chosen.isoformat(), "ambiguous"
        return None, "invalid"

    m = re.fullmatch(r"(\d{1,2})\s+([^\W\d_]+)\.?,?\s+(\d{4})", s)  # 26 August 2026
    if m and m[2] in MONTHS:
        d = _safe_date(int(m[3]), MONTHS[m[2]], int(m[1]))
        return (d.isoformat(), "exact") if d else (None, "invalid")

    m = re.fullmatch(r"([^\W\d_]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s)  # Aug 26, 2026
    if m and m[1] in MONTHS:
        d = _safe_date(int(m[3]), MONTHS[m[1]], int(m[2]))
        return (d.isoformat(), "exact") if d else (None, "invalid")

    m = re.fullmatch(r"(\d+)\s+(?:days?\s+ago|dni\s+temu|dzień\s+temu)", s)
    if m:
        return (ref - timedelta(days=int(m[1]))).isoformat(), "relative"
    if s in ("today", "dzisiaj", "dziś", "dzis"):
        return ref.isoformat(), "relative"
    if s in ("yesterday", "wczoraj"):
        return (ref - timedelta(days=1)).isoformat(), "relative"
    return None, "invalid"


def parse_int(raw) -> int | None:
    """"♥ 10269 likes" -> 10269; "1 234" -> 1234."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    m = re.search(r"\d[\d\s.,\xa0]*", str(raw))
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    return int(digits) if digits else None


def parse_float(raw) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = clean_text(raw)
    if s is None:
        return None
    return _to_number(re.sub(r"[^\d,.\-]", "", s))

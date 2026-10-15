import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleaning import clean_text, parse_date, parse_float, parse_int, parse_price, to_pln  # noqa: E402
from common import RateLimiter, retry  # noqa: E402

REF = date(2026, 10, 14)


@pytest.mark.parametrize("raw, expected", [
    ("€2,380.41", (2380.41, "EUR")),
    ("2,275.62 £", (2275.62, "GBP")),
    ("Kč1,307.15", (1307.15, "CZK")),
    ("1106.86 GBP", (1106.86, "GBP")),
    ("945.99 zł", (945.99, "PLN")),
    ("1 299,00 zł", (1299.0, "PLN")),          # polski format z twardą spacją
    ("1\xa0299,00 zł", (1299.0, "PLN")),
    ("1.299,50 €", (1299.5, "EUR")),
    ("¥2,077.23", (2077.23, "JPY")),
    ("$1,945.68", (1945.68, "USD")),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


def test_parse_price_does_not_inflate_decimal_comma():
    # klasyczny błąd: "1299,00" -> 129900
    assert parse_price("1299,00 zł")[0] == 1299.0


@pytest.mark.parametrize("raw", [None, "", "Price unavailable", "abc"])
def test_parse_price_missing_returns_none(raw):
    assert parse_price(raw)[0] is None


@pytest.mark.parametrize("raw, expected", [
    ("2026-08-26", ("2026-08-26", "exact")),
    ("26.08.2026", ("2026-08-26", "exact")),
    ("26/08/2026", ("2026-08-26", "exact")),      # dd/mm - dzień > 12
    ("08/26/2026", ("2026-08-26", "exact")),      # mm/dd - drugi człon > 12
    ("03/04/2025", ("2025-04-03", "ambiguous")),  # dwuznaczne -> dd/mm + flaga
    ("26 August 2026", ("2026-08-26", "exact")),
    ("Aug 26, 2026", ("2026-08-26", "exact")),
    ("3 days ago", ("2026-10-11", "relative")),
    ("Today", ("2026-10-14", "relative")),
    ("wczoraj", ("2026-10-13", "relative")),
    ("Date unknown", (None, "missing")),
    ("31/02/2026", (None, "invalid")),
    ("jakiś tekst", (None, "invalid")),
])
def test_parse_date(raw, expected):
    assert parse_date(raw, REF) == expected


def test_clean_text_entities_and_html():
    assert clean_text("Limited&nbsp;time offer! Customer favorite &#39;best&#39;") == "Limited time offer! Customer favorite 'best'"
    assert clean_text("Premium quality &oacute;ptimized") == "Premium quality óptimized"
    assert clean_text("New item. <strong>Best seller</strong> this season.") == "New item. Best seller this season."
    assert clean_text("  a \xa0 b\n c ") == "a b c"


@pytest.mark.parametrize("raw", [None, "", "  ", "Not available", "Unknown"])
def test_clean_text_placeholders_become_none(raw):
    assert clean_text(raw) is None


def test_parse_numbers():
    assert parse_int("♥ 10269 likes") == 10269
    assert parse_int("💬 2 228 comments") == 2228
    assert parse_int("brak") is None
    assert parse_float("4.6") == 4.6
    assert parse_float("Not available") is None


def test_to_pln():
    assert to_pln(100, "PLN") == 100
    assert to_pln(100, "EUR") == 425.0
    assert to_pln(None, "EUR") is None
    assert to_pln(100, "XXX") is None


def test_retry_uses_exponential_backoff():
    delays, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 4:
            raise TimeoutError("boom")
        return "ok"

    assert retry(flaky, attempts=5, base=1.0, sleep=delays.append) == "ok"
    assert delays == [1.0, 2.0, 4.0]


def test_retry_gives_up_after_limit_and_caps_delay():
    delays = []
    with pytest.raises(ValueError):
        retry(lambda: (_ for _ in ()).throw(ValueError("x")), attempts=6, base=1.0, cap=5.0, sleep=delays.append)
    assert delays == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_rate_limiter_enforces_minimum_gap():
    now = [0.0]
    slept = []

    def fake_sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(0.5, clock=lambda: now[0], sleep=fake_sleep)
    limiter.wait()
    limiter.wait()
    limiter.wait()
    assert slept == [0.5, 0.5]


def test_deduplicate_removes_id_and_content_duplicates():
    import pandas as pd
    from build_dataset import DEDUP_KEY, deduplicate

    base = {k: "x" for k in DEDUP_KEY}
    rows = [
        {**base, "id": 1, "sku": "a"},
        {**base, "id": 1, "sku": "a"},        # duplikat po id
        {**base, "id": 2, "sku": "b"},        # ta sama zawartość, inne id i sku
        {**base, "id": 3, "sku": "c", "title": "inny"},
    ]
    df, info = deduplicate(pd.DataFrame(rows))
    assert list(df["id"]) == [1, 3]
    assert info == {"before": 4, "duplicates_by_id": 1, "duplicates_by_content": 1, "after": 2}


def test_clean_record_survives_missing_everything():
    from build_dataset import clean_record

    rec = clean_record({"id": 5, "source_url": None, "price_raw": None, "published_raw": "Date unknown", "likes": None})
    assert rec["id"] == 5
    assert rec["price"] is None and rec["published_date"] is None and rec["likes"] is None
    assert rec["parse_issues"] == ""


def test_get_json_respects_retry_after_on_429():
    import logging

    from common import Counter
    from scrape_api import get_json

    class Resp:
        def __init__(self, code, headers=None, payload=None):
            self.status_code, self.headers, self._payload = code, headers or {}, payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.replies = [Resp(429, {"Retry-After": "7"}), Resp(200, payload=[{"id": 1}])]

        def get(self, url, params=None, timeout=None):
            return self.replies.pop(0)

    waits, counter = [], Counter()
    limiter = RateLimiter(0.5, sleep=lambda s: None)
    data = get_json(FakeSession(), "http://x/api", {}, limiter, counter, logging.getLogger("t"), sleep=waits.append)
    assert data == [{"id": 1}]
    assert 7.0 in waits                       # odczekano zgodnie z Retry-After
    assert counter.values["http_429"] == 1

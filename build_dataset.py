"""Surowe rekordy (feed + podstrona) -> oczyszczona tabela: czyszczenie, deduplikacja, walidacja, eksport."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from cleaning import (clean_text, parse_date, parse_float, parse_int, parse_price,
                      to_pln)

COLUMNS = [
    "id", "title", "category", "brand", "price", "currency", "price_pln", "price_raw",
    "published_date", "date_quality", "published_raw", "location", "description",
    "tags", "tags_count", "likes", "comments", "rating", "availability", "condition",
    "seller", "sku", "summary", "full_text", "author", "rm_published_date",
    "rm_published_quality", "rm_published_raw", "image_url", "source_url",
    "detail_url", "has_detail", "parse_issues",
]
# Pola, które powinny być wspólne dla listy i podstrony - do kontroli spójności.
CROSS_CHECK = [("title", "d_title"), ("category", "d_category"), ("location", "d_location")]
DEDUP_KEY = ["title", "category", "price", "currency", "published_date", "location",
             "description", "likes", "comments"]


def merge_records(feed_rows: list[dict], details: dict[int, dict]) -> list[dict]:
    """Łączy dane z listy i z podstron (po id). Rekord bez podstrony zostaje z pustymi polami."""
    merged = []
    for row in feed_rows:
        rec = dict(row)
        detail = details.get(row["id"])
        rec["has_detail"] = detail is not None
        if detail:
            rec.update(detail)
        merged.append(rec)
    return merged


def clean_record(rec: dict, base_url: str = "", ref: date | None = None) -> dict:
    """Jeden surowy rekord -> rekord w ujednoliconym formacie. Nie rzuca wyjątków."""
    issues: list[str] = []

    price_src = rec.get("price_raw") if clean_text(rec.get("price_raw")) else rec.get("d_price_raw")
    price, currency = parse_price(clean_text(price_src))
    if clean_text(price_src) and (price is None or currency is None):
        issues.append("price")

    pub_src = rec.get("published_raw") if clean_text(rec.get("published_raw")) else rec.get("d_published_raw")
    published, quality = parse_date(pub_src, ref)
    if quality == "invalid":
        issues.append("published_date")
    rm_pub, rm_quality = parse_date(rec.get("rm_published_raw"), ref)
    if rm_quality == "invalid":
        issues.append("rm_published_date")

    rating = parse_float(rec.get("rating_raw"))
    if clean_text(rec.get("rating_raw")) and (rating is None or not 0 <= rating <= 5):
        issues.append("rating")
        rating = None

    likes, comments = parse_int(rec.get("likes")), parse_int(rec.get("comments"))
    if likes is None and parse_int(rec.get("d_likes")) is not None:
        likes = parse_int(rec.get("d_likes"))
    if comments is None and parse_int(rec.get("d_comments")) is not None:
        comments = parse_int(rec.get("d_comments"))
    for name, val in (("likes", likes), ("comments", comments)):
        if val is not None and val < 0:
            issues.append(name)

    tags = [t for t in (clean_text(t) for t in rec.get("tags") or []) if t]
    pick = lambda a, b: clean_text(rec.get(a)) or clean_text(rec.get(b))  # noqa: E731
    rid = rec["id"]

    return {
        "id": rid,
        "title": pick("title", "d_title"),
        "category": pick("category", "d_category"),
        "brand": clean_text(rec.get("brand")),
        "price": price,
        "currency": currency,
        "price_pln": to_pln(price, currency),
        "price_raw": clean_text(price_src),
        "published_date": published,
        "date_quality": quality,
        "published_raw": clean_text(pub_src),
        "location": pick("location", "d_location"),
        "description": pick("description", "d_description"),
        "tags": "; ".join(tags),
        "tags_count": len(tags),
        "likes": likes,
        "comments": comments,
        "rating": rating,
        "availability": clean_text(rec.get("availability")),
        "condition": clean_text(rec.get("condition")),
        "seller": clean_text(rec.get("seller")),
        "sku": clean_text(rec.get("sku")),
        "summary": clean_text(rec.get("rm_summary")) or clean_text(rec.get("rm_summary_detail")),
        "full_text": clean_text(rec.get("rm_full_text")),
        "author": clean_text(rec.get("author")),
        "rm_published_date": rm_pub,
        "rm_published_quality": rm_quality,
        "rm_published_raw": clean_text(rec.get("rm_published_raw")),
        "image_url": clean_text(rec.get("image_url")),
        "source_url": (base_url.rstrip("/") + rec["source_url"]) if rec.get("source_url", "") and str(rec["source_url"]).startswith("/") else rec.get("source_url"),
        "detail_url": f"{base_url.rstrip('/')}/posts/{rid}",
        "has_detail": bool(rec.get("has_detail", True)),
        "parse_issues": ",".join(issues),
    }


def cross_check(raw_records: list[dict]) -> int:
    """Liczba rozbieżności między listą a podstroną (tytuł/kategoria/lokalizacja)."""
    mismatches = 0
    for rec in raw_records:
        for a, b in CROSS_CHECK:
            va, vb = clean_text(rec.get(a)), clean_text(rec.get(b))
            if va and vb and va != vb:
                mismatches += 1
    return mismatches


def deduplicate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Usuwa duplikaty po id oraz po zawartości (ignorując id/sku)."""
    before = len(df)
    by_id = df.duplicated("id", keep="first")
    df = df[~by_id]
    by_content = df.duplicated(DEDUP_KEY, keep="first")
    df = df[~by_content]
    return df.reset_index(drop=True), {
        "before": before, "duplicates_by_id": int(by_id.sum()),
        "duplicates_by_content": int(by_content.sum()), "after": len(df),
    }


def validation_report(df: pd.DataFrame) -> dict:
    """Typy kolumn i liczba odrzuconych (nieparsowalnych) wartości w każdej kolumnie."""
    rejected: dict[str, int] = {}
    for issues in df["parse_issues"].fillna(""):
        for issue in filter(None, issues.split(",")):
            rejected[issue] = rejected.get(issue, 0) + 1
    numeric = ["price", "price_pln", "likes", "comments", "rating", "tags_count"]
    return {
        "rows": len(df),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "numeric_columns_ok": {c: bool(pd.api.types.is_numeric_dtype(df[c])) for c in numeric},
        "rejected_values": rejected,
        "missing": {c: int(df[c].isna().sum() + (df[c] == "").sum()) for c in df.columns},
        "ambiguous_dates": int((df["date_quality"] == "ambiguous").sum()),
        "relative_dates": int((df["date_quality"] == "relative").sum()),
    }


def build(raw_records: list[dict], base_url: str, out_dir: Path, stem: str = "products",
          formats: tuple[str, ...] = ("csv", "xlsx", "json"), ref: date | None = None) -> tuple[pd.DataFrame, dict]:
    """Pełny pipeline czyszczenia + eksport. Zwraca (DataFrame, statystyki)."""
    ref = ref or date.today()
    cleaned = [clean_record(r, base_url, ref) for r in raw_records]
    df = pd.DataFrame(cleaned, columns=COLUMNS)
    for col in ("price", "price_pln", "rating"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("likes", "comments"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df, dedup = deduplicate(df)
    report = validation_report(df)
    report["deduplication"] = dedup
    report["cross_check_mismatches"] = cross_check(raw_records)
    report["scraped_at"] = datetime.now().isoformat(timespec="seconds")

    out_dir.mkdir(parents=True, exist_ok=True)
    if "csv" in formats:
        df.to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8-sig")
    if "xlsx" in formats:
        df.to_excel(out_dir / f"{stem}.xlsx", index=False)
    if "json" in formats:
        (out_dir / f"{stem}.json").write_text(
            df.astype(object).where(df.notna(), None).to_json(orient="records", force_ascii=False, indent=1),
            encoding="utf-8")
    (out_dir / f"{stem}_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return df, report

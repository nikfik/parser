"""Scraper "bez przeglądarki": korzysta ze źródła danych, którego używa sama strona (/api/v1/feed).

Strona ładuje kolejne porcje rekordów przez fetch('/api/v1/feed?limit=..&offset=..'), więc
zamiast uruchamiać Chrome i symulować scrollowanie, można pytać ten endpoint bezpośrednio.
Odpowiedź zawiera komplet pól (także dodatkowe i "read more"), więc podstrony nie są potrzebne.
Obsługuje kod 429 z nagłówkiem Retry-After.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests

import build_dataset
from common import Counter, RateLimiter, ResourceMonitor, retry, setup_logging


class RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"HTTP 429, Retry-After={wait}s")
        self.wait = wait


def get_json(session: requests.Session, url: str, params: dict, limiter: RateLimiter,
             counter: Counter, log, retries: int = 5, timeout: float = 30, sleep=time.sleep):
    """GET z limiterem, ponawianiem (backoff 1,2,4 s) i poszanowaniem Retry-After przy 429."""

    def once():
        limiter.wait()
        counter.add("requests")
        resp = session.get(url, params=params, timeout=timeout)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", "1") or 1)
            counter.add("http_429")
            raise RateLimited(wait)
        resp.raise_for_status()
        return resp.json()

    def with_retry_after():
        try:
            return once()
        except RateLimited as exc:
            log.warning("429 - czekam %.1f s zgodnie z Retry-After", exc.wait)
            sleep(exc.wait)
            raise

    return retry(with_retry_after, attempts=retries, base=1.0, cap=30.0,
                 retry_on=(requests.RequestException, RateLimited, ValueError),
                 sleep=sleep, log=log, what=f"GET {url}", counter=counter)


def json_to_raw(item: dict) -> tuple[dict, dict]:
    """Rekord JSON -> (wiersz "z listy", dane "z podstrony") w tym samym schemacie co scraper DOM."""
    info, rm, inter = item.get("additional_info") or {}, item.get("read_more") or {}, item.get("interaction") or {}
    feed = {
        "id": item["id"], "title": item.get("title"), "category": item.get("category"),
        "price_raw": item.get("price"), "published_raw": item.get("published_date"),
        "location": item.get("location"), "description": item.get("description"),
        "rm_summary": rm.get("summary"), "source_url": rm.get("source_url"),
        "likes": inter.get("likes"), "comments": inter.get("comments_count"),
    }
    detail = {
        "tags": item.get("tags") or [], "image_url": item.get("url"),
        "brand": info.get("brand"), "sku": info.get("sku"), "condition": info.get("condition"),
        "availability": info.get("availability"), "seller": info.get("seller"),
        "rating_raw": info.get("rating"), "rm_full_text": rm.get("full_text"),
        "author": rm.get("author"), "rm_published_raw": rm.get("published_date"),
    }
    return feed, detail


def run(args, log) -> dict:
    t0 = time.perf_counter()
    monitor = ResourceMonitor()
    monitor.start()
    base = args.base_url.rstrip("/")
    session, counter, limiter = requests.Session(), Counter(), RateLimiter(args.delay)
    session.headers["User-Agent"] = "PJN-lab1-scraper/1.0 (student project)"
    feed_rows, details, offset = [], {}, 0
    while True:
        size = min(args.page_size, args.limit - offset) if args.limit else args.page_size
        if size <= 0:
            break
        batch = get_json(session, f"{base}/api/v1/feed", {"limit": size, "offset": offset}, limiter, counter, log, args.retries)
        if not batch:
            break
        for item in batch:
            feed, detail = json_to_raw(item)
            feed_rows.append(feed)
            details[feed["id"]] = detail
        offset += len(batch)
        log.info("pobrano %d rekordów", offset)
        if len(batch) < size:
            break
    raw = build_dataset.merge_records(feed_rows, details)
    out = Path(args.output_dir)
    df, report = build_dataset.build(raw, base, out, "products", tuple(args.formats.split(",")))
    summary = {
        "mode": "api", "elapsed_s": round(time.perf_counter() - t0, 1), "peak_memory_mb": monitor.stop(),
        "requests": counter.values.get("requests", 0), "records_final": len(df),
        "errors": counter.values.get("errors", 0), "retries": counter.values.get("retries", 0),
        "http_429": counter.values.get("http_429", 0), "dedup": report["deduplication"],
        "finished": datetime.now().isoformat(timespec="seconds"),
    }
    (out / "summary_api.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("PODSUMOWANIE: %s", json.dumps(summary, ensure_ascii=False))
    return summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scraper oparty o endpoint JSON używany przez stronę")
    p.add_argument("--base-url", default="http://localhost:3000")
    p.add_argument("--output-dir", default="output/api")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--delay", type=float, default=0.5)
    p.add_argument("--retries", type=int, default=5)
    p.add_argument("--formats", default="csv,xlsx,json")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    if args.delay < 0.5:
        p.error("--delay musi wynosić co najmniej 0.5 s")
    return args


if __name__ == "__main__":
    args = parse_args()
    run(args, setup_logging(Path(args.output_dir) / "scrape_api.log", args.log_level))

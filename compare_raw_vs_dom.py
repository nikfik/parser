"""Porównanie surowego HTML (requests, bez przeglądarki) z drzewem DOM po wykonaniu skryptów (Selenium).

Wynik trafia do output/raw_vs_dom.json i jest cytowany w sprawozdaniu (wymóg poziomu 5.0).
Dodatkowo wykrywa żądania fetch/XHR wykonywane przez stronę (źródło danych JSON).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from scrape_selenium import FEED_CARDS, make_driver


def raw_counts(base: str, post_id: int) -> dict:
    feed = BeautifulSoup(requests.get(f"{base}/feed", timeout=30).text, "lxml")
    post_html = requests.get(f"{base}/posts/{post_id}", timeout=30).text
    post = BeautifulSoup(post_html, "lxml")
    return {
        "feed_cards": len(feed.select(FEED_CARDS)),
        "feed_html_bytes": len(requests.get(f"{base}/feed", timeout=30).content),
        "detail_spec_rows": len(post.select("#specifications tr")),
        "detail_list_items": len(post.select("#extra-list li")),
        "detail_read_more_elements": len(post.select("#read-more-content > *")),
        "detail_html_bytes": len(post_html.encode()),
    }


def dom_counts(base: str, post_id: int, timeout: float) -> tuple[dict, list[str]]:
    driver = make_driver(headless=True)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        wait = WebDriverWait(driver, timeout)
        driver.get(f"{base}/feed")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, FEED_CARDS)))
        initial = len(driver.find_elements(By.CSS_SELECTOR, FEED_CARDS))
        while True:
            count = len(driver.find_elements(By.CSS_SELECTOR, FEED_CARDS))
            status = driver.find_element(By.ID, "feed-status").text.lower()
            if "end of the feed" in status or "no more posts" in status:
                break
            driver.execute_script("window.scrollTo(0, 0); window.scrollTo(0, document.body.scrollHeight);")
            try:
                wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, FEED_CARDS)) > count
                           or "end of the feed" in d.find_element(By.ID, "feed-status").text.lower()
                           or "no more posts" in d.find_element(By.ID, "feed-status").text.lower())
            except Exception:  # noqa: BLE001
                pass
        feed_cards = len(driver.find_elements(By.CSS_SELECTOR, FEED_CARDS))
        # żądania fetch zarejestrowane przez przeglądarkę (Resource Timing API)
        endpoints = driver.execute_script(
            "return performance.getEntriesByType('resource').filter(e => e.initiatorType === 'fetch').map(e => e.name);")

        driver.get(f"{base}/posts/{post_id}")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.card-top h1")))
        driver.execute_script("document.getElementById('lazy-sentinel').scrollIntoView({block: 'center'});")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#specifications tr")))
        wait.until(EC.element_to_be_clickable((By.ID, "read-more-button"))).click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#read-more-content .summary")))
        endpoints += driver.execute_script(
            "return performance.getEntriesByType('resource').filter(e => e.initiatorType === 'fetch').map(e => e.name);")
        return {
            "feed_cards_initial_dom": initial,
            "feed_cards": feed_cards,
            "detail_spec_rows": len(driver.find_elements(By.CSS_SELECTOR, "#specifications tr")),
            "detail_list_items": len(driver.find_elements(By.CSS_SELECTOR, "#extra-list li")),
            "detail_read_more_elements": len(driver.find_elements(By.CSS_SELECTOR, "#read-more-content > *")),
        }, sorted({e.split("localhost:3000")[-1].split("?")[0] for e in endpoints})
    finally:
        driver.quit()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://localhost:3000")
    p.add_argument("--post-id", type=int, default=7)
    p.add_argument("--output", default="output/raw_vs_dom.json")
    p.add_argument("--timeout", type=float, default=30)
    a = p.parse_args()
    base = a.base_url.rstrip("/")
    raw = raw_counts(base, a.post_id)
    dom, endpoints = dom_counts(base, a.post_id, a.timeout)
    result = {"post_id": a.post_id, "raw_html": raw, "dom_after_js": dom, "fetch_endpoints": endpoints}
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))

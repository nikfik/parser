"""Scraper Selenium dla serwisu z infinite-scrollem (/feed) i podstronami (/posts/:id).

Funkcje (poziom 5.0):
  * jawne oczekiwanie (WebDriverWait z warunkiem), brak sleep() na sztywno do czekania na elementy,
  * doładowywanie porcjami do wyczerpania rekordów (scroll do sentinela),
  * ponawianie z opóźnieniem wykładniczym 1 s, 2 s, 4 s... (limit prób, limit opóźnienia),
  * rozszerzenia: zrzut ekranu + źródło strony przy błędzie, tryb headless, checkpoint/wznawianie,
    równoległe przeglądarki z globalnym limiterem żądań, parametryzacja z linii poleceń.
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import build_dataset
from common import Counter, RateLimiter, ResourceMonitor, retry, setup_logging
from parsing import parse_detail_page, parse_feed_cards


class ScrapeError(Exception):
    """Błąd logiczny scrapowania (np. strona pokazała komunikat o błędzie) - podlega ponawianiu."""


RETRY_ON = (TimeoutException, WebDriverException, ScrapeError)
FEED_CARDS = "#feed article.post"


def make_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--log-level=3")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_experimental_option("excludeSwitches", ["enable-logging"])
    # obrazki (picsum.photos z internetu) nie są nam potrzebne, a spowalniają ładowanie
    opts.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
    opts.page_load_strategy = "eager"  # czekamy jawnie na elementy, nie na pełne "load"
    return webdriver.Chrome(options=opts)


class Scraper:
    def __init__(self, args, log):
        self.args = args
        self.log = log
        self.base = args.base_url.rstrip("/")
        self.out = Path(args.output_dir)
        self.err_dir = self.out / "errors"
        self.limiter = RateLimiter(args.delay)
        self.counter = Counter()
        self.pool: queue.Queue = queue.Queue()
        self.drivers: list = []
        self.ckpt_feed = self.out / "checkpoint_feed.json"
        self.ckpt_details = self.out / "checkpoint_details.jsonl"
        self.save_lock = threading.Lock()
        self.stop_event = threading.Event()   # przycisk "Stop" w GUI
        self.hooks: dict = {}                 # opcjonalne callbacki: feed_progress(n), feed_rows(rows), detail(id, raw)
        self.keep_html = getattr(args, "keep_html", False)

    # ---------- infrastruktura ----------
    def _retry(self, fn, what):
        return retry(fn, attempts=self.args.retries, base=1.0, cap=30.0, retry_on=RETRY_ON,
                     log=self.log, what=what, counter=self.counter)

    def _diagnose(self, driver, name: str):
        """Zrzut ekranu i źródło strony - do diagnozy błędu."""
        self.err_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        try:
            driver.save_screenshot(str(self.err_dir / f"{name}_{stamp}.png"))
            (self.err_dir / f"{name}_{stamp}.html").write_text(driver.page_source, encoding="utf-8")
            self.log.info("zapisano diagnostykę błędu: %s_%s.(png|html)", name, stamp)
        except WebDriverException as exc:
            self.log.warning("nie udało się zapisać diagnostyki: %s", type(exc).__name__)

    def _healthy(self, driver) -> bool:
        try:
            driver.title  # noqa: B018
            return True
        except WebDriverException:
            return False

    def _get(self, driver, url: str):
        self.limiter.wait()
        driver.get(url)
        self.counter.add("requests")

    # ---------- faza 1: lista z infinite scrollem ----------
    def _status_text(self, driver) -> str:
        try:
            return driver.find_element(By.ID, "feed-status").text
        except WebDriverException:
            return ""

    @staticmethod
    def _feed_finished(status: str) -> bool:
        s = status.lower()
        return "reached the end" in s or "no more posts" in s

    def scrape_feed(self, driver) -> tuple[list[dict], dict]:
        wait = WebDriverWait(driver, self.args.timeout)

        def open_feed():
            self._get(driver, f"{self.base}/feed")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, FEED_CARDS)))

        self._retry(open_feed, "otwarcie /feed")
        batches = 0
        while True:
            count = len(driver.find_elements(By.CSS_SELECTOR, FEED_CARDS))
            if self.stop_event.is_set():
                self.log.warning("zatrzymano na żądanie użytkownika")
                break
            if self.args.limit and count >= self.args.limit:
                break
            if self._feed_finished(self._status_text(driver)):
                break

            def load_next_batch(count=count):
                self.limiter.wait()
                # Dojechanie do końca strony przecina sentinel (IntersectionObserver) i startuje fetch.
                # Gdy sentinel już przecina viewport, nie ma nowego zdarzenia - "szarpnięcie" w górę i w dół.
                driver.execute_script("window.scrollTo(0, 0);")
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.counter.add("requests")

                def progressed(d):
                    if len(d.find_elements(By.CSS_SELECTOR, FEED_CARDS)) > count:
                        return True
                    if self._feed_finished(self._status_text(d)):
                        return True
                    if d.find_elements(By.CSS_SELECTOR, "#feed-status button"):
                        raise ScrapeError("serwer zwrócił błąd przy doładowywaniu - przycisk 'Try again'")
                    return False

                WebDriverWait(driver, self.args.timeout).until(progressed)

            try:
                self._retry(load_next_batch, f"doładowanie porcji (po {count} kartach)")
            except RETRY_ON:
                self._diagnose(driver, "feed_error")
                self.counter.add("errors")
                self.log.error("przerywam doładowywanie na %d kartach", count)
                break
            batches += 1
            self.log.info("porcja %d: %d kart", batches, len(driver.find_elements(By.CSS_SELECTOR, FEED_CARDS)))
            if "feed_rows" in self.hooks:  # podgląd na żywo: bieżący snapshot kart (bez ciężkiego HTML)
                snapshot = driver.execute_script("return document.getElementById('feed').outerHTML;")
                rows_now = parse_feed_cards(snapshot)
                self.hooks["feed_rows"](rows_now[: self.args.limit] if self.args.limit else rows_now)

        html = driver.execute_script("return document.getElementById('feed').outerHTML;")
        rows = parse_feed_cards(html, keep_html=self.keep_html)
        if self.args.limit:
            rows = rows[: self.args.limit]
        return rows, {"batches": batches, "status": self._status_text(driver)}

    # ---------- faza 2: podstrony ----------
    def _load_detail(self, driver, post_id: int) -> dict:
        wait = WebDriverWait(driver, self.args.timeout)

        def open_page():
            self._get(driver, f"{self.base}/posts/{post_id}")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "article.card-top h1")))

        self._retry(open_page, f"otwarcie /posts/{post_id}")

        def load_extra():
            self.limiter.wait()
            driver.execute_script("window.scrollTo(0, 0);")
            driver.execute_script("document.getElementById('lazy-sentinel').scrollIntoView({block: 'center'});")
            self.counter.add("requests")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#specifications tr")))

        self._retry(load_extra, f"dane dodatkowe /posts/{post_id}")

        def load_read_more():
            self.limiter.wait()
            wait.until(EC.element_to_be_clickable((By.ID, "read-more-button"))).click()
            self.counter.add("requests")

            def done(d):
                if d.find_elements(By.CSS_SELECTOR, "#read-more-content .summary"):
                    return True
                err = d.find_element(By.ID, "read-more-error")
                if "hidden" not in (err.get_attribute("class") or "") and err.text:
                    raise ScrapeError(err.text)
                return False

            wait.until(done)

        self._retry(load_read_more, f"Read more /posts/{post_id}")
        return parse_detail_page(driver.page_source, keep_html=self.keep_html)

    def _task(self, post_id: int):
        if self.stop_event.is_set():
            return post_id, None
        driver = self.pool.get()
        try:
            detail = self._load_detail(driver, post_id)
            if "detail" in self.hooks:
                self.hooks["detail"](post_id, detail)
            return post_id, detail
        except Exception as exc:  # noqa: BLE001 - jeden zły rekord nie może zatrzymać całości
            self.counter.add("errors")
            self.log.error("rekord %s pominięty: %s: %s", post_id, type(exc).__name__, str(exc).splitlines()[0][:150] if str(exc) else "")
            self._diagnose(driver, f"post_{post_id}")
            if not self._healthy(driver):
                self.log.warning("przeglądarka przestała odpowiadać - uruchamiam nową")
                try:
                    driver.quit()
                except WebDriverException:
                    pass
                driver = make_driver(self.args.headless)
                self.drivers.append(driver)
            return post_id, None
        finally:
            self.pool.put(driver)

    # ---------- checkpoint ----------
    def _load_checkpoint(self):
        feed, details = None, {}
        if self.args.fresh:
            for f in (self.ckpt_feed, self.ckpt_details):
                f.unlink(missing_ok=True)
            return feed, details
        if self.ckpt_feed.exists():
            data = json.loads(self.ckpt_feed.read_text(encoding="utf-8"))
            if data.get("complete") or (self.args.limit and len(data["rows"]) >= self.args.limit):
                feed = data["rows"][: self.args.limit] if self.args.limit else data["rows"]
        if self.ckpt_details.exists():
            for line in self.ckpt_details.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    details[item["id"]] = item["detail"]
        return feed, details

    def _save_detail(self, post_id: int, detail: dict):
        with self.save_lock, self.ckpt_details.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": post_id, "detail": detail}, ensure_ascii=False) + "\n")

    # ---------- fazy (używane przez run() i przez GUI) ----------
    def open_browsers(self):
        n = max(1, self.args.workers)
        self.log.info("start: %s, headless=%s, przeglądarek=%d, opóźnienie=%.2f s",
                      self.base, self.args.headless, n, self.args.delay)
        for _ in range(n):  # tworzone po kolei - Selenium Manager pobiera sterownik raz
            drv = make_driver(self.args.headless)
            self.drivers.append(drv)
            self.pool.put(drv)

    def close_browsers(self):
        for drv in self.drivers:
            try:
                drv.quit()
            except WebDriverException:
                pass
        self.drivers.clear()
        self.pool = queue.Queue()

    def run_feed(self) -> tuple[list[dict], dict]:
        """Faza 1: lista (infinite scroll). Zapisuje checkpoint listy."""
        self.out.mkdir(parents=True, exist_ok=True)
        drv = self.pool.get()
        try:
            rows, info = self.scrape_feed(drv)
        finally:
            self.pool.put(drv)
        complete = self._feed_finished(info["status"]) and not self.args.limit
        self.ckpt_feed.write_text(json.dumps({"complete": complete, "rows": rows}, ensure_ascii=False), encoding="utf-8")
        self.log.info("lista: %d rekordów, %d porcji", len(rows), info["batches"])
        return rows, info

    def run_details(self, ids: list[int], details: dict) -> dict:
        """Faza 2: podstrony dla podanych id; wyniki dopisywane do `details` i do checkpointu."""
        with ThreadPoolExecutor(max_workers=max(1, self.args.workers), thread_name_prefix="w") as ex:
            futures = [ex.submit(self._task, pid) for pid in ids]
            for i, fut in enumerate(as_completed(futures), 1):
                pid, detail = fut.result()
                if detail is not None:
                    details[pid] = detail
                    self._save_detail(pid, detail)
                if i % 20 == 0 or i == len(futures):
                    self.log.info("podstrony: %d/%d", i, len(futures))
        return details

    def export(self, feed_rows, details, started, monitor, feed_info) -> dict:
        raw = build_dataset.merge_records(feed_rows, details)
        df, report = build_dataset.build(raw, self.base, self.out, "products", tuple(self.args.formats.split(",")))
        summary = {
            "mode": "selenium", "headless": self.args.headless, "workers": max(1, self.args.workers),
            "elapsed_s": round(time.perf_counter() - started, 1), "peak_memory_mb": monitor.stop(),
            "feed_batches": feed_info["batches"], "pages_visited": 1 + len(details),
            "records_feed": len(feed_rows), "records_with_detail": len(details),
            "records_final": len(df), "errors": self.counter.values.get("errors", 0),
            "retries": self.counter.values.get("retries", 0), "requests": self.counter.values.get("requests", 0),
            "dedup": report["deduplication"], "finished": datetime.now().isoformat(timespec="seconds"),
        }
        (self.out / "summary_selenium.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        self.log.info("PODSUMOWANIE: %s", json.dumps(summary, ensure_ascii=False))
        return summary

    # ---------- całość ----------
    def run(self) -> dict:
        t0 = time.perf_counter()
        monitor = ResourceMonitor()
        monitor.start()
        self.out.mkdir(parents=True, exist_ok=True)
        feed_rows, details = self._load_checkpoint()
        if feed_rows is not None or details:
            self.log.info("checkpoint: lista=%s, podstrony gotowe=%d", "tak" if feed_rows else "nie", len(details))
        self.open_browsers()
        feed_info = {"batches": 0, "status": "z checkpointu"}
        try:
            if feed_rows is None:
                feed_rows, feed_info = self.run_feed()
            todo = [r["id"] for r in feed_rows if r["id"] not in details]
            self.log.info("podstrony do pobrania: %d (pominięte z checkpointu: %d)", len(todo), len(feed_rows) - len(todo))
            self.run_details(todo, details)
        finally:
            self.close_browsers()
        return self.export(feed_rows, details, t0, monitor, feed_info)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Scraper Selenium (infinite scroll + podstrony szczegółów)")
    p.add_argument("--base-url", default="http://localhost:3000", help="adres serwisu")
    p.add_argument("--output-dir", default="output", help="katalog wyjściowy")
    p.add_argument("--limit", type=int, default=0, help="maks. liczba rekordów (0 = wszystkie)")
    p.add_argument("--headless", action="store_true", help="przeglądarka bez okna")
    p.add_argument("--workers", type=int, default=3, help="liczba równoległych przeglądarek")
    p.add_argument("--delay", type=float, default=0.5, help="min. odstęp między żądaniami [s] (>= 0.5)")
    p.add_argument("--timeout", type=float, default=20, help="limit WebDriverWait [s]")
    p.add_argument("--retries", type=int, default=5, help="maks. liczba prób (opóźnienia 1,2,4,8 s)")
    p.add_argument("--formats", default="csv,xlsx,json", help="formaty eksportu, np. csv,xlsx")
    p.add_argument("--fresh", action="store_true", help="ignoruj checkpoint i zacznij od zera")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    if args.delay < 0.5:
        p.error("--delay musi wynosić co najmniej 0.5 s")
    return args


if __name__ == "__main__":
    args = parse_args()
    log = setup_logging(Path(args.output_dir) / "scrape_selenium.log", args.log_level)
    try:
        Scraper(args, log).run()
    except KeyboardInterrupt:
        log.warning("przerwano - uruchom ponownie, aby wznowić od checkpointu")
        sys.exit(130)

"""Narzędzia wspólne dla scraperów: logowanie, retry z backoffem, limiter żądań, monitor zasobów."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import psutil


def setup_logging(log_path: Path, level: str = "INFO") -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("scraper")
    logger.setLevel(level)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(threadName)s %(message)s", "%H:%M:%S")
    for handler in (logging.FileHandler(log_path, "w", encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger


class Counter:
    """Wątkowo-bezpieczny licznik zdarzeń do podsumowania (retry, błędy...)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.values: dict[str, int] = {}

    def add(self, key: str, n: int = 1):
        with self._lock:
            self.values[key] = self.values.get(key, 0) + n


def retry(fn, *, attempts: int = 4, base: float = 1.0, cap: float = 30.0,
          retry_on: tuple = (Exception,), sleep=time.sleep, log: logging.Logger | None = None,
          what: str = "operacja", counter: Counter | None = None):
    """Wykonuje fn(); przy błędzie ponawia z opóźnieniem wykładniczym base, 2*base, 4*base... (max cap).

    Po ``attempts`` nieudanych próbach rzuca ostatni wyjątek.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if attempt == attempts:
                if log:
                    log.error("%s: porażka po %d próbach (%s)", what, attempts, type(exc).__name__)
                raise
            delay = min(cap, base * 2 ** (attempt - 1))
            if counter:
                counter.add("retries")
            if log:
                log.warning("%s: próba %d/%d nieudana (%s: %s) - ponawiam za %.1f s",
                            what, attempt, attempts, type(exc).__name__, str(exc).splitlines()[0][:120] if str(exc) else "", delay)
            sleep(delay)


class RateLimiter:
    """Gwarantuje minimalny odstęp między żądaniami - wspólny dla wszystkich wątków."""

    def __init__(self, min_interval: float, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = min_interval
        self._clock, self._sleep = clock, sleep
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self.min_interval
        if start > now:
            self._sleep(start - now)


class ResourceMonitor(threading.Thread):
    """Próbkuje pamięć (RSS) procesu i wszystkich jego potomków (Chrome, chromedriver)."""

    def __init__(self, interval: float = 0.5):
        super().__init__(daemon=True, name="resource-monitor")
        self.interval = interval
        self.peak_mb = 0.0
        self._stop_event = threading.Event()
        self._proc = psutil.Process()

    def _sample(self):
        try:
            procs = [self._proc] + self._proc.children(recursive=True)
            total = 0
            for p in procs:
                try:
                    total += p.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            self.peak_mb = max(self.peak_mb, total / 1024 ** 2)
        except psutil.Error:
            pass

    def run(self):
        while not self._stop_event.is_set():
            self._sample()
            self._stop_event.wait(self.interval)

    def stop(self) -> float:
        self._sample()
        self._stop_event.set()
        return round(self.peak_mb, 1)

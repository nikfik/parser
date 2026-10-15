"""Porównanie czasu i pamięci na tym samym podzbiorze danych:
Selenium (z oknem), Selenium (headless) i podejście bez przeglądarki (endpoint JSON).

Uruchamiać, gdy nic innego nie obciąża serwisu. Wynik: output/benchmark.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd: list[str]) -> None:
    print("->", " ".join(cmd), flush=True)
    subprocess.run([sys.executable, *cmd], cwd=HERE, check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--subset", type=int, default=20, help="liczba rekordów w teście")
    p.add_argument("--base-url", default="http://localhost:3000")
    a = p.parse_args()
    n, base = str(a.subset), a.base_url
    plan = {
        "selenium_headed": ["scrape_selenium.py", "--limit", n, "--workers", "1", "--fresh", "--base-url", base,
                            "--output-dir", "output/bench_headed", "--formats", "csv"],
        "selenium_headless": ["scrape_selenium.py", "--limit", n, "--workers", "1", "--fresh", "--headless", "--base-url", base,
                              "--output-dir", "output/bench_headless", "--formats", "csv"],
        "api_no_browser": ["scrape_api.py", "--limit", n, "--base-url", base, "--output-dir", "output/bench_api", "--formats", "csv"],
    }
    results = {}
    for name, cmd in plan.items():
        run(cmd)
        out = Path(cmd[cmd.index("--output-dir") + 1])
        summary = next(out.glob("summary_*.json"))
        results[name] = json.loads(summary.read_text(encoding="utf-8"))
    results["subset"] = a.subset
    (HERE / "output" / "benchmark.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, r in results.items():
        if isinstance(r, dict):
            print(f"{name:20s} czas={r['elapsed_s']:>7} s  pamięć szczyt={r['peak_memory_mb']:>8} MB  żądań={r['requests']}")

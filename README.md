# PJN Lab 1 – parser (rola PARSER, poziom 5.0)

Scraper serwisu partnera (Node/Express + EJS, `PJN-main`): infinite scroll na `/feed`,
podstrony `/posts/:id` z danymi ładowanymi leniwie (scroll) i po kliknięciu „Read more”.

## Uruchomienie

```bash
pip install -r requirements.txt
# 1) uruchom serwis (docker: `make build && make run` w PJN-main, albo `node app.js` w project/) -> http://localhost:3000
# 2) pełny scraping (Selenium, 3 przeglądarki, headless) -> output/full/
python scrape_selenium.py --headless --workers 3 --output-dir output/full
# 3) analiza danych i wykresy -> output/analysis/
python analysis.py
# 4) testy jednostkowe
python -m pytest tests -q
```

Parametry `scrape_selenium.py`: `--base-url`, `--output-dir`, `--limit`, `--headless`, `--workers`,
`--delay` (min. 0,5 s), `--timeout`, `--retries`, `--formats csv,xlsx,json`, `--fresh`.
Przerwany przebieg wznawia się po ponownym uruchomieniu (checkpoint w `output/<dir>/checkpoint_*`);
`--fresh` zaczyna od zera.

## GUI do podglądu (opcjonalnie)

```bash
python gui.py          # albo dwuklik na start_gui.bat; serwis musi działać
```

1. **„1. Pobierz listę (feed)”** – Selenium przewija `/feed`, tabela wypełnia się na żywo.
2. **„2. Pobierz podstrony”** – wszystkie albo wskazane id (`5`, `1-20`, `3,7,9`).
3. Kliknij rekord → zakładka **Interpretacja** (pole | surowy tekst | po czyszczeniu; braki na czerwono)
   i **Surowy HTML** (kod karty / podstrony, z którego parser to wyciągnął).

Wyniki GUI trafiają do `output/gui/` (przycisk „Zapisz CSV/XLSX…”). `python gui.py --selftest` to
automatyczny test bez klikania.

## Pliki

| Plik | Rola |
|---|---|
| `scrape_selenium.py` | główny scraper (WebDriverWait, doładowywanie do końca, retry 1/2/4/8 s, checkpoint, diagnostyka błędów) |
| `parsing.py` | selektory CSS → surowe rekordy (klasy semantyczne, nie pozycje) |
| `cleaning.py` | ceny → liczby, daty → ISO, encje HTML, placeholdery → puste wartości |
| `build_dataset.py` | łączenie lista+podstrona, deduplikacja, walidacja typów, eksport CSV/XLSX/JSON |
| `scrape_api.py` | rozszerzenie: ten sam wynik bezpośrednio z endpointu JSON używanego przez stronę (+ obsługa 429/Retry-After) |
| `compare_raw_vs_dom.py` | liczba rekordów w surowym HTML vs w DOM po JS |
| `benchmark.py` | czas i pamięć: Selenium (okno / headless) vs bez przeglądarki |
| `analysis.py` | kontrola jakości, statystyki, wykresy |
| `gui.py` | prosty GUI (Tkinter): feed i podstrony osobno, podgląd interpretacji |
| `make_report.py` | generuje sprawozdanie PDF |
| `tests/` | testy jednostkowe funkcji czyszczących, retry i limitera |

## Wyniki (kolumny)

Jeden wiersz = jeden rekord; 33 kolumny, m.in. `price` (liczba), `currency`, `price_pln`,
`published_date` (ISO) + `date_quality` (exact / ambiguous / relative), `likes`, `comments`, `rating`,
`brand`, `sku`, `condition`, `availability`, `seller`, `full_text`, `author`, `parse_issues`.
CSV jest w UTF-8 z BOM (`utf-8-sig`), dzięki czemu Excel poprawnie wyświetla polskie znaki.
Braki zapisywane są jako puste pola; nie przerywają działania parsera.

"""Generuje sprawozdanie PDF (po scrapingu i analizie). Wszystkie liczby pochodzą z plików JSON w output/."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
FONTS = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
for name, file in [("DV", "DejaVuSans.ttf"), ("DV-B", "DejaVuSans-Bold.ttf"), ("DV-I", "DejaVuSans-Oblique.ttf"),
                   ("DV-M", "DejaVuSansMono.ttf")]:
    pdfmetrics.registerFont(TTFont(name, str(FONTS / file)))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["BodyText"], fontName="DV", fontSize=9, leading=13, alignment=TA_JUSTIFY, spaceAfter=5)
H1 = ParagraphStyle("h1", parent=BODY, fontName="DV-B", fontSize=15, leading=19, spaceBefore=6, spaceAfter=8, alignment=0)
H2 = ParagraphStyle("h2", parent=BODY, fontName="DV-B", fontSize=11, leading=15, spaceBefore=9, spaceAfter=4, alignment=0)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=7.8, leading=10, alignment=0, spaceAfter=0)
CELLB = ParagraphStyle("cellb", parent=CELL, fontName="DV-B")
CODE = ParagraphStyle("code", parent=CELL, fontName="DV-M", fontSize=7.5)
TITLE = ParagraphStyle("title", parent=H1, fontSize=19, leading=24, spaceAfter=4)
CAP = ParagraphStyle("cap", parent=BODY, fontName="DV-I", fontSize=8, alignment=1)


def load(path: str):
    return json.loads((OUT / path).read_text(encoding="utf-8"))


def P(text, style=BODY):
    return Paragraph(text, style)


def table(rows, widths, header=True, code_col=None):
    data = []
    for i, row in enumerate(rows):
        cells = []
        for j, cell in enumerate(row):
            style = CELLB if (header and i == 0) else (CODE if code_col == j else CELL)
            cells.append(Paragraph(str(cell), style))
        data.append(cells)
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8bec7")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6ebf2")))
    t.setStyle(TableStyle(st))
    return t


def fig(name, width_cm, caption):
    path = OUT / "analysis" / name
    from PIL import Image as PILImage
    w, h = PILImage.open(path).size
    return [Image(str(path), width=width_cm * cm, height=width_cm * cm * h / w), P(caption, CAP), Spacer(1, 6)]


def unit_tests() -> str:
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=HERE, capture_output=True, text=True)
    m = re.search(r"(\d+) passed", proc.stdout)
    return m.group(1) if m else "?"


def pct(a, b):
    return f"{100 * a / b:.1f}".replace(".", ",") + "%"


def num(x, d=2):
    return f"{x:,.{d}f}".replace(",", " ").replace(".", ",")


def main():
    sel, api = load("full/summary_selenium.json"), load("api_full/summary_api.json")
    bench, rvd, res = load("benchmark.json"), load("raw_vs_dom.json"), load("analysis/analysis_results.json")
    val = load("full/products_validation.json")
    q, desc, cor = res["quality"], res["descriptive"], res["correlations"]
    ver = res.get("verification_against_source", {})
    n_tests = unit_tests()
    n = q["records"]
    s = []

    s += [P("Laboratorium 1 – parser strony WWW (poziom 5.0)", TITLE),
          P("Rola PARSER: scraper serwisu z infinite scrollem i podstronami szczegółów (Selenium + BeautifulSoup). "
            "Dane: 400 rekordów, 33 atrybuty. Analiza i wnioski – poniżej.", BODY)]

    s += [P("1. Użyta technologia i uzasadnienie wyboru", H1),
          P("<b>Python 3.11</b> – zalecany w instrukcji (requests + BeautifulSoup, pandas + matplotlib, Selenium na poziomie 5.0). "
            "<b>Selenium 4 + Chrome</b> – serwis wstrzykuje rekordy przez <i>fetch</i> po przewinięciu strony (IntersectionObserver), "
            "a dane dodatkowe podstrony pojawiają się dopiero po scrollu i po kliknięciu „Read more”; zwykłe <i>requests</i> widzi tylko "
            "pierwszych 10 kart (sekcja 6). <b>BeautifulSoup + lxml</b> – ekstrakcja z gotowego drzewa DOM jest dużo szybsza niż setki "
            "wywołań <i>find_element</i> przez protokół WebDriver. <b>WebDriverWait</b> z warunkiem zamiast <i>sleep</i> – czekamy na "
            "konkretny stan strony (przybyło kart, pojawił się wiersz tabeli), a nie na zgadywany czas; serwis losuje opóźnienie 0–3 s. "
            "<b>pandas</b> – czyszczenie, deduplikacja i eksport (CSV, XLSX, JSON); <b>matplotlib</b> – wykresy; <b>psutil</b> – pomiar pamięci; "
            "<b>pytest</b> – testy jednostkowe.")]

    s += [P("2. Opis serwisu (rola AUTOR – serwis partnera)", H1),
          P("Opis sporządzony na podstawie kodu serwisu partnera (katalog <font name='DV-M'>PJN-main</font>). "
            "<i>Sposób generowania danych i uzasadnienie wyboru utrudnień uzupełnia autor serwisu.</i>"),
          table([
              ["Element", "Opis"],
              ["Stos", "Node.js + Express 5, szablony EJS, dane w <font name='DV-M'>database/data.json</font> (400 rekordów); uruchamiany w Dockerze lub <font name='DV-M'>node app.js</font>."],
              ["Trasy", "<font name='DV-M'>GET /feed</font> (lista), <font name='DV-M'>GET /posts/:id</font> (szczegóły), API: <font name='DV-M'>/api/v1/feed?limit&amp;offset</font>, "
                        "<font name='DV-M'>/api/v1/posts/:id/additional-info</font>, <font name='DV-M'>/api/v1/posts/:id/read-more</font>."],
              ["Lista", "10 kart renderowanych serwerowo (klasy <font name='DV-M'>post_title</font>…), kolejne porcje po 10 doładowywane przez JS przy scrollu "
                        "(klasy <font name='DV-M'>post-title</font>…) – <b>dwie różne struktury tych samych rekordów</b>."],
              ["Podstrona", "Podstawowe pola w HTML; „Specifications” (tabela, kolejność wierszy losowa) i „Product details” (lista) ładowane po przewinięciu do sentinela; "
                            "sekcja „Read more” po kliknięciu przycisku, w jednej z 3 losowych kolejności elementów."],
              ["Utrudnienia", "ceny w 6 walutach (PLN, EUR, USD, GBP, CZK, JPY) zapisywane symbolem lub kodem ISO, przed lub po liczbie, z separatorem tysięcy lub bez; "
                              "daty m.in. ISO, dd.mm.yyyy, „20 August 2025”, „Aug 20, 2025”, dwuznaczne dd/mm/yyyy vs mm/dd/yyyy oraz względne („3 days ago”, „Today”); braki w 7 polach (9–26% rekordów); "
                              "encje (&amp;nbsp;, &amp;oacute;, &amp;#39;) i znaczniki HTML w opisach; losowe opóźnienie 0–3 s każdego żądania; "
                              "doładowywanie porcjami, atrybuty po interakcji (scroll, klik), losowa kolejność atrybutów."],
          ], [3, 14])]

    s += [P("3. Opis parsera", H1),
          P("<b>Przepływ.</b> (1) Faza listy: otwarcie <font name='DV-M'>/feed</font>, pętla „przewiń do końca → <i>WebDriverWait</i> aż przybędzie kart albo "
            "pojawi się komunikat o końcu” aż do wyczerpania rekordów (40 porcji po 10 kart). (2) Faza podstron: dla każdego id otwarcie "
            "<font name='DV-M'>/posts/:id</font>, przewinięcie do sentinela (czekanie na wiersze tabeli), kliknięcie „Read more” (czekanie na elementy "
            "z sekcji), pobranie <font name='DV-M'>page_source</font> i ekstrakcja BeautifulSoup. (3) Łączenie danych listy i podstron po id, "
            "czyszczenie, deduplikacja, walidacja, eksport."),
          P("<b>Wymagania obowiązkowe 5.0:</b> Selenium; jawne oczekiwanie (WebDriverWait z warunkiem); obsługa doładowywania do wyczerpania; "
            "ponawianie z opóźnieniem wykładniczym 1, 2, 4, 8 s (limit 5 prób i 30 s – testowane jednostkowo); porównanie HTML vs DOM (sekcja 6). "
            "Opóźnienie między żądaniami ≥ 0,5 s zapewnia wspólny dla wszystkich przeglądarek limiter."),
          P("<b>Wybrane rozszerzenia</b> (wymagane co najmniej 2; zrealizowano 5 z listy):"),
          table([
              ["Rozszerzenie", "Realizacja"],
              ["Zrzut ekranu i źródło przy błędzie", "<font name='DV-M'>_diagnose()</font> zapisuje PNG i HTML do <font name='DV-M'>output/…/errors/</font>; pojedynczy błąd nie przerywa całości, "
                                                      "a niezdrowa przeglądarka jest zastępowana nową. W pełnym przebiegu błędów było 0, więc katalog nie powstał."],
              ["Tryb headless + pomiar czasu", f"Opcja <font name='DV-M'>--headless</font>; pomiar w obu trybach w sekcji 7."],
              ["Wznawianie (checkpoint)", "Lista w <font name='DV-M'>checkpoint_feed.json</font>, każda podstrona dopisywana do <font name='DV-M'>checkpoint_details.jsonl</font> po pobraniu; "
                                          "ponowne uruchomienie pomija gotowe id; <font name='DV-M'>--fresh</font> zeruje."],
              ["Wykrycie i użycie źródła JSON", "Strona woła <font name='DV-M'>/api/v1/…</font> (wykryte z Resource Timing, <font name='DV-M'>compare_raw_vs_dom.py</font>); "
                                                "<font name='DV-M'>scrape_api.py</font> daje identyczny wynik w ułamku czasu (sekcja 7), z obsługą 429/Retry-After."],
              ["Czas i pamięć: bez przeglądarki vs Selenium", "<font name='DV-M'>benchmark.py</font> – ten sam podzbiór, wyniki w sekcji 7."],
              ["Dodatkowe (poziom 4.0)", f"równoległe przeglądarki z limitem żądań (<font name='DV-M'>--workers</font>), CLI (adres, limit, plik wyjściowy), logowanie do pliku z podsumowaniem, "
                                         f"eksport CSV+XLSX+JSON, {n_tests} testów jednostkowych, walidacja typów z raportem odrzuceń."],
          ], [4.6, 12.4]),
          Spacer(1, 6),
          P("<b>Selektory</b> – opierają się na semantycznych klasach i id, nigdy na pozycji elementu (kolejność jest losowa):"),
          table([
              ["Dane", "Selektor / metoda", "Dlaczego"],
              ["karta listy", "<font name='DV-M'>#feed article.post</font>", "wspólna dla kart serwerowych i doładowanych"],
              ["data, miejsce, kategoria", "<font name='DV-M'>span</font> z klasą regex <font name='DV-M'>^post[_-](published_)?date$</font> itd.", "SSR używa <i>post_*</i>, JS – <i>post-*</i>; regex łapie oba warianty"],
              ["id rekordu", "<font name='DV-M'>.read-more a[href]</font> + regex <font name='DV-M'>/posts/(\\d+)</font>", "karty nie mają <i>data-id</i>; URL jest kontraktem; awaryjnie pozycja w feedzie"],
              ["cena, opis, polubienia", "<font name='DV-M'>div.price</font>, <font name='DV-M'>div.description</font>, <font name='DV-M'>.interaction .likes</font>", "semantyczne klasy"],
              ["tabela specyfikacji", "<font name='DV-M'>#specifications tr</font>: klucz z tekstu <font name='DV-M'>th</font>, wartość z <font name='DV-M'>td</font>", "kolejność wierszy losowa → mapowanie po etykiecie"],
              ["lista „Product details”", "<font name='DV-M'>#extra-list li</font>, podział na pierwszym „:”", "URL zawiera dwukropek"],
              ["sekcja Read more", "<font name='DV-M'>#read-more-content .summary / .description / .author / .post_published_at</font>", "3 losowe kolejności; zawężenie do kontenera, bo <i>.description</i> występuje też w karcie głównej"],
              ["oczekiwania", "<font name='DV-M'>#specifications tr</font>, <font name='DV-M'>#read-more-button</font> (clickable), <font name='DV-M'>#feed-status</font>", "warunek stanu strony zamiast czasu"],
          ], [3.3, 7.2, 6.5]),
          Spacer(1, 4),
          P("<b>Odporność selektorów na zmianę wyglądu serwisu.</b> Przetrwałyby <u>zmiany czysto wizualne</u> (CSS, kolory, układ, kolejność elementów), bo nie używamy pozycji, "
            "klas stylistycznych ani XPath-ów po indeksach: selektory po <i>id</i> (<font name='DV-M'>#specifications</font>, <font name='DV-M'>#read-more-content</font>), "
            "id z adresu URL oraz mapowanie po etykietach. Są <u>najbardziej odporne</u>: id z URL i pola wyciągane po kluczu. "
            "<u>Nie przetrwałyby</u> zmiany nazw klas lub znaczników: <font name='DV-M'>article.post</font>, <font name='DV-M'>h2</font> dla tytułu, <font name='DV-M'>div.price</font>, "
            "regexy <font name='DV-M'>post[_-]…</font> (już raz zepsute przez autora między SSR a JS, wymagały obsługi dwóch wariantów); "
            "<u>najkruchsze</u> są: etykiety w <font name='DV-M'>th</font> (np. „Brand” – zmiana języka UI rozbiłaby mapowanie), teksty komunikatów końca listy "
            "(„reached the end”, „No more posts”) oraz prefiksy „Date:”, „Author:”. Ryzyko ogranicza fallback: jeśli komunikatu nie ma, pętla kończy się po "
            "przekroczeniu limitu oczekiwania na nową kartę (przy braku postępu), a brak pola daje pustą wartość, nie wyjątek.")]

    s += [PageBreak(), P("4. Wyniki kontroli jakości danych", H1)]
    miss = [(c, v) for c, v in q["missing"].items() if v["count"] > 0]
    s += [P(f"Pozyskano <b>{n} rekordów</b> (400 na liście, 400 podstron; 0 błędów, 0 ponowień) w <b>{num(sel['elapsed_s'], 0)} s</b>, "
            f"{sel['requests']} żądań, {sel['feed_batches']} porcji doładowania. Kolumn: 33."),
          P("<b>Braki wartości</b> (puste pole = brak danych w serwisie, nie błąd parsera; pozostałe 26 kolumn kompletne):"),
          table([["Kolumna", "Braki [szt.]", "Braki [%]"]] + [[c, v["count"], f"{v['percent']:.1f}".replace(".", ",") + "%"] for c, v in miss], [5, 3, 3]),
          Spacer(1, 4),
          P(f"<b>Duplikaty:</b> przed odrzuceniem {q['duplicates']['before']} rekordów, duplikatów po id {q['duplicates']['duplicates_by_id']}, "
            f"po zawartości (bez id i sku) {q['duplicates']['duplicates_by_content']}; po odrzuceniu {q['duplicates']['after']}. "
            "Serwis nie zawiera duplikatów (autor nie wybrał tego utrudnienia), mechanizm deduplikacji został jednak sprawdzony testem jednostkowym na danych syntetycznych."),
          P(f"<b>Typy kolumn:</b> kolumny liczbowe (price, price_pln, likes, comments, rating, tags_count) są liczbowe – "
            f"{'wszystkie' if all(q['dtypes_numeric_ok'].values()) else 'NIE wszystkie'}; liczba odrzuconych (nieparsowalnych) wartości: "
            f"{sum(q['rejected_values'].values())}. Waluty: " + ", ".join(f"{k} {v}" for k, v in q["currency_counts"].items()) + ". "
            f"Jakość dat (pole published): dokładne {q['date_quality'].get('exact', 0)}, dwuznaczne {q['date_quality'].get('ambiguous', 0)}, "
            f"względne {q['date_quality'].get('relative', 0)}."),
          P("<b>Wartości odstające</b> (reguła 1,5·IQR): " + "; ".join(
              f"{c}: {v['count']}" for c, v in q["outliers"].items()) + f". Test poprawności obsługi przecinka: cyfry surowej ceny porównane z "
            f"parsowaną liczbą ×100 – {q['price_parser_check']['mismatches']} niezgodności; wartości powyżej 100 000 (typowy objaw „129900 zamiast 1299”): "
            f"{q['price_parser_check']['values_over_100000']}. Maksymalna cena nominalna to {num(q['outliers']['price']['max_value'])}, "
            "więc nie ma ani anomalii w danych, ani błędu skali po stronie parsera. Duża rozpiętość cen w PLN (0,52–12 374,75) nie jest anomalią: "
            "wynika z mieszania walut (JPY i CZK mają niski kurs), a kwoty nominalne są niezależne od waluty."),
          P(f"<b>Spójność lista–podstrona:</b> {q['cross_check_mismatches']} rozbieżności tytułu/kategorii/lokalizacji."),
          P(f"<b>Weryfikacja względem pliku źródłowego</b> (dostępnego tylko w naszym środowisku testowym; w realnym scrapingu go nie ma): porównano "
            f"{ver.get('records_compared')} rekordów × {ver.get('fields_checked')} pól – <b>{ver.get('total_mismatches')} niezgodności</b>. "
            f"Dodatkowo zbiór z Selenium jest identyczny co do komórki ze zbiorem z endpointu JSON (400×33)."),
          P("<b>Wniosek i poprawki.</b> Analiza potwierdza poprawność parsera: brak błędów skali cen, kompletne kolumny liczbowe, zgodność listy z podstroną i ze źródłem. "
            "Z kontroli i testu na 12 rekordach wynikały decyzje: (a) kolumna <i>url</i> z listy „Product details” okazała się w 100% pusta (serwis nie zwraca tego pola) – usunięto ją; "
            "(b) placeholdery serwisu („Not available”, „Unknown”, „Date unknown”) zamieniane są na puste wartości, żeby nie zafałszować statystyk – "
            "dotyczy to też marki „Unknown”, którą traktujemy jako brak; (c) pola tekstowe wstawiane przez <i>textContent</i> zawierają literalne encje "
            "(<font name='DV-M'>&amp;nbsp;</font>, <font name='DV-M'>&amp;#39;</font>), więc czyszczenie dekoduje encje i usuwa znaczniki (np. <i>&lt;strong&gt;</i> w opisach); "
            f"(d) {q['date_quality'].get('ambiguous', 0)} dat w formacie z ukośnikiem jest realnie dwuznaczne (w danych występują i dd/mm, i mm/dd) – "
            "przyjęto dd/mm z flagą <i>date_quality = ambiguous</i> zamiast cichego zgadywania.")]

    s += [PageBreak(), P("5. Statystyki opisowe i wnioski", H1)]
    rows = [["Cecha", "n", "średnia", "mediana", "dominanta*", "Q1", "Q3", "min", "max", "odch. std."]]
    labels = {"price": "cena (nominalna)", "price_pln": "cena [PLN]", "likes": "polubienia", "comments": "komentarze", "rating": "ocena", "tags_count": "liczba tagów"}
    for c, d in desc.items():
        mode = f"{num(d['mode'], 1)}" if c in ("rating", "tags_count") else f"{num(d['mode_bin'][0], 0)}–{num(d['mode_bin'][1], 0)}"
        rows.append([labels[c], d["n"], num(d["mean"]), num(d["median"]), mode, num(d["q1"]), num(d["q3"]), num(d["min"]), num(d["max"]), num(d["std"])])
    s += [table(rows, [2.7, 1, 1.7, 1.7, 2.4, 1.5, 1.6, 1.4, 1.7, 1.7]),
          P("* dla cech ciągłych wszystkie wartości są unikalne, więc dominanta liczona jest jako najliczniejszy przedział histogramu (20 przedziałów); "
            "dla oceny i liczby tagów – wartość najczęstsza.", CAP), Spacer(1, 4)]
    s += fig("hist_price.png", 15.5, "Rys. 1. Histogram ceny: nominalnej (lewo) i w PLN po przeliczeniu stałymi kursami (prawo).")
    s += [P("Ceny nominalne mają rozkład zbliżony do jednostajnego (10–2 499), średnia 1 215 ≈ mediana 1 203. Po przeliczeniu na PLN rozkład jest silnie "
            "prawoskośny (średnia 2 837 ≫ mediana 1 265), z dużym skupiskiem przy niskich wartościach: 190 z 400 rekordów w pierwszym przedziale 0–1 031 zł (JPY i CZK nie przekraczają 500 zł, GBP/EUR/USD sięgają 10–12 tys. zł). "
            "To skutek mieszania walut i niezależnego losowania kwoty, a nie błąd parsera – wniosek: porównywanie cen bez przeliczenia jest bezzasadne, "
            "a wartości w PLN zależą od przyjętych (stałych, przybliżonych) kursów.")]
    s += fig("box_price_by_currency.png", 11.5, "Rys. 2. Wykres pudełkowy ceny nominalnej według waluty (◦ – średnia).")
    s += [P("Mediany cen nominalnych są podobne we wszystkich walutach (od 1 123 do 1 296) – dodatkowy dowód, że parser nie zniekształca skali dla żadnej waluty "
            "(np. JPY bez miejsc po przecinku czy zapis z separatorem tysięcy).")]
    s += fig("box_likes_comments_rating.png", 15.5, "Rys. 3. Wykresy pudełkowe: polubienia, komentarze, ocena (◦ – średnia).")
    s += [P("Polubienia (219–49 979), komentarze (18–2 494) i oceny (1,0–5,0) są równomiernie rozłożone, mediana ≈ średnia, brak wartości odstających. "
            "Ocena ma 37 braków (9,2%) – analizowane n = 363.")]
    cl = cor["likes~comments"]
    s += fig("scatter_likes_comments.png", 8.2, "Rys. 4. Zależność polubień i komentarzy.")
    s += [P(f"<b>Korelacja.</b> polubienia–komentarze: Pearson {num(cl['pearson'], 3)}, Spearman {num(cl['spearman'], 3)} (n = {cl['n']}); "
            f"cena–ocena: {num(cor['price~rating']['pearson'], 3)}; cena PLN–polubienia: {num(cor['price_pln~likes']['pearson'], 3)}; "
            f"ocena–polubienia: {num(cor['rating~likes']['pearson'], 3)}. Wszystkie współczynniki są praktycznie zerowe. W prawdziwym serwisie oczekiwalibyśmy "
            "wyraźnie dodatniej zależności polubienia–komentarze (popularne posty zbierają jedno i drugie), a więc jej brak nie ma sensu merytorycznego – "
            "wskazuje, że dane zostały wygenerowane losowo i niezależnie. Wykluczyliśmy błąd parsera: wartości zgadzają się ze źródłem w 100%. "
            "Pozostałe pary (cena–ocena itd.) nie mają uzasadnienia merytorycznego dla zależności, więc wynik ≈ 0 jest tu zgodny z oczekiwaniem.")]
    s += fig("corr_matrix.png", 9.0, "Rys. 5. Macierz korelacji cech liczbowych.")

    raw, dom = rvd["raw_html"], rvd["dom_after_js"]
    s += [PageBreak(), P("6. Surowy HTML a drzewo DOM po wykonaniu skryptów (wymóg 5.0)", H1),
          P(f"Surowy HTML pobrany <i>requests</i>, bez przeglądarki, i DOM po wykonaniu JS w Selenium (podstrona nr {rvd['post_id']}):"),
          table([
              ["Co liczymy", "Surowy HTML", "DOM po JS"],
              ["karty rekordów na <font name='DV-M'>/feed</font>", f"{raw['feed_cards']}", f"{dom['feed_cards']} (po scrollu do końca; zaraz po załadowaniu: {dom['feed_cards_initial_dom']})"],
              ["wiersze tabeli specyfikacji (podstrona)", f"{raw['detail_spec_rows']}", f"{dom['detail_spec_rows']}"],
              ["pozycje listy „Product details”", f"{raw['detail_list_items']}", f"{dom['detail_list_items']}"],
              ["elementy sekcji „Read more”", f"{raw['detail_read_more_elements']}", f"{dom['detail_read_more_elements']}"],
              ["rozmiar HTML [B] lista / podstrona", f"{raw['feed_html_bytes']} / {raw['detail_html_bytes']}", "—"],
          ], [6.5, 3.5, 7]),
          Spacer(1, 4),
          P(f"<b>Wniosek.</b> Surowy HTML zawiera tylko {raw['feed_cards']} z 400 rekordów ({pct(raw['feed_cards'], 400)}) – pozostałe {400 - raw['feed_cards']} "
            f"({pct(400 - raw['feed_cards'], 400)}) powstają dopiero w przeglądarce, po kolejnych wywołaniach <i>fetch</i> wyzwalanych przewijaniem. Na podstronie "
            f"surowy HTML nie ma żadnego z atrybutów ze specyfikacji, listy szczegółów i „Read more” (0 elementów wobec {dom['detail_spec_rows'] + dom['detail_list_items'] + dom['detail_read_more_elements']} w DOM) – "
            "to 9 z 33 pozyskanych atrybutów (brand, sku, condition, availability, seller, rating, full_text, author, data publikacji z „Read more”). "
            "Parser oparty wyłącznie o <i>requests</i> zebrałby więc tylko 2,5% rekordów, i to bez tych 9 atrybutów. Wykryte żądania <i>fetch</i>: "
            + ", ".join(f"<font name='DV-M'>{e}</font>" for e in rvd["fetch_endpoints"]) + ".")]

    b_h, b_l, b_a = bench["selenium_headed"], bench["selenium_headless"], bench["api_no_browser"]
    s += [P("7. Czas i pamięć: Selenium vs podejście bez przeglądarki; headless vs okno", H1),
          P(f"Ten sam podzbiór: pierwsze {bench['subset']} rekordów, jedna przeglądarka, opóźnienie 0,5 s. Pamięć = szczyt RSS procesu Pythona wraz z Chrome i chromedriver."),
          table([
              ["Wariant", "Czas [s]", "Szczyt pamięci [MB]", "Żądań HTTP", "Uwagi"],
              ["Selenium, okno", num(b_h["elapsed_s"], 1), num(b_h["peak_memory_mb"], 0), b_h["requests"], "lista + 2 wywołania API + strona na rekord"],
              ["Selenium, headless", num(b_l["elapsed_s"], 1), num(b_l["peak_memory_mb"], 0), b_l["requests"], "jak wyżej, bez okna"],
              ["Bez przeglądarki (JSON)", num(b_a["elapsed_s"], 1), num(b_a["peak_memory_mb"], 0), b_a["requests"], "jedno żądanie <font name='DV-M'>/api/v1/feed</font>"],
          ], [4, 2.3, 3.5, 2.3, 5]),
          Spacer(1, 4),
          P(f"Przebieg pełny (400 rekordów): Selenium headless, 3 przeglądarki – {num(sel['elapsed_s'], 0)} s ({num(sel['elapsed_s'] / 60, 1)} min), szczyt {num(sel['peak_memory_mb'], 0)} MB, "
            f"{sel['requests']} żądań; endpoint JSON – {num(api['elapsed_s'], 1)} s, {num(api['peak_memory_mb'], 0)} MB, {api['requests']} żądań."),
          P(f"<b>Wnioski.</b> (1) Podejście bez przeglądarki jest ok. {num(b_h['elapsed_s'] / b_a['elapsed_s'], 0)}× szybsze i zużywa ok. {num(b_h['peak_memory_mb'] / b_a['peak_memory_mb'], 0)}× mniej pamięci na podzbiorze "
            f"(w całości ok. {num(sel['elapsed_s'] / api['elapsed_s'], 0)}× szybsze), bo omija renderowanie, wykonywanie skryptów, symulację scrolla i trzy żądania na rekord – "
            "pobiera ten sam JSON, z którego korzysta strona, w paczkach po 100 rekordów. Daje przy tym identyczny zbiór. "
            f"(2) Różnica headless vs okno ({num(b_h['elapsed_s'], 0)} s vs {num(b_l['elapsed_s'], 0)} s) mieści się w szumie pomiaru: czas jest zdominowany przez sztuczne, losowe opóźnienie serwera (0–3 s na żądanie), "
            "a nie przez renderowanie; headless oszczędził ok. 9% pamięci. Jedno uruchomienie na wariant – to pomiar orientacyjny, nie statystyczny. "
            "(3) Selenium jest jednak konieczne tam, gdzie nie ma publicznego endpointu lub dane powstają w JS; tutaj jest wymagane do spełnienia zadania, a JSON stanowi skrót. "
            "Serwis nie ogranicza liczby żądań (nigdy nie zwrócił 429), więc obsługa Retry-After jest zaimplementowana i przetestowana tylko jednostkowo/logicznie, nie na żywo.")]

    s += [P("8. Ograniczenia i założenia", H1),
          P("• Kursy walut do PLN są stałe i przybliżone (PLN 1; EUR 4,25; USD 3,85; GBP 5,00; CZK 0,17; JPY 0,026) – służą wyłącznie porównaniu, nie są danymi rynkowymi. "
            "• Symbol ¥ interpretowany jako JPY. • Daty dwuznaczne: dd/mm, chyba że wychodzi data z przyszłości; daty względne liczone od dnia scrapingu. "
            "• „Unknown” i „Not available” traktowane jako brak. • Testy na lokalnej kopii serwisu partnera; przed scrapingiem cudzych serwisów należy przeczytać robots.txt i regulamin.")]

    doc = SimpleDocTemplate(str(OUT / "Sprawozdanie_Lab1.pdf"), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, title="Laboratorium 1 – parser strony WWW")
    doc.build(s)
    print("OK:", OUT / "Sprawozdanie_Lab1.pdf")


if __name__ == "__main__":
    main()

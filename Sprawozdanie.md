# Przetwarznie jezyka naturalnego Laboratorium 1 – parser strony WWW 

## 1. użytą technologię i uzasadnienie wyboru
* **Python 3.11** – wykorzystany do generowania danych, oraz całości parsera w tym GUI. zalecane w instrukcji :)
* **Selenium 4 + Chrome** – serwis wstrzykuje rekordy przez fetch po przewinięciu strony, a dane dodatkowe podstrony pojawiają się dopiero po scrollu i po kliknięciu
„Read more”. feed pokazuje tylko pierwszych 10 kart przed rozwinięciem i tak samo postrzega to requests 
* **BeautifulSoup + lxml** ekstrakcja z gotowego drzewa DOM jest dużo szybsza niż setki wywołań find_element przez protokół
WebDriver. WebDriverWait z warunkiem zamiast sleep – czekamy na konkretny stan strony (przybyło
kart, pojawił się wiersz tabeli), a nie na zgadywany czas; serwis losuje opóźnienie 0–3 s
* **pandas** czyszczenie, deduplikacja i eksport (CSV, XLSX, JSON)
* **matplotlib** – wykresy
* **psutil** – pomiar pamięci
* **pytest** – testy jednostkowe

## 2. opis zbudowanego serwisu (rola AUTOR) — struktura, sposób generowania, wybrane utrudnienia i 
powód wyboru; 

## 3. opis parsera (rola PARSER) — wybrane rozszerzenia oraz zastosowane selektory wraz z uzasadnieniem,

### 3.1 Przepływ.  

**1. Faza listy:**
→ Otwarcie /feed, pętla „przewiń do końca 

→ WebDriverWait aż przybędzie kart albo pojawi się komunikat o końcu wyczerpania rekordów

**2. Faza podstron:**

→Dla każdego id otwarcie /posts/:id, przewinięcie do sentinela 

→czekanie na wiersze tabeli

→kliknięcie „Read more”

→czekanie na elementy z sekcji

→pobranie page_source i ekstrakcja
BeautifulSoup.

**3. Łączenie danych listy i podstron:**
→czyszczenie

→deduplikacja

→walidacja

→eksport

→generowanie wykresów

## 3.2 Wybrane Rozszerzenia

### Pareser Rozszrzenia 4.0
* walidacja typów wszystkich kolumn i raport z liczbą odrzuconych wartości

oczyszczona baza na której bazuje parser jest tworzona w build_dataset.py

https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/build_dataset.py#L136-L151
  
* logowanie przebiegu do pliku wraz z podsumowaniem: liczba stron, rekordów, błędów, czas działania

pliki logujące są zapisywane w summary_selenium.json oraz scrape_selenium.log

<img width="1128" height="232" alt="image" src="https://github.com/user-attachments/assets/2c2cfbd0-f6ea-4650-bb12-5bc559cf9f2f" />
<img width="372" height="535" alt="image" src="https://github.com/user-attachments/assets/e35c437d-edda-42ee-9a0a-28be4a50e627" />

https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L302-L316

  
* minimum 3 testy jednostkowe funkcji czyszczących dane
  
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/tests/test_cleaning.py#L41-L57
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/tests/test_cleaning.py#L60-L64
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/tests/test_cleaning.py#L72-L77
  
* pobieranie równoległe z ograniczeniem liczby jednoczesnych żądań
  
  parser tworzy ilość okien równą zmiennej workers, po czym wykonują scrapping równolegle aż osiągnął limit rekordów
  
https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L258-L265
https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L276-L287
  
* parametryzacja z linii poleceń
  
  parser przyjmuje następujące argumenty:
  * base url -adres strony do parsowania
  * output dir - katalog wyjśiowy
  * limit - maksymalna liczba rekordów
  * headless - toggle pracy bez włączania okna przeglądarki
  * workers - ilość przeglądarek
  * delay- opóźnienie wysyłąnia żądań
  * retries -maksymalna ilość prób przed porzuceniem wątku
  * formats - format exportu danych 
  * fresh - flaga zaczęcia od 0  i ignorowanie już zgromadzonych danych
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L340-L356

### Pareser Rozszrzenia 5.0
* automatyczny zrzut ekranu i zapis źródła strony przy każdym błędzie, do celów diagnostycznych
  
diagnose() zapisuje PNG i HTML do output/…/errors/, pojedynczy błąd nie
przerywa całości, a przeglądarka na której błąd wystąpił jest zastępowana nową
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L80-L89

* tryb headless wraz z pomiarem czasu działania w obu trybach + porównanie czasu działania i zużycia pamięci: podejście bez przeglądarki kontra Selenium, na tym samym podzbiorze danych

  Opcja --headless
  https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L42-L54
  <img width="911" height="132" alt="image" src="https://github.com/user-attachments/assets/896e3d46-832c-4052-b72c-f02bdd71f979" />

  **Wnioski:**
    * Podejście bez przeglądarki jest ok. 58× szybsze i zużywa ok. 9× mniej pamięci na
podzbiorze , bo omija renderowanie, wykonywanie skryptów, symulację
scrolla i trzy żądania na rekord – pobiera ten sam JSON, z którego korzysta strona, w paczkach po 100 rekordów. 
    * Różnica headless vs okno  mieści się w szumie pomiaru: czas jest zdominowany przez sztuczne, losowe opóźnienie serwera (0–3 s na żądanie),
a nie przez renderowanie; headless oszczędził ok. 9% pamięci. Jedno uruchomienie na wariant – to
pomiar orientacyjny, nie statystyczny
    * Selenium jest jednak konieczne tam, gdzie nie ma publicznego endpointu lub dane powstają w JS. Tutaj jest wymagane do spełnienia zadania, a JSON
stanowi skrót
  
  
* wznawianie przerwanej sesji od ostatniego zapisanego punktu (checkpoint);

Lista w checkpoint_feed.json, każda podstrona dopisywana do
checkpoint_details.jsonl po pobraniu; ponowne uruchomienie pomija gotowe id;--fresh zeruje

https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/scrape_selenium.py#L235-L255

* własne : gui

<img width="1917" height="1138" alt="image" src="https://github.com/user-attachments/assets/49f12308-82a7-4cb3-bd0a-5cd9cd2aba63" />
 
https://github.com/nikfik/parser/blob/ab688e44ea22822aa2d00542bbbacd1ff964a72f/gui.py#L1-L488

## 3.3 Selektory
  | Dane | Selektor / metoda | Dlaczego |
|------|-------------------|----------|
| karta listy | #feed article.post | wspólna dla kart serwerowych i downloadowych |
| data, miesiąc, kategoria | span z klasy regex ^post_[_](published_)?date itd. | SSR używa post_*; JS - post-*; regex łapie oba warianty |
| id rekordu | .read-more a[href] + regex /posts/(\\d+) | karty nie mają data-id; URL jest kontrakttem; awaryjnie pożyczenie w feedzie |
| cena, opis, polubienia | div.price, div.description, .interaction .likes | semantyczna klasa |
| tabela specyfikacji | #specifications tr: klucz z tekstu th, wartość td | kolejność wersji losowo → mapowanie po etykietce |
| lista „Product details” | #extra-list li, podzielnia na pierwszym „.” | URL zawiera dwojakropek |
| sekcja Read more | #read-more-content .summary / .description / .author / .post.published_at | 3 losowe kolejnosci; zabezpieczenie do kontenera, bo .description występuje tez w karcie głównej |
| oczekiwania | #specifications tr, #read-more-button (clickable), #feed-status | warunki stanu strony zamiesz czasu |

## 4. ocenę odporności własnych selektorów — które z nich przetrwałyby zmianę wyglądu serwisu, a które nie i dlaczego; 
Przetrwałyby zmiany czysto wizualne, bo nie bazujemy na pozycji, klas stylistycznych ani XPath-ów po indeksach: selektory po id (#specifications, #read-more-content), id z adresu URL oraz mapowanie po etykietach.

Najbardziej odporne są: id z URL i pola wyciągane po kluczu

Nie przetrwałyby zmiany nazw klas lub znaczników: article.post, h2 dla tytułu, div.price, regexy post; 

najkruchsze są: etykiety w th np.„Brand” – zmiana języka UI rozbiłaby mapowanie
, teksty komunikatów końca listy np. „reached the end”,„No more posts” oraz prefiksy „Date:”, „Author:”. Ryzyko ogranicza fallback: jeśli komunikatu nie ma, pętla kończy się po przekroczeniu limitu oczekiwania na nową kartę (przy braku postępu), a brak pola daje pustą wartość, nie wyjątek.
## 5. wyniki kontroli jakości danych; 

**Reguła:** Braki wartości/puste pole = brak danych w serwisie, nie błąd parsera

Pozyskano 400 rekordów (400 na liście, 400 podstron; 0 błędów, 0 ponowień) w 864 s, 1241 żądań, 40 porcji doładowania. Kolumn: 33.

| Kolumna | Braki [szt.] | Braki [%] |
|---------|--------------|-----------|
| brand   | 95           | 23,8%     |
| location| 51           | 12,8%     |
| rating  | 37           | 9,2%      |
| availability| 70          | 17,5%     |
| condition| 102          | 25,5%     |
| seller  | 87           | 21,8%     |
| author  | 76           | 19,0%     |

**Duplikaty:**
mechanizm deduplikacji jest jedynie sprawdzany testem jednostkowym na danych syntetycznych
przed odrzuceniem 400 rekordów, po odrzuceniu 400 rekordów czyli serwis nie zawiera żadnych  

**Typy kolumn:** 
* kolumny liczbowe: price, price_pln, likes, comments, rating, tags_count 
* liczba odrzuconych (nieparsowalnych) wartości: 0.
* Waluty: CZK 76, EUR 73, JPY 68, USD 65, GBP 60, PLN 58
* Jakość dat: dokładne 348, dwuznaczne 52
  
**Wartości odstające** 
* reguła rozstępu ćwiartkowego (1,5·IQR): price: 0; price_pln: 0; likes: 0; comments: 0; rating: 0. 
* Test poprawności obsługi przecinka: cyfry surowej ceny porównane z parsowaną liczbą ×100 – 0
niezgodności
* wartości powyżej 100 000: 0, naksymalna cena
nominalna to 2 499,48, więc nie ma ani anomalii w danych, ani błędu skali po stronie parsera. Duża rozpiętość cen w PLN (0,52–12 374,75) nie jest anomalią: wynika z mieszania walut (JPY i CZK mają niskikurs), a kwoty nominalne są niezależne od waluty

**Wnioski**
 Analiza potwierdza poprawność parsera (chyba że czegoś nie rozumiem): brak błędów skali cen, kompletne, kolumny liczbowe, zgodność listy z podstroną i ze źródłem.
 
Z kontroli i testu na  rekordach wynikały decyzje:
* kolumna url z listy „Product details” okazała się w 100% pusta bo serwis nie zwraca tego
pola – usunięto ją
* placeholdery serwisu „Not available”, „Unknown”, „Date unknown” zamieniane
są na puste wartości, żeby nie zafałszować statystyk – dotyczy to też marki „Unknown”, którą
traktujemy jako brak
* pola tekstowe wstawiane przez textContent zawierają literalne encje (&nbsp;,
&#39;), więc czyszczenie dekoduje encje i usuwa znaczniki (np. <strong> w opisach)
* 52 dat w formacie z ukośnikiem jest realnie dwuznaczne (w danych występują i dd/mm, i mm/dd) przyjęto dd/mm z flagą date_quality = ambiguous zamiast cichego zgadywania

## 6. omówienie statystyk i wnioski; 
<img width="915" height="292" alt="image" src="https://github.com/user-attachments/assets/c00abb3f-accb-40e0-b2bf-5f6f5b2c3a64" />

<img width="858" height="311" alt="image" src="https://github.com/user-attachments/assets/509a2689-4c5f-4758-b3e2-1987e8cf2147" />
Ceny nominalne mają rozkład zbliżony do jednostajnego (10–2 499), średnia 1 215 ≈ mediana 1 203. Po przeliczeniu na PLN rozkład jest silnie prawoskośny (średnia 2 837 ≫ mediana 1 265), z dużym skupiskiem przy niskich wartościach: 190 z 400 rekordów w pierwszym przedziale 0–1 031 zł, JPY i CZK nie przekraczają 500 zł, GBP/EUR/USD sięgają 10–12 tys. zł. To skutek mieszania walut i niezależnego losowania kwoty, a nie błąd parsera – wniosek: porównywanie cen bez przeliczenia jest bezzasadne, a
wartości w PLN zależą od przyjętych stałych oraz przybliżonych kursów

<img width="602" height="297" alt="image" src="https://github.com/user-attachments/assets/227d5803-e7f3-4d56-8c74-c032ce99cf62" />
Mediany cen nominalnych są podobne we wszystkich walutach (od 1 123 do 1 296) co jest oczekiwane biorąc pod uwagę sposób generowania danych na stronie

<img width="842" height="288" alt="image" src="https://github.com/user-attachments/assets/249fe137-b957-411d-a205-b826c9145014" />
Polubienia (219–49 979), komentarze (18–2 494) i oceny (1,0–5,0) są równomiernie rozłożone, mediana ≈ średnia, brak wartości odstających. 

Ocena ma 37 braków (9,2%) – analizowane n = 363.

<img width="445" height="325" alt="image" src="https://github.com/user-attachments/assets/fe87bc2d-3a64-4e15-bc14-faf7614614cb" />
<img width="462" height="408" alt="image" src="https://github.com/user-attachments/assets/3c731665-b99d-4e1b-a12c-cac1137cf44b" />
Wszystkie współczynniki Korelacji są praktycznie zerowe.
W prawdziwym serwisie oczekiwalibyśmy wyraźnie dodatniej zależności polubienia–komentarze
, więc pomimo jej sensu merytorycznego fakt, że
dane zostały wygenerowane losowo i niezależnie zgadza się ze
źródłem w 100%.
Pozostałe pary mogły by mieć uzasadnienie merytoryczne, ale były by one mocno zależne od algorytmów, a np pary jak (tag–cena itd.) nie mają uzasadnienia merytorycznego dla
zależności, więc wynik ≈ 0 jest tu zgodny z oczekiwaniem.

## 7. porównanie surowego HTML z drzewem DOM.
Surowy HTML pobrany requests, bez przeglądarki, i DOM po wykonaniu JS w Selenium
<img width="893" height="187" alt="image" src="https://github.com/user-attachments/assets/c76c1d52-7b44-4352-8485-5e76e61a4edf" />
**Wniosek:** Surowy HTML zawiera tylko 10 z 400 rekordów (2,5%) – pozostałe 390 (97,5%) powstają dopiero w przeglądarce, po kolejnych wywołaniach fetch wyzwalanych przewijaniem. Na podstronie surowy HTML nie ma żadnego z atrybutów ze specyfikacji, listy szczegółów i „Read more” (0 elementów wobec 12 w DOM) - to 9 z 33 pozyskanych atrybutów. Parser oparty wyłącznie o requests zebrałby więc tylko
2,5% rekordów, i to bez tych 9 atrybutów. Wykryte żądania fetch: /api/v1/feed,
/api/v1/posts/7/additional-info, /api/v1/posts/7/read-more

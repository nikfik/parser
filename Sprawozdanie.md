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
* eksport do dwóch formatów jednocześnie (np. CSV oraz XLSX lub JSON)
* logowanie przebiegu do pliku wraz z podsumowaniem: liczba stron, rekordów, błędów, czas działania
* minimum 3 testy jednostkowe funkcji czyszczących dane 
* pobieranie równoległe z ograniczeniem liczby jednoczesnych żądań 
* parametryzacja z linii poleceń 

### Pareser Rozszrzenia 4.0
* obsługa kodu 429 z poszanowaniem nagłówka Retry-After  
* automatyczny zrzut ekranu i zapis źródła strony przy każdym błędzie, do celów diagnostycznych 
* wznawianie przerwanej sesji od ostatniego zapisanego punktu (checkpoint);
* porównanie czasu działania i zużycia pamięci: podejście bez przeglądarki kontra Selenium, na tym 
samym podzbiorze danych
* wykrycie i wykorzystanie źródła danych, z którego korzysta strona (plik JSON), wraz z omówieniem, 
dlaczego jest to szybsze;
* własne : gui

## 4. ocenę odporności własnych selektorów — które z nich przetrwałyby zmianę wyglądu serwisu, a które 
nie i dlaczego; 
## 5. wyniki kontroli jakości danych; 
## 6. omówienie statystyk i wnioski; 
## 7. porównanie surowego HTML z drzewem DOM.

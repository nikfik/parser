"""Ekstrakcja danych z HTML (po wykonaniu JS przez przeglądarkę).

Selektory opierają się na semantycznych klasach/id, a NIE na pozycji elementów -
serwis losowo zmienia kolejność atrybutów, a pierwsze 10 kart z /feed jest
renderowane serwerowo z innymi nazwami klas (post_title) niż karty doładowane
przez JS (post-title).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

_DATE_CLS = re.compile(r"^post[_-](published[_-])?date$")
_LOC_CLS = re.compile(r"^post[_-]location$")
_CAT_CLS = re.compile(r"^post[_-]category$")
_RM_CLS = re.compile(r"^post[_-]read[_-]more$")


def _text(el) -> str | None:
    return el.get_text() if el is not None else None


def _strip_label(text: str | None, label: str) -> str | None:
    if text is None:
        return None
    return re.sub(rf"^\s*{label}\s*:\s*", "", text.strip(), flags=re.I)


def parse_feed_cards(html: str, keep_html: bool = False) -> list[dict]:
    """Karty z listy /feed -> surowe rekordy (teksty tak, jak widzi je użytkownik)."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for index, art in enumerate(soup.select("article.post"), start=1):
        link = art.select_one(".read-more a[href]")
        href = link["href"] if link else None
        m = re.search(r"/posts/(\d+)", href or "")
        rows.append({
            "id": int(m.group(1)) if m else None,
            "feed_position": index,
            "title": _text(art.find("h2")),
            "published_raw": _text(art.find("span", class_=_DATE_CLS)),
            "location": _text(art.find("span", class_=_LOC_CLS)),
            "category": _text(art.find("span", class_=_CAT_CLS)),
            "price_raw": _text(art.select_one("div.price")),
            "description": _text(art.select_one("div.description")),
            "rm_summary": _text(art.find("p", class_=_RM_CLS)),
            "source_url": href,
            "likes": _text(art.select_one(".interaction .likes")),
            "comments": _text(art.select_one(".interaction .comments")),
        })
        if keep_html:  # do podglądu w GUI: surowy HTML karty
            rows[-1]["_html"] = art.prettify()
    # pozycja w feedzie = id (feed jest posortowany rosnąco) - ratunek, gdy brak linku
    for row in rows:
        if row["id"] is None:
            row["id"] = row["feed_position"]
            row["id_inferred"] = True
    return rows


def parse_detail_page(html: str, keep_html: bool = False) -> dict:
    """Podstrona /posts/:id po załadowaniu dodatkowych danych i kliknięciu "Read more"."""
    soup = BeautifulSoup(html, "lxml")
    top = soup.select_one("article.card-top") or soup

    detail = {
        "d_title": _text(top.find("h1")),
        "d_published_raw": _strip_label(_text(top.select_one(".post_publishing_date")), "Date"),
        "d_location": _strip_label(_text(top.select_one(".post_location")), "Location"),
        "d_category": _strip_label(_text(top.select_one(".post_category")), "Category"),
        "d_price_raw": _text(top.select_one(".price")),
        "d_description": _text(top.select_one("p.description")),
        "d_likes": _text(top.select_one(".stats .like")),
        "d_comments": _text(top.select_one(".stats .comment")),
        "tags": [t.get_text(strip=True) for t in soup.select("#tags .tag")],
    }
    img = soup.select_one("img#post-image")
    detail["image_url"] = img.get("src") if img else None

    # tabela "Specifications": klucz z nagłówka <th>, nie z pozycji wiersza (kolejność losowa)
    spec = {}
    for tr in soup.select("#specifications tr"):
        th, td = tr.find("th"), tr.find("td")
        if th and td:
            spec[th.get_text(strip=True).lower()] = td.get_text()
    for key in ("brand", "sku", "condition", "availability", "seller"):
        detail[key] = spec.get(key)

    # lista "Product details": "Rating: 4.6", "Tags: a, b", "URL: https://..."
    extra = {}
    for li in soup.select("#extra-list li"):
        key, _, value = li.get_text().partition(":")
        extra[key.strip().lower()] = value.strip()
    detail["rating_raw"] = extra.get("rating")
    detail["url"] = extra.get("url")
    detail["extra_tags"] = extra.get("tags")

    # sekcja "Read more" (kolejność elementów losowa -> po klasach)
    rm = soup.select_one("#read-more-content")
    if rm is not None:
        detail["rm_summary_detail"] = _text(rm.select_one(".summary"))
        detail["rm_full_text"] = _text(rm.select_one(".description"))
        detail["author"] = _strip_label(_text(rm.select_one(".author")), "Author")
        detail["rm_published_raw"] = _strip_label(_text(rm.select_one(".post_published_at")), "Published")
    if keep_html:  # do podglądu w GUI: HTML treści strony po wykonaniu JS
        main = soup.select_one("main")
        detail["_html"] = main.prettify() if main else None
    return detail

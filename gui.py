"""Prosty GUI (Tkinter) do uruchamiania parsera krok po kroku i podglądu tego, co parser widzi.

  1. "Pobierz listę (feed)"  - Selenium przewija /feed; tabela wypełnia się na żywo
  2. "Pobierz podstrony"      - wchodzi w /posts/:id (wszystkie albo wskazane id, np. 5, 1-20, 3,7,9)
  Kliknij rekord w tabeli -> zakładka "Interpretacja" pokazuje: pole | surowy tekst ze strony | wynik czyszczenia,
  a zakładka "Surowy HTML" - kod karty / podstrony, z którego parser to wyciągnął.

Uruchomienie:  python gui.py        (serwis kolegi musi działać, domyślnie http://localhost:3000)
Test automatyczny (bez klikania):  python gui.py --selftest
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
from argparse import Namespace
from pathlib import Path
from tkinter import messagebox, ttk
import tkinter as tk

import build_dataset
from build_dataset import clean_record, merge_records
from scrape_selenium import Scraper

OUT_DIR = Path(__file__).resolve().parent / "output" / "gui"
MONO = ("Consolas", 9)


class QueueLogHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        self.q.put(("log", self.format(record)))


def parse_ids(text: str) -> list[int] | None:
    """"5" / "1-20" / "3,7,9" / "1-5,9" -> lista id; pusty tekst -> None (czyli wszystkie)."""
    text = text.strip()
    if not text:
        return None
    ids: list[int] = []
    for part in text.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            ids.extend(range(int(a), int(b) + 1))
        elif part:
            ids.append(int(part))
    return ids


def short(value, n=110) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        value = "; ".join(map(str, value))
    return " ".join(str(value).split())[:n]


def interpret(raw: dict, base_url: str) -> list[tuple[str, str, str, str]]:
    """Rekord surowy -> wiersze (sekcja, pole, surowe, po czyszczeniu). Pusty wynik = brak danych."""
    c = clean_record(raw, base_url)
    has_detail = raw.get("has_detail")
    price = "" if c["price"] is None else f"{c['price']:g} {c['currency'] or '?'}  (≈ {c['price_pln']} PLN)"
    date = lambda iso, q: "" if iso is None else f"{iso}  [{q}]"  # noqa: E731
    rows = [
        ("lista", "id", raw.get("source_url"), c["id"]),
        ("lista", "title", raw.get("title"), c["title"]),
        ("lista", "category", raw.get("category"), c["category"]),
        ("lista", "price", raw.get("price_raw"), price),
        ("lista", "published", raw.get("published_raw"), date(c["published_date"], c["date_quality"])),
        ("lista", "location", raw.get("location"), c["location"]),
        ("lista", "description", raw.get("description"), c["description"]),
        ("lista", "likes", raw.get("likes"), c["likes"]),
        ("lista", "comments", raw.get("comments"), c["comments"]),
        ("lista", "summary", raw.get("rm_summary"), c["summary"]),
    ]
    if has_detail:
        rows += [
            ("podstrona", "brand", raw.get("brand"), c["brand"]),
            ("podstrona", "sku", raw.get("sku"), c["sku"]),
            ("podstrona", "condition", raw.get("condition"), c["condition"]),
            ("podstrona", "availability", raw.get("availability"), c["availability"]),
            ("podstrona", "seller", raw.get("seller"), c["seller"]),
            ("podstrona", "rating", raw.get("rating_raw"), c["rating"]),
            ("podstrona", "tags", raw.get("tags"), c["tags"]),
            ("podstrona", "full_text", raw.get("rm_full_text"), c["full_text"]),
            ("podstrona", "author", raw.get("author"), c["author"]),
            ("podstrona", "rm_published", raw.get("rm_published_raw"), date(c["rm_published_date"], c["rm_published_quality"])),
            ("podstrona", "image_url", raw.get("image_url"), c["image_url"]),
        ]
    else:
        rows.append(("podstrona", "—", "", "(podstrona jeszcze nie pobrana – przycisk 2)"))
    return [(sec, f, short(r), short(v) if v not in (None, "") else "") for sec, f, r, v in rows]


class App:
    def __init__(self, root: tk.Tk, selftest: bool = False):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.rows: dict[int, dict] = {}        # id -> wiersz z listy
        self.details: dict[int, dict] = {}     # id -> dane z podstrony
        self.scraper: Scraper | None = None
        self.busy = False
        self.closing = False
        self.total_ids = 0
        self.done_ids = 0
        self.selftest = selftest
        root.title("PJN Lab 1 – parser: podgląd")
        root.geometry("1180x720")
        root.minsize(900, 560)
        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.poll)

    # ---------- UI ----------
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        self.url = tk.StringVar(value="http://localhost:3000")
        self.limit = tk.StringVar(value="0")
        self.headless = tk.BooleanVar(value=self.selftest)
        self.workers = tk.StringVar(value="1")
        self.delay = tk.StringVar(value="0.5")
        self.ids = tk.StringVar(value="")
        for label, var, w in [("Adres serwisu", self.url, 24), ("Limit rekordów (0 = wszystkie)", self.limit, 5),
                              ("Przeglądarek", self.workers, 3), ("Opóźnienie [s]", self.delay, 5)]:
            ttk.Label(top, text=label).pack(side="left", padx=(0, 3))
            ttk.Entry(top, textvariable=var, width=w).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(top, text="Bez okna (headless)", variable=self.headless).pack(side="left")

        bar = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        bar.pack(fill="x")
        self.btn_feed = ttk.Button(bar, text="1. Pobierz listę (feed)", command=self.start_feed)
        self.btn_feed.pack(side="left")
        ttk.Label(bar, text="   id podstron (puste = wszystkie, np. 5 / 1-20 / 3,7,9):").pack(side="left")
        ttk.Entry(bar, textvariable=self.ids, width=14).pack(side="left", padx=4)
        self.btn_det = ttk.Button(bar, text="2. Pobierz podstrony", command=self.start_details)
        self.btn_det.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        self.btn_save = ttk.Button(bar, text="Zapisz CSV/XLSX…", command=self.save)
        self.btn_save.pack(side="left")
        self.btn_clear = ttk.Button(bar, text="Wyczyść", command=self.clear)
        self.btn_clear.pack(side="left", padx=10)

        st = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        st.pack(fill="x")
        self.status = tk.StringVar(value="Gotowy. Uruchom serwis kolegi, potem kliknij „1. Pobierz listę”.")
        ttk.Label(st, textvariable=self.status).pack(side="left")
        self.progress = ttk.Progressbar(st, length=260, mode="determinate")
        self.progress.pack(side="right")

        vert = ttk.PanedWindow(self.root, orient="vertical")
        vert.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        horiz = ttk.PanedWindow(vert, orient="horizontal")
        vert.add(horiz, weight=4)

        left = ttk.Frame(horiz)
        horiz.add(left, weight=5)
        cols = ("id", "title", "price", "date", "location", "likes", "stan")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        for c, w, t in [("id", 35, "id"), ("title", 105, "tytuł"), ("price", 150, "cena (surowa → liczba)"),
                        ("date", 150, "data (surowa → ISO)"), ("location", 85, "miejsce"), ("likes", 50, "likes"), ("stan", 85, "stan")]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("detail", background="#e6f4ea")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected())

        right = ttk.Notebook(horiz)
        horiz.add(right, weight=4)
        f1 = ttk.Frame(right)
        right.add(f1, text="Interpretacja")
        self.interp = ttk.Treeview(f1, columns=("sec", "field", "raw", "clean"), show="headings")
        for c, w, t in [("sec", 65, "źródło"), ("field", 80, "pole"), ("raw", 210, "surowy tekst ze strony"), ("clean", 210, "po czyszczeniu")]:
            self.interp.heading(c, text=t)
            self.interp.column(c, width=w, anchor="w")
        self.interp.tag_configure("missing", foreground="#a33")
        self.interp.pack(fill="both", expand=True)
        f2 = ttk.Frame(right)
        right.add(f2, text="Surowy HTML")
        self.html = tk.Text(f2, font=MONO, wrap="none", state="disabled")
        self.html.pack(fill="both", expand=True)

        logf = ttk.Frame(vert)
        vert.add(logf, weight=1)
        self.log_text = tk.Text(logf, height=7, font=MONO, state="disabled", background="#f7f7f7")
        lsb = ttk.Scrollbar(logf, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=lsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")

    # ---------- pomocnicze ----------
    def log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_busy(self, busy: bool):
        self.busy = busy
        for b in (self.btn_feed, self.btn_det, self.btn_save, self.btn_clear):
            b.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def make_scraper(self) -> Scraper | None:
        try:
            args = Namespace(base_url=self.url.get().strip(), output_dir=str(OUT_DIR), limit=int(self.limit.get() or 0),
                             headless=self.headless.get(), workers=max(1, int(self.workers.get() or 1)),
                             delay=max(0.5, float(self.delay.get().replace(",", "."))), timeout=20, retries=5,
                             formats="csv,xlsx", fresh=True, keep_html=True)
        except ValueError:
            messagebox.showerror("Błędne ustawienia", "Limit i liczba przeglądarek muszą być liczbami całkowitymi, opóźnienie liczbą.")
            return None
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("scraper")
        logger.setLevel("INFO")
        logger.handlers.clear()
        handler = QueueLogHandler(self.q)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)
        fh = logging.FileHandler(OUT_DIR / "gui.log", "a", encoding="utf-8")
        fh.setFormatter(handler.formatter)
        logger.addHandler(fh)
        sc = Scraper(args, logger)
        sc.hooks = {"feed_rows": lambda rows: self.q.put(("feed_rows", rows)),
                    "detail": lambda pid, d: self.q.put(("detail", pid, d))}
        return sc

    def run_in_thread(self, target):
        def wrapper():
            try:
                target()
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                try:
                    self.scraper.close_browsers()
                except Exception:  # noqa: BLE001
                    pass
                self.q.put(("idle",))

        self.set_busy(True)
        threading.Thread(target=wrapper, daemon=True).start()

    # ---------- akcje ----------
    def start_feed(self):
        sc = self.make_scraper()
        if sc is None:
            return
        self.scraper = sc
        self.status.set("Lista: otwieram przeglądarkę i przewijam /feed…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def work():
            sc.open_browsers()
            rows, info = sc.run_feed()
            self.q.put(("feed_done", rows, info))

        self.run_in_thread(work)

    def start_details(self):
        if not self.rows:
            messagebox.showinfo("Brak listy", "Najpierw pobierz listę (przycisk 1) – podstrony są wybierane z listy.")
            return
        try:
            wanted = parse_ids(self.ids.get())
        except ValueError:
            messagebox.showerror("Błędne id", "Użyj formatu: 5, 1-20 albo 3,7,9.")
            return
        ids = [i for i in (wanted if wanted is not None else sorted(self.rows)) if i in self.rows and i not in self.details]
        if not ids:
            messagebox.showinfo("Nic do zrobienia", "Wszystkie wskazane podstrony są już pobrane (albo id nie ma na liście).")
            return
        sc = self.make_scraper()
        if sc is None:
            return
        self.scraper = sc
        self.total_ids, self.done_ids = len(ids), 0
        self.progress.configure(mode="determinate", maximum=len(ids), value=0)
        self.status.set(f"Podstrony: 0/{len(ids)}")

        def work():
            sc.open_browsers()
            sc.run_details(ids, {})

        self.run_in_thread(work)

    def stop(self):
        if self.scraper:
            self.scraper.stop_event.set()
            self.status.set("Zatrzymywanie… (kończę bieżące żądania)")

    def clear(self):
        self.rows.clear()
        self.details.clear()
        self.tree.delete(*self.tree.get_children())
        self.interp.delete(*self.interp.get_children())
        self.set_html("")
        self.progress.configure(value=0)
        self.status.set("Wyczyszczono.")

    def save(self):
        if not self.rows:
            messagebox.showinfo("Brak danych", "Nie ma jeszcze żadnych rekordów do zapisania.")
            return
        raw = merge_records([self.rows[i] for i in sorted(self.rows)], self.details)
        for r in raw:
            r.pop("_html", None)
        df, rep = build_dataset.build(raw, self.url.get().strip(), OUT_DIR, "products_gui", ("csv", "xlsx"))
        self.log(f"Zapisano {len(df)} rekordów ({len(self.details)} z podstronami) do {OUT_DIR}")
        messagebox.showinfo("Zapisano", f"{len(df)} rekordów → {OUT_DIR}\\products_gui.csv / .xlsx")
        if not self.selftest and hasattr(os, "startfile"):
            os.startfile(OUT_DIR)  # noqa: S606

    # ---------- wyświetlanie ----------
    def tree_values(self, rid: int):
        from cleaning import parse_date, parse_int, parse_price
        row = self.rows[rid]
        raw = merge_records([row], {rid: self.details[rid]} if rid in self.details else {})[0]
        price, cur = parse_price(raw.get("price_raw"))
        iso, q = parse_date(raw.get("published_raw"))
        return (rid, short(row.get("title"), 30), f"{short(row.get('price_raw'), 18)} → {'' if price is None else f'{price:g} {cur}'}",
                f"{short(row.get('published_raw'), 18)} → {iso or '—'}{'?' if q == 'ambiguous' else ''}",
                short(row.get("location"), 22) or "—", parse_int(row.get("likes")) or "", "lista+podstrona" if rid in self.details else "lista")

    def upsert_row(self, rid: int):
        values = self.tree_values(rid)
        tags = ("detail",) if rid in self.details else ()
        if self.tree.exists(str(rid)):
            self.tree.item(str(rid), values=values, tags=tags)
        else:
            self.tree.insert("", "end", iid=str(rid), values=values, tags=tags)

    def selected_id(self) -> int | None:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def set_html(self, text: str):
        self.html.configure(state="normal")
        self.html.delete("1.0", "end")
        self.html.insert("1.0", text[:30000])
        self.html.configure(state="disabled")

    def show_selected(self):
        rid = self.selected_id()
        if rid is None or rid not in self.rows:
            return
        row, det = self.rows[rid], self.details.get(rid)
        raw = merge_records([row], {rid: det} if det else {})[0]
        self.interp.delete(*self.interp.get_children())
        for sec, field, r, c in interpret(raw, self.url.get().strip()):
            self.interp.insert("", "end", values=(sec, field, r, c or "— brak —"), tags=("missing",) if not c else ())
        parts = []
        if row.get("_html"):
            parts.append("<!-- ===== KARTA Z LISTY /feed ===== -->\n" + row["_html"])
        if det and det.get("_html"):
            parts.append("<!-- ===== PODSTRONA /posts/%d (po JS i kliknięciu Read more) ===== -->\n%s" % (rid, det["_html"]))
        self.set_html("\n\n".join(parts) or "(HTML dostępny po zakończeniu pobierania listy / podstrony)")

    # ---------- pętla zdarzeń ----------
    def poll(self):
        refresh_selected = False
        try:
            while True:
                ev = self.q.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log(ev[1])
                elif kind in ("feed_rows", "feed_done"):
                    rows = ev[1]
                    for r in rows:
                        old = self.rows.get(r["id"])
                        if old is None or ("_html" in r and "_html" not in old):
                            self.rows[r["id"]] = r
                        self.upsert_row(r["id"])
                    self.status.set(f"Lista: {len(self.rows)} rekordów" + (" – gotowe" if kind == "feed_done" else " (przewijam dalej…)"))
                    refresh_selected = True
                    if kind == "feed_done":
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=0)
                elif kind == "detail":
                    self.details[ev[1]] = ev[2]
                    self.done_ids += 1
                    self.progress.configure(value=self.done_ids)
                    self.status.set(f"Podstrony: {self.done_ids}/{self.total_ids}  (ostatnia: id {ev[1]})")
                    if ev[1] in self.rows:
                        self.upsert_row(ev[1])
                    refresh_selected = refresh_selected or self.selected_id() == ev[1]
                elif kind == "error":
                    self.log("BŁĄD: " + ev[1])
                    self.status.set("Błąd – szczegóły w logu poniżej")
                elif kind == "idle":
                    self.progress.stop()
                    self.set_busy(False)
                    if "Zatrzymywanie" in self.status.get():
                        self.status.set(f"Zatrzymano. Rekordów: {len(self.rows)}, podstron: {len(self.details)}.")
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        if refresh_selected:
            self.show_selected()
        if self.selftest:
            try:
                self.selftest_step()
            except Exception:  # noqa: BLE001 - błąd testu ma zakończyć proces, a nie zawiesić pętlę Tk
                import traceback
                traceback.print_exc()
                print("SELFTEST FAILED")
                self.root.destroy()
                sys.exit(1)
        self.root.after(100, self.poll)

    def on_close(self):
        if self.busy:
            self.closing = True
            self.stop()
            self.status.set("Zamykam przeglądarki…")
        else:
            self.root.destroy()

    # ---------- test automatyczny ----------
    _st = "start"
    shot: str | None = None

    def selftest_step(self):
        st = self._st
        if st == "start":
            self.limit.set("12")
            self._st = "feed"
            self.start_feed()
        elif st == "feed" and not self.busy:
            assert len(self.rows) == 12, f"oczekiwano 12 rekordów, jest {len(self.rows)}"
            assert len(self.tree.get_children()) == 12
            self.ids.set("2-4")
            self._st = "details"
            self.start_details()
        elif st == "details" and not self.busy:
            assert sorted(self.details) == [2, 3, 4], sorted(self.details)
            self.tree.selection_set("3")
            self.show_selected()
            rows = [self.interp.item(i, "values") for i in self.interp.get_children()]
            fields = {r[1]: r for r in rows}
            assert "brand" in fields and "price" in fields, fields.keys()
            html = self.html.get("1.0", "end")
            assert "KARTA Z LISTY" in html and "PODSTRONA" in html
            print("SELFTEST OK")
            for r in rows[:12]:
                print("  ", r)
            self._st = "done"
            if self.shot:
                from PIL import ImageGrab
                self.root.update()
                x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height())).save(self.shot)
            self.root.destroy()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--screenshot", help="(z --selftest) zapisz zrzut okna do pliku PNG")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:  # ostre czcionki i poprawne współrzędne przy skalowaniu Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    root = tk.Tk()
    app = App(root, selftest=args.selftest)
    app.shot = args.screenshot
    root.mainloop()


if __name__ == "__main__":
    main()

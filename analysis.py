"""Analiza danych: kontrola jakości, statystyki opisowe i wykresy.

Wejście:  output/full/products.csv (+ products_validation.json, summary_selenium.json)
Wyjście:  output/analysis/analysis_results.json oraz output/analysis/*.png
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cleaning import clean_text  # noqa: E402

NUMERIC = ["price", "price_pln", "likes", "comments", "rating", "tags_count"]


def quality_control(df: pd.DataFrame, validation: dict) -> dict:
    n = len(df)
    missing = {}
    for c in df.columns:
        if c in ("parse_issues", "has_detail"):  # kolumny-flagi, nie atrybuty produktu
            continue
        k = int(df[c].isna().sum())
        missing[c] = {"count": k, "percent": round(100 * k / n, 1)}

    # wartości odstające regułą 1.5*IQR
    outliers = {}
    for c in ["price", "price_pln", "likes", "comments", "rating"]:
        s = df[c].dropna().astype(float)
        q1, q3 = s.quantile(.25), s.quantile(.75)
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        out = s[(s < lo) | (s > hi)]
        outliers[c] = {"count": int(len(out)), "lower": round(lo, 2), "upper": round(hi, 2),
                       "min_value": float(s.min()), "max_value": float(s.max())}

    # test poprawności parsera: cyfry z surowej ceny muszą dać tę samą liczbę po przesunięciu przecinka
    mism = 0
    for raw, val in zip(df["price_raw"], df["price"]):
        if pd.isna(raw) or pd.isna(val):
            continue
        digits = int(re.sub(r"\D", "", raw))
        if digits != round(val * 100):
            mism += 1
    # ceny w skali x100 (klasyczny błąd przecinka) wystąpiłyby jako wartości > 100 000
    suspicious_scale = int((df["price"] > 100_000).sum())

    return {
        "records": n,
        "missing": missing,
        "dtypes_numeric_ok": validation["numeric_columns_ok"],
        "duplicates": validation["deduplication"],
        "outliers": outliers,
        "price_parser_check": {"mismatches": mism, "values_over_100000": suspicious_scale},
        "date_quality": df["date_quality"].value_counts().to_dict(),
        "rm_date_quality": df["rm_published_quality"].value_counts().to_dict(),
        "currency_counts": df["currency"].value_counts().to_dict(),
        "rejected_values": validation["rejected_values"],
        "cross_check_mismatches": validation.get("cross_check_mismatches"),
        "records_without_detail": int((~df["has_detail"].astype(bool)).sum()),
    }


def descriptive(df: pd.DataFrame) -> dict:
    out = {}
    for c in NUMERIC:
        s = df[c].dropna().astype(float)
        mode = s.mode()
        counts, edges = np.histogram(s, bins=20)  # dominanta ma sens dla ciągłych tylko po binowaniu
        k = int(counts.argmax())
        out[c] = {
            "n": int(len(s)), "mean": round(s.mean(), 2), "median": round(s.median(), 2),
            "mode": round(float(mode.iloc[0]), 2) if len(mode) else None,
            "mode_bin": [round(float(edges[k]), 1), round(float(edges[k + 1]), 1)],
            "std": round(s.std(), 2), "min": round(s.min(), 2), "q1": round(s.quantile(.25), 2),
            "q3": round(s.quantile(.75), 2), "max": round(s.max(), 2),
        }
    return out


def correlations(df: pd.DataFrame) -> dict:
    pairs = [("likes", "comments"), ("price", "rating"), ("price_pln", "likes"), ("rating", "likes"), ("tags_count", "likes")]
    res = {}
    for a, b in pairs:
        sub = df[[a, b]].dropna().astype(float)
        res[f"{a}~{b}"] = {"n": len(sub), "pearson": round(sub[a].corr(sub[b]), 3),
                           "spearman": round(sub[a].corr(sub[b], method="spearman"), 3)}
    return res


def make_plots(df: pd.DataFrame, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    files = []

    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    axes[0].hist(df["price"].dropna(), bins=25, color="#3b6ea5", edgecolor="white")
    axes[0].set(title="Cena w walucie oryginalnej (mieszane waluty)", xlabel="cena [jednostki waluty]", ylabel="liczba rekordów")
    axes[1].hist(df["price_pln"].dropna(), bins=25, color="#c0623b", edgecolor="white")
    axes[1].set(title="Cena przeliczona na PLN (kursy stałe)", xlabel="cena [PLN]", ylabel="liczba rekordów")
    fig.tight_layout()
    fig.savefig(out / "hist_price.png", dpi=150)
    plt.close(fig)
    files.append("hist_price.png")

    fig, ax = plt.subplots(figsize=(7.5, 4))
    order = df.groupby("currency")["price"].median().sort_values().index
    ax.boxplot([df.loc[df["currency"] == c, "price"].dropna() for c in order], tick_labels=list(order), showmeans=True)
    ax.set(title="Cena nominalna według waluty", xlabel="waluta", ylabel="cena nominalna")
    fig.tight_layout()
    fig.savefig(out / "box_price_by_currency.png", dpi=150)
    plt.close(fig)
    files.append("box_price_by_currency.png")

    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8))
    for ax, col, title in zip(axes, ["likes", "comments", "rating"], ["Polubienia", "Komentarze", "Ocena (rating)"]):
        ax.boxplot(df[col].dropna().astype(float), showmeans=True)
        ax.set(title=title, xticks=[])
    fig.tight_layout()
    fig.savefig(out / "box_likes_comments_rating.png", dpi=150)
    plt.close(fig)
    files.append("box_likes_comments_rating.png")

    fig, ax = plt.subplots(figsize=(5.8, 4.4))
    sub = df[["likes", "comments"]].dropna().astype(float)
    ax.scatter(sub["likes"], sub["comments"], s=14, alpha=.6, color="#3b6ea5")
    ax.set(title="Polubienia a komentarze", xlabel="polubienia", ylabel="komentarze")
    fig.tight_layout()
    fig.savefig(out / "scatter_likes_comments.png", dpi=150)
    plt.close(fig)
    files.append("scatter_likes_comments.png")

    fig, ax = plt.subplots(figsize=(5.5, 4.6))
    corr = df[NUMERIC].astype(float).corr()
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(NUMERIC)), NUMERIC, rotation=45, ha="right")
    ax.set_yticks(range(len(NUMERIC)), NUMERIC)
    for i in range(len(NUMERIC)):
        for j in range(len(NUMERIC)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, shrink=.8)
    ax.set_title("Macierz korelacji (Pearson)")
    fig.tight_layout()
    fig.savefig(out / "corr_matrix.png", dpi=150)
    plt.close(fig)
    files.append("corr_matrix.png")
    return files


def verify_against_source(df: pd.DataFrame, truth_path: Path) -> dict:
    """Test dodatkowy (tylko w środowisku testowym, gdzie mamy plik źródłowy serwisu)."""
    truth = {r["id"]: r for r in json.loads(truth_path.read_text(encoding="utf-8"))}
    mism: dict[str, int] = {}

    def check(field, got, expected):
        got = None if (got is None or (isinstance(got, float) and np.isnan(got)) or got is pd.NA) else got
        if isinstance(expected, (int, float)) and got is not None:
            ok = abs(float(got) - float(expected)) < 1e-6
        else:
            ok = got == expected
        if not ok:
            mism[field] = mism.get(field, 0) + 1

    for _, r in df.iterrows():
        t = truth.get(int(r["id"]))
        if t is None:
            mism["id_not_in_source"] = mism.get("id_not_in_source", 0) + 1
            continue
        ai, rm = t["additional_info"], t["read_more"]
        check("title", r["title"], t["title"])
        check("category", r["category"], t["category"])
        check("location", r["location"], clean_text(t["location"]))
        check("price_raw", r["price_raw"], t["price"])
        check("description", r["description"], clean_text(t["description"]))
        check("likes", r["likes"], t["interaction"]["likes"])
        check("comments", r["comments"], t["interaction"]["comments_count"])
        check("brand", r["brand"], clean_text(ai["brand"]))
        check("sku", r["sku"], ai["sku"])
        check("condition", r["condition"], ai["condition"])
        check("availability", r["availability"], ai["availability"])
        check("seller", r["seller"], ai["seller"])
        check("rating", r["rating"], ai["rating"])
        check("author", r["author"], clean_text(rm["author"]))
        check("full_text", r["full_text"], clean_text(rm["full_text"]))
        check("summary", r["summary"], clean_text(rm["summary"]))
        check("tags", r["tags"], "; ".join(t["tags"]))
    return {"records_compared": len(df), "fields_checked": 17, "mismatches_by_field": mism,
            "total_mismatches": int(sum(mism.values()))}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", default="output/full")
    p.add_argument("--output-dir", default="output/analysis")
    p.add_argument("--truth", default="../PJN-main/project/database/data.json")
    a = p.parse_args()
    inp, out = Path(a.input_dir), Path(a.output_dir)
    df = pd.read_csv(inp / "products.csv", encoding="utf-8-sig")
    validation = json.loads((inp / "products_validation.json").read_text(encoding="utf-8"))
    results = {
        "quality": quality_control(df, validation),
        "descriptive": descriptive(df),
        "correlations": correlations(df),
        "figures": make_plots(df, out),
    }
    if Path(a.truth).exists():
        results["verification_against_source"] = verify_against_source(df, Path(a.truth))
    (out / "analysis_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if k != "figures"}, ensure_ascii=False, indent=1, default=str)[:6000])

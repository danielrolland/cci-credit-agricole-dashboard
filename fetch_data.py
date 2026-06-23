#!/usr/bin/env python3
"""Récupère les données des 13 CCI depuis Yahoo Finance et écrit un snapshot JSON.

Conçu pour tourner dans GitHub Actions, PAS dans l'app Streamlit : l'IP des
runners GitHub n'est pas rate-limitée par Yahoo comme celle de Streamlit Cloud
(cf. l'erreur YFRateLimitError observée en prod). L'app ne contacte donc plus
Yahoo du tout — elle lit seulement le JSON produit ici.

Fusion avec le snapshot précédent : un ticker qui échoue conserve sa dernière
valeur connue (et son horodatage) au lieu d'être vidé. Le JSON est donc toujours
le « meilleur état connu » par ticker, et comme il est versionné dans git
(branche `data`), il survit aux redéploiements / mises en sommeil de Streamlit.

Usage : python fetch_data.py [sortie.json] [precedent.json]
"""
import datetime as dt
import json
import sys
import time
from zoneinfo import ZoneInfo

import yfinance as yf
from curl_cffi import requests as cf_requests

PARIS = ZoneInfo("Europe/Paris")
OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "cci-data.json"
PREVIOUS = sys.argv[2] if len(sys.argv) > 2 else None

CCI = {
    "CRAP.PA":  "Alpes Provence",
    "CRAV.PA":  "Atlantique Vendée",
    "CRBP2.PA": "Brie Picardie",
    "CIV.PA":   "Ille-et-Vilaine",
    "CRLA.PA":  "Languedoc",
    "CRLO.PA":  "Loire Haute-Loire",
    "CMO.PA":   "Morbihan",
    "CNDF.PA":  "Nord de France",
    "CCN.PA":   "Normandie-Seine",
    "CAF.PA":   "Paris Île-de-France",
    "CRSU.PA":  "Sud Rhône Alpes",
    "CAT31.PA": "Toulouse 31",
    "CRTO.PA":  "Touraine Poitou",
}


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


def fetch_one(ticker: str, session) -> dict:
    """Données d'un ticker. Lève une exception en cas d'échec (le ticker
    retombera alors sur son snapshot précédent)."""
    t = yf.Ticker(ticker, session=session)
    info = t.info or {}
    if not info.get("currentPrice") and not info.get("regularMarketPrice"):
        raise RuntimeError("aucune donnée de cours")

    last_balance_date = None
    total_equity = None
    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            last_balance_date = bs.columns[0].date().isoformat()
            for row in ("Stockholders Equity", "Common Stock Equity",
                        "Total Equity Gross Minority Interest"):
                if row in bs.index:
                    total_equity = float(bs.loc[row].iloc[0])
                    break
        else:
            _log("WARN", f"{ticker}: balance_sheet vide")
    except Exception as e:
        _log("WARN", f"{ticker}: balance_sheet KO ({type(e).__name__}: {e})")

    pb = info.get("priceToBook")
    return {
        "Ticker": ticker,
        "Cours (€)": info.get("currentPrice") or info.get("regularMarketPrice"),
        "Capitaux propres / titre (€)": info.get("bookValue"),
        "Capitaux propres totaux (M€)": (
            total_equity / 1e6 if total_equity is not None else None
        ),
        "Ratio P/B": pb,
        "Décote (%)": (1 - pb) * 100 if pb is not None else None,
        "CCI cotés": info.get("sharesOutstanding"),
        "Capi. CCI (M€)": (
            info.get("marketCap") / 1e6 if info.get("marketCap") else None
        ),
        "Dernier bilan": last_balance_date,
    }


def _empty_row(ticker: str, name: str) -> dict:
    return {
        "Caisse régionale": name,
        "Ticker": ticker,
        "Cours (€)": None,
        "Capitaux propres / titre (€)": None,
        "Capitaux propres totaux (M€)": None,
        "Ratio P/B": None,
        "Décote (%)": None,
        "CCI cotés": None,
        "Capi. CCI (M€)": None,
        "Dernier bilan": None,
        "Mis à jour": None,
    }


def load_previous() -> dict[str, dict]:
    """Indexe le snapshot précédent par ticker (pour le repli)."""
    if not PREVIOUS:
        return {}
    try:
        with open(PREVIOUS, encoding="utf-8") as f:
            data = json.load(f)
        return {r["Ticker"]: r for r in data.get("rows", []) if r.get("Ticker")}
    except (OSError, ValueError) as e:
        _log("WARN", f"snapshot précédent illisible ({e}) — on repart de zéro")
        return {}


def main() -> None:
    session = cf_requests.Session(impersonate="chrome")
    previous = load_previous()
    now = dt.datetime.now(PARIS).isoformat(timespec="seconds")

    rows, stale, missing = [], [], []
    for i, (ticker, name) in enumerate(CCI.items()):
        if i:
            time.sleep(1.5)  # on reste poli avec Yahoo (≈20 s au total)
        try:
            data = fetch_one(ticker, session)
            rows.append({"Caisse régionale": name, **data, "Mis à jour": now})
            _log("INFO", f"{ticker}: OK ({data['Cours (€)']} €)")
        except Exception as e:
            _log("ERROR", f"{ticker}: {type(e).__name__}: {e}")
            prev = previous.get(ticker)
            if prev and prev.get("Cours (€)") is not None:
                row = dict(prev)
                row["Caisse régionale"] = name  # au cas où le libellé change
                rows.append(row)
                stale.append(ticker)
                _log("WARN", f"{ticker}: repli sur snapshot du {prev.get('Mis à jour')}")
            else:
                rows.append(_empty_row(ticker, name))
                missing.append(ticker)

    snapshot = {
        "generated_at": now,
        "rows": rows,
        "stale_tickers": stale,
        "missing_tickers": missing,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    _log("INFO", f"écrit {OUTPUT} — {len(rows)} lignes, "
                 f"{len(stale)} périmées, {len(missing)} sans donnée")

    # Échec dur seulement si TOUT a échoué sans aucun repli possible : on évite
    # alors d'écraser un bon snapshot par un fichier vide (le job ne committe pas).
    if len(missing) == len(CCI):
        sys.exit(1)


if __name__ == "__main__":
    main()

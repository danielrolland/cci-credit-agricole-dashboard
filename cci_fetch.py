#!/usr/bin/env python3
"""Primitives de récupération des données des 13 CCI depuis Yahoo Finance.

Module volontairement SANS dépendance Streamlit : il est importé à la fois par
le job GitHub Actions (`fetch_data.py`, qui tourne depuis l'IP non rate-limitée
des runners) et par l'app Streamlit (`app.py`, qui tente un fetch live depuis
son IP, avec repli). Une seule source de vérité pour la liste des tickers — qui
sont contre-intuitifs, cf. le tableau du CLAUDE.local.md — et pour le parsing.
"""
import sys
from zoneinfo import ZoneInfo

import yfinance as yf
from curl_cffi import requests as cf_requests

PARIS = ZoneInfo("Europe/Paris")

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


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


def make_session():
    """Session curl_cffi imitant le TLS de Chrome — limite les blocages Yahoo."""
    return cf_requests.Session(impersonate="chrome")


def fetch_one(ticker: str, session) -> dict:
    """Données d'un ticker. Lève une exception en cas d'échec (l'appelant
    décidera alors du repli sur une valeur connue)."""
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
            log("WARN", f"{ticker}: balance_sheet vide")
    except Exception as e:
        log("WARN", f"{ticker}: balance_sheet KO ({type(e).__name__}: {e})")

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


def empty_row(ticker: str, name: str) -> dict:
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

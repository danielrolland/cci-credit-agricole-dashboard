import datetime as dt
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cf_requests

PARIS = ZoneInfo("Europe/Paris")


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


@st.cache_resource(show_spinner=False)
def _yf_session():
    """Session avec empreinte TLS Chrome — contourne le throttling Yahoo
    sur les IP datacenter (notamment Streamlit Cloud)."""
    return cf_requests.Session(impersonate="chrome")


@st.cache_resource(show_spinner=False)
def _last_good() -> dict[str, dict]:
    """Dict partagé entre toutes les sessions, qui mémorise le dernier fetch
    RÉUSSI par ticker : {"data": <dict de fetch_one>, "ts": <datetime>}.
    Sert de repli quand Yahoo est injoignable — on réaffiche les dernières
    valeurs connues plutôt qu'une ligne vide. Survit aux invalidations de
    cache_data (TTL) mais pas au redémarrage / sommeil du conteneur."""
    return {}

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


def _empty_row(ticker: str) -> dict:
    return {
        "Ticker": ticker,
        "Cours (€)": None,
        "Capitaux propres / titre (€)": None,
        "Capitaux propres totaux (M€)": None,
        "Ratio P/B": None,
        "Décote (%)": None,
        "CCI cotés": None,
        "Capi. CCI (M€)": None,
        "Dernier bilan": None,
    }


@st.cache_data(ttl=900, show_spinner=False)
def fetch_one(ticker: str) -> dict:
    """Renvoie les données du ticker. Lève une exception en cas d'échec :
    Streamlit ne cache pas les exceptions, donc le ticker sera retenté
    à la prochaine visite (pas de TTL "négatif" sur les échecs)."""
    t = yf.Ticker(ticker, session=_yf_session())
    info = t.info or {}
    if not info.get("currentPrice") and not info.get("regularMarketPrice"):
        _log("WARN", f"{ticker}: info vide (probable throttle Yahoo) — keys={list(info.keys())[:5]}")
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

    result = {
        "Ticker": ticker,
        "Cours (€)": info.get("currentPrice") or info.get("regularMarketPrice"),
        "Capitaux propres / titre (€)": info.get("bookValue"),
        "Capitaux propres totaux (M€)": (
            total_equity / 1e6 if total_equity is not None else None
        ),
        "Ratio P/B": info.get("priceToBook"),
        "Décote (%)": (
            (1 - info.get("priceToBook")) * 100
            if info.get("priceToBook") is not None else None
        ),
        "CCI cotés": info.get("sharesOutstanding"),
        "Capi. CCI (M€)": (
            info.get("marketCap") / 1e6 if info.get("marketCap") else None
        ),
        "Dernier bilan": last_balance_date,
    }
    _last_good()[ticker] = {"data": result, "ts": dt.datetime.now(PARIS)}
    return result


def fetch_all() -> tuple[pd.DataFrame, dict[str, str], set[str]]:
    """Pas cachée — chaque appel rejoue la boucle, mais fetch_one ne fait
    un appel réel à Yahoo que sur cache miss (succès expirés ou échecs).

    En cas d'échec, on retombe sur le dernier fetch réussi mémorisé
    (`_last_good`) si disponible : les valeurs affichées sont alors « périmées »
    (stale) mais réelles, plutôt qu'une ligne vide. `stale` contient les tickers
    affichés ainsi ; `failures` reste la liste de tous les tickers en échec."""
    rows = []
    failures: dict[str, str] = {}
    stale: set[str] = set()
    last_good = _last_good()
    for ticker, name in CCI.items():
        try:
            data = fetch_one(ticker)
            ts = last_good.get(ticker, {}).get("ts")
        except Exception as e:
            failures[ticker] = f"{type(e).__name__}: {e}"
            cached = last_good.get(ticker)
            if cached:
                _log("WARN", f"{ticker}: fetch KO, repli sur les données du {cached['ts']}")
                data = cached["data"]
                ts = cached["ts"]
                stale.add(ticker)
            else:
                _log("ERROR", f"{ticker}: {type(e).__name__}: {e} (aucune donnée en cache)")
                data = _empty_row(ticker)
                ts = None
        rows.append({
            "Caisse régionale": name,
            **data,
            "Mis à jour": ts,
        })
    return pd.DataFrame(rows), failures, stale


st.set_page_config(
    page_title="CCI Crédit Agricole",
    page_icon="🌾",
    layout="wide",
)

st.title("CCI Crédit Agricole — cours & capitaux propres")
st.caption(
    "Suivi des 13 Certificats Coopératifs d'Investissement des Caisses Régionales du "
    "Crédit Agricole cotés à Euronext Paris. Données : Yahoo Finance."
)

with st.spinner("Récupération des données…"):
    try:
        df, failures, stale = fetch_all()
    except Exception as e:
        st.error(
            "Yahoo Finance temporairement injoignable. "
            "Réessayez dans quelques minutes."
        )
        st.caption(f"Détail technique : `{type(e).__name__}: {e}`")
        st.stop()

if failures:
    no_data = [tk for tk in failures if tk not in stale]
    if stale:
        st.warning(
            f"Yahoo Finance injoignable pour {len(stale)} CCI : dernières valeurs "
            "connues affichées (voir la colonne « Mis à jour » pour leur fraîcheur)."
        )
    if no_data:
        if len(no_data) == len(CCI):
            st.error(
                "Aucune donnée n'a pu être récupérée pour les 13 CCI, et aucune valeur "
                "n'est en cache. Yahoo Finance est probablement injoignable, réessayez plus tard."
            )
        else:
            details = ", ".join(f"{tk} ({CCI[tk]})" for tk in no_data)
            st.warning(
                f"Aucune donnée (même en cache) pour {len(no_data)} CCI : {details}. "
                "Le reste du tableau reste exploitable."
            )

df_sorted = df.sort_values("Ratio P/B", ascending=True, na_position="last").reset_index(drop=True)

median_pb = df_sorted["Ratio P/B"].median()
mean_decote = df_sorted["Décote (%)"].mean()
total_capi = df_sorted["Capi. CCI (M€)"].sum()

m1, m2, m3 = st.columns(3)
m1.metric("P/B médian", f"{median_pb:.2f}" if pd.notna(median_pb) else "—")
m2.metric("Décote moyenne", f"{mean_decote:.1f} %" if pd.notna(mean_decote) else "—")
m3.metric("Capi. CCI cumulée", f"{total_capi:,.0f} M€".replace(",", " ") if pd.notna(total_capi) else "—")

st.dataframe(
    df_sorted,
    width="stretch",
    hide_index=True,
    height=(len(df_sorted) + 1) * 35 + 3,
    column_config={
        "Cours (€)": st.column_config.NumberColumn(format="%.2f €"),
        "Capitaux propres / titre (€)": st.column_config.NumberColumn(
            format="%.2f €",
            help="Actif net comptable rapporté au nombre TOTAL de titres "
                 "composant le capital de la caisse (parts sociales + CCA + CCI), "
                 "pas seulement les CCI cotés. Source : Yahoo Finance (mrq).",
        ),
        "Capitaux propres totaux (M€)": st.column_config.NumberColumn(format="%.0f"),
        "Ratio P/B": st.column_config.NumberColumn(format="%.3f"),
        "Décote (%)": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f %%"
        ),
        "CCI cotés": st.column_config.NumberColumn(
            format="%d",
            help="Nombre de CCI cotés à Euronext Paris. Ne représente qu'une "
                 "fraction du capital total ; ce n'est PAS le dénominateur du "
                 "champ « Capitaux propres / titre » ci-dessus.",
        ),
        "Capi. CCI (M€)": st.column_config.NumberColumn(format="%.0f"),
        "Mis à jour": st.column_config.DatetimeColumn(
            format="DD/MM/YYYY HH:mm",
            help="Date du dernier fetch réussi pour ce ticker. Vide si aucun succès depuis le démarrage du serveur.",
        ),
    },
)


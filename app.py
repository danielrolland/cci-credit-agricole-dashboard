import pandas as pd
import streamlit as st
import yfinance as yf
from curl_cffi import requests as cf_requests


@st.cache_resource(show_spinner=False)
def _yf_session():
    """Session avec empreinte TLS Chrome — contourne le throttling Yahoo
    sur les IP datacenter (notamment Streamlit Cloud)."""
    return cf_requests.Session(impersonate="chrome")

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
        "Titres cotés (CCI)": None,
        "Capi. CCI (M€)": None,
        "Dernier bilan": None,
    }


@st.cache_data(ttl=900, show_spinner=False)
def fetch_one(ticker: str) -> tuple[dict, str | None]:
    """Renvoie (data, error). error vaut None si tout s'est bien passé."""
    try:
        t = yf.Ticker(ticker, session=_yf_session())
        info = t.info or {}
        if not info.get("currentPrice") and not info.get("regularMarketPrice"):
            return _empty_row(ticker), "aucune donnée de cours"

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
        except Exception:
            pass

        return {
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
            "Titres cotés (CCI)": info.get("sharesOutstanding"),
            "Capi. CCI (M€)": (
                info.get("marketCap") / 1e6 if info.get("marketCap") else None
            ),
            "Dernier bilan": last_balance_date,
        }, None
    except Exception as e:
        return _empty_row(ticker), f"{type(e).__name__}: {e}"


@st.cache_data(ttl=900, show_spinner=False)
def fetch_all() -> tuple[pd.DataFrame, dict[str, str]]:
    rows = []
    failures: dict[str, str] = {}
    for ticker, name in CCI.items():
        data, err = fetch_one(ticker)
        if err:
            failures[ticker] = err
        rows.append({"Caisse régionale": name, **data})
    return pd.DataFrame(rows), failures


st.set_page_config(
    page_title="CCI Crédit Agricole",
    page_icon="🌾",
    layout="wide",
)

st.title("CCI Crédit Agricole — cours & capitaux propres")
st.caption(
    "Suivi des 13 Certificats Coopératifs d'Investissement des Caisses Régionales du "
    "Crédit Agricole cotés à Euronext Paris. Données : Yahoo Finance via yfinance."
)

with st.spinner("Récupération des données…"):
    try:
        df, failures = fetch_all()
    except Exception as e:
        st.error(
            "Yahoo Finance temporairement injoignable. "
            "Réessayez dans quelques minutes."
        )
        st.caption(f"Détail technique : `{type(e).__name__}: {e}`")
        st.stop()

if failures:
    if len(failures) == len(CCI):
        st.error(
            "Aucune donnée n'a pu être récupérée pour les 13 CCI. "
            "Yahoo Finance est probablement injoignable, réessayez plus tard."
        )
    else:
        details = ", ".join(f"{tk} ({CCI[tk]})" for tk in failures)
        st.warning(
            f"Données indisponibles pour {len(failures)} CCI : {details}. "
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
        "Capitaux propres / titre (€)": st.column_config.NumberColumn(format="%.2f €"),
        "Capitaux propres totaux (M€)": st.column_config.NumberColumn(format="%.0f"),
        "Ratio P/B": st.column_config.NumberColumn(format="%.3f"),
        "Décote (%)": st.column_config.ProgressColumn(
            min_value=0, max_value=100, format="%.1f %%"
        ),
        "Titres cotés (CCI)": st.column_config.NumberColumn(format="%d"),
        "Capi. CCI (M€)": st.column_config.NumberColumn(format="%.0f"),
    },
)


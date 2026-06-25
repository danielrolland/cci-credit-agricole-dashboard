import datetime as dt
import json
import time
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from cci_fetch import CCI, PARIS, empty_row, fetch_one, log, make_session

# Repli en cascade — le plus frais l'emporte, par ticker :
#   1. live    : on interroge Yahoo ici (cache 30 min, partagé entre sessions) ;
#   2. mémoire : dernier fetch live réussi du process (survit au cache 30 min) ;
#   3. branche : snapshot publié par le job GitHub Actions, tenu à jour ~quelques
#                fois/jour — plancher qui survit au cold start de Streamlit Cloud.
# L'app peut se faire 429 par Yahoo depuis l'IP datacenter (cf. gotcha #1) : dans
# ce cas elle retombe sur (2) puis (3), donc jamais de page vide — au pire on
# voit ce que la branche `data` contient, comme avant.
DATA_URL = (
    "https://raw.githubusercontent.com/"
    "danielrolland/cci-credit-agricole-dashboard/data/cci-data.json"
)

COLUMNS = [
    "Caisse régionale", "Ticker", "Cours (€)",
    "Capitaux propres / titre (€)", "Capitaux propres totaux (M€)",
    "Ratio P/B", "Décote (%)", "CCI cotés", "Capi. CCI (M€)",
    "Dernier bilan", "Mis à jour",
]

_MIN_TS = pd.Timestamp.min.tz_localize("UTC")


@st.cache_resource(show_spinner=False)
def _memory_store() -> dict:
    """Singleton process : dernière ligne live réussie par ticker. Survit aux
    évictions du cache 30 min et aux sessions ; perdu au cold start (→ branche)."""
    return {}


@st.cache_data(ttl=900, show_spinner=False)
def _branch_rows() -> dict:
    """Plancher : snapshot de la branche `data` (publié par GitHub Actions),
    indexé par ticker. Lecture best-effort : en cas d'échec on renvoie {}."""
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "cci-dashboard"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            snap = json.loads(resp.read().decode("utf-8"))
        return {r["Ticker"]: r for r in snap.get("rows", []) if r.get("Ticker")}
    except Exception as e:
        log("WARN", f"branche `data` illisible : {type(e).__name__}: {e}")
        return {}


def _ts(row: dict | None) -> pd.Timestamp:
    """Horodatage « Mis à jour » comparable (None → très ancien)."""
    val = row.get("Mis à jour") if row else None
    return pd.to_datetime(val, utc=True) if val else _MIN_TS


@st.cache_data(ttl=1800, show_spinner=False)
def load_data() -> dict:
    """Fetch live Yahoo (≤ 1× / 30 min, partagé entre toutes les sessions grâce
    au cache). Par ticker en échec : repli sur la valeur connue la plus récente
    (mémoire process, puis branche `data`)."""
    session = make_session()
    memory = _memory_store()
    branch = _branch_rows()
    now = dt.datetime.now(PARIS).isoformat(timespec="seconds")

    rows, stale, missing = [], [], []
    for i, (ticker, name) in enumerate(CCI.items()):
        if i:
            time.sleep(1.5)  # on reste poli avec Yahoo
        try:
            data = fetch_one(ticker, session)
            row = {"Caisse régionale": name, **data, "Mis à jour": now}
            memory[ticker] = row  # mémorise le dernier live réussi
            rows.append(row)
            log("INFO", f"{ticker}: live OK ({data['Cours (€)']} €)")
        except Exception as e:
            log("WARN", f"{ticker}: live KO ({type(e).__name__}: {e})")
            known = [r for r in (memory.get(ticker), branch.get(ticker))
                     if r and r.get("Cours (€)") is not None]
            if known:
                best = max(known, key=_ts)
                row = dict(best)
                row["Caisse régionale"] = name  # au cas où le libellé change
                rows.append(row)
                stale.append(ticker)
                log("WARN", f"{ticker}: repli sur valeur du {best.get('Mis à jour')}")
            else:
                rows.append(empty_row(ticker, name))
                missing.append(ticker)

    # Fraîcheur globale = horodatage de ligne le plus récent.
    ts_all = [_ts(r) for r in rows if _ts(r) != _MIN_TS]
    generated_at = max(ts_all).isoformat() if ts_all else now
    return {
        "generated_at": generated_at,
        "rows": rows,
        "stale_tickers": stale,
        "missing_tickers": missing,
    }


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

with st.spinner("Récupération des cours… (peut prendre ~20 s lors d'une actualisation)"):
    try:
        snapshot = load_data()
    except Exception as e:
        log("ERROR", f"chargement des données impossible : {type(e).__name__}: {e}")
        st.error(
            "Données momentanément indisponibles. Réessayez dans quelques minutes."
        )
        st.caption(f"Détail technique : `{type(e).__name__}: {e}`")
        st.stop()

df = pd.DataFrame(snapshot.get("rows", []))
stale = snapshot.get("stale_tickers", [])
missing = snapshot.get("missing_tickers", [])

if df.empty:
    st.error("Le snapshot ne contient aucune donnée. Réessayez plus tard.")
    st.stop()

# Réordonne les colonnes et type les dates pour l'affichage.
df = df.reindex(columns=COLUMNS)
df["Mis à jour"] = pd.to_datetime(df["Mis à jour"], utc=True).dt.tz_convert(PARIS)

# Bandeau de fraîcheur globale du snapshot.
generated_at = snapshot.get("generated_at")
if generated_at:
    gen = pd.to_datetime(generated_at)
    age = dt.datetime.now(PARIS) - gen.to_pydatetime()
    st.caption(f"Dernière actualisation des données : {gen:%d/%m/%Y %H:%M}.")
    if age > dt.timedelta(hours=6):
        st.warning(
            "Les données n'ont pas été rafraîchies depuis plus de 6 h — le job de "
            "récupération est peut-être en échec. Les valeurs affichées restent les "
            "dernières connues."
        )

# État par ticker.
if missing:
    if len(missing) == len(df):
        st.error(
            "Aucune donnée n'a pu être récupérée pour les 13 CCI, et aucune valeur "
            "n'est en cache. Réessayez plus tard."
        )
    else:
        details = ", ".join(missing)
        st.warning(
            f"Aucune donnée (même en cache) pour {len(missing)} CCI : {details}. "
            "Le reste du tableau reste exploitable."
        )
if stale:
    st.info(
        f"Cours non rafraîchis pour {len(stale)} CCI lors de la dernière collecte "
        "(Yahoo momentanément injoignable) : dernières valeurs connues affichées "
        "— voir la colonne « Mis à jour »."
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
            help="Date du dernier relevé réussi pour ce ticker.",
        ),
    },
)

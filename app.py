import datetime as dt
import json
import sys
import urllib.request
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

PARIS = ZoneInfo("Europe/Paris")

# Snapshot publié par le job GitHub Actions (`fetch_data.py`) sur la branche
# `data`. L'app ne contacte JAMAIS Yahoo directement : c'est le fetcher qui le
# fait depuis une IP non rate-limitée, et écrit ce JSON versionné dans git.
# Conséquence : plus de YFRateLimitError côté app, et les dernières valeurs
# connues survivent aux redéploiements / mises en sommeil de Streamlit Cloud.
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


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", file=sys.stderr, flush=True)


@st.cache_data(ttl=900, show_spinner=False)
def load_snapshot() -> dict:
    """Lit le dernier snapshot publié (branche `data`). Mis en cache 15 min ;
    le fetcher rafraîchit la donnée toutes les ~30 min côté GitHub."""
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": "cci-dashboard"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


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

with st.spinner("Chargement des données…"):
    try:
        snapshot = load_snapshot()
    except Exception as e:
        _log("ERROR", f"snapshot illisible : {type(e).__name__}: {e}")
        st.error(
            "Données momentanément indisponibles (snapshot introuvable). "
            "Réessayez dans quelques minutes."
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

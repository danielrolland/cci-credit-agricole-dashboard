#!/usr/bin/env python3
"""Récupère les données des 13 CCI depuis Yahoo Finance et écrit un snapshot JSON.

Tourne dans GitHub Actions, depuis l'IP des runners (non rate-limitée par Yahoo
comme peut l'être celle de Streamlit Cloud). Publie le résultat sur la branche
`data`, qui sert de PLANCHER à l'app : celle-ci tente d'abord un fetch live, et
ne retombe sur ce snapshot que si elle n'a rien de plus récent (cf. app.py).

Fusion avec le snapshot précédent : un ticker qui échoue conserve sa dernière
valeur connue (et son horodatage) au lieu d'être vidé. Le JSON est donc toujours
le « meilleur état connu » par ticker, et comme il est versionné dans git, il
survit aux redéploiements / mises en sommeil de Streamlit.

Usage : python fetch_data.py [sortie.json] [precedent.json]
"""
import datetime as dt
import json
import sys
import time

from cci_fetch import CCI, PARIS, empty_row, fetch_one, log, make_session

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "cci-data.json"
PREVIOUS = sys.argv[2] if len(sys.argv) > 2 else None


def load_previous() -> dict[str, dict]:
    """Indexe le snapshot précédent par ticker (pour le repli)."""
    if not PREVIOUS:
        return {}
    try:
        with open(PREVIOUS, encoding="utf-8") as f:
            data = json.load(f)
        return {r["Ticker"]: r for r in data.get("rows", []) if r.get("Ticker")}
    except (OSError, ValueError) as e:
        log("WARN", f"snapshot précédent illisible ({e}) — on repart de zéro")
        return {}


def main() -> None:
    session = make_session()
    previous = load_previous()
    now = dt.datetime.now(PARIS).isoformat(timespec="seconds")

    rows, stale, missing = [], [], []
    for i, (ticker, name) in enumerate(CCI.items()):
        if i:
            time.sleep(1.5)  # on reste poli avec Yahoo (≈20 s au total)
        try:
            data = fetch_one(ticker, session)
            rows.append({"Caisse régionale": name, **data, "Mis à jour": now})
            log("INFO", f"{ticker}: OK ({data['Cours (€)']} €)")
        except Exception as e:
            log("ERROR", f"{ticker}: {type(e).__name__}: {e}")
            prev = previous.get(ticker)
            if prev and prev.get("Cours (€)") is not None:
                row = dict(prev)
                row["Caisse régionale"] = name  # au cas où le libellé change
                rows.append(row)
                stale.append(ticker)
                log("WARN", f"{ticker}: repli sur snapshot du {prev.get('Mis à jour')}")
            else:
                rows.append(empty_row(ticker, name))
                missing.append(ticker)

    snapshot = {
        "generated_at": now,
        "rows": rows,
        "stale_tickers": stale,
        "missing_tickers": missing,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    log("INFO", f"écrit {OUTPUT} — {len(rows)} lignes, "
                f"{len(stale)} périmées, {len(missing)} sans donnée")

    # Échec dur seulement si TOUT a échoué sans aucun repli possible : on évite
    # alors d'écraser un bon snapshot par un fichier vide (le job ne committe pas).
    if len(missing) == len(CCI):
        sys.exit(1)


if __name__ == "__main__":
    main()

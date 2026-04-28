# CCI Crédit Agricole

Tableau de bord léger des 13 Certificats Coopératifs d'Investissement (CCI) des Caisses Régionales du Crédit Agricole cotés à Euronext Paris : cours, capitaux propres par titre, ratio P/B et décote.

Données : Yahoo Finance via `yfinance`.

## Lancer en local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Déploiement sur Streamlit Community Cloud

1. Pousser ce dossier sur un repo GitHub public.
2. Sur https://share.streamlit.io, cliquer **New app**, sélectionner le repo, la branche, et `app.py`.
3. Choisir un sous-domaine (ex. `cci-credit-agricole.streamlit.app`).

Pas de variable d'environnement ni de secret nécessaires.

## Notes

- Cache de 15 minutes sur les requêtes yfinance pour éviter le rate limiting.
- Le `bookValue` retourné par Yahoo correspond à l'actif net comptable rapporté au nombre **total** de titres (parts sociales + CCA + CCI), donc le ratio P/B affiché est directement comparable au cours du CCI.
- Les capitaux propres ne bougent qu'aux publications de comptes (annuels en mars, semestriels).

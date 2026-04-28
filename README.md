# CCI Crédit Agricole

Tableau de bord léger des 13 Certificats Coopératifs d'Investissement (CCI) des Caisses Régionales du Crédit Agricole cotés à Euronext Paris : cours, capitaux propres par titre, ratio P/B et décote.

Données : Yahoo Finance via `yfinance`.

## Lancer en local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Application en ligne

https://cci-credit-agricole-dashboard-uld6b42hndmrskucnchnpc.streamlit.app/

## Notes

- Cache de 15 minutes sur les requêtes yfinance pour éviter le rate limiting.
- Le `bookValue` retourné par Yahoo correspond à l'actif net comptable rapporté au nombre **total** de titres (parts sociales + CCA + CCI), donc le ratio P/B affiché est directement comparable au cours du CCI.
- Les capitaux propres ne bougent qu'aux publications de comptes (annuels en mars, semestriels).

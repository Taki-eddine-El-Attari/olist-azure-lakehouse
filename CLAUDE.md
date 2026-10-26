# CLAUDE.md — Olist Lakehouse (repo `olist-azure-lakehouse`)

Lis `CAHIER_DES_CHARGES.md` et `AZURE_SETUP.md` avant toute tâche. Les décisions prises sont dans `docs/decisions.md`.

- Dev local dans Docker : `docker compose build`, puis `docker compose run --rm dev pytest`.
- Les versions (Python 3.12, Spark 4.1, Delta 4.2, Java 21) suivent Databricks Runtime 18 LTS ML : ne pas les changer sans changer aussi le runtime du cluster.
- Doc en français, code et commits en anglais.

<!-- claude-reflect: learned rules (saved from the band; edit freely) -->
## Learned rules
- Write files and run checks yourself, but give the user critical or deterministic steps (Azure work, key commands) to run, with a brief explanation.
<!-- end claude-reflect -->

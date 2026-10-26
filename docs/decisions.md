# Journal des décisions

## ADR-001 — Environnement local : Docker aligné sur Databricks Runtime 18 LTS ML (2026-10-26)

**Contexte.** Le poste Windows a Python 3.13 et Java 8, et WSL n'a pas de distro Ubuntu. Le cluster Azure tournera sur Databricks Runtime 18 LTS ML (Spark 4.1.0, Python 3.12.3, Java Zulu 21, Delta 4.2.0, d'après les release notes Microsoft Learn du 11/09/2026).

**Décision.** Image Docker `python:3.12-slim-trixie` + OpenJDK 21 + `pyspark==4.1.1` + `delta-spark==4.2.0` (Delta 4.2.x supporte Spark 4.0.x et 4.1.x, d'après la table de compatibilité docs.delta.io ; `delta-spark` 4.2.0 impose `pyspark<=4.1.1`, d'où 4.1.1 et pas 4.1.3).

**Conséquences.** Le code testé en local tourne sur les mêmes versions majeures que le cluster. L'écart restant : pyspark 4.1.1 en local contre le Spark 4.1.0 de Databricks (qui est un fork maison). La même image pourra servir à la CI.

## ADR-002 — Cluster *Single user* et ADF

L'identité managée d'ADF n'est pas l'utilisateur assigné au cluster. Plan : tester d'abord avec l'identité managée en phase 5, et passer au fallback *Access token* dans Key Vault si c'est refusé.

## ADR-003 — Suites du benchmark : l'option la moins risquée à chaque fois (2026-10-26)

**Contexte.** Le benchmark (`docs/benchmark.md`) posait 4 questions. Consigne : choisir l'option la moins risquée et approfondir plus tard.

**Décisions.**
1. **Nom :** on garde `olist-azure-lakehouse`, déjà utilisé dans tous les documents et dans le sujet OIDC (AZURE_SETUP.md étape 11). Le ML apparaît dans la description GitHub et dans le titre CV (« Pipeline Data & ML sur Azure »).
2. **ADF → Databricks :** pas de changement de plan. Phase 5 = activité *Notebook* sur le cluster existant, identité managée, puis fallback token (ADR-002). L'activité *Databricks Job* + job cluster sera essayée en phase 5 seulement si l'identité managée est refusée, et avant le token. Raison : c'est une activité plus récente, que nous n'avons pas encore testée, et elle impose d'éteindre le cluster interactif pendant le run (quota 6 vCPU).
3. **Power BI :** on garde `.pbix` + export PDF + captures + `measures.dax`. `.pbip` n'est pas adopté tant que son statut (preview ou GA) n'est pas vérifié dans Power BI Desktop.
4. **Ajouts au cahier des charges** (tous à faible coût) : lecture `multiLine` des avis + test des comptes (phase 1), contrôle paiements sans article + table `quarantine` (phase 2), contrôles Gold qui font échouer le run (phase 3), « Known gaps » et coûts réels dans le README (phase 9), serverless interdit (risques).

**Écarté pour l'instant.** `TIMESTAMP_NTZ` : la session est déjà figée en UTC dans `spark.py` (testé), et la lecture de `TIMESTAMP_NTZ` par le connecteur Power BI n'est pas vérifiée. Un test de phase 1 vérifie qu'aucune date ne se décale. À revoir si ce test échoue.

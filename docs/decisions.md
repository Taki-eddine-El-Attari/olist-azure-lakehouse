# Journal des décisions

## ADR-001 — Environnement local : Docker aligné sur Databricks Runtime 18 LTS ML (2026-10-26)

**Contexte.** Le poste Windows a Python 3.13 et Java 8, et WSL n'a pas de distro Ubuntu. Le cluster Azure tournera sur Databricks Runtime 18 LTS ML (Spark 4.1.0, Python 3.12.3, Java Zulu 21, Delta 4.2.0, d'après les release notes Microsoft Learn du 11/09/2026).

**Décision.** Image Docker `python:3.12-slim-trixie` + OpenJDK 21 + `pyspark==4.1.1` + `delta-spark==4.2.0` (Delta 4.2.x supporte Spark 4.0.x et 4.1.x, d'après la table de compatibilité docs.delta.io ; `delta-spark` 4.2.0 impose `pyspark<=4.1.1`, d'où 4.1.1 et pas 4.1.3).

**Conséquences.** Le code testé en local tourne sur les mêmes versions majeures que le cluster. L'écart restant : pyspark 4.1.1 en local contre le Spark 4.1.0 de Databricks (qui est un fork maison). La même image pourra servir à la CI.

## ADR-002 — Cluster *Single user* et ADF

L'identité managée d'ADF n'est pas l'utilisateur assigné au cluster. Plan : tester d'abord avec l'identité managée en phase 5, et passer au fallback *Access token* dans Key Vault si c'est refusé.

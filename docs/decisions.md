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

## ADR-004 — Bronze et défauts mesurés en phase 1 (2026-10-26)

**Bronze.** `src/olist/bronze.py` lit les 9 CSV avec un schéma explicite (noms de colonnes de la source conservés, codes postaux en `STRING` pour garder les zéros, montants en `DECIMAL(10,2)`, dates en `TIMESTAMP` sous session UTC), en `multiLine` et en `FAILFAST` : une valeur hors schéma arrête le run au lieu de devenir `null`. Chaque table reçoit `_ingested_at` et `_source_file` (`_metadata.file_path`, qui marche aussi sous Unity Catalog). Écriture Delta en `overwrite` : la source est un instantané complet. Ingestion locale : ~47 s dans Docker.

**Piège de test découvert.** `count()` sur un CSV ne parse pas les colonnes, donc `FAILFAST` ne se déclenche pas. Le test utilise `collect()`. L'écriture Delta parse tout, donc l'ingestion elle-même est bien protégée.

**Défauts mesurés** (`python -m olist.eda` sur Bronze ; comptes CSV recomptés indépendamment avec le module `csv`) :

| Constat | Valeur | Conséquence (phase 2) |
|---|---|---|
| Commandes sans date de livraison client | 2 965 (dont 8 au statut `delivered`) | `delivery_status` ; exclure de la cible ML |
| Commandes sans date d'approbation | 160 | autoriser `null` |
| Livrées avant achat ou approbation | 61 | contrôle DQ (règle de dates), en quarantaine |
| Remises au transporteur avant approbation | 1 359 | contrôle DQ en avertissement, pas bloquant (trop fréquent pour être une erreur de saisie isolée) |
| Produits sans catégorie | 610 | `unknown` |
| Catégories absentes de la traduction | `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos` | traduction manuelle |
| Produits sans poids ni dimensions | 2 | `null`, pas d'imputation en Silver |
| `review_id` présents plusieurs fois | 789 identifiants, 814 lignes en trop | **la clé est `(review_id, order_id)`** : un même avis (même note, même texte) est rattaché à plusieurs commandes. Ne pas dédoublonner sur `review_id` |
| Commandes avec plusieurs avis | 547 | garder l'avis le plus récent par `order_id` |
| Commandes sans avis | 768 | `review_score` nullable dans `fact_orders` |
| Geolocation | 1 000 163 lignes pour 19 015 préfixes | médiane lat/lng par préfixe |
| Préfixes clients absents de geolocation | 157 | distance client-vendeur nullable (feature ML) |
| `customer_id` / `customer_unique_id` distincts | 99 441 / 96 096 | `dim_customer` sur `customer_unique_id` |
| Commandes sans aucun article | 775 (toutes payées) | contrôle DQ « payée sans article » |
| Paiements − (prix + fret) | 165 318,88 BRL | à expliquer en phase 2 (commandes sans article, intérêts des échéances) |
| Paiements à 0 | 9 | à examiner (bons d'achat ?) |
| Taux de retard (livrées) | 8,11 % | confirme l'histoire (~8,1 %) |
| Note moyenne retard / à l'heure | 2,57 / 4,29 | confirme l'histoire |

Écarts avec le benchmark : BDhabekar annonce 622 commandes payées sans article et un écart de 122 510 BRL ; nous mesurons 775 et 165 318,88 BRL sur les données brutes. Leur filtre exact n'est pas connu (README seulement).

## ADR-005 — Règles Silver et contrôles qualité (2026-10-26)

**Enquête avant les règles** (sur les CSV) : trois points de l'ADR-004 changent de sens.
- Les **61** commandes « livrées avant approbation » ont toutes une livraison après l'achat : c'est la date d'**approbation** qui est enregistrée en retard (de 0,1 h à 7 jours). On garde ces commandes, en avertissement.
- L'écart paiements − articles (**165 318,88 BRL**) est expliqué : 162 591,95 BRL viennent des 775 commandes sans article (603 `unavailable`, 164 `canceled` : payées, jamais expédiées), et 2 870,39 BRL des commandes avec articles, dont 99 % des trop-payées ont plusieurs échéances (intérêts).
- Les villes clients sont déjà en minuscules sans espaces superflus (0 à corriger) : pas de règle trim/lower.

**Règles Silver** (`src/olist/silver.py`) :

| Table | Règle |
|---|---|
| orders | `delivery_status` = `delivered` si la date de livraison client existe, sinon `not_delivered` (les 8 `delivered` sans date deviennent `not_delivered`) |
| order_reviews | un avis par commande, le plus récent (création puis réponse) ; un `review_id` partagé est gardé pour chaque commande |
| products | catégorie nulle → `unknown` ; 2 traductions manuelles ; colonnes `*_lenght` renommées `*_length` |
| geolocation | points hors du Brésil (lat −34..6, lng −74..−34) en quarantaine (42), puis médiane lat/lng par préfixe |
| order_items, order_payments | montants négatifs en quarantaine (0 trouvé) |
| autres | colonnes Bronze `_ingested_at` / `_source_file` retirées, rien d'autre |

**Quarantaine** : une seule table `silver/quarantine` (`table`, `_rule`, `record` en JSON, `_quarantined_at`), pour garder des schémas différents dans une table.

**Contrôles** (`src/olist/quality.py`, résultats ajoutés à `gold/dq_results` à chaque run) : 16 contrôles `error` (clés uniques et non nulles, intégrité référentielle, catégories remplies, livraison après achat) qui font échouer le run, et 7 `warn` qui comptent les défauts connus sans bloquer.

**Résultat du premier run complet** : 16/16 `error` passent. Warnings : livrée avant approbation 61, transporteur avant achat 166, payées sans article 775, commande sans paiement 1, paiements à 0 9, clients dont le préfixe n'a pas de géolocalisation 279 (157 préfixes), quarantaine 42. Silver : 98 673 avis (= 99 441 commandes − 768 sans avis), 19 010 préfixes (5 préfixes n'avaient que des points hors du Brésil).

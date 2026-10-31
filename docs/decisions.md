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

## ADR-006 — Gold : définition du retard et choix du modèle en étoile (2026-10-26)

**Retard au jour près.** La date estimée est toujours à minuit (0 exception sur 99 441). Comparer les horodatages compte donc en retard toute commande livrée **le jour promis** après minuit : 1 292 commandes, dont la note moyenne est 4,03, proche de celle des commandes à l'heure. Décision (validée) : `is_late = date(livraison) > date(estimation)`.

| Définition | Taux de retard | Note en retard / à l'heure |
|---|---|---|
| Horodatage (chiffre courant dans les autres projets) | 8,11 % | 2,57 / 4,29 |
| **Jour (retenue)** | **6,77 %** | **2,27 / 4,29** |

Conséquences : `sql/checks.sql`, `measures.dax` et la cible ML (phase 7) utilisent cette définition. L'histoire est plus forte (2,27 au lieu de 2,57), et c'est un argument d'entretien : le chiffre de 8,1 % surcompte.

**Autres choix Gold** (`src/olist/gold.py`) :
- Clés de substitution = rang dans l'ordre de la clé naturelle (`row_number`) : stables d'une reconstruction à l'autre sur les mêmes données. Limite : fenêtre globale sur une seule partition, à remplacer par `xxhash64` au-delà de quelques millions de lignes.
- `dim_customer` sur `customer_unique_id` (96 096 lignes), avec l'adresse de la **dernière** commande du client.
- `dim_date` couvre des années entières (2016-2018, 1 096 jours) pour l'intelligence temporelle de Power BI. `day_of_week` : 1 = lundi.
- `fact_orders` : `delivery_status` ajouté (repris de Silver) ; montants à 0 et non `null` pour les commandes sans article ni paiement ; `payment_type_main` = le type du plus gros paiement ; `is_late` et `is_negative_review` restent `null` quand il n'y a pas de livraison ou pas d'avis.
- Pas de membre « inconnu » (clé −1) dans les dimensions : les contrôles Silver garantissent toutes les clés étrangères, et `checks.sql` vérifie qu'aucune clé de fait n'est nulle.
- Export pour Power BI : un fichier Parquet par table dans `data/powerbi/`, parce que Power BI Desktop n'a pas de lecteur intégré pour un dossier Delta local *(d'après mes connaissances, non vérifié dans ta version de Power BI)*. Lire directement les fichiers Parquet d'une table Delta serait faux : après un `overwrite`, les anciens fichiers restent dans le dossier jusqu'au `VACUUM`.

**Résultat du run complet :** 11/11 contrôles Gold passent (volumes, sommes de prix et de paiements identiques à Silver, aucune clé nulle, 6,77 %, 2,27, 4,29).

## ADR-007 — Databricks serverless : aucune VM utilisable sur l'abonnement (2026-10-26)

**Constat** (`az vm list-skus`, `az vm list-usage`, policy « Allowed resource deployment regions ») : le compte Azure for Students n'autorise que 5 régions. Les deux seules qui proposent Databricks (switzerlandnorth, norwayeast) n'offrent **aucune** taille de VM utilisable : toutes sont `NotAvailableForSubscription`, ou dépassent le quota de 6 vCPU. Les régions qui ont des VM utilisables (austriaeast, denmarkeast) ne proposent pas Databricks. Les quotas vus en phase 0 (DSv2 = 4…) ne garantissaient donc rien : un quota n'est pas une autorisation.

**Décision (validée) :** workspace Databricks **Premium** en switzerlandnorth, calcul **serverless** uniquement. Le serverless y est supporté (Microsoft Learn, « Features with limited regional availability », mise à jour du 2026-10-21) et ses machines tournent chez Databricks, pas dans l'abonnement.

**Options écartées :** demande au support pour débloquer DS3_v2 (lente, incertaine, pas de plan de support sur un compte Students) ; quitter Azure Databricks (Free Edition, Synapse), ce qui fait perdre la compétence visée.

**Conséquences :**
- Pas de cluster. Le pipeline tourne en **job serverless** `olist_pipeline` (notebooks 01 → 03), en mode standard (moins cher).
- La règle « serverless interdit » (ADR-003) devient « **pas de développement interactif sur serverless** » : le risque du benchmark venait du développement interactif, pas du serverless en soi.
- Code : `src/olist/config.py` choisit entre dossiers Delta locaux et tables Unity Catalog `olist.<couche>.<table>`. Les CSV sont lus dans le volume `/Volumes/olist/landing/raw` (sous-dossier `olist/` du conteneur `landing`). Session forcée en UTC aussi sur Databricks. Pas de `.cache()` (non supporté en serverless).
- Phase 5 : ADF lance le job via l'activité *Databricks Job* (piste d'ADR-003), puisqu'il n'y a pas de cluster existant.
- Phase 6 : Power BI se connecte à un SQL warehouse serverless.
- L'image Docker reste alignée sur DBR 18 LTS ML. Le serverless suit sa propre version d'environnement : l'alignement des versions devient approximatif, à vérifier au premier run (version de Python et de Spark affichées).
- Prix serverless Azure **non vérifié** (page de prix officielle trop lourde à charger, sources tierces contradictoires) : le coût réel du premier run sera mesuré et noté avant d'aller plus loin.

**Premier run serverless (2026-10-26)** : job `olist_pipeline` réussi de bout en bout. Mêmes chiffres qu'en local à l'unité près (Bronze = CSV, Silver 98 673 avis et 42 lignes en quarantaine, 16 `pass` / 7 `warn`, Gold 11/11 dont 6,77 %, 2,27, 4,29). Le code testé en Docker a tourné sur Databricks sans modification. La tâche Bronze a pris 4 min 14 s, contre ~47 s en local : démarrage du serverless en mode standard et écritures sur ADLS. Captures : `docs/screenshots/phase4_*.png`.

**Coût réel (Cost analysis, relevé le 2026-10-31)** : le run a coûté **0,22 USD** (service *Azure Databricks*, facturé le 26/10 seulement, inchangé au 31/10). Mais le cumul atteint **5,42 USD** au 31/10, dont 4,67 USD de *NAT Gateway* et 0,52 USD de *Virtual Network* dans le groupe managé `databricks-rg-dbw-olist-*`, sans aucune exécution. Cause (Microsoft Learn, « Enable secure cluster connectivity ») : un workspace *Hybrid* créé avec le réseau par défaut active la connectivité sécurisée (No Public IP) et Databricks crée une NAT Gateway, facturée à l'heure, pour un calcul classique que l'abonnement ne peut pas lancer (ADR-007). Le *Virtual Network* est probablement l'IP publique de cette NAT Gateway *(déduit, non vérifié)*. Rythme mesuré : ~1 USD/jour, soit ~30 USD/mois, au-dessus du budget de 20 USD. Captures : `docs/screenshots/phase4_cost_daily_2026-10-26.png`, `docs/screenshots/cost_cumulative_2026-10-31.png`.
Version observée au premier run : le serverless exécute **Python 3.12** (chemin `/databricks/python/lib/python3.12/` dans un avertissement), comme l'image Docker. Avertissement attendu sans conséquence : `No Partition Defined for Window operation`, causé par les clés de substitution `row_number` globales (limite notée dans `gold.py`).

## ADR-008 — Orchestration ADF du job serverless (2026-10-31)

**Contexte.** Pas de cluster (ADR-007), donc pas d'activité *Notebook* sur un cluster existant (ADR-002, ADR-003). Le cahier des charges prévoyait une *Copy* landing → bronze dans ADF ; or la Bronze est déjà écrite par `01_bronze` depuis le volume `olist.landing.raw`, avec schéma explicite et `FAILFAST` (ADR-004). Copier en plus dans `bronze` dupliquerait la couche.

**Décision.** Pipeline `pl_olist_daily` (JSON dans `adf/`, versionné par l'intégration Git d'ADF, branche `main`, dossier `/adf`) :

1. *Get Metadata* `Check landing files` : liste `landing/olist`.
2. *If Condition* `Files present` : le nombre de fichiers doit valoir le paramètre `expectedFileCount` (9) ; sinon *Fail* `MISSING_FILES` avec le nombre trouvé.
3. *Job* `Run olist_pipeline` (type `DatabricksJob`, linked service `ls_databricks` en identité managée, option *Serverless*) : lance le job 01 → 03.
4. *Copy* `Archive CSVs` : copie des CSV vers `landing/archive/<runDate ou date du déclenchement>/`.
5. Sur échec du job : *Fail* `JOB_FAILED` qui reprend le message d'erreur du job. Sans activité *Fail*, un chemin « sur échec » qui réussit rendrait le run vert.

**Identité managée acceptée.** L'identité d'ADF (Contributor sur le seul workspace) lance le job sans token : le fallback *Access token* d'ADR-002 n'a pas servi. Rôle de données limité au conteneur `landing`.

**Constats.**
- *Test connection* du linked service Databricks en *Serverless* échoue toujours (`27001`, « Cluster Serverless does not exist ») ; le linked service fonctionne quand même au run.
- Debug avec l'activité Job désactivée (*Mark as succeeded*) : teste Get Metadata, la condition et la copie sans coût Databricks.
- **Run complet du 2026-10-31** (`e7d35bfe-227f-4dda-811f-216d89fa2916`, *Trigger now*) : Get Metadata 11 s, Job 8 min 25 s, Copy 16 s, 9 CSV dans `landing/archive/2026-10-31/`. Captures `docs/screenshots/phase5_*.png`. Coût à relever (attendu ~0,22 USD comme en phase 4).
- Trigger `tr_daily` (quotidien) publié à l'état `Stopped`.

**Écarté.** Vérifier les noms des 9 fichiers au lieu de leur nombre (il faudrait un *ForEach* de *Get Metadata* `exists`) : le nombre suffit tant que `landing/olist` ne reçoit que la source Olist. Alerte e-mail sur échec (Azure Monitor) : le *Fail* et le Monitor d'ADF suffisent pour un projet de démonstration.

**Limite.** L'ID d'abonnement et l'ID de tenant figurent dans `adf/` (ressource du workspace, identité de la factory) : ce sont des identifiants, pas des secrets.

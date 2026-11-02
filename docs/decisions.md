# Journal des décisions

## ADR-001 — Environnement local : Docker aligné sur Databricks Runtime 18 LTS ML (Jour 1)

**Contexte.** Le poste Windows a Python 3.13 et Java 8, et WSL n'a pas de distro Ubuntu. Le cluster Azure tournera sur Databricks Runtime 18 LTS ML (Spark 4.1.0, Python 3.12.3, Java Zulu 21, Delta 4.2.0, d'après les release notes Microsoft Learn du 11/09/2026).

**Décision.** Image Docker `python:3.12-slim-trixie` + OpenJDK 21 + `pyspark==4.1.1` + `delta-spark==4.2.0` (Delta 4.2.x supporte Spark 4.0.x et 4.1.x, d'après la table de compatibilité docs.delta.io ; `delta-spark` 4.2.0 impose `pyspark<=4.1.1`, d'où 4.1.1 et pas 4.1.3).

**Conséquences.** Le code testé en local tourne sur les mêmes versions majeures que le cluster. L'écart restant : pyspark 4.1.1 en local contre le Spark 4.1.0 de Databricks (qui est un fork maison). La même image pourra servir à la CI.

## ADR-002 — Cluster *Single user* et ADF

L'identité managée d'ADF n'est pas l'utilisateur assigné au cluster. Plan : tester d'abord avec l'identité managée en phase 5, et passer au fallback *Access token* dans Key Vault si c'est refusé.

## ADR-003 — Suites du benchmark : l'option la moins risquée à chaque fois (Jour 1)

**Contexte.** Le benchmark (`docs/benchmark.md`) posait 4 questions. Consigne : choisir l'option la moins risquée et approfondir plus tard.

**Décisions.**
1. **Nom :** on garde `olist-azure-lakehouse`, déjà utilisé dans tous les documents et dans le sujet OIDC (AZURE_SETUP.md étape 11). Le ML apparaît dans la description GitHub et dans le titre CV (« Pipeline Data & ML sur Azure »).
2. **ADF → Databricks :** pas de changement de plan. Phase 5 = activité *Notebook* sur le cluster existant, identité managée, puis fallback token (ADR-002). L'activité *Databricks Job* + job cluster sera essayée en phase 5 seulement si l'identité managée est refusée, et avant le token. Raison : c'est une activité plus récente, que nous n'avons pas encore testée, et elle impose d'éteindre le cluster interactif pendant le run (quota 6 vCPU).
3. **Power BI :** on garde `.pbix` + export PDF + captures + `measures.dax`. `.pbip` n'est pas adopté tant que son statut (preview ou GA) n'est pas vérifié dans Power BI Desktop.
4. **Ajouts au cahier des charges** (tous à faible coût) : lecture `multiLine` des avis + test des comptes (phase 1), contrôle paiements sans article + table `quarantine` (phase 2), contrôles Gold qui font échouer le run (phase 3), « Known gaps » et coûts réels dans le README (phase 9), serverless interdit (risques).

**Écarté pour l'instant.** `TIMESTAMP_NTZ` : la session est déjà figée en UTC dans `spark.py` (testé), et la lecture de `TIMESTAMP_NTZ` par le connecteur Power BI n'est pas vérifiée. Un test de phase 1 vérifie qu'aucune date ne se décale. À revoir si ce test échoue.

## ADR-004 — Bronze et défauts mesurés en phase 1 (Jour 1)

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

## ADR-005 — Règles Silver et contrôles qualité (Jour 1)

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

## ADR-006 — Gold : définition du retard et choix du modèle en étoile (Jour 1)

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

## ADR-007 — Databricks serverless : aucune VM utilisable sur l'abonnement (Jour 1)

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

**Premier run serverless (Jour 1)** : job `olist_pipeline` réussi de bout en bout. Mêmes chiffres qu'en local à l'unité près (Bronze = CSV, Silver 98 673 avis et 42 lignes en quarantaine, 16 `pass` / 7 `warn`, Gold 11/11 dont 6,77 %, 2,27, 4,29). Le code testé en Docker a tourné sur Databricks sans modification. La tâche Bronze a pris 4 min 14 s, contre ~47 s en local : démarrage du serverless en mode standard et écritures sur ADLS. Captures : `docs/screenshots/phase4_*.png`.

**Coût réel (Cost analysis, relevé au Jour 6)** : le run a coûté **0,22 USD** (service *Azure Databricks*, facturé au Jour 1 seulement, inchangé au Jour 6). Mais le cumul atteint **5,42 USD** au Jour 6, dont 4,67 USD de *NAT Gateway* et 0,52 USD de *Virtual Network* dans le groupe managé `databricks-rg-dbw-olist-*`, sans aucune exécution. Cause (Microsoft Learn, « Enable secure cluster connectivity ») : un workspace *Hybrid* créé avec le réseau par défaut active la connectivité sécurisée (No Public IP) et Databricks crée une NAT Gateway, facturée à l'heure, pour un calcul classique que l'abonnement ne peut pas lancer (ADR-007). Le *Virtual Network* est probablement l'IP publique de cette NAT Gateway *(déduit, non vérifié)*. Rythme mesuré : ~1 USD/jour, soit ~30 USD/mois, au-dessus du budget de 20 USD. Captures : `docs/screenshots/cost_daily_jour1.png`, `docs/screenshots/cost_cumulative_jour6.png`.
Version observée au premier run : le serverless exécute **Python 3.12** (chemin `/databricks/python/lib/python3.12/` dans un avertissement), comme l'image Docker. Avertissement attendu sans conséquence : `No Partition Defined for Window operation`, causé par les clés de substitution `row_number` globales (limite notée dans `gold.py`).

## ADR-008 — Orchestration ADF du job serverless (Jour 6)

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
- **Run complet du Jour 6** (`e7d35bfe-227f-4dda-811f-216d89fa2916`, *Trigger now*) : Get Metadata 11 s, Job 8 min 25 s, Copy 16 s, 9 CSV dans `landing/archive/<date du run>/`. Captures `docs/screenshots/phase5_*.png`. Coût du Jour 6 (Cost analysis, capture `docs/screenshots/cost_daily_jour6.png`) : *Azure Data Factory v2* **0,06 USD** ; *Azure Databricks* 1,60 USD pour la journée, qui regroupe ce run et le SQL warehouse de la phase 6 (ADR-009).
- Trigger `tr_daily` (quotidien) rattaché à `pl_olist_daily`, publié à l'état `Stopped` ; il passe `runDate = formatDateTime(trigger().scheduledTime, 'yyyy-MM-dd')`, la date prévue et non celle d'un éventuel redémarrage.

**Écarté.** Vérifier les noms des 9 fichiers au lieu de leur nombre (il faudrait un *ForEach* de *Get Metadata* `exists`) : le nombre suffit tant que `landing/olist` ne reçoit que la source Olist. Alerte e-mail sur échec (Azure Monitor) : le *Fail* et le Monitor d'ADF suffisent pour un projet de démonstration.

**Limite.** L'ID d'abonnement et l'ID de tenant figurent dans `adf/` (ressource du workspace, identité de la factory) : ce sont des identifiants, pas des secrets.

## ADR-009 — Power BI sur SQL warehouse, authentification par jeton (Jour 6)

**Contexte.** Phase 6 : Power BI Desktop doit lire `olist.gold.*` dans Databricks. Le compte Azure est un compte Microsoft personnel (gmail, annuaire par défaut `takieddineelattarigmail.onmicrosoft.com`). La connexion *Microsoft Entra ID* du connecteur Azure Databricks le refuse : « Vous ne pouvez pas vous connecter ici avec un compte personnel ».

**Décision.**
- Calcul : le **Serverless Starter Warehouse** déjà fourni par le workspace, réglé au minimum (2X-Small, arrêt après 5 min) plutôt qu'un nouveau warehouse, dont le défaut est X-Large.
- Mode **Import** : le warehouse ne tourne que pendant une actualisation. Constaté : il démarre à la connexion et s'arrête seul quelques minutes après (capture `docs/screenshots/phase6_sql_warehouse.png`).
- Authentification : **jeton d'accès personnel Databricks**, 30 jours, saisi uniquement dans Power BI Desktop (jamais dans Git ni dans `.env`), **révoqué en phase 9**.
- Bascule du `.pbix` en changeant seulement la source des 6 requêtes (Éditeur avancé) : relations, mesures et visuels conservés.

**Résultat.** Mêmes chiffres qu'avec les Parquet locaux : 6,77 % / 2,27 / 4,29 ; seule la source Azure Databricks reste dans le fichier (captures `powerbi/screenshots/phase6_*.png`).

**Options écartées.** Créer un utilisateur professionnel dans l'annuaire par défaut et lui donner les droits sur le workspace, `olist.gold` et le warehouse : propre (Entra ID, pas de jeton) mais plusieurs étapes de plus pour un livrable identique. Service principal en OAuth M2M : même coût de mise en place, et un secret client à gérer.

**Écart assumé avec « aucun secret ».** ADF et l'accès au stockage restent en identité managée ; seul le poste de BI utilise un jeton, à durée courte. En production : comptes professionnels et Entra ID (SSO), ou service principal.

**Coût.** Au Jour 6, *Azure Databricks* = 1,60 USD pour le job lancé par ADF et le warehouse réunis. Si le job coûte comme en phase 4 (0,22 USD, même code), le warehouse a coûté ~1,4 USD *(déduit, non séparé)* : plus que prévu pour un import de quelques minutes, peut-être parce qu'il a tourné à sa taille d'origine avant d'être réduit. Pour séparer : Cost analysis, regrouper par *Meter*. La NAT Gateway coûte 1,20 USD/jour (avec *Virtual Network*), plus que tout le calcul.

**Conséquence.** Pas de publication sur Power BI Service, qui demande un compte professionnel ou scolaire : le livrable reste `.pbix` + PDF + captures (ADR-003).

## ADR-010 — Modèle de retard : features au moment de l'achat, backtest glissant, MLflow (Jour 7)

**Cible et population.** `is_late` lu dans `gold.fact_orders` (au jour près, ADR-006), sur les commandes `delivered` avec date de livraison : la même population que `Late Rate %`. Une ligne par commande ; toutes les commandes sont scorées, y compris les non livrées.

**Features** (`src/olist/ml/features.py`), uniquement des informations connues au clic « acheter » :
- commande : délai promis (`estimated - purchase`), valeur, fret, ratio fret / valeur, nb d'articles et de vendeurs, poids et volume totaux, type de paiement, échéances, jour de semaine et heure ;
- géographie : état du client (adresse **de cette commande**, pas la dernière adresse de `dim_customer`), état du vendeur principal (article le plus cher), distance client-vendeur maximale (haversine sur la géolocalisation médiane) ;
- historique : pour le vendeur et pour l'axe état vendeur → état client, nombre de commandes **déjà livrées avant l'achat** et part en retard. Une commande achetée plus tôt mais encore en route n'est pas comptée : son issue était inconnue (testé dans `tests/test_ml_features.py`).
- Exclus : dates de livraison et de remise au transporteur, statut final, avis, tout agrégat sur toute la période.

**Protocole.** Test = commandes achetées à partir du 2018-06-01, lu seulement pour le rapport final. Avant : **backtest glissant** sur 8 mois (oct. 2017 → mai 2018) ; chaque mois est prédit par un modèle entraîné sur tout le passé. Champion = meilleur *lift* moyen (PR-AUC / taux de retard du mois, comparable entre mois), qui doit battre la règle de base. Le modèle final suit la même recette (entraîné sur tout ce qui précède le test) ; son seuil maximise le F1 sur les prédictions hors échantillon du backtest.

**Pourquoi pas la validation fixe prévue (avril-mai 2018).** Le taux de retard dérive fortement : 7,9 % sur l'entraînement (qui contient le pic de février-mars 2018), 5,5 % en avril-mai, 3,6 % sur le test. Sur une seule fenêtre de 2 mois, le classement des modèles s'inversait d'une variante à l'autre.

**Itérations, en toute transparence.** Le test a été regardé 4 fois pendant la mise au point : (1) avec `purchase_month` et une validation fixe : aucun modèle ne battait la règle en validation ; (2) mois remplacé par l'historique d'axe et le taux de retard des 30 derniers jours : meilleur en validation, pire au test ; (3) choix par backtest ; (4) modèle final aligné sur la recette du backtest. Chaque changement a une raison de protocole (le mois mémorise un choc propre à 2018 ; une fenêtre de validation unique est instable ; le modèle final doit suivre la recette évaluée), et le choix du champion n'utilise jamais le test. Le chiffre de test reste néanmoins légèrement optimiste.

**Résultats** (run local du Jour 7, 77 867 commandes avant le test, 18 603 en test, retard 3,6 %) :

| Modèle | Lift backtest (mois battant la règle) | PR-AUC test | ROC-AUC test | Précision / rappel test |
|---|---|---|---|---|
| Règle : km par jour promis | 1,84 | 0,050 | 0,500 | 3,9 % / 40,5 % |
| Régression logistique (pondérée) | 1,99 (6/8) | **0,074** | **0,702** | 6,2 % / 70,7 % |
| LightGBM | 2,20 (5/8) | 0,038 | 0,495 | 4,0 % / 26,9 % |
| LightGBM pondéré | 2,21 (5/8) | 0,038 | 0,500 | 3,9 % / 18,2 % |
| **LightGBM sans taux récent (champion)** | **2,25 (7/8)** | 0,056 | 0,538 | 4,9 % / 27,4 % |

Variables les plus utiles du champion (gain) : historique de l'axe (nombre 15 %, part en retard 14 %), état du client 14 %, délai promis 11 %, catégorie 8 %, distance 7 %.

**Lecture honnête.** Le champion bat la règle au test (0,056 contre 0,050), mais de peu : prédire un retard dès la commande reste difficile ici, parce que les retards viennent surtout de chocs de période (pic de février-mars 2018) que les données de commande ne voient pas. La régression logistique généralise mieux sur une période calme ; elle n'a pas été promue après coup, ce serait choisir sur le test. Production : signaux externes (calendrier des fêtes, capacité transporteurs, météo, grèves), réentraînement mensuel, suivi de la dérive.

**MLflow.** Expérience `/Shared/olist_late_delivery` sur Databricks (`olist_late_delivery` en local, dossier `mlruns/` ignoré par Git) ; 5 runs avec paramètres, métriques backtest et test, importance des variables. Modèle enregistré dans Unity Catalog `olist.ml.late_delivery`, alias `champion`, seuil en tag `threshold`. Le seuil n'est pas une probabilité calibrée commune à toutes les périodes : sur le test, il signale 20 % des commandes.

**Scoring.** `score.py` → `gold.fact_late_predictions` (`order_id`, `model_version`, `proba_late`, `predicted_late`, `dataset` = `fit` / `test` / `unlabeled`, `scored_at`). Power BI juge le modèle sur `dataset = "test"` uniquement.

**Environnement.** Serverless version 6, base standard + dépendance `lightgbm==4.6.0` (seule bibliothèque absente) ; Docker épinglé sur les mêmes versions (pandas 2.3.3, numpy 2.3.4, pyarrow 21.0.0, scikit-learn 1.7.2, lightgbm 4.6.0, mlflow-skinny 3.12.0) + `libgomp1` pour LightGBM.

**Premier run Databricks (Jour 7, job `olist_train`).** Réussi : 5 runs dans `/Shared/olist_late_delivery`, champion `lightgbm_no_recent` enregistré en `olist.ml.late_delivery` v1, alias `champion`, seuil 0,1314 identique au run local (même données, même graine : les métriques sont très probablement les mêmes, non relues une à une). Captures `docs/screenshots/phase7_*.png`.

**Scoring dans le pipeline (Jour 7).** Tâche `05_ml_score` ajoutée après `03_gold` dans le job `olist_pipeline` (même environnement). Run ADF `0399eb7d-8de9-40d8-8e32-be2ccbfd24ad` vert : job 14 min 35 s (contre 8 min 25 s sans scoring), archive 20 s. `fact_late_predictions` = mêmes chiffres qu'en local (fit 77 867, test 18 603 dont 20,2 % signalées, non étiquetées 2 971). Captures `docs/screenshots/phase7_adf_run_with_scoring.png`, `phase7_score_output.png`, `phase7_job_tasks.png`.

**Écarté pour l'instant.** Recherche d'hyperparamètres (à faire sur le backtest, jamais sur le test) ; SHAP ; graphiques de courbes PR dans MLflow (importance en JSON seulement) ; proximité des fêtes ; entraînement limité aux commandes déjà livrées à la date de coupure (le modèle final voit des retards de fin de période qu'on n'aurait pas encore connus).

## ADR-011 — CI GitHub Actions : lint + tests, sans déploiement (Jour 7)

**Décision.** Plan B du cahier des charges (phase 8) : `.github/workflows/ci.yml` lance `ruff check` puis `pytest` à chaque push sur `main` et à chaque pull request. Pas de `databricks bundle deploy` : il faudrait un service principal fédéré en OIDC (AZURE_SETUP étape 11), et un compte Microsoft personnel sur Azure for Students a peu de chances de pouvoir créer une app registration *(non vérifié, non tenté)*. Le job Databricks se met à jour par le Git folder (*Pull*).

**Même environnement qu'en local.** La CI construit l'image Docker du projet (`docker compose build`) au lieu d'installer Python et Java sur le runner : une seule définition des versions, alignée sur Databricks.

**Sans les données.** Les CSV Kaggle ne sont pas dans Git : les 10 tests qui lisent `data/raw` ou la Bronze locale se sautent d'eux-mêmes. Reproduit en local dans une copie sans `data/` : 19 passed, 10 skipped (29 passed avec les données).

**Ruff.** `ruff==0.17.0` dans `requirements.txt` (même outil en local et en CI). Règles explicites dans `pyproject.toml` (`E4`, `E7`, `E9`, `F`, `I`) : la 0.17 active par défaut beaucoup plus de règles que la 0.12, et une mise à jour ne doit pas changer silencieusement ce que la CI vérifie. Écarté : `EXE002` (faux positif du montage Windows, les fichiers sont en 100644 dans Git), `ISC`, `RUF` (style).

**Écarté.** Cache Docker entre les runs (la construction prend quelques minutes, acceptable pour un projet de démonstration) ; déploiement par Databricks Asset Bundle.

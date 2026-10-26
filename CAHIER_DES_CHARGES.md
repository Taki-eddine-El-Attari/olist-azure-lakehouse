# CAHIER DES CHARGES — Olist Lakehouse sur Azure (Data Engineering + BI + ML)

> Ce fichier sert aussi de **CLAUDE.md** de départ : copie-le à la racine du repo sous le nom `CLAUDE.md` (ou garde-le tel quel et crée un `CLAUDE.md` qui dit « Lis CAHIER_DES_CHARGES.md et AZURE_SETUP.md avant toute tâche »).
> Langue de travail : français pour la doc, anglais pour le code (noms de variables, tables, commits).

---

## 1. Contexte et objectif

**Pourquoi ce projet :** compléter un CV IA/ML (déjà fort en LLM/RAG) avec les compétences qui manquent dans les offres analysées : **Cloud, Azure, ETL, Spark/Databricks, Power BI, SQL analytique, statistiques, MLOps**.

**Ce que le projet doit prouver à un recruteur :**
1. Je sais construire un pipeline de données cloud de bout en bout (ingestion → nettoyage → modèle dimensionnel).
2. Je sais modéliser pour la BI (schéma en étoile) et produire un dashboard qui raconte une histoire.
3. Je sais entraîner, tracer et industrialiser un modèle ML sans fuite de données.
4. Je maîtrise les coûts et la sécurité (identités managées, pas de secret en clair, arrêt des ressources).

**Question métier centrale (le fil rouge) :**
> « Les retards de livraison détruisent la satisfaction client (note 2,57/5 contre 4,29/5). Où, pourquoi, et peut-on prédire un retard dès la commande ? »

---

## 2. Périmètre

### Dans le périmètre
- Lakehouse **ADLS Gen2** en couches **Bronze / Silver / Gold** (format **Delta**).
- Orchestration **Azure Data Factory**.
- Transformations **PySpark** sur **Azure Databricks** (cluster single node).
- Modèle en étoile Gold + **Power BI** (4 pages).
- Modèle ML **« retard de livraison »** (cible principale) entraîné dans Databricks, suivi **MLflow**, enregistré dans le registre de modèles, **scoring batch** écrit en Gold et affiché dans Power BI.
- Tests unitaires des fonctions de transformation + contrôles de qualité des données.
- (Option) **CI/CD GitHub Actions** : lint + tests, puis déploiement des notebooks/jobs (Databricks Asset Bundles).

### Hors périmètre (assumé, à dire en entretien)
- Endpoint de modèle temps réel (coût permanent, inutile pour un scoring batch).
- Streaming, IA générative, Docker comme livrable de déploiement (déjà couverts ailleurs sur le CV ou sans valeur ajoutée ici). Docker sert uniquement d'environnement de dev local (§7).
- Haute disponibilité, VNet injection, Private Endpoints (mentionnés comme « ce que je ferais en production »).

### Cible secondaire (seulement si le temps le permet)
- Prédiction d'**avis négatif (note ≤ 2)**, même pipeline de features.

---

## 3. Données

Source : dataset Kaggle « Brazilian E-Commerce Public Dataset by Olist ». **Les 9 fichiers sont présents** (customers et geolocation inclus).

| Fichier | Lignes | Clé | Rôle |
|---|---|---|---|
| olist_orders_dataset | 99 441 | order_id | commandes + dates (achat, approbation, expédition, livraison, estimée) |
| olist_order_items_dataset | 112 650 | order_id + order_item_id | lignes de commande, prix, fret, vendeur |
| olist_order_payments_dataset | 103 886 | order_id + payment_sequential | paiements (type, échéances) |
| olist_order_reviews_dataset | 99 224 | review_id (pas unique !) | note 1-5, commentaire PT (40 977) |
| olist_customers_dataset | 99 441 | customer_id | customer_unique_id, ville, état |
| olist_products_dataset | 32 951 | product_id | catégorie PT, poids, dimensions |
| olist_sellers_dataset | 3 095 | seller_id | ville, état |
| olist_geolocation_dataset | ~1 000 163 | zip_code_prefix (pas unique) | lat/lng par préfixe postal |
| product_category_name_translation | 71 | category PT | traduction EN |

**Défauts connus (à traiter en Silver, et à raconter en entretien) :**
- 2 965 commandes sans date de livraison (annulées, en cours, indisponibles).
- 610 produits sans catégorie → `unknown`.
- 2 catégories absentes de la traduction (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) → traduction manuelle.
- 814 `review_id` en double → dédoublonner (garder la plus récente par `order_id`).
- Geolocation : plusieurs lat/lng par préfixe → agréger (médiane) par `zip_code_prefix`.
- `customer_id` ≠ client réel : le vrai client est `customer_unique_id`.

**Faits à retrouver dans tes propres résultats (tests de non-régression de l'histoire) :**
- ~8,1 % des commandes livrées arrivent après la date estimée.
- Note moyenne ≈ 2,57 en retard vs ≈ 4,29 à l'heure.

---

## 4. Architecture cible

```
 CSV Kaggle (local)
      │  az storage fs directory upload
      ▼
┌──────────────────────── ADLS Gen2 (stolistXXXX, switzerlandnorth) ────────────────────────┐
│ landing/olist/*.csv ──ADF Copy──► bronze (Delta brut + métadonnées d'ingestion)            │
│                                     │ Databricks notebook 02_silver (PySpark)              │
│                                     ▼                                                      │
│                                   silver (Delta nettoyé, typé, dédoublonné, conformé)      │
│                                     │ Databricks notebook 03_gold                          │
│                                     ▼                                                      │
│                                   gold (schéma en étoile + dq_results + predictions)       │
└────────────────────────────────────────────────────────────────────────────────────────────┘
      ▲ orchestration : ADF pipeline pl_olist_daily (Copy → Silver → Gold → ML score)
      │
 Databricks : MLflow (expériences) + Unity Catalog (tables, modèle olist.ml.late_delivery)
      │
      ▼
 Power BI Desktop (connecteur Azure Databricks, mode Import) → .pbix + PDF
      ▲
 GitHub : code, notebooks, JSON ADF (Git integration), GitHub Actions (lint/tests/deploy)
```

Sécurité : identités managées partout (ADF → stockage, Access Connector Databricks → stockage, ADF → Databricks). Aucun secret dans Git. Détails : `AZURE_SETUP.md`.

---

## 5. Modèle de données Gold (schéma en étoile)

| Table | Grain | Colonnes principales |
|---|---|---|
| `fact_order_items` | 1 ligne de commande | order_id, order_item_id, product_key, seller_key, customer_key, purchase_date_key, price, freight_value |
| `fact_orders` | 1 commande | order_id, customer_key, purchase_date_key, order_status, nb_items, order_value, freight_total, payment_total, payment_type_main, installments_max, delivery_days, estimated_days, delay_days, **is_late**, review_score, is_negative_review |
| `dim_customer` | 1 customer_unique_id | customer_key, customer_unique_id, city, state, lat, lng |
| `dim_seller` | 1 vendeur | seller_key, seller_id, city, state, lat, lng |
| `dim_product` | 1 produit | product_key, product_id, category_pt, category_en, weight_g, volume_cm3 |
| `dim_date` | 1 jour | date_key (yyyymmdd), date, year, quarter, month, week, day_of_week, is_weekend, is_br_holiday (option) |
| `fact_late_predictions` | 1 commande scorée | order_id, model_version, proba_late, predicted_late, scored_at |
| `dq_results` | 1 contrôle × 1 run | run_id, table, check_name, failed_rows, status, run_ts |

Points de modélisation à savoir défendre :
- **Deux faits à grain différent** : les paiements et les avis sont au niveau commande, les prix au niveau article. Les mélanger dans une seule table double les montants.
- Clés de substitution (`*_key`) vs clés naturelles.
- `dim_customer` construite sur `customer_unique_id` (sinon chaque commande = un client).

---

## 6. Structure du repo

**Nom retenu :** repo GitHub `olist-azure-lakehouse` (public à la fin). Nom affiché sur le CV et le portfolio : **Olist Lakehouse — Pipeline Data & ML sur Azure**.

```
olist-azure-lakehouse/
├── CLAUDE.md                     # ce cahier des charges (ou pointeur vers lui)
├── AZURE_SETUP.md
├── README.md                     # vitrine : schéma, captures, résultats, comment reproduire
├── .gitignore                    # data/, .env, *.pbix lourds si besoin, .venv/
├── .env.example                  # noms de ressources, sans secret
├── pyproject.toml / requirements.txt
├── Dockerfile / docker-compose.yml  # env local aligné sur Databricks Runtime 18 LTS ML
├── data/
│   ├── raw/                      # 9 CSV (ignorés par Git)
│   └── lake/                     # lakehouse local bronze/silver/gold (ignoré par Git)
├── src/olist/
│   ├── config.py                 # chemins : local (data/lake) ou cloud (abfss:// ou catalogue UC)
│   ├── spark.py                  # get_spark() local (delta-spark) ou session Databricks
│   ├── bronze.py                 # ingestion CSV → Delta + colonnes _ingested_at, _source_file
│   ├── silver.py                 # une fonction pure par table : clean_orders(df), ...
│   ├── gold.py                   # build_dim_*, build_fact_*
│   ├── quality.py                # contrôles DQ → dq_results
│   └── ml/
│       ├── features.py           # features "au moment de l'achat" uniquement
│       ├── train.py              # entraînement + MLflow
│       └── score.py              # scoring batch → fact_late_predictions
├── notebooks/                    # fins wrappers Databricks qui appellent src/olist
│   ├── 01_bronze.py
│   ├── 02_silver.py
│   ├── 03_gold.py
│   ├── 04_ml_train.py
│   └── 05_ml_score.py
├── tests/                        # pytest + petits DataFrames d'exemple
├── sql/                          # requêtes d'analyse / vérifications
├── adf/                          # JSON exportés par l'intégration Git d'ADF
├── powerbi/
│   ├── olist.pbix
│   ├── measures.dax              # copie texte des mesures (lisible dans Git)
│   └── screenshots/
├── docs/
│   ├── architecture.png
│   ├── decisions.md              # journal des choix (ADR courts)
│   └── interview_notes.md
├── databricks.yml                # (option phase 8) Databricks Asset Bundle
└── .github/workflows/ci.yml      # (option phase 8)
```

Règle d'architecture du code : **la logique vit dans `src/olist` (testable en local), les notebooks ne font qu'appeler ces fonctions.** C'est ce qui rend le passage local → Databricks quasi gratuit et ce qui impressionne en entretien.

---

## 7. Environnement de développement local

**Choix retenu (phase 0) : conteneur Docker** (`Dockerfile` + `docker-compose.yml`), avec des versions alignées sur **Databricks Runtime 18 LTS ML** : Python 3.12, Java 21, `pyspark` 4.1.x, `delta-spark` 4.2.0. Ça évite `winutils` sous Windows et une distro WSL à maintenir, et la même image pourra servir à la CI (phase 8).

```bash
docker compose build              # une fois (et après chaque changement de requirements.txt)
docker compose run --rm dev pytest
docker compose run --rm dev python -m olist.bronze   # exemple pour la phase 1
```

- Le repo est monté dans `/workspace` : les écritures dans `data/lake/` passent par le partage Windows→Linux, ce qui est lent mais suffisant pour 100k lignes.
- **Power BI Desktop** (Windows) pour la maquette sur les fichiers Gold locaux.

Avec 100 000 commandes, **pandas suffit pour le ML** ; Spark sert au pipeline (compétence visée), pas à la taille des données. Sois honnête là-dessus en entretien : c'est un bon signe de maturité.

---

## 8. Phases, livrables et Definition of Done

Durée indicative : **5 semaines** à ~10 h/semaine. Chaque phase = une ou plusieurs sessions Claude Code dédiées (voir §11).

### Phase 0 — Cadrage et repo (½ jour)
- Créer le repo, `.gitignore`, `requirements.txt`, structure §6, `CLAUDE.md`, `.env.example`.
- Copier les 9 CSV dans `data/raw/`.
- Faire **les étapes 0 à 3 de AZURE_SETUP.md** (CLI, suivi du crédit, providers, quotas). Rien d'autre dans Azure.

**DoD :** repo poussé sur GitHub, `pytest` tourne (même avec 0 test), crédit et quotas vérifiés.

### Phase 1 — Exploration et Bronze en local (1-2 jours)
- Notebook/script d'EDA : volumes, nulls, doublons, distributions, vérifier les défauts du §3.
- `bronze.py` : lire chaque CSV avec un **schéma explicite**, ajouter `_ingested_at`, `_source_file`, écrire en Delta dans `data/lake/bronze/`.
- Les commentaires d'avis contiennent des retours à la ligne : lire avec `multiLine=True`, `quote='"'`, `escape='"'` (99 224 avis, pas 104 719 lignes physiques).
- Dates : garder `TimestampType` + session en UTC (déjà dans `spark.py`) ; un test vérifie qu'une date relue en Delta est identique à la chaîne du CSV.

**DoD :** 9 tables Bronze Delta ; un **test pytest** vérifie que comptes Bronze = comptes des CSV (dont reviews = 99 224, traduction = 71) ; `docs/decisions.md` contient les défauts trouvés.

### Phase 2 — Silver en local (2-3 jours)
- Une fonction pure par table : typage des dates, trim/lower des villes, dédoublonnage des reviews, catégorie `unknown` + traduction manquante ajoutée, geolocation agrégée par préfixe, `delivery_status` (`delivered` / `not_delivered`).
- `quality.py` : contrôles (unicité des clés, non-null des clés, intégrité référentielle items→orders/products/sellers, dates cohérentes `purchase ≤ approved ≤ delivered`, montants ≥ 0, commandes payées sans aucun article) → table `dq_results`.
- Les lignes invalides vont dans une table `quarantine` (ligne + règle violée) au lieu d'être supprimées en silence.
- Tests pytest sur chaque fonction de nettoyage avec 5-10 lignes d'exemple.

**DoD :** Silver écrit ; tous les tests passent ; `dq_results` sans échec bloquant ; les règles de nettoyage sont listées dans `docs/decisions.md`.

### Phase 3 — Gold + maquette Power BI en local (3-4 jours)
- `gold.py` : dims + faits du §5.
- Vérifications SQL (`sql/checks.sql`) : somme des prix Gold = somme Silver ; taux de retard ≈ 8,1 % ; notes 2,57 / 4,29. Un contrôle en échec **fait échouer le run** (exception), il ne se contente pas d'afficher.
- Power BI Desktop sur les fichiers Gold locaux : relations en étoile, mesures DAX de base.

**DoD :** les chiffres de l'histoire sont retrouvés ; le modèle Power BI a des relations 1-* propres (pas de bidirectionnel) ; 1 page de dashboard fonctionnelle.

> **Point d'arrêt honnête :** si tu es en retard, les phases 0-3 + une capture forment déjà un projet montrable. Le cloud vient après, sur du code qui marche.

### Phase 4 — Déploiement Azure : stockage + Databricks (2-3 jours)
- AZURE_SETUP.md étapes 4 à 8.
- `config.py` bascule sur les chemins Unity Catalog (`olist.bronze.*`, etc.).
- Synchroniser le repo dans Databricks (**Workspace → Git folders**), lancer 01 → 03 sur le cluster.

**DoD :** tables `olist.bronze/silver/gold.*` visibles dans Catalog Explorer ; mêmes chiffres qu'en local ; cluster terminé après la session ; coût de la session noté dans `docs/decisions.md`.

### Phase 5 — Orchestration Data Factory (1-2 jours)
- AZURE_SETUP.md étape 9 : linked services, pipeline `pl_olist_daily`, intégration Git.
- Paramétrer le pipeline (date de run, liste de fichiers) ; gérer l'échec (activité « on failure »).

**DoD :** un run complet **vert** de bout en bout depuis ADF (capture du monitoring) ; JSON du pipeline dans `adf/` sur GitHub ; trigger désactivé.

### Phase 6 — Power BI final (2-3 jours)
Connexion au cluster en mode Import (AZURE_SETUP.md étape 10). 4 pages :
1. **Vue d'ensemble** : CA, commandes, panier moyen, évolution mensuelle, carte par état.
2. **Logistique** : taux de retard par état client/vendeur, par catégorie, par mois ; délai réel vs estimé.
3. **Satisfaction** : note moyenne vs retard (le chiffre choc 2,57 vs 4,29), part d'avis négatifs.
4. **Prédictions** : commandes à risque, distribution des probabilités, performance du modèle (rappel/précision sur la période de test). *Dépend de la phase 7 : on la finalise après le ML.*

Mesures DAX minimales (à copier dans `powerbi/measures.dax`) : `Total Revenue`, `Orders`, `AOV`, `Late Rate %`, `Avg Review`, `Avg Review Late`, `Avg Review On Time`, `Revenue YoY %` (avec `dim_date` marquée comme table de dates), `Predicted Late Orders`.

**DoD :** `.pbix` + export PDF + 4 captures dans `powerbi/screenshots/` ; chaque page répond à une question écrite en titre.

### Phase 7 — Machine Learning + MLflow (4-5 jours)
**Cible :** `is_late = delivered_date > estimated_date`, sur les commandes livrées.

**Règle anti-fuite (non négociable) :** seules les informations connues **au moment de l'achat** sont autorisées.
- Autorisé : délai estimé (`estimated - purchase`), distance client-vendeur (geolocation), état client/vendeur, prix, fret, poids/volume, catégorie, nb d'articles, nb de vendeurs dans la commande, type de paiement, échéances, mois / jour de semaine / proximité des fêtes, **historique du vendeur calculé uniquement sur les commandes antérieures** (taux de retard passé).
- Interdit : date de livraison réelle, date de remise au transporteur, statut final, note d'avis, tout agrégat calculé sur toute la période.

**Méthode :**
- **Split temporel** (ex. train ≤ 2018-03, validation 2018-04/05, test ≥ 2018-06), jamais aléatoire.
- Baseline : règle simple (ex. délai estimé court + longue distance) et régression logistique.
- Modèle principal : LightGBM ou XGBoost (pandas/sklearn sur le driver suffit).
- Déséquilibre (~8 %) : `class_weight` / `scale_pos_weight`, choix du seuil sur la validation.
- Métriques : **PR-AUC** (principale), ROC-AUC, rappel à précision fixée, matrice de confusion ; importance des variables (SHAP si le temps le permet).
- **MLflow** : une expérience `/olist/late_delivery`, paramètres, métriques, artefacts (courbes PR, importance), modèle enregistré dans Unity Catalog `olist.ml.late_delivery` avec un alias `champion`.
- `score.py` : charge `models:/olist.ml.late_delivery@champion`, score les commandes, écrit `gold.fact_late_predictions`. Ajouté au pipeline ADF.

**DoD :** modèle > baseline sur le test en PR-AUC (chiffres réels notés dans le README, pas inventés) ; run MLflow comparant ≥ 3 modèles ; modèle enregistré avec alias ; table de prédictions alimentée par ADF ; page Power BI 4 à jour.

### Phase 8 (option) — CI/CD GitHub Actions (1-2 jours)
- `ci.yml` : sur PR → `ruff` + `pytest` (Spark local). Sur `main` → `databricks bundle deploy` (Databricks Asset Bundle qui définit un job 01→05).
- Authentification OIDC (AZURE_SETUP.md étape 11). Plan B si le tenant bloque : CI = lint + tests uniquement.

**DoD :** badge CI vert dans le README ; un commit sur `main` met à jour le job Databricks (ou CI test-only documenté).

### Phase 9 — Vitrine, captures, nettoyage (1 jour)
Captures à faire **avant** de supprimer quoi que ce soit :
- [ ] Resource group avec les ressources (portail)
- [ ] Conteneurs ADLS bronze/silver/gold
- [ ] Pipeline ADF + run vert dans Monitor
- [ ] Catalog Explorer Databricks (tables Gold, lineage si visible)
- [ ] Notebook Silver ou Gold exécuté
- [ ] Expérience MLflow (comparaison de runs) + modèle enregistré
- [ ] 4 pages Power BI
- [ ] Analyse de coût (Cost analysis ou crédit restant)

Puis : README final (schéma, captures, résultats, coûts réels, « Known gaps », « ce que je ferais en production / à 100× le volume »), nettoyage selon AZURE_SETUP.md étape 12.

**DoD :** README lisible en 2 minutes par un recruteur ; plus aucune ressource facturable active.

---

## 9. Budget et risques

| Risque | Probabilité | Impact | Parade |
|---|---|---|---|
| Cluster oublié allumé | moyenne | perte de crédit | auto-stop 15 min + Terminate manuel + suivi du crédit à chaque session |
| Calcul **serverless** Databricks utilisé par défaut | moyenne | ~35 USD en 3 jours constatés sur un autre projet Students | serverless interdit : notebooks et jobs toujours attachés au cluster single node (docs/benchmark.md, leçon 5) |
| Quota vCPU (6 / DSv2 4) | élevée si multi-nœud | cluster ne démarre pas | single node DS3_v2, ADF sur cluster existant, pas de SQL Warehouse |
| ADF (identité managée) refusé sur le cluster *Single user* | moyenne *(non vérifié)* | pipeline ADF en échec | fallback *Access token* Databricks dans Key Vault (AZURE_SETUP.md étape 9) |
| Unity Catalog indisponible | faible *(non vérifié)* | accès stockage | plan B secret scope (AZURE_SETUP.md étape 7) |
| Pas le droit de créer un service principal | moyenne *(non vérifié)* | CI/CD deploy | CI lint + tests seulement |
| Power BI Service sans licence | moyenne | partage en ligne | livrer .pbix + PDF + captures |
| Fuite de données dans le ML | élevée si on ne fait pas attention | résultats faux, entretien raté | §8 phase 7, split temporel, liste de features revue |
| Scope creep (GenAI, streaming...) | moyenne | projet jamais fini | hors périmètre §2 ; finir 0-7 avant toute option |

Budget estimé total : **15 à 35 USD** sur 100 USD *(estimation non vérifiée, dominée par les heures de cluster)*.

---

## 10. Valorisation CV et entretien

**Ligne de projet pour le CV (à ajuster avec tes vrais chiffres) :**
> **Olist Lakehouse — Pipeline Data & ML sur Azure** — Pipeline de données de bout en bout sur 100k commandes e-commerce : ingestion orchestrée par Azure Data Factory dans ADLS Gen2, architecture médaillon (Bronze/Silver/Gold) en PySpark/Delta Lake sur Azure Databricks, schéma en étoile et dashboard Power BI (DAX). Modèle de prédiction des retards de livraison (LightGBM, PR-AUC X vs baseline Y) tracé avec MLflow et scoré en batch. Identités managées, tests pytest, contrôles qualité, CI GitHub Actions, coût total < Z USD.

**Mots-clés couverts :** Azure, ADLS Gen2, Data Factory, Databricks, PySpark, Delta Lake, Unity Catalog, ETL/ELT, architecture médaillon, modélisation dimensionnelle, SQL, Power BI, DAX, MLflow, LightGBM, CI/CD, GitHub Actions.

**Questions d'entretien à préparer (réponses dans `docs/interview_notes.md`) :**
1. Pourquoi Bronze/Silver/Gold ? Qu'est-ce qui va dans chaque couche ?
2. Pourquoi Delta plutôt que Parquet ? (ACID, time travel, MERGE, schéma)
3. Comment as-tu évité de doubler les montants entre paiements et articles ?
4. Comment ADF s'authentifie au stockage et à Databricks ? Pourquoi pas de clé ?
5. Comment as-tu évité la fuite de données dans le modèle ? Pourquoi un split temporel ?
6. Pourquoi PR-AUC et pas accuracy avec 8 % de positifs ?
7. Pourquoi pas d'endpoint temps réel ? Quand en faudrait-il un ?
8. Comment as-tu contrôlé les coûts ? Qu'est-ce qui changerait en production (VNet, Private Endpoints, environnements dev/prod, monitoring) ?
9. Spark était-il nécessaire pour 100k lignes ? (Réponse honnête : non pour le volume, oui pour démontrer un pipeline qui passe à l'échelle.)
10. Qu'as-tu appris de la qualité des données (doublons de reviews, catégories manquantes) ?

---

## 11. Règles de travail pour Claude Code

- **Une session Claude Code par phase** (ou sous-phase). En début de session : « Lis CLAUDE.md, on travaille sur la phase N. » En fin de session : mettre à jour la section *Journal d'avancement* ci-dessous et commiter.
- Avant de coder une phase : relire sa DoD ; à la fin : vérifier chaque point de DoD avec une commande ou un test, pas « à l'œil ».
- Logique dans `src/olist`, notebooks fins. Fonctions pures et testées.
- Ne jamais commiter `data/`, `.env`, clés, tokens. Les noms de ressources vont dans `.env` (modèle dans `.env.example`).
- Ne rien inventer : chaque chiffre du README vient d'une exécution réelle (sortie de script, run MLflow).
- Toute action Azure qui crée une ressource facturable : la proposer, ne pas l'exécuter sans mon accord. Rappeler de terminer le cluster en fin de session.
- Commits courts en anglais, style conventionnel (`feat:`, `fix:`, `test:`, `docs:`).
- Région Azure : **toujours `switzerlandnorth`**.

---

## 12. Journal d'avancement (à tenir à jour)

| Date | Phase | Fait | Chiffres / coût | Prochaine étape |
|---|---|---|---|---|
| 2026-10-26 | 0 | Structure du repo, git init, image Docker (DBR 18 LTS ML), test Spark+Delta | `pytest` : 1 passed ; 0 USD | Azure CLI + étapes 0-3, commit, push GitHub |
| 2026-10-26 | 0 | Benchmark de 9 repos, décisions ADR-003 ; Azure CLI 2.91.0, login OK après `az login --tenant` (MFA) ; abonnement « Azure for Students » Enabled ; 7 providers enregistrés ; quotas switzerlandnorth vérifiés (6 régionaux, DSv2 4, DSv3 4) ; repo poussé sur GitHub ; budget mensuel 20 USD créé dans le portail (alertes 50/80/100 %), mais pas visible par l'API au niveau abonnement (périmètre à confirmer) ; `pytest` : 1 passed. **Phase 0 terminée.** | 0 USD | Phase 1 : EDA + Bronze en local |

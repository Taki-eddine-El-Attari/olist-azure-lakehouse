# Benchmark — 9 projets GitHub « Olist + Azure Lakehouse » (2026-10-26)

**Méthode :** lecture des README via l'API GitHub (pas du code, pas des notebooks). Ce que les README affirment (« fail fast », « tests »…) **n'est pas vérifié**. Aucun des 9 repos n'a d'étoile.

## 1. Vue d'ensemble

| Repo | Dernier push | Niveau | Points notables | ML ? |
|---|---|---|---|---|
| **BDhabekar/olist-azure-lakehouse** | 2026-10 | ⭐ très abouti | SQL Server on-prem → ADF (self-hosted IR, incrémental par watermark) → Databricks Job (SQL) → UC ; dev + prod, CI/CD Azure DevOps, alerte Azure Monitor, 13 contrôles de réconciliation Gold, `.pbip` dans Git, coûts chiffrés, « Known gaps » assumés | non |
| mukutarmanekka/Olist-Azure-Lakehouse-ELT | 2026-09 | bon, notebooks | Multi-source (GitHub HTTP, MySQL, MongoDB), table de quarantaine, 5 tables Gold « analytics » (pas vraiment une étoile), 2 dashboards Power BI | non |
| durgesh-plum/olist-azure-lakehouse | 2026-01 | moyen | ADF piloté par config (Lookup + ForEach), MERGE en Silver, étoile 6 dims / 2 faits, Power BI via SQL Warehouse | non |
| hruday-45/Olist-Azure-Medallion-Lakehouse | 2026-04 | moyen | SCD Type 2, pipelines ADF imbriqués, alerte e-mail via Logic App, MERGE partout | non |
| zohaibshahzadTO/azure-olist-lakehouse | 2026-10 | squelette | Terraform, `src/olist/transforms.py` + tests unitaires, Grafana, CI GitHub Actions (plan, contenu non vérifié) | non |
| varshaburra10/Azure-Lakehouse-Project-Olist | 2026-06 | en cours | Ingestion ADF seulement, Silver/Gold « planned » | non |
| galo-coder/azure-lakehouse-olist | 2025-08 | jour 1 | Squelette + diagramme | non |
| ishan-databricks/olist-azure-data-lakehouse | 2026-03 | vide | README d'une ligne | non |
| SalmaTAMMARI12/azure-olist-lakehouse | 2026-09 | vide | Titre seul | non |

**Constat principal :** le sujet « Olist + ADF + Databricks + Power BI » est **saturé**, et deux repos portent déjà exactement le nom `olist-azure-lakehouse`. **Aucun des 9 ne fait de ML.** Un seul (BDhabekar) donne des chiffres réels et des coûts.

## 2. Leçons concrètes (vérifiées sur nos données quand c'est possible)

1. **Les avis contiennent des retours à la ligne.** Vérifié sur notre CSV : `olist_order_reviews_dataset.csv` = **99 224 enregistrements** mais **104 719 lignes physiques**. mukutarmanekka annonce 104 719 lignes : c'est le symptôme d'un mauvais parsing. → En phase 1 : `multiLine=True`, `quote='"'`, `escape='"'`, puis test du compte = 99 224.
2. **Catégories :** notre fichier de traduction a **71 enregistrements** (vérifié). mukutarmanekka annonce 70 : c'est une autre erreur de comptage. → Les comptes Bronze = comptes CSV doivent être un test, pas un coup d'œil (déjà dans la DoD de la phase 1).
3. **Fuseau horaire :** BDhabekar montre qu'un `TIMESTAMP` décale une livraison d'un jour selon le fuseau de la session ; `TIMESTAMP_NTZ` corrige le problème. Aujourd'hui on fige la session en UTC ([spark.py](../src/olist/spark.py)). → **À adopter :** typer les dates en `TimestampNTZType` dans les schémas explicites de Bronze. C'est plus robuste, y compris côté Power BI.
4. **Paiements > valeur des commandes :** BDhabekar mesure un écart de 122 510 BRL, dû surtout à 622 commandes payées sans aucune ligne d'article. → Ajouter ce contrôle dans `quality.py` (phase 2) et le raconter. C'est le même piège que celui du §5 sur le double comptage.
5. **Coût :** BDhabekar (lui aussi sur Azure for Students) a dépensé **~35 USD en 3 jours** en développant sur du **calcul serverless interactif**. → Interdire le serverless pour nous : à ajouter aux risques.
6. **ADF → Databricks :** BDhabekar utilise l'activité ADF *Databricks Job* (un job qui enchaîne les 3 étapes) avec l'**identité managée** d'ADF, et le job s'exécute sur un **job cluster** single node créé pour le run. Ça répond à notre risque ADR-002 (cluster *Single user*) **sans token**, et le DBU « Jobs » coûte moins cher que le DBU « All-Purpose » *(tarifs à vérifier)*. Contrainte quota : le cluster interactif doit être éteint pendant le run (4 + 4 vCPU > 6).
7. **Power BI dans Git :** format `.pbip` (texte, diffable) plutôt que `.pbix` (binaire, contient les données).
8. **Quarantaine :** 2 repos isolent les lignes invalides dans une table `quarantine` (avec la règle violée) au lieu de les supprimer ou de faire échouer tout le chargement. C'est complémentaire de notre `dq_results`.

## 3. Idées : à reprendre, à discuter, à rejeter

| Idée | Source | Avis | Coût en temps |
|---|---|---|---|
| `multiLine` + test des comptes | leçons 1-2 | **reprendre** (phase 1) | faible |
| `TIMESTAMP_NTZ` | BDhabekar | **reprendre** (phase 1) | faible |
| Contrôle paiements vs articles | BDhabekar | **reprendre** (phase 2) | faible |
| Table de quarantaine | mukutar, BDhabekar | **reprendre** (phase 2), simple | faible |
| Contrôles de réconciliation Gold qui font échouer le run | BDhabekar | **reprendre** : on a déjà `sql/checks.sql`, il suffit de le faire lever une erreur | faible |
| ADF → *Databricks Job* + job cluster | BDhabekar | **à discuter** : remplace « 1 activité Notebook par étape » et le token | moyen |
| `.pbip` au lieu de `.pbix` | BDhabekar | **à discuter** : format en preview dans Power BI Desktop *(à vérifier)* | faible |
| Section README « Known gaps » + « ce qui change à 100× » | BDhabekar | **reprendre** (phase 9) : très bon signal de maturité | faible |
| Ingestion incrémentale (watermark, MERGE) | BDhabekar, durgesh | **rejeter** : notre source est un snapshot statique, l'incrémental serait simulé | élevé |
| SCD Type 2 | hruday | **rejeter** : sans changements à la source, l'historisation est vide (on peut l'expliquer en entretien) | moyen |
| dev + prod, Azure DevOps, Bicep/Terraform | BDhabekar, zohaib | **rejeter** : double le coût et le temps ; garder en « ce que je ferais en production » | élevé |
| Multi-source MySQL/MongoDB | mukutar | **rejeter** : artificiel, et ajoute des ressources payantes | moyen |
| SQL Warehouse pour Power BI | durgesh | **rejeter** : quota vCPU et coût ; Import depuis le cluster suffit | — |

## 4. Notre différenciation (ce qu'aucun des 9 ne fait)

1. **Une question métier** au lieu d'une démo d'outils : « les retards détruisent la satisfaction (2,57 vs 4,29), peut-on les prédire ? »
2. **Le ML en bout de chaîne :** modèle de retard **sans fuite** (features connues à l'achat, split temporel), MLflow, registre UC, scoring batch dans le pipeline, page Power BI dédiée.
3. **Code testable :** logique dans `src/olist` + pytest dans un Docker aligné sur le runtime. Un seul autre repo l'annonce (zohaib), sans contenu vérifiable.
4. **Chiffres réels et coûts** dans le README. Seul BDhabekar le fait ; c'est la barre à atteindre.

## 5. Points à discuter

1. **Le nom.** `olist-azure-lakehouse` existe déjà 2 fois et décrit exactement ce que font les 9 autres. Notre vrai différenciateur (le ML sur les retards) n'apparaît pas dans le nom. Option : garder `olist-azure-lakehouse` (mots-clés) mais mettre le ML dans la description GitHub et dans le titre CV, ou passer à `olist-lakehouse-late-delivery-ml`.
2. **ADF → Databricks Job (leçon 6)** : on l'adopte dès maintenant dans le plan des phases 5 et 8 ?
3. **`.pbip`** : OK pour versionner le rapport en texte ?
4. On ajoute les « reprendre » des §2-3 au cahier des charges (phases 1, 2, 9) ?

**Réponses (2026-10-26) :** option la moins risquée retenue à chaque fois, détail dans [ADR-003](decisions.md). 1 : nom gardé. 2 : plan inchangé, *Databricks Job* gardé en plan B de phase 5. 3 : `.pbix` gardé. 4 : oui, ajoutés au cahier des charges, sauf `TIMESTAMP_NTZ` (reporté).

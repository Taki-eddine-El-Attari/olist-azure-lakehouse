# AZURE_SETUP.md — Configuration Azure pour le projet Olist

> Compte : **Azure for Students** (100 USD, expire le 25/10/2027).
> Région unique : **switzerlandnorth** (autorisée par la policy du compte).
> **Calcul : Databricks serverless uniquement** (ADR-007). L'abonnement ne peut lancer aucune VM dans les régions où Databricks existe : pas de cluster classique.
> Règle d'or : **ne rien créer dans Azure avant que le pipeline marche en local** (voir CAHIER_DES_CHARGES.md, phases 0 à 3).
> Les prix et limites marqués *(non vérifié)* sont des ordres de grandeur, à confirmer dans le portail ou sur la calculatrice de prix Azure le jour où tu crées la ressource.

---

## Ordre des étapes (résumé)

| # | Étape | Quand | Coût si oubliée allumée |
|---|---|---|---|
| 0 | Installer Azure CLI + extensions | Jour 1 | 0 |
| 1 | Alerte de budget / suivi du crédit | Jour 1, **avant tout** | 0 |
| 2 | Enregistrer les resource providers | Jour 1 | 0 |
| 3 | Vérifier les quotas vCPU | Jour 1 | 0 |
| 4 | Resource group `rg-olist` | Début phase 4 | 0 |
| 5 | Storage ADLS Gen2 + conteneurs + upload CSV | Phase 4 | quelques centimes/mois |
| 6 | Workspace Azure Databricks (Premium) | Phase 4 | 0 tant que rien ne s'exécute |
| 7 | Access Connector + Unity Catalog (catalogue, schémas, volume) | Phase 4 | 0 |
| 8 | Job serverless 01 → 03 | Phase 4 | **le poste principal** (payé à l'exécution) |
| 9 | Azure Data Factory + linked services | Phase 5 | faible (paiement à l'exécution) |
| 10 | Connexion Power BI | Phase 6 | 0 (Desktop gratuit) |
| 11 | (Option) Service principal pour GitHub Actions | Phase 8 | 0 |
| 12 | Nettoyage final | Après les captures | — |

---

## 0. Outils locaux

- [ ] Installer **Azure CLI** : https://learn.microsoft.com/cli/azure/install-azure-cli
- [ ] Se connecter et vérifier l'abonnement :

```bash
az login
az account list -o table
az account set --subscription "<nom ou id de l'abonnement Azure for Students>"
az account show -o table
```

> Si `az login` répond `AADSTS50076` puis « No subscriptions found » : Azure exige la MFA pour la gestion des ressources, et le premier login n'a pas fait passer l'étape MFA. Relancer en ciblant le tenant affiché dans l'erreur : `az login --tenant <TENANT_ID>`. Si la fenêtre Windows de choix de compte bloque : `az config set core.enable_broker_on_windows=false`, puis relancer (connexion par le navigateur). Plan B sans installation : **Cloud Shell** dans le portail (déjà connecté).

- [ ] Ajouter les extensions CLI utilisées plus bas :

```bash
az extension add --name databricks
az extension add --name datafactory
```

- [ ] (Phase 4+) Installer **Databricks CLI** (nouvelle version, binaire `databricks`) : https://docs.databricks.com/dev-tools/cli/install.html

Variables réutilisées dans toutes les commandes (Bash / Git Bash) :

```bash
export LOC=switzerlandnorth
export RG=rg-olist
export SA=stolist$RANDOM          # nom unique, 3-24 caractères minuscules/chiffres. Note-le !
export DBW=dbw-olist
export ADF=adf-olist-$RANDOM      # doit être unique globalement
export ME=$(az ad signed-in-user show --query id -o tsv)
echo $SA $ADF                     # copie ces valeurs dans un fichier .env local (jamais dans Git)
```

> Sous PowerShell, remplace `export X=...` par `$X = "..."` et `$RANDOM` par `Get-Random`.

---

## 1. Surveiller le crédit (avant toute ressource)

Les abonnements « sponsorship » comme Azure for Students n'ont **pas toujours accès aux budgets Cost Management** *(non vérifié pour ton compte)*. Essaie dans cet ordre :

- [ ] **Portail → Cost Management → Budgets → + Ajouter** : budget mensuel **20 USD**, alertes à 50 %, 80 %, 100 % vers ton e-mail.
- [ ] Si l'option est grisée : **Portail → Education** (ou https://www.microsoftazuresponsorships.com/balance) pour voir le crédit restant. Mets un rappel calendrier pour le consulter à chaque fin de session de travail.
- [ ] Bon à savoir : avec Azure for Students, quand le crédit est épuisé les ressources sont **suspendues**, pas facturées sur une carte (tu n'en as pas donné). Le risque réel est donc de **perdre le crédit**, pas de l'argent. *(Comportement documenté par Microsoft, à reconfirmer sur la page de ton offre.)*

Tentative en CLI (peut échouer sur un abonnement Students, ce n'est pas grave) :

```bash
az consumption budget create \
  --budget-name budget-olist --amount 20 --category cost --time-grain monthly \
  --start-date 2026-11-01 --end-date 2027-10-01
```

---

## 2. Enregistrer les resource providers

`Microsoft.Compute` est déjà enregistré. Il reste :

```bash
for p in Microsoft.Storage Microsoft.Databricks Microsoft.DataFactory Microsoft.Network Microsoft.ManagedIdentity Microsoft.KeyVault; do
  az provider register --namespace $p
done
# Vérifier (attendre "Registered", 1 à 5 min)
az provider list --query "[?namespace=='Microsoft.Storage' || namespace=='Microsoft.Databricks' || namespace=='Microsoft.DataFactory' || namespace=='Microsoft.Network'].{ns:namespace,state:registrationState}" -o table
```

Portail : **Abonnements → ton abonnement → Fournisseurs de ressources → rechercher → Inscrire**.

---

## 3. Quotas et tailles de VM (constaté le 2026-10-26)

Un quota n'est pas une autorisation : `az vm list-usage` montre des quotas (6 vCPU régionaux, DSv2 = 4…), mais `az vm list-skus` montre que **presque toutes les tailles sont `NotAvailableForSubscription`** sur ce compte.

| Région autorisée (policy) | Databricks proposé | VM 4 vCPU utilisable |
|---|---|---|
| switzerlandnorth | oui | **aucune** |
| norwayeast | oui | **aucune** |
| austriaeast | non | DS3_v2_Promo… |
| denmarkeast | non | DS3_v2… |
| polandcentral | non | aucune |

Conséquence : **aucun cluster Databricks classique possible**. On utilise le **calcul serverless** (les machines tournent dans l'abonnement Databricks, pas le nôtre), supporté en switzerlandnorth d'après la page « Features with limited regional availability » de Microsoft Learn (mise à jour le 2026-10-21). Voir ADR-007.

```powershell
# Revérifier une taille dans une région (restrictions vides = utilisable)
az vm list-skus --location switzerlandnorth --size Standard_DS3_v2 --all --query "[].{name:name, r:restrictions[].reasonCode}" -o table
```

---

## 4. Resource group

```bash
az group create --name $RG --location $LOC --tags projet=olist owner=taki
```

Tout le projet va dans ce groupe : le supprimer en fin de projet supprime tout (sauf le groupe managé Databricks, supprimé avec le workspace).

---

## 5. Stockage ADLS Gen2 (Bronze / Silver / Gold)

```bash
az storage account create -n $SA -g $RG -l $LOC \
  --sku Standard_LRS --kind StorageV2 --hns true \
  --min-tls-version TLS1_2 --allow-blob-public-access false

# Te donner le droit de lire/écrire les données (le rôle "Owner" ne suffit PAS pour les données)
SA_ID=$(az storage account show -n $SA -g $RG --query id -o tsv)
az role assignment create --assignee $ME --role "Storage Blob Data Contributor" --scope $SA_ID
# attendre ~2 min que le rôle se propage

for c in landing bronze silver gold; do
  az storage fs create -n $c --account-name $SA --auth-mode login
done

# Upload des 9 CSV dans landing/olist/
az storage fs directory upload -f landing --account-name $SA --auth-mode login \
  -s "./data/raw/*" -d olist --recursive
az storage fs file list -f landing --account-name $SA --auth-mode login -o table
```

- `--hns true` = espace de noms hiérarchique = **ADLS Gen2** (point clé en entretien).
- `landing` reçoit les CSV bruts ; ADF les copie dans `bronze` (étape 9). Si tu veux simplifier, ADF peut aussi lire `landing` et écrire du Parquet/Delta en Bronze.
- Coût : ~150 Mo de CSV + quelques Delta → **quelques centimes par mois** *(non vérifié, ordre de grandeur LRS Hot)*.

DoD : `az storage fs file list` montre les 9 CSV.

---

## 6. Workspace Azure Databricks

**Pricing tier :** **Premium** (nécessaire pour Unity Catalog et le serverless). **Pas de Trial** : il offre des DBU sur le calcul classique, que l'on ne peut pas utiliser ici *(non vérifié pour le serverless)*.

> Ne crée le workspace « Trial » que le jour où tu es prêt à travailler dessus, sinon les 14 jours filent pour rien.

```bash
# Hybrid (défaut) et pas Serverless : le mode Serverless n'accepte pas d'Access Connector (référence az CLI)
az databricks workspace create -g $RG -n $DBW -l $LOC --sku premium --compute-mode Hybrid --tags projet=olist
az databricks workspace show -g $RG -n $DBW --query workspaceUrl -o tsv
```

Portail : **Créer une ressource → Azure Databricks → RG `rg-olist`, région Switzerland North, tier Premium/Trial → Mise en réseau : laisser par défaut (pas de VNet injection) → Créer.**

Ce que ça crée en plus : un groupe managé `databricks-rg-dbw-olist-...` (ne le modifie pas). Le workspace seul ne coûte rien ; seules les exécutions serverless coûtent.

---

## 7. Accès Databricks → ADLS (Unity Catalog, sans clé ni secret)

1. Créer l'**Access Connector** (identité managée) :

```bash
az databricks access-connector create -g $RG -n ac-olist -l $LOC --identity-type SystemAssigned
AC_PID=$(az databricks access-connector show -g $RG -n ac-olist --query identity.principalId -o tsv)
AC_ID=$(az databricks access-connector show -g $RG -n ac-olist --query id -o tsv)
az role assignment create --assignee-object-id $AC_PID --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope $SA_ID
echo $AC_ID   # à coller dans Databricks
```

2. Dans Databricks (UI) :
   - [ ] Vérifier que le workspace a un **metastore Unity Catalog** (Catalog Explorer). Les nouveaux workspaces Premium sont normalement activés automatiquement *(non vérifié pour ta région)*.
   - [ ] **Catalog → External data → Credentials → Create credential** : type *Azure Managed Identity*, coller `$AC_ID`. Nom : `cred_olist`.
   - [ ] **External locations → Create** : une par conteneur, URL `abfss://bronze@<SA>.dfs.core.windows.net/` (idem `landing`, `silver`, `gold`), credential `cred_olist`. Cliquer **Test connection**.
   - [ ] Créer, **depuis Catalog Explorer** (aucun calcul nécessaire, donc 0 €) :
     - catalogue `olist` ;
     - schémas `bronze`, `silver`, `gold` avec comme emplacement de stockage l'external location du conteneur du même nom, et `ml` ;
     - schéma `landing` et, dedans, un **volume externe** `raw` sur `abfss://landing@<SA>.dfs.core.windows.net/olist` (le sous-dossier des CSV, pas la racine du conteneur). Le code lit les CSV dans `/Volumes/olist/landing/raw/` (`src/olist/config.py`), donc le nom du compte de stockage n'est jamais dans le code.

   Équivalent SQL (si on dispose déjà d'un calcul) :

```sql
CREATE CATALOG IF NOT EXISTS olist;
CREATE SCHEMA IF NOT EXISTS olist.bronze  MANAGED LOCATION 'abfss://bronze@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.silver  MANAGED LOCATION 'abfss://silver@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.gold    MANAGED LOCATION 'abfss://gold@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.ml;
CREATE SCHEMA IF NOT EXISTS olist.landing;
CREATE EXTERNAL VOLUME IF NOT EXISTS olist.landing.raw LOCATION 'abfss://landing@<SA>.dfs.core.windows.net/olist';
```

**Plan B** si Unity Catalog n'est pas disponible : clé du compte de stockage dans un **Databricks secret scope** + `spark.conf.set("fs.azure.account.key.<SA>.dfs.core.windows.net", dbutils.secrets.get(...))`. Moins propre, mais fonctionne. Ne jamais mettre la clé en clair dans un notebook ou dans Git.

---

## 8. Exécution serverless (le seul poste de coût important)

Pas de cluster (étape 3). Le code s'exécute en **Job** sur le calcul serverless.

1. **Workspace → Git folders → Create** : URL du repo GitHub, branche `main`. Les notebooks `notebooks/01_bronze`, `02_silver`, `03_gold` y apparaissent.
2. **Jobs & Pipelines → Create job** `olist_pipeline`, 3 tâches de type *Notebook*, source *Workspace* (le Git folder), calcul **Serverless**, dépendances 01 → 02 → 03.
3. Dans les réglages du job : **Performance optimized = désactivé** (mode standard, moins cher, démarrage plus lent) *(option à confirmer dans l'interface)*.
4. **Run now**, une fois. Vérifier les tables dans Catalog Explorer, puis le coût (étape 1, et `system.billing.usage` si accessible).

Règles :
- [ ] **Jamais de développement interactif sur serverless** : le code est développé et testé en local (Docker), le cloud ne fait qu'exécuter du code qui marche. C'est l'erreur à ~35 USD en 3 jours vue dans le benchmark.
- [ ] Un notebook attaché au serverless facture tant qu'il est actif : le détacher après usage.
- [ ] Noter le coût de chaque run dans le journal d'avancement.

## 9. Azure Data Factory

Pas de cluster (ADR-007) : ADF lance le job serverless `olist_pipeline` avec l'activité **Job** d'Azure Databricks (type JSON `DatabricksJob`), qui « tourne automatiquement sur serverless » d'après Microsoft Learn (« Transform data with Databricks Job »).

### Bloc A — factory et rôles (fait le 2026-10-26)

```bash
az datafactory create -g $RG -n $ADF -l $LOC
ADF_PID=$(az datafactory show -g $RG -n $ADF --query identity.principalId -o tsv)

# Données : uniquement le conteneur landing (lecture des CSV + archive)
az role assignment create --assignee-object-id $ADF_PID --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$SA_ID/blobServices/default/containers/landing"

# Databricks : Contributor sur le seul workspace
DBW_ID=$(az databricks workspace show -g $RG -n $DBW --query id -o tsv)
az role assignment create --assignee-object-id $ADF_PID --assignee-principal-type ServicePrincipal \
  --role "Contributor" --scope $DBW_ID
```

Le rôle Contributor sur le workspace fait de l'identité d'ADF un administrateur du workspace à sa première connexion. Le job s'exécute avec l'identité *Run as* du job (toi), donc ADF n'a besoin d'aucun droit Unity Catalog *(déduit du fonctionnement des jobs, à confirmer au premier run)*.

### Bloc B — ADF Studio (portail → `adf-olist-42747` → *Launch studio*)

Ordre important : **Git d'abord**, pour que chaque objet créé ensuite soit commité dans `/adf`.

**1. Manage → Git configuration → Configure**
- Type *GitHub*, compte `Taki-eddine-El-Attari`, repo `olist-azure-lakehouse`.
- Collaboration branch `main`, publish branch `adf_publish`, root folder `/adf`.
- *Import existing resources* : oui (vers `main`).
- Chaque **Save all** fait un commit sur `main` dans GitHub : faire `git pull` en local ensuite.

**2. Manage → Linked services → New**
- `ls_adls` : *Azure Data Lake Storage Gen2* ; authentification *System-assigned managed identity* ; URL `https://<SA>.dfs.core.windows.net`. *Test connection* : choisir **To file path** → `landing/olist` (le rôle ne couvre que le conteneur `landing`, un test à la racine du compte peut échouer).
- `ls_databricks` : *Azure Databricks* ; workspace choisi *From Azure subscription* (`dbw-olist`) ; authentification *Managed service identity* ; cluster : **Serverless**. **Ne pas cliquer sur *Test connection*** : il échoue toujours avec `27001 ... Cluster Serverless does not exist` (le test cherche un cluster interactif portant ce nom). Cliquer directement **Create** ; le vrai test est le run du job (constaté le 2026-10-31).

**3. Author → Datasets → New → ADLS Gen2 → Binary** : `ds_landing`
- Linked service `ls_adls` ; paramètre `folder` (String).
- File path : file system `landing`, directory `@dataset().folder`, fichier vide.

**4. Author → Pipelines → New** : `pl_olist_daily`
- Paramètres : `runDate` (String, vide = date du déclenchement), `expectedFileCount` (Int, `9`).
- Activités :

| # | Activité | Nom | Réglages | Lien |
|---|---|---|---|---|
| 1 | Get Metadata | `Check landing files` | dataset `ds_landing`, folder `olist` ; field list : *Child items* | — |
| 2 | If Condition | `Files present` | expression ci-dessous ; **False** : une activité *Fail* `Missing files` (message ci-dessous, code `MISSING_FILES`) ; **True** : vide | succès de 1 |
| 3 | Job (Azure Databricks) | `Run olist_pipeline` | linked service `ls_databricks` ; *Settings* → job `olist_pipeline` | succès de 2 |
| 4 | Copy data | `Archive CSVs` | source `ds_landing` folder `olist`, *Wildcard file path* `*.csv` ; sink `ds_landing` folder = expression archive | succès de 3 |
| 5 | Fail | `Job failed` | message ci-dessous, code `JOB_FAILED` | **échec** de 3 |

Expressions :

```text
Files present (If)  : @equals(length(activity('Check landing files').output.childItems), pipeline().parameters.expectedFileCount)
Missing files (Fail): @concat('Expected ', string(pipeline().parameters.expectedFileCount), ' files in landing/olist, found ', string(length(activity('Check landing files').output.childItems)))
Archive folder      : @concat('archive/', if(empty(pipeline().parameters.runDate), formatDateTime(pipeline().TriggerTime, 'yyyy-MM-dd'), pipeline().parameters.runDate))
Job failed (Fail)   : @activity('Run olist_pipeline').error.message
```

Le chemin d'échec 5 relance l'erreur avec un message lisible : sans activité *Fail*, un chemin « on failure » qui réussit rendrait le run vert.

**5. Debug sans coût Databricks**
- Clic droit sur `Run olist_pipeline` → *Deactivate* (état *Mark as succeeded*), puis **Debug**. Vérifie Get Metadata (9 fichiers), la condition et la copie dans `landing/archive/<date>/`.
- Réactiver l'activité.

**6. Publish**, puis **Add trigger → Trigger now** : un seul run complet (~0,22 USD de serverless, mesuré en phase 4). Capture : *Monitor → Pipeline runs* (run vert) et le détail des activités.

**7. Trigger planifié pour la démo** : dans le pipeline, *Add trigger → New/Edit* → `tr_daily` (Schedule, 1 jour), **Status = Stopped** ; dans *Trigger Run Parameters*, `runDate` = `@formatDateTime(trigger().scheduledTime, 'yyyy-MM-dd')` (sans valeur, le Publish échoue : « Parameter 'runDate' has no default value »), puis Publish. Le créer depuis le pipeline le rattache à `pl_olist_daily` ; créé depuis *Manage → Triggers*, il n'est lié à aucun pipeline (`"pipelines": []` dans le JSON). Un trigger actif relance le job chaque jour.

**8. En local** : `git pull`, pour récupérer `adf/` (pipeline, dataset, linked services, trigger) ; aucun secret n'y figure, l'authentification étant par identité managée.

Coût : orchestration ADF négligeable pour quelques runs *(non vérifié)* ; le vrai coût d'un run est le job serverless.

---

## 10. Power BI

> ⚠️ **À réviser en phase 6 (ADR-007)** : pas de cluster. La connexion se fera sur un **SQL warehouse serverless** (2X-Small, arrêt auto court), en mode Import.

- [ ] Installer **Power BI Desktop** (gratuit, Windows).
- [ ] Phase 3 (local) : connecter Desktop aux fichiers Parquet/CSV Gold produits en local.
- [ ] Phase 6 (cloud) : **Obtenir les données → Azure Databricks** → Server hostname + HTTP path du cluster (*Compute → ton cluster → Advanced → JDBC/ODBC*) → authentification *Microsoft Entra ID* → mode **Import** (pas DirectQuery : une fois importé, tu peux éteindre le cluster).
- [ ] Publier sur **Power BI Service** demande un compte professionnel/scolaire et, pour partager, une licence Pro ou Fabric *(non vérifié pour ton compte étudiant)*. Le livrable minimal est le fichier `.pbix` + captures + export PDF, ce qui ne dépend d'aucune licence.

---

## 11. (Option phase 8) Identité pour GitHub Actions

Recommandé : **OIDC (fédération)**, sans secret stocké.

```bash
az ad app create --display-name gh-olist-ci
APP_ID=$(az ad app list --display-name gh-olist-ci --query [0].appId -o tsv)
az ad sp create --id $APP_ID
az ad app federated-credential create --id $APP_ID --parameters '{
  "name":"gh-main","issuer":"https://token.actions.githubusercontent.com",
  "subject":"repo:Taki-eddine-El-Attari/olist-azure-lakehouse:ref:refs/heads/main",
  "audiences":["api://AzureADTokenExchange"]}'
```

Puis ajouter ce service principal au workspace Databricks (**Settings → Identity and access → Service principals**) avec le droit d'utiliser le cluster / les jobs. Secrets GitHub : `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `DATABRICKS_HOST`.

> Un compte étudiant peut ne pas avoir le droit de créer des App registrations dans le tenant de l'école *(non vérifié)*. Plan B : CI qui fait seulement lint + tests (pytest) sans déployer, ce qui reste un vrai CI.

---

## 12. Fin de projet / nettoyage

Après avoir pris **toutes** les captures (voir la liste dans CAHIER_DES_CHARGES.md, phase 9) :

- [ ] Exporter les JSON ADF (déjà dans Git si l'étape 9 Git est faite), les notebooks (`databricks workspace export-dir`), le `.pbix`.
- [ ] Désactiver les triggers ADF.
- [ ] Supprimer le job et le SQL warehouse serverless.
- [ ] Option économe : garder seulement le compte de stockage (centimes/mois) pour pouvoir refaire une démo.
- [ ] Option zéro coût :

```bash
az group delete --name $RG --yes --no-wait
```

- [ ] Vérifier 24 h plus tard dans le suivi de crédit qu'aucune consommation ne continue (groupe `databricks-rg-*` bien parti).

---

## Pièges fréquents

| Symptôme | Cause probable | Correctif |
|---|---|---|
| `NotAvailableForSubscription` / `QuotaExceeded` sur un cluster | Taille de VM interdite sur ce compte (étape 3) | Serverless uniquement |
| `RequestDisallowedByPolicy` | Région non autorisée | Toujours `switzerlandnorth` |
| `AuthorizationPermissionMismatch` sur le stockage | Rôle de données manquant ou pas encore propagé | `Storage Blob Data Contributor` + attendre 2-5 min |
| `MissingSubscriptionRegistration` | Provider non enregistré | Étape 2 |
| `AADSTS50076` + « No subscriptions found » à `az login` | MFA exigée, non faite au login | `az login --tenant <TENANT_ID>` (étape 0) |
| Crédit qui baisse sans travailler | Cluster allumé, trigger ADF actif | Terminate + désactiver trigger |
| Coût quotidien (~1 USD/jour) dans `databricks-rg-*` sans exécution | NAT Gateway créée par un workspace *Hybrid* (No Public IP, ADR-007) | Accepté jusqu'à la phase 9, puis workspace supprimé ou recréé en *Serverless* |
| `27001 Cluster Serverless does not exist` au *Test connection* ADF | Le test ne gère pas l'option Serverless | Ignorer, créer le linked service et tester par un run (étape 9) |

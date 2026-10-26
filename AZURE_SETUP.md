# AZURE_SETUP.md — Configuration Azure pour le projet Olist

> Compte : **Azure for Students** (100 USD, expire le 25/10/2027).
> Région unique : **switzerlandnorth** (autorisée par la policy du compte).
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
| 6 | Workspace Azure Databricks | Phase 4 | 0 tant qu'aucun cluster ne tourne |
| 7 | Access Connector + droits sur le stockage | Phase 4 | 0 |
| 8 | Cluster single node (auto-stop 15 min) | Phase 4 | **le poste principal** |
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

## 3. Vérifier les quotas (déjà constaté)

Dans switzerlandnorth : **Total Regional vCPUs = 6, DSv2 = 4, DSv3 = 4.**

Conséquence directe :
- Un `Standard_DS3_v2` = 4 vCPU. **Un seul cluster à la fois**, en **single node** (pas de workers).
- Data Factory ne doit **pas** lancer un « job cluster » en parallèle d'un cluster interactif allumé : ça demanderait 8 vCPU et échouerait. → ADF utilisera le **cluster existant** (étape 9).
- Pas de SQL Warehouse Databricks classique (il démarre ses propres VM). Power BI se connectera au cluster.

```bash
az vm list-usage --location $LOC -o table | grep -Ei "Total Regional|DSv2|DSv3"
```

Si un quota bloque : **Portail → Quotas → Calcul → switzerlandnorth → Demander une augmentation**. Sur un compte étudiant la demande peut être refusée *(non vérifié)* ; le plan ci-dessous fonctionne avec les quotas actuels.

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

**Pricing tier :** choisis **Premium** (ou **Trial**, qui donne 14 jours de DBU offerts puis bascule en Premium, *non vérifié pour Azure for Students*). Premium est nécessaire pour **Unity Catalog**, qui est la façon actuelle de connecter le stockage. Le tier Standard est en cours de retrait pour les nouveaux workspaces *(non vérifié, à lire dans le portail)*.

> Ne crée le workspace « Trial » que le jour où tu es prêt à travailler dessus, sinon les 14 jours filent pour rien.

```bash
az databricks workspace create -g $RG -n $DBW -l $LOC --sku premium
# ou --sku trial
az databricks workspace show -g $RG -n $DBW --query workspaceUrl -o tsv
```

Portail : **Créer une ressource → Azure Databricks → RG `rg-olist`, région Switzerland North, tier Premium/Trial → Mise en réseau : laisser par défaut (pas de VNet injection) → Créer.**

Ce que ça crée en plus : un groupe managé `databricks-rg-dbw-olist-...` (ne le modifie pas). Le workspace seul ne coûte rien ; ce sont les clusters qui coûtent.

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
   - [ ] Créer le catalogue et les schémas :

```sql
CREATE CATALOG IF NOT EXISTS olist;
CREATE SCHEMA IF NOT EXISTS olist.bronze  MANAGED LOCATION 'abfss://bronze@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.silver  MANAGED LOCATION 'abfss://silver@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.gold    MANAGED LOCATION 'abfss://gold@<SA>.dfs.core.windows.net/';
CREATE SCHEMA IF NOT EXISTS olist.ml;
```

**Plan B** si Unity Catalog n'est pas disponible : clé du compte de stockage dans un **Databricks secret scope** + `spark.conf.set("fs.azure.account.key.<SA>.dfs.core.windows.net", dbutils.secrets.get(...))`. Moins propre, mais fonctionne. Ne jamais mettre la clé en clair dans un notebook ou dans Git.

---

## 8. Cluster (le seul poste de coût important)

UI : **Compute → Create compute**

| Paramètre | Valeur |
|---|---|
| Policy | Unrestricted (ou Personal Compute) |
| Mode | **Single node** |
| Access mode | **Dedicated / Single user** (requis pour MLflow + UC simplement) |
| Runtime | **18 LTS ML** (Spark 4.1, Python 3.12, Java 21, Delta 4.2) : mêmes versions que l'image Docker locale |
| Node type | **Standard_DS3_v2** (4 vCPU, 14 Go) |
| Photon | **désactivé** (coûte plus de DBU, inutile ici) |
| Terminate after | **15 minutes** d'inactivité |
| Tags | `projet=olist` |

Coût estimé : VM DS3_v2 + ~0,75 DBU/h → **environ 0,6 à 1,2 USD par heure allumée** *(non vérifié : dépend du tarif Premium DBU et du prix VM en Suisse, vérifie sur la calculatrice Azure)*. Avec ~25 heures de cluster sur le projet → **15 à 30 USD**. Le crédit de 100 USD suffit si tu respectes l'arrêt auto.

Règles :
- [ ] Toujours **Terminate** à la main en fin de session (ne compte pas uniquement sur l'auto-stop).
- [ ] Développer d'abord en local (phases 1-3), n'utiliser le cluster que pour exécuter du code qui marche déjà.
- [ ] Récupère le **Cluster ID** (URL ou JSON du cluster) : nécessaire pour ADF et Power BI.

---

## 9. Azure Data Factory

```bash
az datafactory create -g $RG -n $ADF -l $LOC
ADF_PID=$(az datafactory show -g $RG -n $ADF --query identity.principalId -o tsv)

# ADF lit/écrit le stockage via son identité managée
az role assignment create --assignee-object-id $ADF_PID --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope $SA_ID

# ADF lance des notebooks Databricks via son identité managée
DBW_ID=$(az databricks workspace show -g $RG -n $DBW --query id -o tsv)
az role assignment create --assignee-object-id $ADF_PID --assignee-principal-type ServicePrincipal \
  --role "Contributor" --scope $DBW_ID
```

Dans **ADF Studio** (portail → la factory → *Launch studio*) :

- [ ] **Manage → Git configuration** : relier au repo GitHub (dossier `/adf`). Tout le JSON des pipelines est alors versionné : c'est une preuve visible dans le repo.
- [ ] **Linked service `ls_adls`** : Azure Data Lake Storage Gen2, authentification *System-assigned managed identity*, URL `https://<SA>.dfs.core.windows.net`.
- [ ] **Linked service `ls_databricks`** : Azure Databricks, authentification *Managed service identity*, workspace URL, **Existing interactive cluster** = ton Cluster ID. (Fallback : *Access token* Databricks stocké dans Key Vault.)
  > ⚠️ *(à vérifier en phase 5)* Le cluster est en mode *Dedicated / Single user* assigné à **toi**. L'identité managée d'ADF est un **autre principal** : elle risque d'être refusée sur ce cluster (le fait d'être seul sur le projet n'y change rien). Si le Debug échoue sur ce point, passer au fallback *Access token* (le run s'exécute alors en ton nom).
- [ ] **Datasets** : `ds_csv_landing` (DelimitedText, paramètre `fileName`) et `ds_bronze` (Parquet ou DelimitedText dans `bronze/olist/`).
- [ ] **Pipeline `pl_olist_daily`** :
  1. *ForEach* sur la liste des 9 fichiers → *Copy data* landing → bronze.
  2. *Notebook* `02_silver` (ls_databricks).
  3. *Notebook* `03_gold`.
  4. *Notebook* `05_ml_score` (prédictions batch).
  5. (option) *Web activity* / e-mail en cas d'échec.
- [ ] **Debug** une fois, puis **Publish**. Ajouter un **trigger** planifié uniquement pour la démo, puis le **désactiver** (sinon il rallume le cluster chaque jour).

Coût : ADF facture à l'exécution d'activité et à la durée de copie ; pour quelques exécutions → **moins de 1 USD** *(non vérifié)*. Le coût réel d'un run = le temps où il allume le cluster Databricks.

---

## 10. Power BI

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
- [ ] Terminer puis **supprimer** le cluster.
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
| `QuotaExceeded` au démarrage du cluster | Un autre cluster / job cluster tourne déjà, ou multi-nœud | Single node, un seul cluster, ADF sur cluster existant |
| `RequestDisallowedByPolicy` | Région non autorisée | Toujours `switzerlandnorth` |
| `AuthorizationPermissionMismatch` sur le stockage | Rôle de données manquant ou pas encore propagé | `Storage Blob Data Contributor` + attendre 2-5 min |
| `MissingSubscriptionRegistration` | Provider non enregistré | Étape 2 |
| `AADSTS50076` + « No subscriptions found » à `az login` | MFA exigée, non faite au login | `az login --tenant <TENANT_ID>` (étape 0) |
| Crédit qui baisse sans travailler | Cluster allumé, trigger ADF actif | Terminate + désactiver trigger |

# Power BI — maquette locale (phase 3)

## Installer Power BI Desktop (gratuit, Windows uniquement)

Version **Microsoft Store**, qui se met à jour toute seule. En ligne de commande :

```bash
winget install -e --id 9NTXR16HNW1T --source msstore
```

Ou à la main : ouvrir le **Microsoft Store**, chercher « Power BI Desktop » et cliquer sur *Obtenir*.

- Pas besoin de compte pour travailler en local : au premier lancement, fermer la fenêtre de connexion.
- Le compte (et une licence pour partager) ne sert qu'à publier sur Power BI Service, ce qui est hors du livrable minimal (AZURE_SETUP.md étape 10).
- L'interface suit la langue de Windows. Les noms de menus ci-dessous sont en français.

Source : `data/powerbi/*.parquet`, produits par `python -m olist.gold`. Power BI Desktop n'a pas de lecteur intégré pour un dossier Delta local, d'où cette copie Parquet (un fichier par table). En phase 6, la source devient le cluster Databricks.

## Étapes

1. **Désactiver la détection automatique des relations** : *Fichier → Options et paramètres → Options → Fichier actif → Chargement des données → décocher « Détecter automatiquement les nouvelles relations »*. Sinon Power BI relie `fact_orders` et `fact_order_items` par `order_id`, ce qui double les montants.
2. **Charger les 6 tables** : *Obtenir les données → Parquet* → `data/powerbi/<table>.parquet` (une fois par table) → *Charger*.
3. **Relations** (vue *Modèle*), toutes en **1 → plusieurs**, filtrage **unique** (sens simple) :

   | Dimension (côté 1) | Fait (côté plusieurs) | Colonne |
   |---|---|---|
   | dim_date[date_key] | fact_orders, fact_order_items | purchase_date_key |
   | dim_customer[customer_key] | fact_orders, fact_order_items | customer_key |
   | dim_product[product_key] | fact_order_items | product_key |
   | dim_seller[seller_key] | fact_order_items | seller_key |

   Aucune relation entre les deux faits.
4. **Table de dates** : sélectionner `dim_date` → *Outils de table → Marquer comme table de dates* → colonne `date`.
5. **Mesures** : copier celles de [measures.dax](measures.dax).
6. **Page 1 « Les retards détruisent la satisfaction »** :
   - 3 cartes : `Late Rate %`, `Avg Review Late`, `Avg Review On Time` ;
   - histogramme : `Late Rate %` par `dim_date[year]` puis `month` ;
   - barres : `Late Rate %` par `dim_customer[state]`.
7. Enregistrer sous `powerbi/olist.pbix`.

**Contrôle :** les cartes doivent afficher **6,77 %**, **2,27** et **4,29**, comme `sql/checks.sql`. Un autre chiffre veut dire qu'une relation ou un filtre est faux.

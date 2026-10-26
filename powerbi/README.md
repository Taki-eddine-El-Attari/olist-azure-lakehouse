# Power BI — maquette locale (phase 3)

## Installer Power BI Desktop (gratuit, Windows uniquement)

Version **Microsoft Store**, qui se met à jour toute seule. En ligne de commande :

```bash
winget install -e --id 9NTXR16HNW1T --source msstore
```

Ou à la main : ouvrir le **Microsoft Store**, chercher « Power BI Desktop » et cliquer sur *Obtenir*.

**Si le Store échoue avec `0x80070422`** (services « Microsoft Store Install Service » / « Windows Update » désactivés, c'est le cas sur ce poste) : utiliser l'**installateur autonome**, qui n'a pas besoin du Store.
1. Ouvrir https://www.microsoft.com/download/details.aspx?id=58494 (Microsoft Download Center, page « Microsoft Power BI Desktop »).
2. *Download* → choisir `PBIDesktopSetup_x64.exe`.
3. Lancer le fichier et suivre l'assistant. Cette version ne se met pas à jour toute seule : la retélécharger de temps en temps.

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
6. **Page 1 « Les retards détruisent la satisfaction »** (vue *Rapport*, la première icône à gauche). Principe de Power BI : on clique sur un type de visuel dans le volet *Visualisations*, un cadre vide apparaît sur la page, puis on glisse des champs du volet *Données* dans les zones du visuel (*Valeurs*, *Axe X*…).
   1. **Formater les mesures** (une fois) : dans *Données*, cliquer sur `Late Rate %` → ruban *Outils de mesure* → *Format* = *Pourcentage*, 2 décimales. Pour `Avg Review Late` et `Avg Review On Time` : *Nombre décimal*, 2 décimales.
   2. **Titre** : *Insérer → Zone de texte* → écrire « Les retards détruisent la satisfaction » → le placer en haut.
   3. **3 cartes** : cliquer sur la page vide (pour ne rien sélectionner) → *Visualisations → Carte* (l'icône « 123 ») → glisser `Late Rate %` dans *Champs*. Recommencer pour `Avg Review Late` et `Avg Review On Time`. Aligner les 3 cartes sous le titre.
   4. **Retard par mois** : page vide → *Histogramme groupé* (barres verticales) → `dim_date[year]` puis `dim_date[month]` dans *Axe X* → `Late Rate %` dans *Axe Y*. Le visuel affiche d'abord les années : cliquer sur l'icône **double flèche vers le bas** (« Développer tous les niveaux ») en haut du visuel pour voir année + mois.
   5. **Retard par État** : page vide → *Graphique à barres groupées* (barres horizontales) → `dim_customer[state]` dans *Axe Y* → `Late Rate %` dans *Axe X* → *…* en haut du visuel → *Trier l'axe* → `Late Rate %`, décroissant.
   6. **Essayer l'interaction** : cliquer sur une barre d'État filtre les autres visuels de la page. C'est l'effet des relations du modèle.
7. Enregistrer sous `powerbi/Olist.pbix` (*Fichier → Enregistrer sous*).

**Contrôle :** les cartes doivent afficher **6,77 %**, **2,27** et **4,29**, comme `sql/checks.sql`. Un autre chiffre veut dire qu'une relation ou un filtre est faux.

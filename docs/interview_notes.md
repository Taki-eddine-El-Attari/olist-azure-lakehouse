# Notes d'entretien

Réponses courtes aux 10 questions du cahier des charges (§10), à partir de ce que le projet a réellement fait. Les détails sont dans `docs/decisions.md` (ADR).

## 1. Pourquoi Bronze / Silver / Gold ? Qu'est-ce qui va dans chaque couche ?

- **Bronze :** la source telle quelle, typée par un schéma explicite, avec `_ingested_at` et `_source_file`. Lecture `FAILFAST` : une valeur hors schéma arrête le run au lieu de devenir `null` en silence.
- **Silver :** une table propre par entité. Règles métier (`delivery_status`, un avis par commande, catégories `unknown`, géolocalisation médiane par préfixe), lignes invalides en quarantaine, 16 contrôles bloquants.
- **Gold :** ce que le métier consomme : un schéma en étoile, `dq_results`, les prédictions.
- L'intérêt : chaque couche se reconstruit depuis la précédente, et on sait où chercher quand un chiffre est faux.

## 2. Pourquoi Delta plutôt que Parquet ?

Transactions ACID : un `overwrite` qui échoue ne laisse pas une table à moitié écrite. Schéma contrôlé, time travel, `MERGE` pour l'incrémental. Exemple vécu : lire directement les fichiers Parquet d'une table Delta après un `overwrite` aurait doublé les données, car les anciens fichiers restent jusqu'au `VACUUM`. C'est pourquoi l'export local pour Power BI passe par Spark (ADR-006).

## 3. Comment avez-vous évité de doubler les montants entre paiements et articles ?

Deux faits à grain différent : `fact_order_items` (un article, avec prix et fret) et `fact_orders` (une commande, avec totaux, paiements et avis). Jamais de jointure entre les deux faits ; dans Power BI, aucune relation entre eux (détection automatique désactivée). Quand une dimension n'est reliée qu'aux articles (vendeur, catégorie), la mesure passe par `TREATAS` plutôt que par une relation bidirectionnelle. Les contrôles Gold vérifient que les sommes Gold égalent celles de Silver.

## 4. Comment ADF s'authentifie-t-il au stockage et à Databricks ? Pourquoi pas de clé ?

Identité managée de la factory : *Storage Blob Data Contributor* sur le seul conteneur `landing`, *Contributor* sur le seul workspace. Databricks accède au stockage par un Access Connector (autre identité managée) déclaré dans Unity Catalog. Aucune clé à stocker, faire tourner ou risquer de fuiter, et des droits limités au strict nécessaire. Seule exception assumée : Power BI Desktop passe par un jeton à durée courte, parce qu'un compte Microsoft personnel est refusé par Entra ID (ADR-009).

## 5. Comment avez-vous évité la fuite de données dans le modèle ? Pourquoi un split temporel ?

- Uniquement des informations connues au clic « acheter » : délai promis, distance, états, montants, poids, catégorie, paiement. Pas de date de livraison ni de remise au transporteur, pas de statut final, pas d'avis.
- L'historique d'un vendeur ne compte que les commandes **déjà livrées** avant l'achat. Une commande achetée plus tôt mais encore en route avait une issue inconnue, et un test unitaire le vérifie.
- Split temporel : en production, on prédit toujours le futur à partir du passé. Un split aléatoire mélangerait des commandes de mars 2018 dans l'entraînement d'un modèle testé sur février 2018.
- Leçon : `purchase_month` paraissait anodin, mais il mémorisait le pic de février-mars 2018, qui ne se répète pas. Je l'ai retiré.

## 6. Pourquoi PR-AUC et pas l'accuracy, avec si peu de positifs ?

Avec 3,6 % de retards sur le test, un modèle qui répond toujours « à l'heure » a 96,4 % d'accuracy et ne sert à rien. La PR-AUC mesure la capacité à remonter les retards en tête de liste ; sa valeur de hasard est le taux de positifs (0,036). D'où le *lift* (PR-AUC / taux de retard), comparable entre des mois où le taux varie de 1 à 19 %.

## 7. Pourquoi pas d'endpoint temps réel ? Quand en faudrait-il un ?

Le besoin est un score par commande, recalculé une fois par jour avec le pipeline : un batch suffit et ne coûte rien entre deux runs. Un endpoint coûte en continu. Il deviendrait utile pour décider au moment du paiement : choisir un transporteur, afficher un délai plus prudent, proposer une option express.

## 8. Comment avez-vous contrôlé les coûts ? Qu'est-ce qui changerait en production ?

- Budget à 20 USD avec alertes ; jamais de développement interactif sur le cloud : code testé en local dans Docker, le cloud n'exécute que des jobs ; SQL warehouse en 2X-Small avec arrêt après 5 minutes ; mode Import dans Power BI ; trigger ADF arrêté ; coût relevé après chaque étape.
- Erreur apprise : le workspace *Hybrid* crée une NAT Gateway facturée en continu (~1,2 USD/jour), plus chère que tout le calcul. Un workspace *Serverless* l'aurait évitée (ADR-007).
- En production : environnements dev et prod, réseau privé, tags et budgets par équipe, *system tables* de facturation, réservations si la charge est stable.

## 9. Spark était-il nécessaire pour 100 000 lignes ?

Non pour le volume : pandas suffit, et le ML est d'ailleurs en pandas. Oui pour démontrer un pipeline qui passe à l'échelle sans réécriture : le même code PySpark a tourné en local et sur Databricks serverless sans modification.

## 10. Qu'avez-vous appris de la qualité des données ?

- `review_id` n'est pas une clé : 789 avis sont rattachés à plusieurs commandes. La clé réelle est `(review_id, order_id)`, et on garde l'avis le plus récent par commande.
- Le retard « classique » de 8,1 % compte en retard les commandes livrées le jour promis, parce que l'estimation est à minuit. Le vrai chiffre est 6,77 %, et l'écart de notes s'en trouve renforcé (2,27 au lieu de 2,57).
- L'écart de 165 319 BRL entre paiements et articles s'explique à 98 % par 775 commandes payées jamais expédiées.
- Enquêter avant d'écrire une règle : les 61 commandes « livrées avant approbation » étaient des approbations enregistrées en retard, pas des erreurs de livraison.

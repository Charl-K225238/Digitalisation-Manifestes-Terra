# Guide Power BI — import du classeur Excel de l'app

L'app contient déjà son tableau de bord (page **Activité du terminal**).
Power BI sert uniquement aux analyses que l'app ne fait pas. Aucune connexion
à la base : vous importez un fichier Excel exporté par l'app.

Coût : Power BI Desktop est gratuit. Pas de licence, pas de passerelle.

## 1. Exporter (30 s)
App › **Activité du terminal** › bas de page › **Préparer l'export Excel** ›
**Télécharger le classeur Power BI** (`TERRA_activite_PowerBI.xlsx`).
Refaites l'export après chaque nouveau mois chargé.

## 2. Importer (2 min, une fois)
Power BI Desktop › Obtenir des données › **Classeur Excel** › choisissez le
fichier › cochez les 6 tables : `t_Indicateurs`, `t_Stats_mensuelles`,
`t_Escales`, `t_Corrections`, `t_Traitements`, `t_Calendrier` › Charger.

Pour actualiser plus tard : remplacez le fichier au même emplacement, puis
Accueil › **Actualiser**.

## 3. Relations (vue Modèle, glisser-déposer)
| De | Vers |
|---|---|
| `t_Calendrier[date_mois]` | `t_Stats_mensuelles[date_mois]` |
| `t_Calendrier[date_mois]` | `t_Escales[date_mois]` |
| `t_Calendrier[date_mois]` | `t_Traitements[date_mois]` |
| `t_Indicateurs[indicateur]` | `t_Stats_mensuelles[indicateur]` |
| `t_Indicateurs[indicateur]` | `t_Corrections[indicateur]` |

Marquez `t_Calendrier` comme table de dates (colonne `date_mois`).
Triez `t_Calendrier[mois]` par `t_Calendrier[date_mois]` et
`t_Indicateurs[libelle]` par `t_Indicateurs[ordre]`.

## 4. Mesures utiles (Nouvelle mesure)
```DAX
Réalisé = CALCULATE ( SUM ( t_Stats_mensuelles[valeur] ),
    t_Stats_mensuelles[nature] = "realise", t_Stats_mensuelles[mois] > 0 )

Réalisé N-1 = CALCULATE ( [Réalisé], SAMEPERIODLASTYEAR ( t_Calendrier[date_mois] ) )

% vs N-1 = DIVIDE ( [Réalisé] - [Réalisé N-1], [Réalisé N-1] )

Cumul annuel = TOTALYTD ( [Réalisé], t_Calendrier[date_mois] )

Escales = COUNTROWS ( t_Escales )

Durée moyenne escale (h) = AVERAGE ( t_Escales[duree_escale_h] )

Véhicules par heure d'escale =
    DIVIDE ( SUM ( t_Escales[roro] ), SUM ( t_Escales[duree_escale_h] ) )

Part neufs = DIVIDE ( SUM ( t_Escales[neufs] ), SUM ( t_Escales[roro] ) )

Écart classeur-PAA (véh.) = SUMX ( t_Escales, ABS ( t_Escales[ecart_roro_classeur_paa] ) )

Manifestes traités = COUNTROWS ( t_Traitements )
Temps moyen app (min) = DIVIDE ( AVERAGE ( t_Traitements[duree_traitement_sec] ), 60 )
```
Pour le budget : le budget mensuel est la ligne `nature = "budget"`,
`mois = 0` de `t_Stats_mensuelles`. Multipliez-le par le nombre de mois.

## 5. Quoi analyser en priorité
- **Durée d'escale par type de navire** : les Lo/Lo restent-ils plus longtemps ?
- **Véhicules par heure d'escale** : productivité par navire et par mois.
- **Écarts classeur / PAA** : où les saisies manuelles se trompent le plus.
- **Temps gagné** : manifestes traités × (temps manuel mesuré − temps de l'app).
  Le temps manuel est à chronométrer auprès des agents (3 à 5 saisies), jamais à estimer.

## 6. Limites
- Détail par escale disponible seulement pour les mois chargés avec leurs fichiers
  (à partir de septembre 2026). Janvier à août viennent du rapport existant.
- Historique N-1 mensuel : seul septembre 2025 est connu à ce jour.
- Hinterland par tranche : saisi ou repris du rapport, pas calculé.

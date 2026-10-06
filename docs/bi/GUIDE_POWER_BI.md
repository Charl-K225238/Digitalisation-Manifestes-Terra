# Guide Power BI — Activité TERRA (étape 2)

Objectif : analyser l'activité depuis les données propres de l'app, sans
ressaisie. L'app collecte et contrôle ; Power BI explore.

Coût : **Power BI Desktop (gratuit)**, actualisation manuelle (bouton
« Actualiser »). Publier sur le service Power BI et planifier l'actualisation
demande une licence Pro et une passerelle : à décider plus tard, seulement si
le besoin de partage est réel.

---

## 1. Préparer l'accès (une fois, 5 min)

1. Supabase › SQL Editor : exécutez la **partie 2** de `docs/bi/bi_schema.sql`
   en choisissant un mot de passe fort. Le compte `powerbi_lecture` ne lit que
   le schéma `bi` (vues), jamais les tables de l'app.
2. Supabase › Project Settings › Database › **Connection string › Session
   pooler** : notez l'hôte (`aws-…pooler.supabase.com`) et le port `5432`.
3. Même page › **SSL Configuration › Download certificate**, puis double-clic
   sur le fichier › Installer › « Autorités de certification racines de
   confiance ». Sans ça, Power BI refuse la connexion chiffrée.

## 2. Se connecter

Power BI Desktop › Obtenir des données › **Base de données PostgreSQL**
- Serveur : `<hôte du session pooler>:5432`
- Base : `postgres`
- Mode : **Importer**
- Identifiants (onglet Base de données) : utilisateur
  `powerbi_lecture.<référence du projet>` (la référence figure dans l'URL du
  projet Supabase), mot de passe choisi à l'étape 1.

Cochez dans `bi` : `dim_indicateur`, `f_stats_mensuelles`, `f_escales`,
`f_corrections`, `f_traitements`.

## 3. Modèle (étoile)

Créez la table de dates (Modélisation › Nouvelle table) :

```DAX
Calendrier =
ADDCOLUMNS (
    CALENDAR ( DATE ( 2025, 1, 1 ), DATE ( 2027, 12, 31 ) ),
    "Année", YEAR ( [Date] ),
    "Mois n°", MONTH ( [Date] ),
    "Mois", FORMAT ( [Date], "mmm yyyy" ),
    "Semaine ISO", WEEKNUM ( [Date], 21 )
)
```
Marquez-la comme table de dates. Triez « Mois » par « Date ».

Relations (1 → plusieurs, filtre simple) :

| De | Vers |
|---|---|
| `Calendrier[Date]` | `f_stats_mensuelles[date_mois]` |
| `Calendrier[Date]` | `f_escales[date_mois]` |
| `Calendrier[Date]` | `f_traitements[date_traitement]` |
| `dim_indicateur[indicateur]` | `f_stats_mensuelles[indicateur]` |
| `dim_indicateur[indicateur]` | `f_corrections[indicateur]` |

Triez `dim_indicateur[libelle]` par `dim_indicateur[ordre]`.
Les lignes `mois = 0` (total N-1, budget) n'ont pas de date : elles ne sont
lues que par les mesures Budget et Référence N-1 ci-dessous.

## 4. Mesures DAX

Rangez-les dans une table vide `_Mesures`.

```DAX
-- Réalisé
Réalisé =
CALCULATE ( SUM ( f_stats_mensuelles[valeur] ),
    f_stats_mensuelles[nature] = "realise", f_stats_mensuelles[mois] > 0 )

Réalisé N-1 = CALCULATE ( [Réalisé], SAMEPERIODLASTYEAR ( Calendrier[Date] ) )

% vs N-1 = DIVIDE ( [Réalisé] - [Réalisé N-1], [Réalisé N-1] )

Cumul annuel = TOTALYTD ( [Réalisé], Calendrier[Date] )

Cumul annuel N-1 = CALCULATE ( [Cumul annuel], SAMEPERIODLASTYEAR ( Calendrier[Date] ) )

-- Budget : budget mensuel constant × nombre de mois dans le contexte
Nb mois = COUNTROWS ( SUMMARIZE ( Calendrier, Calendrier[Année], Calendrier[Mois n°] ) )

Budget =
VAR _annee = MAX ( Calendrier[Année] )
VAR _bm =
    CALCULATE ( SUM ( f_stats_mensuelles[valeur] ),
        f_stats_mensuelles[nature] = "budget", f_stats_mensuelles[mois] = 0,
        f_stats_mensuelles[annee] = _annee, REMOVEFILTERS ( Calendrier ) )
RETURN IF ( NOT ISBLANK ( _bm ), _bm * [Nb mois] )

% vs Budget = DIVIDE ( [Réalisé] - [Budget], [Budget] )

-- Part de valeurs corrigées à la main (qualité de saisie)
Taux de correction =
DIVIDE (
    CALCULATE ( COUNTROWS ( f_stats_mensuelles ), f_stats_mensuelles[est_corrigee] = TRUE () ),
    COUNTROWS ( f_stats_mensuelles ) )

-- Escales
Escales = COUNTROWS ( f_escales )
Durée moyenne escale (h) = AVERAGE ( f_escales[duree_escale_h] )
Véhicules par escale = DIVIDE ( SUM ( f_escales[roro] ), [Escales] )
Part neufs = DIVIDE ( SUM ( f_escales[neufs] ), SUM ( f_escales[roro] ) )
Part Hinterland = DIVIDE ( SUM ( f_escales[hinterland] ), SUM ( f_escales[roro] ) )
Véhicules par heure d'escale = DIVIDE ( SUM ( f_escales[roro] ), SUM ( f_escales[duree_escale_h] ) )
Écart sources (véh.) = SUMX ( f_escales, ABS ( f_escales[ecart_roro_classeur_paa] ) )
Taux d'écart sources = DIVIDE ( [Écart sources (véh.)], SUM ( f_escales[roro_paa] ) )

-- Usage de l'app
Manifestes traités = COUNTROWS ( f_traitements )
Temps moyen app (min) = DIVIDE ( AVERAGE ( f_traitements[duree_traitement_sec] ), 60 )
```

**Temps gagné** : créez un paramètre de simulation « Temps manuel par
manifeste (min) » (Modélisation › Nouveau paramètre). La valeur de référence
est à **mesurer** auprès des agents (chronométrer 3 à 5 saisies manuelles),
jamais à estimer.

Power BI crée avec le paramètre une mesure qui renvoie la valeur choisie
(son nom dépend de la langue de Power BI) : remplacez `[Temps manuel]`
ci-dessous par cette mesure.

```DAX
Temps gagné (h) =
DIVIDE ( [Manifestes traités] *
    ( [Temps manuel] - [Temps moyen app (min)] ), 60 )
```

## 5. Pages proposées

**Page 1 — Activité du mois**
- Segment : Mois.
- 5 cartes : Escales, TEU, RORO, Neufs, Usagés, avec `% vs N-1` et `% vs Budget`.
- Courbes mensuelles RORO et TEU, année en cours vs N-1.
- Barres empilées 100 % : tranches de volume par mois (Côte d'Ivoire, Lo/Lo).
- Matrice : `dim_indicateur[groupe]` / `[libelle]` × Réalisé, Budget, % vs Budget, Réalisé N-1, % vs N-1.

**Page 2 — Escales et qualité des données**
- Barres : durée moyenne d'escale par type de navire (Ro/Ro, Car carrier, Lo/Lo).
- Nuage de points : durée d'escale (x) × véhicules (y), une bulle par navire.
- Tableau : navires avec écart classeur / PAA ≠ 0 (mise en forme conditionnelle).
- Cartes : Taux d'écart sources, Taux de correction, nombre de corrections du mois.

**Page 3 (option) — Usage de l'app** : manifestes traités par semaine,
temps moyen, temps gagné.

## 6. Limites connues

- Historique : seuls les mois chargés dans l'app existent. Janvier → août 2026
  viennent du rapport existant (pas de détail par escale avant septembre).
- N-1 : seul le total annuel 2025 et septembre 2025 sont connus ; les mesures
  N-1 mensuelles restent vides tant que les fichiers 2025 ne sont pas chargés.
- Hinterland par tranche : saisi, pas calculé (aucune source ne le contient).

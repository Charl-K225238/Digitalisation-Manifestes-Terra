# Structuration des manifestes cargo — v5 (dashboard + archives + persistance)

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans le navigateur (par défaut http://localhost:8501).
Pour un accès depuis d'autres postes du réseau bureau :

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

puis accéder depuis un autre poste via `http://<IP_du_poste>:8501`.

## Pages

L'application a trois pages, accessibles depuis le menu à gauche :

### 📦 Structuration des manifestes

1. Renseigner son nom et prénom (traçabilité).
2. Charger un ou plusieurs manifestes PDF (Grimaldi, format PBREPORT).
3. Cliquer sur **Lancer le traitement** — une barre de progression indique
   l'avancement fichier par fichier. Si un navire/voyage a déjà été traité
   auparavant, un avertissement de doublon s'affiche.
4. Vérifier les indicateurs et l'aperçu par catégorie (Véhicule / Conteneur /
   Colis) — les colonnes issues d'une heuristique de reconnaissance de texte
   (adresse, statut neuf/usager, type de colis) méritent une relecture
   ponctuelle.
5. Décocher les colonnes non nécessaires dans chaque onglet si besoin.
6. Télécharger le fichier Excel (un classeur par navire/voyage détecté,
   regroupés en `.zip` s'il y en a plusieurs).

Chaque traitement est journalisé automatiquement (traité par, navire,
volumes, durée, type de cargaison) dans `traitement_log.db` — c'est ce qui
alimente le tableau de bord et l'archive. Le PDF source et un Excel structuré
(toutes colonnes) sont également conservés pour consultation ultérieure.

**⚠️ Emplacement des données (important pour les mises à jour de l'app) :**
la base et les fichiers archivés sont stockés dans un dossier **utilisateur
persistant**, séparé du code de l'application :
`%APPDATA%\StructurationManifestesGrimaldi` sous Windows (`~/.local/share/…`
ou équivalent `XDG_DATA_HOME` sous Linux/Mac). Ainsi, remplacer le dossier de
l'application par une nouvelle version (nouveau `.zip` dézippé) **ne fait
plus perdre l'historique déjà accumulé** — contrairement aux versions
précédentes, où la base vivait à côté du code et était donc "abandonnée"
dans l'ancien dossier à chaque mise à jour. Une éventuelle base/archive
trouvée dans l'ancien emplacement (à côté du code) est reprise
automatiquement une fois au premier lancement de cette version.

Le type de cargaison (🚗 Véhicules uniquement / 📦 Conteneurs uniquement /
📋 Colis uniquement / 🔀 Mixte) est détecté automatiquement à partir des
catégories réellement présentes dans chaque manifeste — visible dans le
récapitulatif de la page Structuration, filtrable dans l'Archive, et les
onglets d'aperçu vides (ex. Conteneur/Colis pour un manifeste
"véhicules uniquement") ne s'affichent plus.

### 📊 Tableau de bord

Suivi de performance, avec :

- **Filtres** : période (semaine/mois/année en cours, tout l'historique ou
  plage personnalisée), granularité des tendances (semaine ou mois),
  intervenant(s).
- **Indicateurs clés** : manifestes traités, B/L structurés, volume traité,
  temps de traitement moyen, intervenants actifs — avec variation par rapport
  à la période précédente.
- **Vue globale** : tendance dans le temps, répartition par type de
  marchandise, journal d'activité récente avec recherche.
- **Vue par intervenant** : classement par volume traité, tableau détaillé,
  tendance individuelle.
- Une aide contextuelle (**ℹ️ Comment lire ce tableau de bord ?**) explique
  chaque indicateur et filtre directement dans la page.

Le tableau de bord n'affiche que des traitements réels — il ne génère ni
n'invente aucune donnée. Tant qu'aucun manifeste n'a été traité depuis la
page Structuration, il affiche un état vide ; il se remplit automatiquement
au fil des traitements réels.

### 🗂️ Archives

Historique complet et recherche de tous les manifestes déjà traités :

- **Recherche** libre (navire, voyage, fichier, traité par) + filtre par
  **statut de vérification**.
- Tableau paginé ; cliquer une ligne ouvre le détail (indicateurs complets,
  case à cocher « Manifeste vérifié », téléchargement du PDF source et de
  l'Excel structuré archivés).
- **Export global** de la sélection filtrée en un clic (.xlsx), pratique pour
  un point hebdo/mensuel.

## Fichiers

- `app.py` — point d'entrée, gère la navigation entre les pages
- `views/structuration.py` — interface d'upload, export Excel, archivage,
  détection de doublons
- `views/dashboard.py` — tableau de bord de suivi de performance
- `views/archive.py` — historique, recherche et re-téléchargement des
  manifestes déjà traités
- `manifest_parser.py` — moteur d'extraction et de structuration (déterministe,
  sans IA, basé sur la structure fixe des rapports Grimaldi)
- `tracking.py` — journalisation SQLite des traitements + gestion de
  l'archive de fichiers (données réelles uniquement)
- `ui_helpers.py` — style commun (police, couleurs, aide contextuelle, format
  des durées)
- `.streamlit/config.toml` — thème visuel de l'application
- Données persistantes (hors dossier de l'app) : `traitement_log.db` +
  `archive/` (PDF sources dans `sources/`, Excel structurés dans `exports/`),
  dans `%APPDATA%\StructurationManifestesGrimaldi` — créés automatiquement au
  premier traitement

## Notes techniques

- Nécessite **Streamlit ≥ 1.61** (fonctionnalités récentes utilisées :
  `st.pagination`, `st.segmented_control`, `st.dialog`, recherche native dans
  `st.multiselect`) et **pandas ≥ 2.2**.
- Aucun package tiers ajouté pour la recherche/pagination/interface : tout
  repose sur les capacités natives de Streamlit 1.61, pour rester 100 %
  gratuit et limiter les dépendances.

## Prochaines étapes possibles

- Brancher la durée applicative sur une estimation du temps de saisie
  manuelle (baseline à documenter) pour objectiver le temps réellement gagné.
- Purge/archivage à froid des fichiers `archive/` les plus anciens si le
  volume devient important (le PDF source pèse plus lourd que l'Excel).
- Authentification légère si l'outil est partagé au-delà de l'équipe actuelle.
- Déploiement sur Streamlit Community Cloud (à finaliser — le dossier de
  données persistant décrit ci-dessus est une solution locale ; en
  hébergement cloud la persistance dépend du stockage fourni par la
  plateforme, à vérifier séparément).

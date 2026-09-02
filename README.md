# Structuration des manifestes cargo Grimaldi

Outil Streamlit qui structure automatiquement les manifestes PDF Grimaldi (format PBREPORT) vers Excel, pour que les agents n'aient plus qu'à vérifier et compléter au lieu de ressaisir.

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

Nécessite un projet Supabase (base + stockage) configuré dans `.streamlit/secrets.toml` :

```toml
SUPABASE_DB_URL = "..."
SUPABASE_URL = "..."
SUPABASE_SERVICE_KEY = "..."
APP_PASSWORD = "..."   # optionnel — active un écran d'accès par mot de passe
```

Schéma de base : `supabase_schema.sql`.

## Pages

| Page | Description |
|------|-------------|
| 👤 Profil | Identification (nom, service, rôle) |
| 📦 Pré-Masque | Upload PDF → extraction → aperçu par profil → export Excel |
| 📋 Masque / Type ISO | Structuration des rapports de chargement (loading report) |
| 📊 Tableau de bord | Suivi de performance (volumes, taux vérification, top navires, par service) |
| 🗂️ Archives | Historique complet, recherche, re-téléchargement PDF/Excel |
| 💬 Avis & Retours | Commentaires et suggestions des équipes |

## Fonctionnement

1. **Identifiez-vous une seule fois** — nom, service et rôle sont mémorisés.
2. **Chargez un ou plusieurs PDF** puis cliquez sur *Lancer le traitement*.
3. **Choisissez votre profil** (*Reporting* ou *Opérations*) pour afficher les colonnes adaptées.
4. **Cochez Vérifié** après relecture, puis **téléchargez** le classeur Excel.

## Stack

- Python 3.12 · Streamlit ≥ 1.61 · pandas ≥ 2.2 · pdfplumber · openpyxl · plotly
- Extraction déterministe (regex + machine à états) — aucun LLM
- Données persistées sur Supabase (PostgreSQL + Storage pour les PDF/Excel archivés)

# Structuration des manifestes cargo Grimaldi

Outil Streamlit de structuration automatique des manifestes PDF Grimaldi (format PBREPORT) vers Excel.

## Lancer en local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Pages

| Page | Description |
|------|-------------|
| 📦 Structuration | Upload PDF → extraction → aperçu par profil → export Excel |
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
- Données persistées dans `%APPDATA%\StructurationManifestesGrimaldi` (SQLite + archive PDF/Excel)

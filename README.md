# Manifestes TERRA

Application Streamlit qui structure les manifestes navires (PDF/Excel) en Excel, pour que les agents vérifient et complètent au lieu de ressaisir.

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Système : `packages.txt` (poppler-utils, tesseract-ocr) · Python 3.12 · Streamlit ≥ 1.61.

## Secrets (`.streamlit/secrets.toml`, jamais versionné)

`APP_PASSWORD` (obligatoire) · `SUPABASE_DB_URL` · `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` · `BOOTSTRAP_ADMIN_PASSWORD` (optionnel)

Base : `supabase_schema.sql`.

## Hébergement sur un serveur TERRA (sans Supabase)

Secrets à la place des trois `SUPABASE_*` :

```toml
DATABASE_URL = "postgresql://utilisateur:motdepasse@hote:5432/manifestes"
ARCHIVE_DIR  = "/opt/manifestes/archive"   # PDF/Excel archivés, sur le disque du serveur
```

- Base : **PostgreSQL ≥ 15** requis (le code utilise `ON CONFLICT`, `JSONB`, `RETURNING`). Tables : `supabase_schema.sql`, ou restauration de l'export Supabase (`pg_restore --no-owner --no-privileges -d "$DATABASE_URL" manifestes.dump`).
- Fichiers : `python scripts/migrer_archive_supabase.py /opt/manifestes/archive` copie le bucket Supabase avec la même arborescence (relançable).
- `ARCHIVE_DIR` doit appartenir à l'utilisateur du service et être inclus dans les sauvegardes du serveur, comme la base.
- Sans `DATABASE_URL`/`ARCHIVE_DIR`, l'app garde le fonctionnement Supabase.

## Comptes, droits et notifications (v7.43)

- `CONNEXION_PAR_COMPTE = true` : connexion e-mail + mot de passe ; groupes de droits et utilisateurs gérés dans **Administration › Utilisateurs et droits**. Catalogue des fonctionnalités : `permissions.py`. Premier administrateur créé avec `BOOTSTRAP_ADMIN_PASSWORD`. `false` (défaut) : mot de passe commun `APP_PASSWORD` comme avant.
- Notifications e-mail des Avis & retours : secrets `SMTP_*`, `AVIS_EMAIL_TO`, `AVIS_EMAIL_CC` (voir `notifications.py`). Facultatif.
- Procédure complète : `deploiement/base_de_donnees/LISEZMOI_IT.md`.

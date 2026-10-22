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

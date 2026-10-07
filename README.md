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

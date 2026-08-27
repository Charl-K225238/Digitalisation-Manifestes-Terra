-- ============================================================================
-- Schéma Supabase — Digitalisation des manifestes navires (Terra Grimaldi)
-- ============================================================================
-- À exécuter UNE SEULE FOIS dans Supabase : Project → SQL Editor → New query
-- → coller ce fichier entier → Run.
--
-- Procédure complète de mise en place :
--   1. Ouvrir l'un de vos projets Supabase EXISTANTS (pas besoin d'en créer
--      un nouveau — toutes les tables ci-dessous sont préfixées "manifestes_"
--      pour ne jamais entrer en conflit avec les données d'une autre app déjà
--      présente dans ce projet).
--   2. SQL Editor → coller ce fichier → Run (crée toutes les tables).
--   3. Storage (menu de gauche) → New bucket → nom exact "manifestes-archive" → Public
--      bucket : NON (laisser privé). Créer.
--   4. Project Settings → Database → Connection string → onglet "Transaction
--      pooler" (port 6543, recommandé pour les apps serverless comme
--      Streamlit Cloud) → copier l'URL complète (avec le mot de passe) →
--      c'est la valeur de SUPABASE_DB_URL.
--   5. Project Settings → API → copier "Project URL" (SUPABASE_URL) et la
--      clé "service_role" — PAS la clé "anon" — (SUPABASE_SERVICE_KEY).
--   6. Ajouter ces 3 valeurs dans les secrets de l'app :
--        - En local : fichier .streamlit/secrets.toml (déjà ignoré par git)
--        - Sur Streamlit Cloud : "Manage app" → Settings → Secrets
--      Format :
--        SUPABASE_DB_URL = "postgresql://postgres.xxxx:MOTDEPASSE@..."
--        SUPABASE_URL = "https://xxxx.supabase.co"
--        SUPABASE_SERVICE_KEY = "eyJ..."
--   7. Redéployer l'app (ou redémarrer si en local).
--
-- La clé "service_role" contourne les règles de sécurité niveau ligne (RLS)
-- de Supabase — c'est voulu ici : l'app fait déjà sa propre gestion d'accès
-- (mot de passe commun + identification), et c'est la seule clé qui accède
-- au bucket de stockage. Elle ne doit JAMAIS être exposée côté client — elle
-- ne l'est pas ici, elle reste uniquement dans les secrets serveur Streamlit.
-- ============================================================================

CREATE TABLE IF NOT EXISTS manifestes_traitements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    horodatage TIMESTAMPTZ NOT NULL,
    agent TEXT NOT NULL,
    fichier TEXT NOT NULL,
    navire TEXT,
    voyage TEXT,
    nb_bl INTEGER,
    nb_vehicules INTEGER,
    nb_conteneurs INTEGER,
    nb_colis INTEGER,
    nb_transit INTEGER,
    duree_traitement_sec DOUBLE PRECISION,
    export_path TEXT,
    pdf_path TEXT,
    verifie INTEGER DEFAULT 0,
    type_cargo TEXT,
    service TEXT,
    role TEXT
);

CREATE TABLE IF NOT EXISTS manifestes_traitement_bl (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    traitement_id BIGINT NOT NULL REFERENCES manifestes_traitements(id) ON DELETE CASCADE,
    bl_numero TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traitement_bl_numero ON manifestes_traitement_bl(bl_numero);

CREATE TABLE IF NOT EXISTS manifestes_avis (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    horodatage TIMESTAMPTZ NOT NULL,
    auteur TEXT NOT NULL,
    service TEXT,
    role TEXT,
    message TEXT NOT NULL,
    parent_id BIGINT REFERENCES manifestes_avis(id) ON DELETE CASCADE,
    categorie TEXT,
    statut TEXT,
    version_app TEXT
);

CREATE TABLE IF NOT EXISTS manifestes_avis_soutiens (
    avis_id BIGINT NOT NULL REFERENCES manifestes_avis(id) ON DELETE CASCADE,
    auteur_normalise TEXT NOT NULL,
    horodatage TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (avis_id, auteur_normalise)
);

CREATE TABLE IF NOT EXISTS manifestes_loading_reports (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    horodatage TIMESTAMPTZ NOT NULL,
    agent TEXT NOT NULL,
    navire TEXT,
    voyage TEXT,
    compte_escale TEXT,
    nb_conteneurs INTEGER,
    source_file TEXT,
    masque_path TEXT,
    iso_path TEXT
);

-- Mots de passe personnels des agents (salés + hachés PBKDF2, jamais en clair)
CREATE TABLE IF NOT EXISTS manifestes_user_credentials (
    agent_normalise TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    horodatage TIMESTAMPTZ NOT NULL
);

-- Petite table clé/valeur générique — utilisée pour la dernière identité
-- saisie (usage secondaire, best-effort ; la persistance principale de
-- l'identité par utilisateur passe par l'URL du navigateur, pas par ici).
CREATE TABLE IF NOT EXISTS manifestes_app_kv (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

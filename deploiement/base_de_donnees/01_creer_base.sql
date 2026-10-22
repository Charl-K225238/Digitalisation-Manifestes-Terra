-- ============================================================================
-- 01 — Création de la base et de son utilisateur (PostgreSQL >= 15)
-- À exécuter UNE fois en administrateur :  sudo -u postgres psql -f 01_creer_base.sql
-- Remplacer CHANGER_MOI par un mot de passe fort AVANT exécution.
-- Ce mot de passe va ensuite dans DATABASE_URL (secrets de l'app), nulle part ailleurs.
-- ============================================================================

CREATE ROLE manifestes LOGIN PASSWORD 'CHANGER_MOI';
CREATE DATABASE manifestes OWNER manifestes ENCODING 'UTF8' TEMPLATE template0;

-- L'utilisateur de l'app possède la base : il crée/lit/écrit ses tables,
-- sans aucun droit sur le reste du serveur PostgreSQL.
\connect manifestes
ALTER SCHEMA public OWNER TO manifestes;
REVOKE ALL ON DATABASE manifestes FROM PUBLIC;

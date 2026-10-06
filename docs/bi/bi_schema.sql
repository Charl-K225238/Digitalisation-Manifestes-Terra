-- ============================================================================
-- Couche d'analyse Power BI — schéma « bi » (MISE À JOUR v9)
-- ============================================================================
-- Partie 1 (vues) : DÉJÀ APPLIQUÉE le 06/10/2026 (migration manifestes_v9_bi_views).
-- Partie 2 (rôle de connexion lecture seule) : À EXÉCUTER PAR L'ANALYSTE dans
-- Supabase › SQL Editor, en choisissant soi-même le mot de passe. Ce mot de
-- passe ne doit jamais être écrit dans le dépôt ni partagé dans un chat.
--
-- Le schéma « bi » n'est pas exposé par l'API REST de Supabase : seules les
-- connexions PostgreSQL directes (Power BI) y accèdent.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Partie 1 — Vues (déjà en place ; ré-exécutable sans risque)
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS bi;

CREATE OR REPLACE VIEW bi.dim_indicateur AS
SELECT * FROM (VALUES
  ('escales', 1, 'Côte d''Ivoire', 'Nb d''escales', 'Escales'),
  ('teu', 2, 'Côte d''Ivoire', 'TEUS', 'TEU'),
  ('roro', 3, 'Côte d''Ivoire', 'RORO', 'Véhicules'),
  ('neufs', 4, 'Côte d''Ivoire', 'VEH. NEUFS', 'Véhicules'),
  ('usages', 5, 'Côte d''Ivoire', 'VEH. USAGES', 'Véhicules'),
  ('t_lt15', 6, 'Côte d''Ivoire', 'VEH. - 15M3', 'Véhicules'),
  ('t_15_50', 7, 'Côte d''Ivoire', 'VEH. 15M3 - 50M3', 'Véhicules'),
  ('t_gt50', 8, 'Côte d''Ivoire', 'VEH. + 50M3', 'Véhicules'),
  ('h_lt15', 9, 'Hinterland', 'VEH. - 15M3', 'Véhicules'),
  ('h_15_50', 10, 'Hinterland', 'VEH. 15M3 - 50M3', 'Véhicules'),
  ('h_gt50', 11, 'Hinterland', 'VEH. + 50M3', 'Véhicules'),
  ('l_lt15', 12, 'Trafic navires Lo/Lo', 'VEH. - 15M3', 'Véhicules'),
  ('l_15_50', 13, 'Trafic navires Lo/Lo', 'VEH. 15M3 - 50M3', 'Véhicules'),
  ('l_gt50', 14, 'Trafic navires Lo/Lo', 'VEH. + 50M3', 'Véhicules')
) AS t(indicateur, ordre, groupe, libelle, unite);

-- Faits mensuels. mois = 0 : total annuel (réf. N-1) ou budget mensuel.
CREATE OR REPLACE VIEW bi.f_stats_mensuelles AS
SELECT
  s.annee, s.mois,
  CASE WHEN s.mois BETWEEN 1 AND 12 THEN make_date(s.annee, s.mois, 1) END AS date_mois,
  s.indicateur, s.nature,
  COALESCE(s.valeur_saisie, s.valeur_calculee) AS valeur,
  s.valeur_calculee, s.valeur_saisie,
  (s.valeur_saisie IS NOT NULL) AS est_corrigee,
  CASE WHEN s.valeur_saisie IS NOT NULL THEN 'Saisie manuelle' ELSE s.source END AS source,
  s.fichier, s.motif, s.agent, s.horodatage
FROM public.manifestes_stats_mensuelles s;

CREATE OR REPLACE VIEW bi.f_escales AS
SELECT
  e.annee, e.mois, make_date(e.annee, e.mois, 1) AS date_mois,
  e.navire, e.type_navire, e.armateur,
  e.debut, e.fin, e.duree_escale_h,
  e.teu, e.roro, e.neufs, e.usages, e.transit AS hinterland,
  e.paa_lt15, e.paa_15_50, e.paa_gt50, e.roro_paa,
  e.roro - e.roro_paa AS ecart_roro_classeur_paa,
  e.sup50_classeur, e.paa_gt50 - e.sup50_classeur AS ecart_sup50_paa_classeur,
  e.fichier_volumes, e.fichier_paa, e.horodatage
FROM public.manifestes_stats_escales e;

CREATE OR REPLACE VIEW bi.f_corrections AS
SELECT c.horodatage, c.annee, c.mois, c.indicateur, c.nature,
       c.valeur_calculee, c.ancienne_valeur, c.nouvelle_valeur,
       c.nouvelle_valeur - c.valeur_calculee AS ecart_vs_calcul,
       c.motif, c.agent
FROM public.manifestes_stats_corrections c;

CREATE OR REPLACE VIEW bi.f_traitements AS
SELECT t.id, t.horodatage, (t.horodatage AT TIME ZONE 'Africa/Abidjan')::date AS date_traitement,
       t.agent, t.service, t.navire, t.voyage, t.type_cargo,
       t.nb_bl, t.nb_vehicules, t.nb_conteneurs, t.nb_colis, t.nb_transit,
       t.duree_traitement_sec, (t.verifie = 1) AS verifie
FROM public.manifestes_traitements t;

-- ---------------------------------------------------------------------------
-- Partie 2 — Rôle de connexion Power BI (à exécuter vous-même)
-- Remplacez <MOT_DE_PASSE_FORT> avant d'exécuter. Lecture seule, schéma bi
-- uniquement : ce compte ne peut ni modifier ni lire les tables de l'app.
-- ---------------------------------------------------------------------------
-- CREATE ROLE powerbi_lecture LOGIN PASSWORD '<MOT_DE_PASSE_FORT>';
-- GRANT USAGE ON SCHEMA bi TO powerbi_lecture;
-- GRANT SELECT ON ALL TABLES IN SCHEMA bi TO powerbi_lecture;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA bi GRANT SELECT ON TABLES TO powerbi_lecture;

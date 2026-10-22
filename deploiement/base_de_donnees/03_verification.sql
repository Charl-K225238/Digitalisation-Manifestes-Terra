-- ============================================================================
-- 03 — Contrôle après restauration (lecture seule, ré-exécutable)
--   psql "$DATABASE_URL" -f 03_verification.sql
-- Attendu : 18 tables présentes (15 reprises de Supabase + 3 tables des comptes) ; nombres de lignes identiques à ceux
-- relevés par Charlie au moment de l'export Supabase (fichier comptages_supabase.txt).
-- ============================================================================

\echo '--- 1. Tables présentes (attendu : 18) ---'
SELECT count(*) AS nb_tables
FROM information_schema.tables
WHERE table_schema = 'public' AND table_name LIKE 'manifestes\_%';

\echo '--- 2. Lignes par table (à comparer avec comptages_supabase.txt) ---'
SELECT 'manifestes_app_kv' AS table_name, count(*) AS lignes FROM manifestes_app_kv
UNION ALL SELECT 'manifestes_avis', count(*) FROM manifestes_avis
UNION ALL SELECT 'manifestes_avis_soutiens', count(*) FROM manifestes_avis_soutiens
UNION ALL SELECT 'manifestes_hinterland_tranches', count(*) FROM manifestes_hinterland_tranches
UNION ALL SELECT 'manifestes_known_values', count(*) FROM manifestes_known_values
UNION ALL SELECT 'manifestes_liste_finalisation', count(*) FROM manifestes_liste_finalisation
UNION ALL SELECT 'manifestes_loading_reports', count(*) FROM manifestes_loading_reports
UNION ALL SELECT 'manifestes_stats_corr_escales', count(*) FROM manifestes_stats_corr_escales
UNION ALL SELECT 'manifestes_stats_corrections', count(*) FROM manifestes_stats_corrections
UNION ALL SELECT 'manifestes_stats_escales', count(*) FROM manifestes_stats_escales
UNION ALL SELECT 'manifestes_stats_mensuelles', count(*) FROM manifestes_stats_mensuelles
UNION ALL SELECT 'manifestes_suivi_escale', count(*) FROM manifestes_suivi_escale
UNION ALL SELECT 'manifestes_traitement_bl', count(*) FROM manifestes_traitement_bl
UNION ALL SELECT 'manifestes_traitements', count(*) FROM manifestes_traitements
UNION ALL SELECT 'manifestes_user_credentials', count(*) FROM manifestes_user_credentials
ORDER BY 1;

\echo '--- 3. Compteurs d''identifiants (attendu : aucune ligne = OK) ---'
-- Une ligne ici signifie que le prochain enregistrement créé par l'app
-- entrerait en conflit avec un identifiant existant.
SELECT s.table_name, s.dernier_id_en_base, s.prochain_id
FROM (
  SELECT c.table_name,
         (xpath('/row/m/text()', query_to_xml(format('SELECT max(%I) AS m FROM %I', c.column_name, c.table_name), false, true, '')))[1]::text::bigint AS dernier_id_en_base,
         pg_sequence_last_value(pg_get_serial_sequence(c.table_name, c.column_name)::regclass) AS prochain_id
  FROM information_schema.columns c
  WHERE c.table_schema = 'public' AND c.is_identity = 'YES' AND c.table_name LIKE 'manifestes\_%'
) s
WHERE s.dernier_id_en_base IS NOT NULL
  AND (s.prochain_id IS NULL OR s.prochain_id < s.dernier_id_en_base);

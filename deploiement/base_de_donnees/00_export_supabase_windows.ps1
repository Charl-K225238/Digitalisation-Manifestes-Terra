# ============================================================================
# 00 — Export de la base Supabase (à lancer par Charlie, sur son PC Windows)
#
# Prérequis : PostgreSQL 17 "Command Line Tools" installé (postgresql.org > Windows).
# Lancer : clic droit sur ce fichier > "Exécuter avec PowerShell"
#   (si Windows bloque : PowerShell > Set-ExecutionPolicy -Scope Process Bypass, puis .\00_export_supabase_windows.ps1)
#
# Produit sur le Bureau, dans un dossier "Export_Manifestes_AAAA-MM-JJ" :
#   manifestes_AAAA-MM-JJ.dump   -> la base (15 tables manifestes_*), à remettre à l'IT
#   comptages_supabase.txt       -> nombre de lignes par table, pour le contrôle après restauration
#
# CONFIDENTIEL : le .dump contient les vraies données TERRA. Remise en main propre ou partage
# interne uniquement, jamais par e-mail/messagerie. Supprimer le dossier une fois remis.
# ============================================================================
$ErrorActionPreference = "Stop"

# 1. Trouver les outils PostgreSQL (version la plus récente installée, >= 15)
$bin = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" -ErrorAction SilentlyContinue |
       Sort-Object { [int]$_.Directory.Parent.Name } -Descending | Select-Object -First 1
if (-not $bin -or [int]$bin.Directory.Parent.Name -lt 15) {
    Write-Host "PostgreSQL (version 15 ou plus) introuvable. Installez PostgreSQL 17 'Command Line Tools'." -ForegroundColor Red
    Read-Host "Entrée pour fermer"; exit 1
}
$pgdump = $bin.FullName
$psql   = Join-Path $bin.DirectoryName "psql.exe"
$pgrest = Join-Path $bin.DirectoryName "pg_restore.exe"
Write-Host "Outils PostgreSQL $($bin.Directory.Parent.Name) trouvés." -ForegroundColor Green

# 2. Adresse de la base (saisie masquée, jamais enregistrée sur le disque)
Write-Host "Collez la valeur de SUPABASE_DB_URL (sans les guillemets), puis Entrée :"
$sec = Read-Host -AsSecureString
$url = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
$url = $url.Trim().Trim('"')
if ($url -notmatch '^postgres(ql)?://') { Write-Host "Adresse invalide (doit commencer par postgresql://)." -ForegroundColor Red; Read-Host "Entrée pour fermer"; exit 1 }
if ($url -match 'pooler\.supabase\.com:6543') {
    $url = $url -replace 'pooler\.supabase\.com:6543', 'pooler.supabase.com:5432'
    Write-Host "Port 6543 (mode transaction) remplacé par 5432 (mode session), requis pour l'export." -ForegroundColor Yellow
}

# 3. Export
$jour = Get-Date -Format "yyyy-MM-dd"
$dir  = Join-Path ([Environment]::GetFolderPath("Desktop")) "Export_Manifestes_$jour"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$dump = Join-Path $dir "manifestes_$jour.dump"
Write-Host "Export en cours (1 à 5 minutes)..."
& $pgdump $url --table='public.manifestes_*' --no-owner --no-privileges -Fc -f $dump
if ($LASTEXITCODE -ne 0) { Write-Host "Échec de l'export (voir message ci-dessus)." -ForegroundColor Red; Read-Host "Entrée pour fermer"; exit 1 }

# 4. Comptages de référence
$requete = @"
SELECT 'manifestes_app_kv', count(*) FROM manifestes_app_kv
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
ORDER BY 1
"@
$comptes = & $psql $url -tA -F " : " -c $requete
"Comptages Supabase du $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Out-File -Encoding utf8 (Join-Path $dir "comptages_supabase.txt")
$comptes | Out-File -Encoding utf8 -Append (Join-Path $dir "comptages_supabase.txt")

# 5. Contrôle du fichier produit
$nbTables = (& $pgrest --list $dump | Select-String "TABLE DATA").Count
$taille = "{0:N1} Mo" -f ((Get-Item $dump).Length / 1MB)
$url = $null; $sec = $null
Write-Host ""
Write-Host "Export terminé : $nbTables tables (attendu : 15), $taille" -ForegroundColor Green
$comptes | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "Dossier : $dir"
Write-Host "À remettre à l'IT : tout le dossier (en main propre / partage interne)." -ForegroundColor Yellow
Read-Host "Entrée pour fermer"

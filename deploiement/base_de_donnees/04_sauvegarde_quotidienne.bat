@echo off
REM ============================================================================
REM 04 (Windows) - Sauvegarde quotidienne : base PostgreSQL + dossier d'archive
REM 1. Remplacer MOT_DE_PASSE ci-dessous (meme valeur que DATABASE_URL des secrets).
REM 2. Programmer (cmd administrateur) :
REM    schtasks /create /tn "Manifestes sauvegarde" /sc daily /st 02:30 /ru SYSTEM /tr "C:\manifestes\deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat"
REM 3. Copier regulierement C:\sauvegardes\manifestes hors du serveur (NAS / sauvegarde TERRA).
REM Restaurer : pg_restore --no-owner --no-privileges --clean --if-exists -d "%DATABASE_URL%" base_AAAA-MM-JJ.dump
REM ============================================================================
setlocal
set "DATABASE_URL=postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
set "ARCHIVE_DIR=C:\manifestes\archive"
set "DEST=C:\sauvegardes\manifestes"
set "GARDER_JOURS=14"
set "PGBIN=C:\Program Files\PostgreSQL\17\bin"

for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set "JOUR=%%d"
if not exist "%DEST%" mkdir "%DEST%"

"%PGBIN%\pg_dump.exe" "%DATABASE_URL%" --no-owner --no-privileges -Fc -f "%DEST%\base_%JOUR%.dump"
if errorlevel 1 (echo %date% %time% ECHEC sauvegarde base >> "%DEST%\sauvegarde.log" & exit /b 1)

tar -czf "%DEST%\archive_%JOUR%.tar.gz" -C "%ARCHIVE_DIR%\.." archive
if errorlevel 1 (echo %date% %time% ECHEC sauvegarde fichiers >> "%DEST%\sauvegarde.log" & exit /b 1)

forfiles /p "%DEST%" /m base_*.dump /d -%GARDER_JOURS% /c "cmd /c del @path" 2>nul
forfiles /p "%DEST%" /m archive_*.tar.gz /d -%GARDER_JOURS% /c "cmd /c del @path" 2>nul

echo %date% %time% sauvegarde OK >> "%DEST%\sauvegarde.log"
endlocal

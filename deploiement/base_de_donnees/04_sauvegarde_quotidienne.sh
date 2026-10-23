#!/usr/bin/env bash
# ============================================================================
# 04 — Sauvegarde quotidienne : base PostgreSQL + dossier d'archive (PDF/Excel)
# Installation (root) :
#   install -m 750 -o manifestes -g manifestes 04_sauvegarde_quotidienne.sh /opt/manifestes/sauvegarde.sh
#   echo '30 2 * * * manifestes /opt/manifestes/sauvegarde.sh >> /var/backups/manifestes/sauvegarde.log 2>&1' \
#     > /etc/cron.d/manifestes-sauvegarde
# Restaurer la base : pg_restore --no-owner --no-privileges --clean --if-exists -d "$DATABASE_URL" base_AAAA-MM-JJ.dump
# Copier aussi DEST hors de ce serveur (NAS / sauvegarde TERRA) : une sauvegarde
# sur la même machine ne protège pas d'une panne de disque.
# ============================================================================
set -euo pipefail

SECRETS=/opt/manifestes/.streamlit/secrets.toml
DEST=/var/backups/manifestes
GARDER_JOURS=14

lire_secret() { grep -E "^$1[[:space:]]*=" "$SECRETS" | head -1 | sed -E 's/^[^=]+=[[:space:]]*"([^"]*)".*$/\1/'; }
DATABASE_URL=$(lire_secret DATABASE_URL)
ARCHIVE_DIR=$(lire_secret ARCHIVE_DIR)
JOUR=$(date +%F)

mkdir -p "$DEST" && chmod 700 "$DEST"
pg_dump "$DATABASE_URL" --no-owner --no-privileges -Fc -f "$DEST/base_$JOUR.dump"
tar -czf "$DEST/archive_$JOUR.tar.gz" -C "$(dirname "$ARCHIVE_DIR")" "$(basename "$ARCHIVE_DIR")"
find "$DEST" -type f \( -name 'base_*.dump' -o -name 'archive_*.tar.gz' \) -mtime +"$GARDER_JOURS" -delete

echo "$(date '+%F %T') sauvegarde OK : $(du -sh "$DEST" | cut -f1) au total"

# Base de données de l'app Manifestes — migration Supabase → serveur TERRA

**Pour :** équipe IT TERRA · **Contact :** Charles Emmanuel Kouadio · **Version de l'app requise :** 7.42.0 ou plus

L'app quitte Supabase entièrement : la base passe sur un **PostgreSQL TERRA**, et les fichiers archivés
(PDF/Excel) passent sur le **disque du serveur**. Le code est le même ; seuls les secrets changent.

## Contenu du dossier

| Fichier | Qui | Rôle |
|---|---|---|
| `00_export_supabase_windows.ps1` | Charlie | Exporte la base Supabase → `manifestes_AAAA-MM-JJ.dump` + `comptages_supabase.txt` |
| `01_creer_base.sql` | IT | Crée l'utilisateur `manifestes` et la base `manifestes` |
| `02_schema_manifestes.sql` | IT | Crée les 15 tables **vides** (uniquement si on ne restaure pas l'export) |
| `03_verification.sql` | IT | Contrôle après restauration (tables, lignes, compteurs d'identifiants) |
| `04_sauvegarde_quotidienne.sh` | IT | Sauvegarde quotidienne base + fichiers, conservation 14 jours |
| `../../scripts/migrer_archive_supabase.py` | IT | Copie les fichiers archivés de Supabase vers le disque du serveur |

## Prérequis

- **PostgreSQL 15 ou plus** (testé sur 16). ⚠️ **SQL Server n'est pas compatible** : le code utilise des fonctions propres à PostgreSQL.
- Base sur le serveur de l'app ou sur un serveur PostgreSQL TERRA joignable depuis celui-ci.
- Volume : quelques Mo pour la base ; prévoir **5 Go** pour le dossier d'archive (croissance lente).

## Étapes

**1. Créer la base** — remplacer `CHANGER_MOI` dans le fichier, puis :
```bash
sudo -u postgres psql -f 01_creer_base.sql
```

**2. Charger les données** — avec le dossier d'export remis par Charlie :
```bash
export DATABASE_URL="postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
pg_restore --no-owner --no-privileges -d "$DATABASE_URL" manifestes_AAAA-MM-JJ.dump
```
Attendu : aucune ligne d'erreur. *(Option base vide, déconseillée : `psql "$DATABASE_URL" -f 02_schema_manifestes.sql` à la place — l'historique, les comptes agents et les tables de référence seraient perdus.)*

**3. Vérifier**
```bash
psql "$DATABASE_URL" -f 03_verification.sql
```
Attendu : `15` tables · nombres de lignes **identiques** à `comptages_supabase.txt` · partie 3 vide `(0 rows)`.

**4. Copier les fichiers archivés** (clés Supabase fournies par Charlie, utilisées une seule fois) :
```bash
sudo mkdir -p /opt/manifestes/archive && sudo chown manifestes:manifestes /opt/manifestes/archive
cd /opt/manifestes
sudo -u manifestes env SUPABASE_URL="https://xxxx.supabase.co" SUPABASE_SERVICE_KEY="..." \
  .venv/bin/python scripts/migrer_archive_supabase.py /opt/manifestes/archive
```
Attendu : `Terminé : N copiés, 0 déjà présents, 0 erreur(s)`. Relançable sans risque.

**5. Secrets de l'app** — dans `/opt/manifestes/.streamlit/secrets.toml` (droits `600`), **remplacer** les trois `SUPABASE_*` par :
```toml
APP_PASSWORD = "..."                  # inchangé
BOOTSTRAP_ADMIN_PASSWORD = "..."      # inchangé
DATABASE_URL = "postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
ARCHIVE_DIR  = "/opt/manifestes/archive"
```
Puis `sudo systemctl restart manifestes`.

**6. Sauvegardes**
```bash
sudo install -m 750 -o manifestes -g manifestes 04_sauvegarde_quotidienne.sh /opt/manifestes/sauvegarde.sh
echo '30 2 * * * manifestes /opt/manifestes/sauvegarde.sh >> /var/log/manifestes-sauvegarde.log 2>&1' | sudo tee /etc/cron.d/manifestes-sauvegarde
sudo mkdir -p /var/backups/manifestes && sudo chown manifestes:manifestes /var/backups/manifestes
```
Copier `/var/backups/manifestes` hors du serveur (NAS / sauvegarde TERRA).

## Déroulé conseillé (zéro perte de données)

1. **Répétition** : un premier export → étapes 1 à 5 → tests avec Charlie. L'ancienne app reste en service.
2. **Bascule** (créneau convenu, ~30 min) : les agents arrêtent d'utiliser l'ancienne app → Charlie refait l'export →
   `pg_restore --no-owner --no-privileges --clean --if-exists -d "$DATABASE_URL" <nouveau dump>` → étape 3 → étape 4 (ne copie que les nouveaux fichiers) → nouvelle adresse communiquée aux agents.
3. **Retour arrière** possible tant que Supabase n'est pas supprimé : remettre les secrets `SUPABASE_*` et redémarrer.

## Points d'attention

- **Taille des envois** : l'app accepte des fichiers jusqu'à **25 Mo**. Caddy n'impose pas de limite ; avec **Nginx**, ajouter `client_max_body_size 30M;` (défaut : 1 Mo).
- **Confidentialité** : le `.dump`, les sauvegardes et le dossier d'archive contiennent des données opérationnelles TERRA. Accès restreint (`700`), jamais de transfert par e-mail. Le `.dump` remis par Charlie est à supprimer après restauration.
- **Clés Supabase** : à révoquer une fois la migration validée (Supabase › Project Settings › API).
- Les tables `manifestes_user_credentials` contiennent des mots de passe **hachés** (jamais en clair).

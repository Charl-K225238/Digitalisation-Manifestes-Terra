# App Manifestes — migration Supabase → serveur TERRA (base, comptes, e-mail)

**Pour :** équipe IT TERRA · **Contact :** Charles Emmanuel Kouadio · **Version de l'app requise :** 7.43.0 ou plus

L'app quitte Supabase entièrement : la base passe sur un **PostgreSQL TERRA**, les fichiers archivés (PDF/Excel)
sur le **disque du serveur**. Sur le nouveau serveur, chaque agent se connecte avec **son e-mail et son mot de passe** ;
l'IT gère les groupes de droits et les comptes dans la page **Administration › Utilisateurs et droits**.

## Contenu du dossier

| Fichier | Qui | Rôle |
|---|---|---|
| `00_export_supabase_windows.ps1` | Charlie | Exporte la base Supabase → `manifestes_AAAA-MM-JJ.dump` + `comptages_supabase.txt` |
| `01_creer_base.sql` | IT | Crée l'utilisateur `manifestes` et la base `manifestes` |
| `02_schema_manifestes.sql` | IT | Crée/complète les tables (dont les 3 tables des comptes). Ré-exécutable sans risque |
| `03_verification.sql` | IT | Contrôle après restauration (tables, lignes, compteurs d'identifiants) |
| `04_sauvegarde_quotidienne.sh` | IT | Sauvegarde quotidienne base + fichiers, conservation 14 jours |
| `scripts/migrer_archive_supabase.py` (dans le code de l'app) | IT | Copie les fichiers archivés de Supabase vers le disque du serveur |

## Prérequis

- **PostgreSQL 15 ou plus** (testé sur 16).
- Volume : quelques Mo pour la base ; prévoir **5 Go** pour le dossier d'archive (croissance lente).
- Pour les notifications d'avis : un **relais SMTP** TERRA (ou Microsoft 365) et une adresse d'expédition.

## Étapes

**1. Créer la base** — remplacer `CHANGER_MOI` dans le fichier, puis :
```bash
sudo -u postgres psql -f 01_creer_base.sql
```

**2. Charger les données puis ajouter les tables des comptes** — avec le dossier d'export remis par Charlie :
```bash
export DATABASE_URL="postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
pg_restore --no-owner --no-privileges -d "$DATABASE_URL" manifestes_AAAA-MM-JJ.dump
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 02_schema_manifestes.sql
```
Attendu : aucune ligne d'erreur.

**3. Vérifier**
```bash
psql "$DATABASE_URL" -f 03_verification.sql
```
Attendu : `18` tables · nombres de lignes **identiques** à `comptages_supabase.txt` · partie 3 vide `(0 rows)`.

**4. Copier les fichiers archivés** (clés Supabase fournies par Charlie, utilisées une seule fois) :
```bash
sudo mkdir -p /opt/manifestes/archive && sudo chown manifestes:manifestes /opt/manifestes/archive
cd /opt/manifestes
sudo -u manifestes env SUPABASE_URL="https://xxxx.supabase.co" SUPABASE_SERVICE_KEY="..." \
  .venv/bin/python scripts/migrer_archive_supabase.py /opt/manifestes/archive
```
Attendu : `Terminé : N copiés, 0 déjà présents, 0 erreur(s)`. Relançable sans risque.

**5. Secrets de l'app** — `/opt/manifestes/.streamlit/secrets.toml` (droits `600`). Les `SUPABASE_*` ne servent plus :
```toml
# Base et fichiers
DATABASE_URL = "postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
ARCHIVE_DIR  = "/opt/manifestes/archive"

# Connexion par compte (e-mail + mot de passe, groupes gérés par l'IT)
CONNEXION_PAR_COMPTE = true
BOOTSTRAP_ADMIN_PASSWORD = "..."   # code à usage unique pour créer le 1er administrateur (étape 6)
APP_PASSWORD = "..."               # ancien mot de passe commun : gardé pour le retour arrière

# Notifications e-mail des avis (sans SMTP_HOST, aucun e-mail n'est envoyé ; l'app fonctionne)
SMTP_HOST = "smtp.office365.com"   # ou le relais SMTP TERRA
SMTP_PORT = 587
SMTP_STARTTLS = true
SMTP_USER = "manifestes@terra.ci"  # vide si le relais n'exige pas d'authentification
SMTP_PASSWORD = "..."
SMTP_FROM = "manifestes@terra.ci"
AVIS_EMAIL_TO = "charles.kouadio@terra.ci"
AVIS_EMAIL_CC = "christian.danho@terra.ci"     # plusieurs adresses : séparées par des virgules
APP_URL = "https://ADRESSE-DE-L-APP"           # lien inséré dans l'e-mail
```
Puis `sudo systemctl restart manifestes`.

**6. Premier administrateur et comptes**
1. Ouvrir l'app : l'écran **« Première configuration »** s'affiche (une seule fois). Saisir le code `BOOTSTRAP_ADMIN_PASSWORD`,
   nom, prénom, e-mail, mot de passe, groupe **Administrateur IT** (gestion des comptes seule) ou **Analyste Data** (tout).
2. Se connecter, puis **Administration › Utilisateurs et droits** :
   - **Groupes** : 4 groupes de départ reprennent les accès actuels (Agent, Direction, Analyste Data, Administrateur IT).
     Pour en créer un : « Nouveau groupe » → nom → cocher les fonctionnalités par catégorie → **Valider le groupe**.
   - **Utilisateurs** : « Nouvel utilisateur » → nom, prénom, e-mail, service, groupe → **Créer**. Un **mot de passe provisoire**
     s'affiche une seule fois : le remettre à la personne en main propre. Elle le change à sa première connexion.
   - Désactiver un compte, changer de groupe, **réinitialiser un mot de passe** (débloque aussi un compte bloqué après
     trop d'essais) : section « Modifier un utilisateur ». Toutes les actions sont tracées dans l'onglet **Journal**.
3. Saisir le **nom et le prénom comme les agents les utilisaient** (ex. Kouadio / Charles) : l'historique des traitements
   et le tableau de bord restent rattachés à la même personne.

**7. Sauvegardes**
```bash
sudo install -m 750 -o manifestes -g manifestes 04_sauvegarde_quotidienne.sh /opt/manifestes/sauvegarde.sh
echo '30 2 * * * manifestes /opt/manifestes/sauvegarde.sh >> /var/log/manifestes-sauvegarde.log 2>&1' | sudo tee /etc/cron.d/manifestes-sauvegarde
sudo mkdir -p /var/backups/manifestes && sudo chown manifestes:manifestes /var/backups/manifestes
```
Copier `/var/backups/manifestes` hors du serveur (NAS / sauvegarde TERRA).

## Déroulé conseillé (zéro perte de données)

1. **Répétition** : premier export → étapes 1 à 7 → création des comptes → tests avec Charlie. L'ancienne app reste en service.
2. **Bascule** (créneau convenu, ~30 min) : les agents arrêtent d'utiliser l'ancienne app → Charlie refait l'export →
   `pg_restore --no-owner --no-privileges --clean --if-exists -d "$DATABASE_URL" <nouveau dump>` → étape 3 → étape 4
   (ne copie que les nouveaux fichiers) → nouvelle adresse communiquée aux agents.
   Les comptes et groupes créés pendant la répétition sont **conservés** (ils ne font pas partie de l'export).
3. **Retour arrière** :
   - problème de connexion par compte → `CONNEXION_PAR_COMPTE = false` + redémarrage : retour au mot de passe commun ;
   - problème de serveur → l'ancienne app Streamlit Cloud reste en service tant que Supabase n'est pas supprimé.

## Points d'attention

- **Taille des envois** : 25 Mo par fichier. Caddy n'impose pas de limite ; avec **Nginx**, ajouter `client_max_body_size 30M;` (défaut : 1 Mo).
- **Mots de passe** : 8 caractères minimum, lettres et chiffres, stockés **hachés** (PBKDF2). 3 échecs → blocage 15 min,
  5 échecs → blocage jusqu'à réinitialisation par l'IT (ou redémarrage du service).
- **Microsoft 365** : l'envoi SMTP authentifié (« SMTP AUTH ») est souvent désactivé par défaut ; l'activer pour la boîte d'expédition, ou utiliser un relais SMTP interne.
- **Garde-fou** : l'app refuse toute action qui laisserait **zéro** administrateur actif.
- **Confidentialité** : `.dump`, sauvegardes et dossier d'archive = données opérationnelles TERRA. Accès restreint, jamais par e-mail.
  Supprimer le `.dump` remis par Charlie après restauration.
- **Clés Supabase** : à révoquer une fois la migration validée (Supabase › Project Settings › API).

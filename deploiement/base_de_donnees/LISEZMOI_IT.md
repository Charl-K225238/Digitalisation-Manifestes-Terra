# Installer l'app Manifestes sur un serveur TERRA

**Pour :** équipe IT TERRA · **Contact :** Charles Emmanuel Kouadio · **Version de l'app :** 7.43.2 ou plus

L'app tourne sur un serveur TERRA, avec sa base **PostgreSQL 17** et ses fichiers (PDF/Excel archivés) sur le disque du serveur.
Chaque agent se connecte avec **son e-mail et son mot de passe** ; l'IT gère les groupes et les comptes dans l'app.

Ce guide couvre un serveur **Linux (partie A, recommandé)** ou **Windows (partie B)**. Suivre une seule des deux parties,
puis la partie C. Chaque commande se copie telle quelle ; remplacer seulement les mots en MAJUSCULES.

## Ce qu'il vous faut

| Élément | Fourni par |
|---|---|
| `Digitalisation-Manifestes-Terra_v7.43.2_main.zip` — le code (scripts de base dans `deploiement/base_de_donnees/`) | Charlie, par e-mail |
| Dossier `Export_Manifestes_AAAA-MM-JJ` — l'export de la base | Charlie, en main propre |
| Fichier des secrets (mots de passe et clés actuels) | Charlie, en main propre |
| Un serveur : 2 cœurs, 4 Go de mémoire, 20 Go de disque | IT |
| **Accès internet du serveur pendant l'installation** (pypi.org, supabase.co, dépôts du système) | IT |

Choisir un mot de passe de base composé **uniquement de lettres et de chiffres** (il est placé dans une adresse
`postgresql://…`, où les caractères `@ : / # ?` cassent la connexion). Il sert de `MOT_DE_PASSE` dans tout le guide.

---

## A. Serveur Linux (Ubuntu 24.04)

**A1. Se connecter au serveur et y copier les fichiers** — depuis votre PC Windows : ouvrir le dossier qui contient le zip
et l'export, cliquer dans la barre d'adresse de l'explorateur, taper `cmd`, Entrée. Une invite de commandes s'ouvre dans ce dossier :
```
scp Digitalisation-Manifestes-Terra_v7.43.2_main.zip UTILISATEUR@ADRESSE_SERVEUR:~/
scp -r Export_Manifestes_AAAA-MM-JJ UTILISATEUR@ADRESSE_SERVEUR:~/
ssh UTILISATEUR@ADRESSE_SERVEUR
```
Toutes les commandes suivantes se tapent dans cette session `ssh` (ou directement sur la console du serveur).

**A2. Installer les programmes** (PostgreSQL 17 vient du dépôt officiel PostgreSQL ; appuyer sur Entrée si une question s'affiche) :
```bash
sudo apt update
sudo apt install -y unzip python3.12 python3.12-venv poppler-utils tesseract-ocr caddy postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt install -y postgresql-17
psql --version
```
Attendu : `psql (PostgreSQL) 17.x`.

**A3. Installer le code de l'app** (quelques minutes) :
```bash
sudo useradd --system --home-dir /opt/manifestes --shell /usr/sbin/nologin manifestes
sudo unzip -q ~/Digitalisation-Manifestes-Terra_v7.43.2_main.zip -d /opt
sudo mv /opt/Digitalisation-Manifestes-Terra /opt/manifestes
sudo mkdir -p /opt/manifestes/archive
sudo chown -R manifestes:manifestes /opt/manifestes
sudo -u manifestes python3.12 -m venv /opt/manifestes/.venv
sudo -u manifestes /opt/manifestes/.venv/bin/pip install -r /opt/manifestes/requirements.txt
```
Attendu : la dernière ligne commence par `Successfully installed`.

**A4. Créer la base et charger les données**
```bash
cd /opt/manifestes/deploiement/base_de_donnees
sudo nano 01_creer_base.sql
```
Remplacer `CHANGER_MOI` par `MOT_DE_PASSE`, puis Ctrl+O, Entrée, Ctrl+X. Ensuite :
```bash
sudo -u postgres psql -f 01_creer_base.sql
export DATABASE_URL="postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
pg_restore --no-owner --no-privileges -d "$DATABASE_URL" ~/Export_Manifestes_AAAA-MM-JJ/manifestes_AAAA-MM-JJ.dump
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 02_schema_manifestes.sql
psql "$DATABASE_URL" -f 03_verification.sql
```
Attendu : aucune ligne `ERROR`, puis `18` tables et des nombres de lignes identiques à `comptages_supabase.txt` (dans le dossier d'export).

**A5. Copier les fichiers archivés** (valeurs `SUPABASE_URL` et `SUPABASE_SERVICE_KEY` du fichier des secrets) :
```bash
cd /opt/manifestes
sudo -u manifestes env SUPABASE_URL="VALEUR" SUPABASE_SERVICE_KEY="VALEUR" \
  .venv/bin/python scripts/migrer_archive_supabase.py /opt/manifestes/archive
```
Attendu : `Terminé : N copiés, 0 déjà présents, 0 erreur(s)`. Relançable sans risque.

**A6. Saisir les secrets** — ouvrir le fichier, y coller le modèle de la partie **C1**, enregistrer (Ctrl+O, Entrée, Ctrl+X), puis le protéger :
```bash
sudo -u manifestes nano /opt/manifestes/.streamlit/secrets.toml
sudo chmod 600 /opt/manifestes/.streamlit/secrets.toml
```
Sur Linux : `ARCHIVE_DIR = "/opt/manifestes/archive"`.

**A7. Lancer l'app comme un service** (démarrage automatique, relance en cas de panne) :
```bash
sudo tee /etc/systemd/system/manifestes.service > /dev/null <<'EOF'
[Unit]
Description=App Manifestes TERRA
After=network-online.target postgresql.service

[Service]
User=manifestes
WorkingDirectory=/opt/manifestes
ExecStart=/opt/manifestes/.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now manifestes
sleep 10
curl -s http://127.0.0.1:8501/_stcore/health
```
Attendu : `ok`. En cas de problème : `sudo journalctl -u manifestes -n 50`.

**A8. Rendre l'app accessible en HTTPS** (remplacer `ADRESSE` par l'adresse choisie, ex. `manifestes.terra.local`) :
```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
ADRESSE {
    reverse_proxy 127.0.0.1:8501
}
EOF
sudo systemctl restart caddy
sudo ufw allow OpenSSH
sudo ufw allow 443/tcp
sudo ufw enable
```
Certificat TERRA : ajouter dans le bloc la ligne `tls /chemin/cert.pem /chemin/cle.pem`.

**A9. Programmer la sauvegarde quotidienne** (2 h 30 chaque nuit, 14 jours conservés) :
```bash
sudo mkdir -p /var/backups/manifestes && sudo chown manifestes:manifestes /var/backups/manifestes
sudo install -m 750 -o manifestes -g manifestes /opt/manifestes/deploiement/base_de_donnees/04_sauvegarde_quotidienne.sh /opt/manifestes/sauvegarde.sh
echo '30 2 * * * manifestes /opt/manifestes/sauvegarde.sh >> /var/backups/manifestes/sauvegarde.log 2>&1' | sudo tee /etc/cron.d/manifestes-sauvegarde
sudo -u manifestes /opt/manifestes/sauvegarde.sh
```
Attendu : `sauvegarde OK`. Copier `/var/backups/manifestes` hors du serveur (NAS / sauvegarde TERRA).

→ Continuer avec la **partie C**.

---

## B. Serveur Windows (Windows Server 2019 ou plus)

**B1. Installer les programmes** (tous gratuits) :

| Programme | Où | Pendant l'installation |
|---|---|---|
| Python 3.12 | python.org › Downloads › Windows | Cocher **« Add python.exe to PATH »** |
| PostgreSQL 17 | postgresql.org › Download › Windows | Installation complète ; noter le mot de passe de l'utilisateur `postgres` |
| Poppler | github.com/oschwartz10612/poppler-windows › Releases | Extraire dans `C:\poppler` |
| Tesseract OCR | github.com/UB-Mannheim/tesseract › Wiki | Installation par défaut |
| NSSM | nssm.cc › Download | Copier `win64\nssm.exe` dans `C:\Windows\System32` |
| Caddy | caddyserver.com › Download › Windows amd64 | Renommer en `caddy.exe` et placer dans `C:\caddy` |

Ajouter ces 3 dossiers au **PATH système** : Démarrer › « Modifier les variables d'environnement système » › Variables
d'environnement › *Path* (variables système) › Modifier › Nouveau :
`C:\Program Files\PostgreSQL\17\bin` · `C:\poppler\Library\bin` · `C:\Program Files\Tesseract-OCR`.
Puis **redémarrer le serveur** (le service de l'app ne voit le nouveau PATH qu'après un redémarrage).

**B2. Ouvrir l'invite de commandes administrateur** — Démarrer › taper `cmd` › clic droit sur « Invite de commandes »
› **Exécuter en tant qu'administrateur**. Toutes les commandes suivantes s'y tapent. Vérifier :
```
python --version
psql --version
pdftotext -v
tesseract --version
```
Attendu : `Python 3.12.x`, `psql (PostgreSQL) 17.x`, puis un numéro de version pour les deux derniers.

**B3. Installer le code de l'app** — clic droit sur le zip › Extraire tout › `C:\`. Renommer le dossier obtenu
`C:\Digitalisation-Manifestes-Terra` en `C:\manifestes`. Puis (quelques minutes) :
```
cd /d C:\manifestes
mkdir archive
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
Attendu : la dernière ligne commence par `Successfully installed`.

**B4. Créer la base et charger les données**
```
notepad deploiement\base_de_donnees\01_creer_base.sql
```
Remplacer `CHANGER_MOI` par `MOT_DE_PASSE`, enregistrer, fermer. Ensuite (le mot de passe de `postgres` est demandé une fois) :
```
chcp 65001
set PGCLIENTENCODING=UTF8
psql -U postgres -f deploiement\base_de_donnees\01_creer_base.sql
set DATABASE_URL=postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes
pg_restore --no-owner --no-privileges -d "%DATABASE_URL%" "CHEMIN\Export_Manifestes_AAAA-MM-JJ\manifestes_AAAA-MM-JJ.dump"
psql "%DATABASE_URL%" -v ON_ERROR_STOP=1 -f deploiement\base_de_donnees\02_schema_manifestes.sql
psql "%DATABASE_URL%" -f deploiement\base_de_donnees\03_verification.sql
```
`CHEMIN` = le dossier où se trouve l'export (ex. `C:\Users\NOM\Desktop`). Attendu : aucune ligne `ERROR`, puis `18` tables
et des nombres de lignes identiques à `comptages_supabase.txt`.

**B5. Copier les fichiers archivés** (valeurs du fichier des secrets, sans guillemets) :
```
set SUPABASE_URL=VALEUR
set SUPABASE_SERVICE_KEY=VALEUR
.venv\Scripts\python scripts\migrer_archive_supabase.py C:\manifestes\archive
```
Attendu : `Terminé : N copiés, 0 déjà présents, 0 erreur(s)`. Relançable sans risque.

**B6. Saisir les secrets** — coller le modèle de la partie **C1**, enregistrer, fermer, puis réserver le fichier aux administrateurs et au système :
```
notepad .streamlit\secrets.toml
icacls .streamlit\secrets.toml /inheritance:r /grant:r *S-1-5-32-544:F *S-1-5-18:F
```
Sur Windows : `ARCHIVE_DIR = "C:/manifestes/archive"` (barres obliques `/`).

**B7. Lancer l'app comme un service**
```
nssm install Manifestes C:\manifestes\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
nssm set Manifestes AppDirectory C:\manifestes
nssm start Manifestes
timeout /t 10
curl http://127.0.0.1:8501/_stcore/health
```
Attendu : `ok`.

**B8. Rendre l'app accessible en HTTPS** (remplacer `ADRESSE`, ex. `manifestes.terra.local`) :
```
notepad C:\caddy\Caddyfile
```
Contenu :
```
ADRESSE {
    reverse_proxy 127.0.0.1:8501
}
```
Puis :
```
nssm install Caddy C:\caddy\caddy.exe run --config C:\caddy\Caddyfile
nssm set Caddy AppDirectory C:\caddy
nssm start Caddy
netsh advfirewall firewall add rule name="Manifestes HTTPS" dir=in action=allow protocol=TCP localport=443
```
Certificat TERRA : ajouter dans le bloc la ligne `tls C:/chemin/cert.pem C:/chemin/cle.pem`.

**B9. Programmer la sauvegarde quotidienne** — remplacer `MOT_DE_PASSE` dans le script, puis le tester et le programmer :
```
notepad deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat
deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat
type C:\sauvegardes\manifestes\sauvegarde.log
schtasks /create /tn "Manifestes sauvegarde" /sc daily /st 02:30 /ru SYSTEM /tr "C:\manifestes\deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat"
```
Attendu : `sauvegarde OK`. Copier `C:\sauvegardes\manifestes` hors du serveur (NAS / sauvegarde TERRA).

→ Continuer avec la **partie C**.

---

## C. Commun aux deux serveurs

**C1. Modèle du fichier des secrets** — reprendre les valeurs du fichier remis par Charlie. Les lignes `SUPABASE_*` ne servent plus.
```toml
DATABASE_URL = "postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
ARCHIVE_DIR  = "/opt/manifestes/archive"       # Windows : "C:/manifestes/archive"

CONNEXION_PAR_COMPTE = true
BOOTSTRAP_ADMIN_PASSWORD = "VALEUR"            # code pour créer le 1er administrateur (C2)
APP_PASSWORD = "VALEUR"                        # ancien mot de passe commun, gardé pour le retour arrière

# Envoi des avis par e-mail — facultatif : sans SMTP_HOST, l'app fonctionne et rien n'est envoyé
SMTP_HOST = "smtp.office365.com"               # ou le relais SMTP TERRA
SMTP_PORT = 587
SMTP_STARTTLS = true
SMTP_USER = "manifestes@terra.ci"              # laisser vide si le relais n'exige pas d'authentification
SMTP_PASSWORD = "VALEUR"
SMTP_FROM = "manifestes@terra.ci"
AVIS_EMAIL_TO = "charles.kouadio@terra.ci"
AVIS_EMAIL_CC = "christian.danho@terra.ci"
APP_URL = "https://ADRESSE"
```
Après toute modification de ce fichier, redémarrer l'app : Linux `sudo systemctl restart manifestes` · Windows `nssm restart Manifestes`.

**C2. Premier administrateur et comptes**
1. Ouvrir `https://ADRESSE` : l'écran **« Première configuration »** s'affiche (une seule fois).
2. Créer le compte de Charlie : code = `BOOTSTRAP_ADMIN_PASSWORD`, groupe **Analyste Data**.
3. Se connecter, aller dans **Administration › Utilisateurs et droits** et créer votre compte (groupe **Administrateur IT**).
4. Créer les comptes des agents : « Nouvel utilisateur » › nom, prénom, e-mail, service, groupe › **Créer**.
   Un **mot de passe provisoire** s'affiche une seule fois : le remettre à la personne en main propre ; elle le change à sa
   première connexion. Conseil : reprendre le nom et le prénom déjà utilisés dans l'app, pour garder l'historique de chacun.
5. Groupes : 4 groupes existent au départ (Agent, Direction, Analyste Data, Administrateur IT). Pour en créer un :
   « Nouveau groupe » › nom › cocher les fonctionnalités › **Valider le groupe**.
6. Mot de passe oublié ou compte bloqué : « Modifier un utilisateur » › **Réinitialiser le mot de passe**.

**C3. Mettre à jour l'app plus tard** (nouvelle version fournie par Charlie) — remplacer les fichiers du code par ceux du
nouveau zip **sans toucher** à `.streamlit/secrets.toml`, `archive/` et `.venv/`, puis :
- Linux : `sudo -u manifestes /opt/manifestes/.venv/bin/pip install -r /opt/manifestes/requirements.txt` puis `sudo systemctl restart manifestes`
- Windows : `cd /d C:\manifestes` · `.venv\Scripts\pip install -r requirements.txt` · `nssm restart Manifestes`

**C4. Retour arrière**
- Problème de connexion par compte : `CONNEXION_PAR_COMPTE = false` dans les secrets, puis redémarrer l'app (retour au mot de passe commun).
- Problème de serveur : l'ancienne app sur Streamlit Cloud reste disponible tant que Supabase n'est pas supprimé.

**C5. Points d'attention**
- **Taille des envois** : 25 Mo par fichier. Caddy n'impose pas de limite ; avec **Nginx** ou **IIS**, autoriser au moins 30 Mo
  (Nginx : `client_max_body_size 30M;`, 1 Mo par défaut), et activer les **WebSocket** (sinon la page reste blanche).
- **Microsoft 365** : l'envoi SMTP authentifié (« SMTP AUTH ») est souvent désactivé par défaut ; l'activer pour la boîte d'expédition.
- **Mots de passe des agents** : 8 caractères minimum, lettres et chiffres, stockés hachés. 5 échecs bloquent le compte jusqu'à
  sa réinitialisation (C2, point 6).
- **Confidentialité** : l'export, les sauvegardes et le dossier `archive` contiennent des données TERRA. Accès restreint, jamais
  par e-mail. Supprimer le dossier d'export du serveur une fois la base chargée.
- **Clés Supabase** : à révoquer une fois l'app validée (Supabase › Project Settings › API).

# Installation de l'application Manifestes sur un serveur TERRA

Bonjour,

Ce guide decrit l'installation de l'application Manifestes sur un serveur TERRA. L'application utilise une base
PostgreSQL 17 et enregistre les fichiers archives (PDF, Excel) sur le disque du serveur. Chaque agent se connecte
avec son e-mail et son mot de passe, et vous gerez les comptes directement dans l'application.

Suivez la partie A (Linux, recommande) ou la partie B (Windows), puis la partie C. Les commandes se copient telles
quelles : il suffit de remplacer les mots en MAJUSCULES.

Charles Emmanuel Kouadio

## Avant de commencer

- Les elements joints a mon e-mail : le zip de l'application (les scripts de base de donnees sont dans
  `deploiement/base_de_donnees/`), le dossier d'export de la base et le fichier des secrets.
- Un serveur avec 2 coeurs, 4 Go de memoire, 20 Go de disque, et un acces internet pendant l'installation.
- Un mot de passe pour la base, compose uniquement de lettres et de chiffres. Il remplace `MOT_DE_PASSE` dans tout le guide.

---

## A. Serveur Linux (Ubuntu 24.04)

**A1. Copier les fichiers sur le serveur et s'y connecter**

Sur votre PC, ouvrez le dossier qui contient le zip et l'export, tapez `cmd` dans la barre d'adresse de l'explorateur,
puis Entree. Dans la fenetre qui s'ouvre :
```
scp Digitalisation-Manifestes-Terra_v7.43.3_main.zip UTILISATEUR@ADRESSE_SERVEUR:~/
scp -r Export_Manifestes_AAAA-MM-JJ UTILISATEUR@ADRESSE_SERVEUR:~/
ssh UTILISATEUR@ADRESSE_SERVEUR
```
Les commandes suivantes se tapent sur le serveur.

**A2. Installer les programmes** (appuyez sur Entree si une question s'affiche)
```bash
sudo apt update
sudo apt install -y unzip python3.12 python3.12-venv poppler-utils tesseract-ocr caddy postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt install -y postgresql-17
psql --version
```
Resultat attendu : `psql (PostgreSQL) 17.x`.

**A3. Installer l'application**
```bash
sudo useradd --system --home-dir /opt/manifestes --shell /usr/sbin/nologin manifestes
sudo unzip -q ~/Digitalisation-Manifestes-Terra_v7.43.3_main.zip -d /opt
sudo mv /opt/Digitalisation-Manifestes-Terra /opt/manifestes
sudo mkdir -p /opt/manifestes/archive
sudo chown -R manifestes:manifestes /opt/manifestes
sudo -u manifestes python3.12 -m venv /opt/manifestes/.venv
sudo -u manifestes /opt/manifestes/.venv/bin/pip install -r /opt/manifestes/requirements.txt
```
Resultat attendu : la derniere ligne commence par `Successfully installed`.

**A4. Creer la base et charger les donnees**
```bash
cd /opt/manifestes/deploiement/base_de_donnees
sudo nano 01_creer_base.sql
```
Remplacez `CHANGER_MOI` par `MOT_DE_PASSE`, puis enregistrez (Ctrl+O, Entree, Ctrl+X).
```bash
sudo -u postgres psql -f 01_creer_base.sql
export DATABASE_URL="postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
pg_restore --no-owner --no-privileges -d "$DATABASE_URL" ~/Export_Manifestes_AAAA-MM-JJ/manifestes_AAAA-MM-JJ.dump
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 02_schema_manifestes.sql
psql "$DATABASE_URL" -f 03_verification.sql
```
Resultat attendu : aucune ligne `ERROR` et 18 tables.

**A5. Recuperer les fichiers archives** (valeurs `SUPABASE_URL` et `SUPABASE_SERVICE_KEY` du fichier des secrets)
```bash
cd /opt/manifestes
sudo -u manifestes env SUPABASE_URL="VALEUR" SUPABASE_SERVICE_KEY="VALEUR" \
  .venv/bin/python scripts/migrer_archive_supabase.py /opt/manifestes/archive
```
Resultat attendu : `0 erreur(s)`.

**A6. Saisir les secrets**

Collez le modele de la partie C1, enregistrez, puis protegez le fichier :
```bash
sudo -u manifestes nano /opt/manifestes/.streamlit/secrets.toml
sudo chmod 600 /opt/manifestes/.streamlit/secrets.toml
```

**A7. Demarrer l'application comme un service**
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
Resultat attendu : `ok`. En cas de probleme : `sudo journalctl -u manifestes -n 50`.

**A8. Rendre l'application accessible en HTTPS** (remplacez `ADRESSE`, par exemple `manifestes.terra.local`)
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
Si vous utilisez un certificat TERRA, ajoutez dans le bloc : `tls /chemin/cert.pem /chemin/cle.pem`.

**A9. Programmer la sauvegarde quotidienne**
```bash
sudo mkdir -p /var/backups/manifestes && sudo chown manifestes:manifestes /var/backups/manifestes
sudo install -m 750 -o manifestes -g manifestes /opt/manifestes/deploiement/base_de_donnees/04_sauvegarde_quotidienne.sh /opt/manifestes/sauvegarde.sh
echo '30 2 * * * manifestes /opt/manifestes/sauvegarde.sh >> /var/backups/manifestes/sauvegarde.log 2>&1' | sudo tee /etc/cron.d/manifestes-sauvegarde
sudo -u manifestes /opt/manifestes/sauvegarde.sh
```
Resultat attendu : `sauvegarde OK`. Pensez a copier `/var/backups/manifestes` hors du serveur.

Passez ensuite a la partie C.

---

## B. Serveur Windows (Windows Server 2019 ou plus recent)

**B1. Installer les programmes**

| Programme | Telechargement | A faire |
|---|---|---|
| Python 3.12 | python.org | Cocher "Add python.exe to PATH" |
| PostgreSQL 17 | postgresql.org | Installation complete, noter le mot de passe de `postgres` |
| Poppler | github.com/oschwartz10612/poppler-windows | Extraire dans `C:\poppler` |
| Tesseract OCR | github.com/UB-Mannheim/tesseract | Installation par defaut |
| NSSM | nssm.cc | Copier `win64\nssm.exe` dans `C:\Windows\System32` |
| Caddy | caddyserver.com/download | Renommer en `caddy.exe` et placer dans `C:\caddy` |

Ajoutez ensuite ces 3 dossiers au Path systeme (Demarrer > "Modifier les variables d'environnement systeme" >
Variables d'environnement > Path > Modifier > Nouveau), puis redemarrez le serveur :
- `C:\Program Files\PostgreSQL\17\bin`
- `C:\poppler\Library\bin`
- `C:\Program Files\Tesseract-OCR`

**B2. Ouvrir l'invite de commandes en administrateur**

Demarrer > tapez `cmd` > clic droit sur "Invite de commandes" > "Executer en tant qu'administrateur".
Toutes les commandes suivantes se tapent dans cette fenetre. Verifiez d'abord les installations :
```
python --version
psql --version
pdftotext -v
tesseract --version
```
Chaque commande doit afficher un numero de version (Python 3.12 et PostgreSQL 17).

**B3. Installer l'application**

Faites un clic droit sur le zip > "Extraire tout" vers `C:\`, puis renommez le dossier en `C:\manifestes`.
```
cd /d C:\manifestes
mkdir archive
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```
Resultat attendu : la derniere ligne commence par `Successfully installed`.

**B4. Creer la base et charger les donnees**
```
notepad deploiement\base_de_donnees\01_creer_base.sql
```
Remplacez `CHANGER_MOI` par `MOT_DE_PASSE`, enregistrez et fermez. Remplacez ensuite `CHEMIN` par le dossier qui
contient l'export (par exemple `C:\Users\NOM\Desktop`) :
```
chcp 65001
set PGCLIENTENCODING=UTF8
psql -U postgres -f deploiement\base_de_donnees\01_creer_base.sql
set DATABASE_URL=postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes
pg_restore --no-owner --no-privileges -d "%DATABASE_URL%" "CHEMIN\Export_Manifestes_AAAA-MM-JJ\manifestes_AAAA-MM-JJ.dump"
psql "%DATABASE_URL%" -v ON_ERROR_STOP=1 -f deploiement\base_de_donnees\02_schema_manifestes.sql
psql "%DATABASE_URL%" -f deploiement\base_de_donnees\03_verification.sql
```
Resultat attendu : aucune ligne `ERROR` et 18 tables.

**B5. Recuperer les fichiers archives** (valeurs du fichier des secrets, sans guillemets)
```
set SUPABASE_URL=VALEUR
set SUPABASE_SERVICE_KEY=VALEUR
.venv\Scripts\python scripts\migrer_archive_supabase.py C:\manifestes\archive
```
Resultat attendu : `0 erreur(s)`.

**B6. Saisir les secrets**

Collez le modele de la partie C1 (avec `ARCHIVE_DIR = "C:/manifestes/archive"`), enregistrez, puis protegez le fichier :
```
notepad .streamlit\secrets.toml
icacls .streamlit\secrets.toml /inheritance:r /grant:r *S-1-5-32-544:F *S-1-5-18:F
```

**B7. Demarrer l'application comme un service**
```
nssm install Manifestes C:\manifestes\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
nssm set Manifestes AppDirectory C:\manifestes
nssm start Manifestes
timeout /t 10
curl http://127.0.0.1:8501/_stcore/health
```
Resultat attendu : `ok`.

**B8. Rendre l'application accessible en HTTPS** (remplacez `ADRESSE`, par exemple `manifestes.terra.local`)
```
notepad C:\caddy\Caddyfile
```
Collez ce contenu, puis enregistrez :
```
ADRESSE {
    reverse_proxy 127.0.0.1:8501
}
```
```
nssm install Caddy C:\caddy\caddy.exe run --config C:\caddy\Caddyfile
nssm set Caddy AppDirectory C:\caddy
nssm start Caddy
netsh advfirewall firewall add rule name="Manifestes HTTPS" dir=in action=allow protocol=TCP localport=443
```
Si vous utilisez un certificat TERRA, ajoutez dans le bloc : `tls C:/chemin/cert.pem C:/chemin/cle.pem`.

**B9. Programmer la sauvegarde quotidienne**

Remplacez `MOT_DE_PASSE` dans le script, enregistrez, puis lancez-le une premiere fois et programmez-le :
```
notepad deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat
deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat
type C:\sauvegardes\manifestes\sauvegarde.log
schtasks /create /tn "Manifestes sauvegarde" /sc daily /st 02:30 /ru SYSTEM /tr "C:\manifestes\deploiement\base_de_donnees\04_sauvegarde_quotidienne.bat"
```
Resultat attendu : `sauvegarde OK`. Pensez a copier `C:\sauvegardes\manifestes` hors du serveur.

Passez ensuite a la partie C.

---

## C. Etapes communes

**C1. Modele du fichier des secrets**

Reprenez les valeurs du fichier des secrets joint a mon e-mail. Les lignes `SUPABASE_` ne sont plus utilisees par l'application.
```toml
DATABASE_URL = "postgresql://manifestes:MOT_DE_PASSE@localhost:5432/manifestes"
ARCHIVE_DIR  = "/opt/manifestes/archive"       # Windows : "C:/manifestes/archive"

CONNEXION_PAR_COMPTE = true
BOOTSTRAP_ADMIN_PASSWORD = "VALEUR"
APP_PASSWORD = "VALEUR"

# Envoi des avis par e-mail (facultatif)
SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587
SMTP_STARTTLS = true
SMTP_USER = "manifestes@terra.ci"
SMTP_PASSWORD = "VALEUR"
SMTP_FROM = "manifestes@terra.ci"
AVIS_EMAIL_TO = "charles.kouadio@terra.ci"
AVIS_EMAIL_CC = "christian.danho@terra.ci"
APP_URL = "https://ADRESSE"
```
Apres chaque modification de ce fichier, redemarrez l'application :
Linux `sudo systemctl restart manifestes`, Windows `nssm restart Manifestes`.

**C2. Creer les comptes**
1. Ouvrez `https://ADRESSE`. L'ecran "Premiere configuration" s'affiche.
2. Nous creons ensemble mon compte, avec le code `BOOTSTRAP_ADMIN_PASSWORD` et le groupe Analyste Data.
3. Une fois connecte, allez dans Administration > Utilisateurs et droits et creez votre compte (groupe Administrateur IT).
4. Creez ensuite les comptes des agents. Un mot de passe provisoire s'affiche une seule fois : remettez-le a la personne,
   qui le changera a sa premiere connexion.
5. En cas d'oubli de mot de passe ou de compte bloque : Modifier un utilisateur > Reinitialiser le mot de passe.

**C3. Mettre a jour l'application**

Remplacez les fichiers par ceux du nouveau zip, sans toucher a `.streamlit/secrets.toml`, `archive/` et `.venv/`, puis :
- Linux : `sudo -u manifestes /opt/manifestes/.venv/bin/pip install -r /opt/manifestes/requirements.txt` puis `sudo systemctl restart manifestes`
- Windows : `.venv\Scripts\pip install -r requirements.txt` (depuis `C:\manifestes`) puis `nssm restart Manifestes`

**C4. Points d'attention**
- L'application accepte des fichiers jusqu'a 25 Mo. Avec Nginx ou IIS a la place de Caddy, autorisez au moins 30 Mo
  et activez les WebSocket (sinon la page reste blanche).
- Avec Microsoft 365, l'option "SMTP AUTH" doit etre activee pour la boite d'envoi.
- En cas de probleme de connexion des agents, passez `CONNEXION_PAR_COMPTE = false` dans les secrets et redemarrez :
  l'application revient au mot de passe commun.
- L'export, les sauvegardes et le dossier `archive` contiennent des donnees TERRA. Une fois la base chargee, merci de
  supprimer l'export du serveur ainsi que mon e-mail et ses pieces jointes.
- Le fichier des secrets ayant circule par e-mail, les cles Supabase seront a revoquer des que l'application est validee.

Merci pour votre aide. Je reste disponible pour toute question.

"""
Journalisation légère des traitements effectués dans l'application, en vue
du tableau de bord et de l'archive (historique, recherche, re-téléchargement).
Utilise SQLite (fichier local, aucune dépendance externe).

Toutes les données proviennent exclusivement des traitements réels effectués
depuis la page Structuration — rien n'est généré ni estimé ici.
"""
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def normalize_name(name: str) -> str:
    """Normalise un nom/prénom saisi librement pour éviter les doublons dus
    uniquement à la casse ou aux espaces (ex. 'KOUADIO Charles',
    'kouadio charles' et 'Kouadio  Charles' donnent tous 'Kouadio Charles').

    Utilisé à la fois pour la valeur stockée/affichée (auteur) et pour le
    rapprochement insensible à la casse (get_known_agents, soutiens d'avis) —
    sans ça, deux variantes de casse du même agent apparaissent comme deux
    personnes distinctes dans les suggestions et peuvent chacune "soutenir"
    le même message séparément.

    Limite connue : une capitalisation naïve mot par mot ne gère pas tous les
    cas de noms composés/particules (ex. 'McCarthy' → 'Mccarthy') — acceptable
    ici vu l'usage (noms français), à revoir si besoin plus tard."""
    if not name:
        return ""
    cleaned = re.sub(r"\s+", " ", name.strip())

    def _cap_token(tok: str) -> str:
        parts = re.split(r"([-'])", tok)
        return "".join(p.capitalize() if p not in ("-", "'") else p for p in parts)

    return " ".join(_cap_token(w) for w in cleaned.split(" ") if w)


def _user_data_dir():
    """Dossier de données PERSISTANT, séparé du dossier de l'application.

    Avant : la base SQLite et l'archive vivaient à côté du code
    (`Path(__file__).parent`). Résultat : à chaque nouvelle version de l'app
    livrée (nouveau dossier dézippé), l'historique et les fichiers archivés
    précédents étaient invisibles pour la nouvelle copie — pas perdus sur
    disque, mais "abandonnés" dans l'ancien dossier. Corrigé en stockant les
    données dans un dossier utilisateur stable (indépendant de l'endroit où
    l'app est dézippée), qui survit donc à une mise à jour de l'application.
    """
    base = os.environ.get("APPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home())
    d = Path(base) / "StructurationManifestesGrimaldi"
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = _user_data_dir()
DB_PATH = DATA_DIR / "traitement_log.db"
IDENTITY_PATH = DATA_DIR / "user_identity.json"

ARCHIVE_DIR = DATA_DIR / "archive"
EXPORTS_DIR = ARCHIVE_DIR / "exports"
SOURCES_DIR = ARCHIVE_DIR / "sources"


def _migrate_legacy_data_dir():
    """Reprend automatiquement, une seule fois, une base/archive laissée dans
    l'ancien emplacement (à côté du code) par une version précédente de
    l'app — pour ne pas faire perdre l'historique déjà accumulé par
    l'utilisateur lors de cette mise à jour."""
    legacy_dir = Path(__file__).parent
    legacy_db = legacy_dir / "traitement_log.db"
    legacy_archive = legacy_dir / "archive"
    if not DB_PATH.exists() and legacy_db.exists():
        shutil.copy2(legacy_db, DB_PATH)
    if not ARCHIVE_DIR.exists() and legacy_archive.exists():
        shutil.copytree(legacy_archive, ARCHIVE_DIR)


_migrate_legacy_data_dir()

SCHEMA = """
CREATE TABLE IF NOT EXISTS traitements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    agent TEXT NOT NULL,
    fichier TEXT NOT NULL,
    navire TEXT,
    voyage TEXT,
    nb_bl INTEGER,
    nb_vehicules INTEGER,
    nb_conteneurs INTEGER,
    nb_colis INTEGER,
    nb_transit INTEGER,
    duree_traitement_sec REAL
);
"""

DEMO_PREFIX = "DEMO_"

# Colonnes ajoutées après la création initiale de la table — migration douce
# (ALTER TABLE) pour préserver l'historique réel déjà présent chez l'utilisateur.
_MIGRATIONS = {
    "duree_traitement_sec": "REAL",
    "export_path": "TEXT",   # chemin relatif vers l'Excel archivé (archive/exports/...)
    "pdf_path": "TEXT",      # chemin relatif vers le PDF source archivé (archive/sources/...)
    "verifie": "INTEGER DEFAULT 0",  # 0/1 — relecture humaine effectuée ou non
    "type_cargo": "TEXT",    # ex: "🚗 Véhicules uniquement", "🔀 Mixte (...)" — voir classify_cargo_type
    "service": "TEXT",       # service de l'agent (Reporting, Opérations, Planification, …)
    "role": "TEXT",          # rôle de l'agent (Agent, Chef de service, Chef de la planification, …)
}

# Table des numéros de B/L individuels de chaque traitement (14/08 v6).
# Nécessaire pour distinguer un vrai doublon (mêmes B/L déjà enregistrés)
# d'un nouveau port de chargement pour le même navire/voyage (B/L différents
# — ex. GTC0526 a un manifeste distinct par port : Amsterdam, Anvers,
# Hambourg, Lagos, Tilbury, tous "même navire/voyage" mais aucun B/L en
# commun). L'ancienne détection (navire+voyage seuls) aurait signalé chacun
# de ces ports comme doublon du précédent, à tort.
_BL_SCHEMA = """
CREATE TABLE IF NOT EXISTS traitement_bl (
    traitement_id INTEGER NOT NULL,
    bl_numero TEXT NOT NULL,
    FOREIGN KEY (traitement_id) REFERENCES traitements(id)
);
"""
_BL_INDEX = "CREATE INDEX IF NOT EXISTS idx_traitement_bl_numero ON traitement_bl(bl_numero);"

# Table des avis / commentaires laissés par les agents sur l'application.
# parent_id NULL = commentaire racine ("demande" catégorisée et suivie) ;
# sinon = réponse dans le fil (pas de catégorie/statut propre, fait partie
# du fil de discussion de la demande racine).
_AVIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS avis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    horodatage TEXT NOT NULL,
    auteur TEXT NOT NULL,
    service TEXT,
    role TEXT,
    message TEXT NOT NULL,
    parent_id INTEGER,
    FOREIGN KEY (parent_id) REFERENCES avis(id)
);
"""

# Colonnes ajoutées après la création initiale de la table avis (v6.1) —
# migration douce (ALTER TABLE), même principe que _MIGRATIONS ci-dessus.
_AVIS_MIGRATIONS = {
    "categorie":   "TEXT",  # 'Fonctionnement' | 'Interface' | 'Fonctionnalité' | 'Discussion' (racines uniquement)
    "statut":      "TEXT",  # 'Nouveau' | 'En cours' | 'Résolu' | 'Refusé' (racines uniquement)
    "version_app": "TEXT",  # version de l'app au moment du post — traçabilité pour les mises à jour futures
}

# Soutiens ("j'appuie cette demande") — une ligne par (message, personne).
# Clé sur le nom NORMALISÉ pour qu'une même personne ne puisse pas compter
# deux fois pour avoir tapé son nom avec une casse différente d'une session
# à l'autre (même souci que la détection de doublon des agents connus).
_AVIS_SOUTIENS_SCHEMA = """
CREATE TABLE IF NOT EXISTS avis_soutiens (
    avis_id INTEGER NOT NULL,
    auteur_normalise TEXT NOT NULL,
    horodatage TEXT NOT NULL,
    PRIMARY KEY (avis_id, auteur_normalise),
    FOREIGN KEY (avis_id) REFERENCES avis(id)
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    conn.execute(_BL_SCHEMA)
    conn.execute(_BL_INDEX)
    conn.execute(_AVIS_SCHEMA)
    conn.execute(_AVIS_SOUTIENS_SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(traitements)").fetchall()]
    for col, coltype in _MIGRATIONS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE traitements ADD COLUMN {col} {coltype}")
    avis_cols = [r[1] for r in conn.execute("PRAGMA table_info(avis)").fetchall()]
    for col, coltype in _AVIS_MIGRATIONS.items():
        if col not in avis_cols:
            conn.execute(f"ALTER TABLE avis ADD COLUMN {col} {coltype}")
    conn.commit()
    return conn


def init_db():
    _connect().close()


def log_traitement(agent, fichier, navire, voyage, nb_bl, nb_vehicules, nb_conteneurs,
                    nb_colis, nb_transit, duree_sec=None, export_path=None, pdf_path=None,
                    type_cargo=None, bl_numeros=None, service=None, role=None):
    """Enregistre un traitement et retourne l'id de la ligne créée (utile pour
    la lier ensuite à ses fichiers archivés). bl_numeros (liste des B/L
    individuellement présents dans ce traitement) alimente la détection de
    doublon réelle — voir find_duplicate_bl(). service et role identifient
    l'agent (ex. "Reporting", "Chef de service") pour la vue Dashboard par rôle."""
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO traitements
           (horodatage, agent, fichier, navire, voyage, nb_bl, nb_vehicules,
            nb_conteneurs, nb_colis, nb_transit, duree_traitement_sec,
            export_path, pdf_path, type_cargo, service, role)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            agent, fichier, navire, voyage,
            nb_bl, nb_vehicules, nb_conteneurs, nb_colis, nb_transit, duree_sec,
            export_path, pdf_path, type_cargo, service, role,
        ),
    )
    new_id = cur.lastrowid
    if bl_numeros:
        conn.executemany(
            "INSERT INTO traitement_bl (traitement_id, bl_numero) VALUES (?, ?)",
            [(new_id, bl) for bl in dict.fromkeys(bl_numeros) if bl],
        )
    conn.commit()
    conn.close()
    return new_id


def read_log():
    """Retourne l'historique des traitements avec colonnes dérivées utiles
    au tableau de bord et à l'archive (date, volume total). Le regroupement
    par semaine/mois est fait à l'affichage (resample) plutôt que stocké ici."""
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM traitements ORDER BY horodatage DESC", conn)
    conn.close()
    if df.empty:
        return df
    df["horodatage"] = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
    df["date"] = df["horodatage"].dt.date
    for col in ("nb_vehicules", "nb_conteneurs", "nb_colis"):
        if col not in df.columns:
            df[col] = 0
    df["volume_total"] = df[["nb_vehicules", "nb_conteneurs", "nb_colis"]].sum(axis=1)
    if "verifie" not in df.columns:
        df["verifie"] = 0
    df["verifie"] = df["verifie"].fillna(0).astype(int).astype(bool)
    for col in ("export_path", "pdf_path"):
        if col not in df.columns:
            df[col] = None
        # SQLite NULL devient NaN (float) via pandas, ce qui casse les
        # vérifications truthy classiques (bool(nan) vaut True) — on
        # normalise donc explicitement en None ici, une fois pour toutes.
        df[col] = df[col].where(df[col].notna(), None)
    if "type_cargo" not in df.columns:
        df["type_cargo"] = "—"
    df["type_cargo"] = df["type_cargo"].fillna("—")
    for col in ("service", "role"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("")
    return df


def has_data():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM traitements").fetchone()[0]
    conn.close()
    return n > 0


def get_known_agents():
    """Retourne la liste des agents enregistrés, triée par fréquence d'usage
    décroissante — pour pré-remplir la liste de suggestions dans la page
    Structuration. Chaque entrée est un dict avec les clés : agent, service,
    role (dernières valeurs connues pour cet agent), n (nb de traitements).
    Retourne [] si la base est vide ou ne contient que des agents anonymes.

    Regroupe par nom NORMALISÉ (insensible à la casse/espaces) plutôt que par
    chaîne exacte : sans ça, 'KOUADIO Charles' et 'kouadio charles' saisis à
    des moments différents apparaissent comme deux agents distincts dans la
    liste de suggestions, ce qui produit des doublons visibles et fausse le
    classement par fréquence d'usage."""
    conn = _connect()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(traitements)").fetchall()]
    if "service" in cols and "role" in cols:
        df = pd.read_sql_query(
            """SELECT agent, service, role, horodatage FROM traitements
               WHERE agent IS NOT NULL AND agent != ''
               ORDER BY horodatage ASC""",
            conn,
        )
    else:
        df = pd.read_sql_query(
            """SELECT agent, horodatage FROM traitements
               WHERE agent IS NOT NULL AND agent != ''
               ORDER BY horodatage ASC""",
            conn,
        )
        df["service"] = ""
        df["role"] = ""
    conn.close()
    if df.empty:
        return []
    df["service"] = df["service"].fillna("")
    df["role"] = df["role"].fillna("")
    df["agent_normalise"] = df["agent"].apply(normalize_name)

    def _last_non_empty(series):
        for v in reversed(series.tolist()):
            if v:
                return v
        return ""

    grouped = (
        df.groupby("agent_normalise")
        .agg(
            agent=("agent_normalise", "first"),
            service=("service", _last_non_empty),
            role=("role", _last_non_empty),
            n=("agent_normalise", "count"),
        )
        .reset_index(drop=True)
        .sort_values("n", ascending=False)
    )
    return grouped.to_dict("records")


def _get_known_values(column: str, defaults: list[str] = ()) -> list[str]:
    """Valeurs déjà utilisées pour une colonne texte libre (service, role),
    fusionnées avec une liste de valeurs par défaut, dédupliquées sans tenir
    compte de la casse (garde la première graphie rencontrée). Alimente les
    sélecteurs "liste + saisie libre" — toute valeur personnalisée saisie une
    fois par un agent devient automatiquement une suggestion pour les autres."""
    conn = _connect()
    vals = list(defaults)
    for table in ("traitements", "avis"):
        try:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if column not in cols:
                continue
            rows = conn.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
            ).fetchall()
            vals.extend(r[0] for r in rows)
        except sqlite3.OperationalError:
            pass
    conn.close()
    seen = {}
    for v in vals:
        v = (v or "").strip()
        key = v.lower()
        if key and key not in seen:
            seen[key] = v
    return sorted(seen.values())


def get_known_services(defaults: list[str] = ()) -> list[str]:
    """Services déjà utilisés (traitements + avis) fusionnés avec des
    valeurs par défaut — alimente un sélecteur "liste + Autre" plutôt qu'une
    liste figée, pour que chaque service personnalisé saisi une fois profite
    ensuite à tout le monde."""
    return _get_known_values("service", defaults)


def get_known_roles(defaults: list[str] = ()) -> list[str]:
    """Rôles déjà utilisés (traitements + avis) fusionnés avec des valeurs
    par défaut — même principe que get_known_services()."""
    return _get_known_values("role", defaults)


def set_verifie(row_id, verifie):
    """Marque (ou démarque) un manifeste comme vérifié — utilisé depuis la
    page Archives après relecture par l'analyste."""
    conn = _connect()
    conn.execute("UPDATE traitements SET verifie = ? WHERE id = ?", (1 if verifie else 0, int(row_id)))
    conn.commit()
    conn.close()


def find_similar(navire, voyage):
    """Retourne les traitements déjà enregistrés pour le même navire ET le même
    voyage — usage informatif seulement (ex. lister l'historique d'un voyage).
    Un même code voyage réutilisé par un navire différent n'est PAS un
    doublon (normal dans ce secteur) : les deux critères doivent correspondre.
    ⚠️ Ne PAS utiliser ceci pour bloquer un import : un même navire/voyage a
    normalement UN manifeste distinct par port de chargement (ex. GTC0526 :
    Amsterdam, Anvers, Hambourg, Lagos, Tilbury), donc ce critère seul
    signalerait à tort un nouveau port comme doublon. Voir find_duplicate_bl()."""
    if not navire or not voyage or navire == "(navire non détecté)":
        return pd.DataFrame()
    conn = _connect()
    df = pd.read_sql_query(
        "SELECT horodatage, agent, fichier, nb_bl FROM traitements "
        "WHERE navire = ? AND voyage = ? ORDER BY horodatage DESC",
        conn, params=(navire, voyage),
    )
    conn.close()
    return df


def find_duplicate_bl(navire, voyage, bl_numeros):
    """Détection de doublon réelle, utilisée pour BLOQUER un import.

    Un doublon = même navire, même voyage, ET au moins un numéro de B/L déjà
    enregistré (= le même connaissement a déjà été structuré — reprise du
    même fichier ou d'un fichier qui le recouvre). Un nouveau port de
    chargement pour le même navire/voyage a des B/L entièrement différents et
    n'est donc jamais considéré comme un doublon, même si navire+voyage sont
    identiques à un traitement précédent.

    Retourne un DataFrame (vide si aucun doublon) : une ligne par traitement
    antérieur concerné, avec la liste des B/L en commun."""
    if not navire or not voyage or navire == "(navire non détecté)" or not bl_numeros:
        return pd.DataFrame()
    bl_set = set(dict.fromkeys(b for b in bl_numeros if b))
    if not bl_set:
        return pd.DataFrame()
    conn = _connect()
    placeholders = ",".join("?" * len(bl_set))
    df = pd.read_sql_query(
        f"""
        SELECT t.id, t.horodatage, t.agent, t.fichier, tb.bl_numero
        FROM traitement_bl tb
        JOIN traitements t ON t.id = tb.traitement_id
        WHERE t.navire = ? AND t.voyage = ? AND tb.bl_numero IN ({placeholders})
        ORDER BY t.horodatage DESC
        """,
        conn, params=(navire, voyage, *bl_set),
    )
    conn.close()
    if df.empty:
        return df
    grouped = (
        df.groupby(["id", "horodatage", "agent", "fichier"])["bl_numero"]
        .apply(lambda s: sorted(set(s)))
        .reset_index()
        .rename(columns={"bl_numero": "bl_communs"})
        .sort_values("horodatage", ascending=False)
    )
    return grouped


def clear_demo_data():
    """Purge d'éventuelles lignes de démonstration héritées d'une version
    précédente de l'app (préfixe DEMO_). N'insère jamais rien — nettoyage
    uniquement. Sans effet (et sans coût notable) si aucune n'existe."""
    conn = _connect()
    conn.execute("DELETE FROM traitements WHERE fichier LIKE ?", (f"{DEMO_PREFIX}%",))
    conn.commit()
    conn.close()


def clear_log():
    """Vide tout l'historique (réel + démo). À utiliser avec prudence — ne
    supprime pas les fichiers déjà archivés sur disque (archive/)."""
    conn = _connect()
    conn.execute("DELETE FROM traitements")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Identité utilisateur — persistée en JSON dans DATA_DIR.
# Permet à l'agent de ne saisir son nom/service/rôle qu'une seule fois ;
# l'app les recharge automatiquement à chaque lancement.
# ---------------------------------------------------------------------------
def save_user_identity(name: str, service: str, role: str) -> None:
    """Sauvegarde l'identité de l'utilisateur local dans un fichier JSON.
    Écrase silencieusement l'entrée précédente (un seul utilisateur par poste)."""
    IDENTITY_PATH.write_text(
        json.dumps({"name": name.strip(), "service": service, "role": role},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def load_user_identity() -> dict:
    """Charge l'identité sauvegardée. Retourne {} si aucune n'a encore été
    enregistrée (premier lancement) ou si le fichier est illisible."""
    if not IDENTITY_PATH.exists():
        return {}
    try:
        data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
        # Validation minimale : les 3 clés doivent être présentes et non vides
        if all(data.get(k) for k in ("name", "service", "role")):
            return data
        return {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Avis & commentaires — "demandes" catégorisées et suivies (racines) + fil de
# discussion (réponses), soutien par les pairs, statut de traitement.
# ---------------------------------------------------------------------------
CATEGORIES_AVIS = ["Fonctionnement", "Interface", "Fonctionnalité", "Discussion"]
STATUTS_AVIS = ["Nouveau", "En cours", "Résolu", "Refusé"]


def save_avis(auteur: str, service: str, role: str, message: str,
              parent_id: int | None = None, categorie: str | None = None,
              version_app: str | None = None) -> int:
    """Enregistre un commentaire (ou une réponse si parent_id est fourni).
    Le nom de l'auteur est normalisé (voir normalize_name) pour que deux
    variantes de casse du même agent soient traitées comme une seule personne
    partout où le nom sert de clé (suggestions, soutiens).

    Une demande racine (parent_id=None) reçoit automatiquement le statut
    'Nouveau' et la version de l'app au moment du post (traçabilité pour le
    triage lors des mises à jour futures) ; une réponse n'a ni catégorie ni
    statut propre (elle fait partie du fil de la demande racine).
    Retourne l'id de la ligne créée."""
    conn = _connect()
    statut = "Nouveau" if parent_id is None else None
    cur = conn.execute(
        """INSERT INTO avis (horodatage, auteur, service, role, message, parent_id,
                              categorie, statut, version_app)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         normalize_name(auteur), service, role, message.strip(), parent_id,
         categorie if parent_id is None else None, statut, version_app),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_avis(avis_id: int, new_message: str) -> None:
    """Modifie le texte d'un commentaire existant (auteur inchangé, horodatage initial conservé)."""
    conn = _connect()
    conn.execute("UPDATE avis SET message = ? WHERE id = ?", (new_message.strip(), int(avis_id)))
    conn.commit()
    conn.close()


def update_avis_statut(avis_id: int, statut: str) -> None:
    """Change le statut d'une demande racine (Nouveau / En cours / Résolu / Refusé) —
    c'est le mécanisme de suivi : sans statut, le soutien seul indique ce qui
    est populaire mais pas ce qui a été traité."""
    conn = _connect()
    conn.execute("UPDATE avis SET statut = ? WHERE id = ?", (statut, int(avis_id)))
    conn.commit()
    conn.close()


def toggle_soutien(avis_id: int, auteur: str) -> bool:
    """Bascule le soutien d'un message par cette personne : l'ajoute s'il est
    absent, le retire s'il existe déjà (comportement type "j'aime" à bascule).
    Le nom est normalisé pour qu'une même personne ne compte jamais deux fois
    sous deux graphies différentes. Retourne True si le message est désormais
    soutenu par cette personne, False s'il vient d'être retiré."""
    auteur_norm = normalize_name(auteur)
    conn = _connect()
    exists = conn.execute(
        "SELECT 1 FROM avis_soutiens WHERE avis_id = ? AND auteur_normalise = ?",
        (int(avis_id), auteur_norm),
    ).fetchone()
    if exists:
        conn.execute(
            "DELETE FROM avis_soutiens WHERE avis_id = ? AND auteur_normalise = ?",
            (int(avis_id), auteur_norm),
        )
        soutenu = False
    else:
        conn.execute(
            "INSERT INTO avis_soutiens (avis_id, auteur_normalise, horodatage) VALUES (?, ?, ?)",
            (int(avis_id), auteur_norm, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        soutenu = True
    conn.commit()
    conn.close()
    return soutenu


def read_soutiens() -> pd.DataFrame:
    """Retourne tous les soutiens (avis_id, auteur_normalise) en une seule
    requête — utilisé pour calculer les compteurs par message et l'état du
    bouton (déjà soutenu ou non par la personne courante) sans requêter à
    chaque ligne affichée."""
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM avis_soutiens", conn)
    conn.close()
    return df


def read_avis() -> pd.DataFrame:
    """Retourne tous les avis/commentaires triés du plus récent au plus ancien.
    Colonnes : id, horodatage, auteur, service, role, message, parent_id,
    categorie, statut, version_app.

    Les lignes créées avant l'ajout de ces 3 dernières colonnes (v6.1) ont
    categorie/statut NULL en base — on leur applique ici un défaut cohérent
    ('Discussion' / 'Nouveau' pour les racines) plutôt que de les afficher
    vides, pour qu'elles restent visibles et filtrables normalement."""
    conn = _connect()
    df = pd.read_sql_query(
        "SELECT * FROM avis ORDER BY horodatage DESC", conn
    )
    conn.close()
    if df.empty:
        return df
    df["horodatage"] = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
    df["parent_id"] = df["parent_id"].where(df["parent_id"].notna(), None)
    for col in ("service", "role"):
        df[col] = df[col].fillna("")
    is_root = df["parent_id"].isna()
    if "categorie" not in df.columns:
        df["categorie"] = None
    df.loc[is_root & df["categorie"].isna(), "categorie"] = "Discussion"
    if "statut" not in df.columns:
        df["statut"] = None
    df.loc[is_root & df["statut"].isna(), "statut"] = "Nouveau"
    if "version_app" not in df.columns:
        df["version_app"] = ""
    df["version_app"] = df["version_app"].fillna("")
    return df


# ---------------------------------------------------------------------------
# Archive — stockage des fichiers (PDF source + Excel structuré) associés à
# chaque traitement, pour consultation et re-téléchargement à tout moment.
# ---------------------------------------------------------------------------
def _ensure_archive_dirs():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)


def save_export_excel(data):
    """Sauvegarde un classeur Excel généré dans l'archive et retourne son
    chemin relatif (stocké en base — reste valide si le dossier de l'app est
    déplacé ou copié)."""
    _ensure_archive_dirs()
    name = f"{uuid.uuid4().hex}.xlsx"
    (EXPORTS_DIR / name).write_bytes(data)
    return f"archive/exports/{name}"


def save_source_pdf(data):
    """Sauvegarde le PDF source dans l'archive et retourne son chemin relatif."""
    _ensure_archive_dirs()
    name = f"{uuid.uuid4().hex}.pdf"
    (SOURCES_DIR / name).write_bytes(data)
    return f"archive/sources/{name}"


def delete_traitement(row_id: int) -> None:
    """Supprime un traitement de la base ainsi que ses fichiers archivés sur disque.

    Cascade manuelle :
    - Supprime les B/L associés dans traitement_bl.
    - Supprime l'Excel exporté et le PDF source s'ils existent encore sur disque.
    - Supprime la ligne principale dans traitements.

    Idempotent : sans effet si l'id n'existe plus."""
    conn = _connect()
    row = conn.execute(
        "SELECT export_path, pdf_path FROM traitements WHERE id = ?", (int(row_id),)
    ).fetchone()
    if row:
        for relpath in row:
            if relpath:
                # Résolution dans DATA_DIR puis fallback legacy
                for base in (DATA_DIR, Path(__file__).parent):
                    p = base / relpath
                    if p.exists():
                        try:
                            p.unlink()
                        except OSError:
                            pass
                        break
        conn.execute("DELETE FROM traitement_bl WHERE traitement_id = ?", (int(row_id),))
        conn.execute("DELETE FROM traitements WHERE id = ?", (int(row_id),))
    conn.commit()
    conn.close()


def archive_file_path(relpath):
    """Résout un chemin relatif stocké en base vers un chemin absolu sur
    disque. Retourne None si absent (ex: ancien traitement, ou extraction
    vide n'ayant généré aucun Excel) — y compris pour un NaN pandas (issu
    d'une valeur NULL en base), qui est truthy et ne doit pas être traité
    comme un chemin valide."""
    if not isinstance(relpath, str) or not relpath:
        return None
    p = DATA_DIR / relpath
    if p.exists():
        return p
    # Filet de sécurité : anciennes entrées enregistrées avant la migration
    # vers le dossier de données persistant (voir _migrate_legacy_data_dir).
    legacy_p = Path(__file__).parent / relpath
    return legacy_p if legacy_p.exists() else None

"""
Journalisation légère des traitements effectués dans l'application, en vue
du tableau de bord et de l'archive (historique, recherche, re-téléchargement).
Utilise SQLite (fichier local, aucune dépendance externe).

Toutes les données proviennent exclusivement des traitements réels effectués
depuis la page Structuration — rien n'est généré ni estimé ici.
"""
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


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
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(traitements)").fetchall()]
    for col, coltype in _MIGRATIONS.items():
        if col not in cols:
            conn.execute(f"ALTER TABLE traitements ADD COLUMN {col} {coltype}")
    conn.commit()
    return conn


def init_db():
    _connect().close()


def log_traitement(agent, fichier, navire, voyage, nb_bl, nb_vehicules, nb_conteneurs,
                    nb_colis, nb_transit, duree_sec=None, export_path=None, pdf_path=None,
                    type_cargo=None):
    """Enregistre un traitement et retourne l'id de la ligne créée (utile pour
    la lier ensuite à ses fichiers archivés)."""
    conn = _connect()
    cur = conn.execute(
        """INSERT INTO traitements
           (horodatage, agent, fichier, navire, voyage, nb_bl, nb_vehicules,
            nb_conteneurs, nb_colis, nb_transit, duree_traitement_sec,
            export_path, pdf_path, type_cargo)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            agent, fichier, navire, voyage,
            nb_bl, nb_vehicules, nb_conteneurs, nb_colis, nb_transit, duree_sec,
            export_path, pdf_path, type_cargo,
        ),
    )
    conn.commit()
    new_id = cur.lastrowid
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
    return df


def has_data():
    conn = _connect()
    n = conn.execute("SELECT COUNT(*) FROM traitements").fetchone()[0]
    conn.close()
    return n > 0


def set_verifie(row_id, verifie):
    """Marque (ou démarque) un manifeste comme vérifié — utilisé depuis la
    page Archives après relecture par l'analyste."""
    conn = _connect()
    conn.execute("UPDATE traitements SET verifie = ? WHERE id = ?", (1 if verifie else 0, int(row_id)))
    conn.commit()
    conn.close()


def find_similar(navire, voyage):
    """Retourne les traitements déjà enregistrés pour le même navire ET le même
    voyage — utilisé pour repérer un doublon avant d'enregistrer un nouveau
    traitement. Un même code voyage réutilisé par un navire différent n'est
    PAS un doublon (normal dans ce secteur) : les deux critères doivent
    correspondre. Inclut les volumes déjà enregistrés pour distinguer un vrai
    doublon (mêmes chiffres) d'une mise à jour (chiffres différents)."""
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

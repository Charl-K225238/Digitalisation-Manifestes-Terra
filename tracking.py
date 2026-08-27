"""
Journalisation des traitements effectués dans l'application, en vue du
tableau de bord et de l'archive (historique, recherche, re-téléchargement).

Stockage : Supabase (PostgreSQL managé + Storage de fichiers). Nécessaire
car Streamlit Community Cloud héberge l'app dans un conteneur ÉPHÉMÈRE — son
disque local est réinitialisé à chaque redéploiement, redémarrage après
inactivité, ou mise à jour du code. Un stockage local (SQLite + fichiers sur
disque) y perd donc silencieusement toutes les données archivées à intervalle
régulier. Supabase, hébergé séparément, persiste réellement les données quel
que soit le cycle de vie du conteneur applicatif, et les partage nativement
entre tous les utilisateurs connectés (un seul projet Supabase pour toute
l'équipe).

Configuration requise (secrets Streamlit — voir .streamlit/secrets.toml en
local, ou "Secrets" dans les réglages de l'app sur Streamlit Cloud) :
    SUPABASE_DB_URL       Connection string Postgres (pooler transaction,
                           port 6543 — recommandé pour les environnements
                           serverless comme Streamlit Cloud).
    SUPABASE_URL           URL du projet (ex: https://xxxx.supabase.co).
    SUPABASE_SERVICE_KEY   Clé "service_role" (Project Settings → API).

Schéma SQL et bucket de stockage à créer une seule fois — voir
supabase_schema.sql fourni à côté de ce fichier.
"""
import hashlib
import re
import secrets
import uuid
from datetime import datetime, timezone

import pandas as pd
import psycopg2
import psycopg2.extras
import requests
import streamlit as st


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


DEMO_PREFIX = "DEMO_"

# Bucket Supabase Storage unique (privé) — sous-dossiers par type de fichier,
# même arborescence logique que l'ancien stockage disque.
_STORAGE_BUCKET = "manifestes-archive"


# ---------------------------------------------------------------------------
# Connexion PostgreSQL (Supabase) — une connexion par appel, fermée aussitôt.
# Volume d'usage de cette app (quelques agents, traitements ponctuels) ne
# justifie pas de pool de connexions ; simplicité > performance ici.
# ---------------------------------------------------------------------------
def _secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        raise RuntimeError(
            f"Configuration manquante : le secret '{key}' n'est pas défini. "
            "Ajoutez SUPABASE_DB_URL, SUPABASE_URL et SUPABASE_SERVICE_KEY "
            "dans les secrets de l'application (voir supabase_schema.sql pour "
            "la procédure de configuration)."
        )


def _connect():
    conn = psycopg2.connect(_secret("SUPABASE_DB_URL"))
    conn.autocommit = False
    return conn


def init_db():
    """Vérifie simplement que la connexion fonctionne — le schéma est créé
    une fois pour toutes via supabase_schema.sql dans l'éditeur SQL Supabase,
    pas depuis l'app (évite de donner à l'app des droits DDL en production)."""
    conn = _connect()
    conn.close()


# ---------------------------------------------------------------------------
# Stockage de fichiers — Supabase Storage (REST), remplace le disque local.
# ---------------------------------------------------------------------------
def _storage_headers(content_type: str = "application/octet-stream") -> dict:
    key = _secret("SUPABASE_SERVICE_KEY")
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": content_type,
    }


def _storage_upload(path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Envoie un fichier dans le bucket archive et retourne son chemin
    relatif (identifiant stocké en base — indépendant de tout disque local)."""
    base_url = _secret("SUPABASE_URL").rstrip("/")
    url = f"{base_url}/storage/v1/object/{_STORAGE_BUCKET}/{path}"
    resp = requests.post(url, headers=_storage_headers(content_type), data=data, timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Échec de l'envoi vers l'archive distante ({resp.status_code}) : {resp.text[:300]}")
    return path


def get_archive_file(relpath: str) -> bytes | None:
    """Télécharge un fichier archivé depuis Supabase Storage. Retourne None
    si le chemin est vide/absent ou si le fichier n'existe plus (ex. entrée
    en base sans fichier associé) — jamais d'exception pour un cas normal,
    pour que l'affichage puisse simplement masquer le bouton correspondant."""
    if not relpath or not isinstance(relpath, str):
        return None
    try:
        base_url = _secret("SUPABASE_URL").rstrip("/")
        url = f"{base_url}/storage/v1/object/{_STORAGE_BUCKET}/{relpath}"
        resp = requests.get(url, headers=_storage_headers(), timeout=30)
        if resp.status_code == 200:
            return resp.content
        return None
    except Exception:
        return None


def _storage_delete(relpath: str) -> None:
    if not relpath:
        return
    try:
        base_url = _secret("SUPABASE_URL").rstrip("/")
        url = f"{base_url}/storage/v1/object/{_STORAGE_BUCKET}/{relpath}"
        requests.delete(url, headers=_storage_headers(), timeout=30)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Mots de passe personnels — au-delà du mot de passe commun de l'application
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt_hex: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 200_000
    ).hex()


def has_password(agent_normalise: str) -> bool:
    """True si cet agent a défini un mot de passe personnel."""
    if not agent_normalise:
        return False
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM manifestes_user_credentials WHERE agent_normalise = %s", (agent_normalise,))
        row = cur.fetchone()
    conn.close()
    return row is not None


def set_user_password(agent_normalise: str, password: str) -> None:
    """Définit ou remplace le mot de passe personnel d'un agent."""
    salt = secrets.token_hex(16)
    pwd_hash = _hash_password(password, salt)
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO manifestes_user_credentials (agent_normalise, salt, password_hash, horodatage)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_normalise) DO UPDATE SET
                   salt = EXCLUDED.salt,
                   password_hash = EXCLUDED.password_hash,
                   horodatage = EXCLUDED.horodatage""",
            (agent_normalise, salt, pwd_hash, datetime.now(timezone.utc)),
        )
    conn.commit()
    conn.close()


def verify_user_password(agent_normalise: str, password: str) -> bool:
    """Vérifie le mot de passe personnel d'un agent. False si aucun mot de
    passe n'est défini pour cet agent ou si le mot de passe est incorrect."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT salt, password_hash FROM manifestes_user_credentials WHERE agent_normalise = %s",
            (agent_normalise,),
        )
        row = cur.fetchone()
    conn.close()
    if not row:
        return False
    salt, stored_hash = row
    return secrets.compare_digest(_hash_password(password, salt), stored_hash)


def remove_user_password(agent_normalise: str) -> None:
    """Supprime le mot de passe personnel d'un agent (redevient protégé par
    le seul mot de passe commun)."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM manifestes_user_credentials WHERE agent_normalise = %s", (agent_normalise,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Traitements (manifestes / pré-masques structurés)
# ---------------------------------------------------------------------------
def log_traitement(agent, fichier, navire, voyage, nb_bl, nb_vehicules, nb_conteneurs,
                    nb_colis, nb_transit, duree_sec=None, export_path=None, pdf_path=None,
                    type_cargo=None, bl_numeros=None, service=None, role=None):
    """Enregistre un traitement et retourne l'id de la ligne créée (utile pour
    la lier ensuite à ses fichiers archivés). bl_numeros (liste des B/L
    individuellement présents dans ce traitement) alimente la détection de
    doublon réelle — voir find_duplicate_bl(). service et role identifient
    l'agent (ex. "Reporting", "Chef de service") pour la vue Dashboard par rôle."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO manifestes_traitements
               (horodatage, agent, fichier, navire, voyage, nb_bl, nb_vehicules,
                nb_conteneurs, nb_colis, nb_transit, duree_traitement_sec,
                export_path, pdf_path, type_cargo, service, role)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                datetime.now(timezone.utc),
                agent, fichier, navire, voyage,
                nb_bl, nb_vehicules, nb_conteneurs, nb_colis, nb_transit, duree_sec,
                export_path, pdf_path, type_cargo, service, role,
            ),
        )
        new_id = cur.fetchone()[0]
        if bl_numeros:
            bl_uniques = [bl for bl in dict.fromkeys(bl_numeros) if bl]
            if bl_uniques:
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO manifestes_traitement_bl (traitement_id, bl_numero) VALUES %s",
                    [(new_id, bl) for bl in bl_uniques],
                )
    conn.commit()
    conn.close()
    return new_id


def read_log():
    """Retourne l'historique des traitements avec colonnes dérivées utiles
    au tableau de bord et à l'archive (date, volume total). Le regroupement
    par semaine/mois est fait à l'affichage (resample) plutôt que stocké ici."""
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM manifestes_traitements ORDER BY horodatage DESC", conn)
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
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM manifestes_traitements")
        n = cur.fetchone()[0]
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
    df = pd.read_sql_query(
        """SELECT agent, service, role, horodatage FROM manifestes_traitements
           WHERE agent IS NOT NULL AND agent != ''
           ORDER BY horodatage ASC""",
        conn,
    )
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
    fois par un agent devient automatiquement une suggestion pour les autres.

    Trois sources combinées : les traitements et avis déjà enregistrés (usage
    réel), PLUS la table manifestes_known_values — qui capture une valeur
    personnalisée dès sa saisie sur la page Profil, avant même qu'un premier
    traitement ou avis existe pour elle (sans quoi un service/rôle tout juste
    créé restait invisible pour les autres agents tant que personne ne
    l'utilisait dans un vrai traitement)."""
    conn = _connect()
    vals = list(defaults)
    with conn.cursor() as cur:
        for table in ("manifestes_traitements", "manifestes_avis"):
            cur.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
            )
            vals.extend(r[0] for r in cur.fetchall())
        try:
            cur.execute("SELECT value FROM manifestes_known_values WHERE kind = %s", (column,))
            vals.extend(r[0] for r in cur.fetchall())
        except psycopg2.Error:
            # Table pas encore créée (migration SQL non exécutée) — dégrade
            # sans casser la page ; les valeurs issues des traitements/avis
            # restent disponibles normalement.
            conn.rollback()
    conn.close()
    seen = {}
    for v in vals:
        v = (v or "").strip()
        key = v.lower()
        if key and key not in seen:
            seen[key] = v
    return sorted(seen.values())


def add_known_value(kind: str, value: str) -> None:
    """Enregistre immédiatement une valeur personnalisée (service ou rôle)
    comme "connue", dès sa saisie sur la page Profil — pour qu'elle soit
    proposée à tous les autres agents sans attendre un premier traitement.
    Idempotent (ON CONFLICT DO NOTHING) ; best-effort côté appelant."""
    value = (value or "").strip()
    if not value or kind not in ("service", "role"):
        return
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO manifestes_known_values (kind, value) VALUES (%s, %s) "
                "ON CONFLICT (kind, value) DO NOTHING",
                (kind, value),
            )
        conn.commit()
        conn.close()
    except Exception:
        # Table pas encore créée (migration SQL non exécutée), ou base
        # momentanément indisponible — n'empêche jamais la validation du
        # profil, qui reste l'action prioritaire ici.
        pass


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
    with conn.cursor() as cur:
        cur.execute("UPDATE manifestes_traitements SET verifie = %s WHERE id = %s", (1 if verifie else 0, int(row_id)))
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
        "SELECT horodatage, agent, fichier, nb_bl FROM manifestes_traitements "
        "WHERE navire = %(navire)s AND voyage = %(voyage)s ORDER BY horodatage DESC",
        conn, params={"navire": navire, "voyage": voyage},
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
    bl_set = list(dict.fromkeys(b for b in bl_numeros if b))
    if not bl_set:
        return pd.DataFrame()
    conn = _connect()
    df = pd.read_sql_query(
        """
        SELECT t.id, t.horodatage, t.agent, t.fichier, tb.bl_numero
        FROM manifestes_traitement_bl tb
        JOIN manifestes_traitements t ON t.id = tb.traitement_id
        WHERE t.navire = %(navire)s AND t.voyage = %(voyage)s AND tb.bl_numero = ANY(%(bls)s)
        ORDER BY t.horodatage DESC
        """,
        conn, params={"navire": navire, "voyage": voyage, "bls": bl_set},
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
    with conn.cursor() as cur:
        cur.execute("DELETE FROM manifestes_traitements WHERE fichier LIKE %s", (f"{DEMO_PREFIX}%",))
    conn.commit()
    conn.close()


def clear_log():
    """Vide tout l'historique (réel + démo). À utiliser avec prudence — ne
    supprime pas les fichiers déjà archivés dans Supabase Storage."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM manifestes_traitements")
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Identité utilisateur — persistée en base (table user_identity), une seule
# ligne globale conservée pour rétro-compatibilité de save_user_identity/
# load_user_identity (usage secondaire désormais : la persistance principale
# de l'identité passe par les paramètres d'URL du navigateur, voir
# views/profil.py — isolée par utilisateur, contrairement à cette fonction).
# ---------------------------------------------------------------------------
def save_user_identity(name: str, service: str, role: str) -> None:
    """Sauvegarde la dernière identité saisie (usage best-effort, non
    critique). Ne bloque jamais le flux applicatif en cas d'échec réseau."""
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO manifestes_app_kv (key, value) VALUES ('last_identity', %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                (psycopg2.extras.Json({"name": name.strip(), "service": service, "role": role}),),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_user_identity() -> dict:
    """Charge la dernière identité enregistrée. Retourne {} si absente ou en
    cas d'erreur — usage purement indicatif (suggestion de pré-remplissage)."""
    try:
        conn = _connect()
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM manifestes_app_kv WHERE key = 'last_identity'")
            row = cur.fetchone()
        conn.close()
        if row and all(row[0].get(k) for k in ("name", "service", "role")):
            return row[0]
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
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO manifestes_avis (horodatage, auteur, service, role, message, parent_id,
                                  categorie, statut, version_app)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (datetime.now(timezone.utc), normalize_name(auteur), service, role, message.strip(),
             parent_id, categorie if parent_id is None else None, statut, version_app),
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return new_id


def update_avis(avis_id: int, new_message: str) -> None:
    """Modifie le texte d'un commentaire existant (auteur inchangé, horodatage initial conservé)."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("UPDATE manifestes_avis SET message = %s WHERE id = %s", (new_message.strip(), int(avis_id)))
    conn.commit()
    conn.close()


def update_avis_statut(avis_id: int, statut: str) -> None:
    """Change le statut d'une demande racine (Nouveau / En cours / Résolu / Refusé) —
    c'est le mécanisme de suivi : sans statut, le soutien seul indique ce qui
    est populaire mais pas ce qui a été traité."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("UPDATE manifestes_avis SET statut = %s WHERE id = %s", (statut, int(avis_id)))
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
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM manifestes_avis_soutiens WHERE avis_id = %s AND auteur_normalise = %s",
            (int(avis_id), auteur_norm),
        )
        exists = cur.fetchone()
        if exists:
            cur.execute(
                "DELETE FROM manifestes_avis_soutiens WHERE avis_id = %s AND auteur_normalise = %s",
                (int(avis_id), auteur_norm),
            )
            soutenu = False
        else:
            cur.execute(
                "INSERT INTO manifestes_avis_soutiens (avis_id, auteur_normalise, horodatage) VALUES (%s, %s, %s)",
                (int(avis_id), auteur_norm, datetime.now(timezone.utc)),
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
    df = pd.read_sql_query("SELECT * FROM manifestes_avis_soutiens", conn)
    conn.close()
    return df


def read_avis() -> pd.DataFrame:
    """Retourne tous les avis/commentaires triés du plus récent au plus ancien.
    Colonnes : id, horodatage, auteur, service, role, message, parent_id,
    categorie, statut, version_app."""
    conn = _connect()
    df = pd.read_sql_query("SELECT * FROM manifestes_avis ORDER BY horodatage DESC", conn)
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
# Archive — fichiers (PDF source + Excel structuré) associés à chaque
# traitement, stockés dans Supabase Storage (bucket "archive").
# ---------------------------------------------------------------------------
def save_export_excel(data):
    """Sauvegarde un classeur Excel généré dans l'archive distante et
    retourne son chemin relatif (stocké en base)."""
    name = f"exports/{uuid.uuid4().hex}.xlsx"
    return _storage_upload(
        name, data,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def save_source_pdf(data):
    """Sauvegarde le PDF source dans l'archive distante et retourne son
    chemin relatif."""
    name = f"sources/{uuid.uuid4().hex}.pdf"
    return _storage_upload(name, data, "application/pdf")


def delete_traitement(row_id: int) -> None:
    """Supprime un traitement de la base ainsi que ses fichiers archivés dans
    Supabase Storage.

    Cascade manuelle :
    - Supprime les B/L associés dans manifestes_traitement_bl.
    - Supprime l'Excel exporté et le PDF source archivés à distance.
    - Supprime la ligne principale dans manifestes_traitements.

    Idempotent : sans effet si l'id n'existe plus."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT export_path, pdf_path FROM manifestes_traitements WHERE id = %s", (int(row_id),))
        row = cur.fetchone()
        if row:
            for relpath in row:
                _storage_delete(relpath)
            cur.execute("DELETE FROM manifestes_traitement_bl WHERE traitement_id = %s", (int(row_id),))
            cur.execute("DELETE FROM manifestes_traitements WHERE id = %s", (int(row_id),))
    conn.commit()
    conn.close()


def archive_file_path(relpath):
    """Conservé pour compatibilité de nom — le stockage n'étant plus un
    disque local, retourne directement les octets du fichier (ou None) via
    get_archive_file(), plutôt qu'un chemin. Préférer get_archive_file()
    dans le nouveau code."""
    return get_archive_file(relpath)


# ---------------------------------------------------------------------------
# Loading Reports — archivage des fichiers MASQUE TCS + TYPE ISO générés
# depuis la page "Génération MASQUE / TYPE ISO".
# ---------------------------------------------------------------------------
def save_masque_csv(data: bytes) -> str:
    """Sauvegarde le fichier MASQUE TCS EXPORT (bytes cp1252) dans l'archive
    distante et retourne son chemin relatif."""
    name = f"manifestes_loading_reports/masque_{uuid.uuid4().hex}.csv"
    return _storage_upload(name, data, "text/csv")


def save_iso_csv(data: bytes) -> str:
    """Sauvegarde le fichier TYPE ISO (bytes cp1252) dans l'archive distante
    et retourne son chemin relatif."""
    name = f"manifestes_loading_reports/iso_{uuid.uuid4().hex}.csv"
    return _storage_upload(name, data, "text/csv")


def log_loading_report(agent: str, navire: str, voyage: str,
                        compte_escale: str, nb_conteneurs: int,
                        source_file: str = "",
                        masque_path: str | None = None,
                        iso_path: str | None = None) -> int:
    """Enregistre un Loading Report archivé dans la base et retourne l'id créé.

    Paramètres :
        agent           Nom de l'agent ayant généré les fichiers.
        navire          Nom du navire (tiré du Loading Report).
        voyage          Code voyage.
        compte_escale   Numéro d'escale saisi par l'agent.
        nb_conteneurs   Nombre de conteneurs dans ce voyage.
        source_file     Nom du fichier Loading Report source (.xls/.xlsx).
        masque_path     Chemin relatif vers le MASQUE TCS archivé.
        iso_path        Chemin relatif vers le TYPE ISO archivé.
    """
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO manifestes_loading_reports
               (horodatage, agent, navire, voyage, compte_escale, nb_conteneurs,
                source_file, masque_path, iso_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                datetime.now(timezone.utc),
                agent, navire, voyage, compte_escale, nb_conteneurs,
                source_file, masque_path, iso_path,
            ),
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return new_id


def read_loading_reports() -> pd.DataFrame:
    """Retourne l'historique des Loading Reports archivés, du plus récent au
    plus ancien. Retourne un DataFrame vide si la table est vide ou absente."""
    conn = _connect()
    try:
        df = pd.read_sql_query("SELECT * FROM manifestes_loading_reports ORDER BY horodatage DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    if df.empty:
        return df
    df["horodatage"] = pd.to_datetime(df["horodatage"], utc=True, errors="coerce")
    for col in ("masque_path", "iso_path", "source_file", "compte_escale"):
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].where(df[col].notna(), None)
    if "nb_conteneurs" not in df.columns:
        df["nb_conteneurs"] = 0
    df["nb_conteneurs"] = df["nb_conteneurs"].fillna(0).astype(int)
    return df


def delete_loading_report(row_id: int) -> None:
    """Supprime un Loading Report archivé (ligne de base + fichiers CSV dans
    Supabase Storage). Idempotent : sans effet si l'id n'existe plus."""
    conn = _connect()
    with conn.cursor() as cur:
        cur.execute("SELECT masque_path, iso_path FROM manifestes_loading_reports WHERE id = %s", (int(row_id),))
        row = cur.fetchone()
        if row:
            for relpath in row:
                _storage_delete(relpath)
            cur.execute("DELETE FROM manifestes_loading_reports WHERE id = %s", (int(row_id),))
    conn.commit()
    conn.close()

"""
Comptes utilisateurs gérés par l'IT : groupes de droits + utilisateurs.

Actif seulement si le secret CONNEXION_PAR_COMPTE = true (voir ui_helpers.accounts_mode).
Tables : manifestes_groupes, manifestes_utilisateurs, manifestes_admin_journal
(supabase_schema.sql). Mots de passe : PBKDF2-SHA256 salé (même méthode que
tracking._hash_password), jamais stockés ni journalisés en clair.

Garde-fou central : aucune modification ne peut laisser l'app sans au moins
un utilisateur ACTIF disposant de « Gérer les groupes et les utilisateurs »
(sinon plus personne ne pourrait administrer) — vérifié dans la transaction,
annulée si besoin.
"""
import re
import secrets
from datetime import datetime, timezone

import pandas as pd

import permissions as P
from tracking import _connect, _hash_password, normalize_name

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PWD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
PWD_MIN = 8


class CompteError(ValueError):
    """Erreur métier affichable telle quelle à l'utilisateur."""


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Règles
# ---------------------------------------------------------------------------
def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def check_email(email: str) -> str:
    e = normalize_email(email)
    if not _EMAIL_RE.match(e):
        raise CompteError("Adresse e-mail invalide.")
    return e


def check_password(pwd: str) -> None:
    if not pwd or len(pwd) < PWD_MIN:
        raise CompteError(f"Le mot de passe doit contenir au moins {PWD_MIN} caractères.")
    if not (re.search(r"[A-Za-z]", pwd) and re.search(r"\d", pwd)):
        raise CompteError("Le mot de passe doit contenir au moins une lettre et un chiffre.")


def temp_password() -> str:
    """Mot de passe provisoire lisible (sans 0/O, 1/l/I), avec au moins un chiffre."""
    while True:
        p = "".join(secrets.choice(_PWD_ALPHABET) for _ in range(12))
        if re.search(r"\d", p) and re.search(r"[A-Za-z]", p):
            return p


def display_name(nom: str, prenom: str) -> str:
    """Nom affiché et utilisé dans les traitements/archives : « Nom Prénom »,
    même convention que l'identification historique (continuité de l'historique)."""
    return normalize_name(f"{nom} {prenom}")


def _hash(pwd: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    return salt, _hash_password(pwd, salt)


# ---------------------------------------------------------------------------
# Journal des actions d'administration (traçabilité IT)
# ---------------------------------------------------------------------------
def _journal(cur, auteur: str, action: str, detail: str) -> None:
    cur.execute(
        "INSERT INTO manifestes_admin_journal (horodatage, auteur, action, detail) VALUES (%s, %s, %s, %s)",
        (_now(), auteur or "?", action, detail),
    )


def list_journal(limit: int = 200) -> pd.DataFrame:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT horodatage, auteur, action, detail FROM manifestes_admin_journal "
                        "ORDER BY horodatage DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows, columns=["horodatage", "auteur", "action", "detail"])


def _assert_admin_reste(cur) -> None:
    cur.execute(
        """SELECT count(*) FROM manifestes_utilisateurs u
           JOIN manifestes_groupes g ON g.id = u.groupe_id
           WHERE u.actif AND %s = ANY(g.permissions)""",
        (P.ADMIN_PERM,),
    )
    if cur.fetchone()[0] == 0:
        raise CompteError("Action refusée : il doit toujours rester au moins un utilisateur actif "
                          "pouvant gérer les groupes et les utilisateurs.")


def _run(fn):
    """Exécute fn(cur) dans une transaction ; annule tout en cas d'erreur."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            out = fn(cur)
        conn.commit()
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Groupes
# ---------------------------------------------------------------------------
def ensure_initial_groups() -> None:
    """Crée les groupes de départ si la table est vide (premier démarrage)."""
    def fn(cur):
        cur.execute("SELECT count(*) FROM manifestes_groupes")
        if cur.fetchone()[0]:
            return
        for nom, desc, perms in P.GROUPES_INITIAUX:
            cur.execute(
                "INSERT INTO manifestes_groupes (nom, description, permissions, modifie_le, modifie_par) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (nom) DO NOTHING",
                (nom, desc, P.clean(perms), _now(), "initialisation"),
            )
    _run(fn)


def list_groupes() -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT g.id, g.nom, coalesce(g.description, ''), g.permissions,
                          count(u.id) FILTER (WHERE u.actif), count(u.id)
                   FROM manifestes_groupes g LEFT JOIN manifestes_utilisateurs u ON u.groupe_id = g.id
                   GROUP BY g.id ORDER BY g.nom"""
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [{"id": r[0], "nom": r[1], "description": r[2], "permissions": P.clean(r[3]),
             "nb_actifs": r[4], "nb_total": r[5]} for r in rows]


def save_groupe(groupe_id: int | None, nom: str, description: str, perms, auteur: str) -> int:
    nom = re.sub(r"\s+", " ", (nom or "").strip())
    if not nom:
        raise CompteError("Donnez un nom au groupe.")
    codes = P.clean(perms)
    if not codes:
        raise CompteError("Cochez au moins une fonctionnalité.")

    def fn(cur):
        cur.execute("SELECT id FROM manifestes_groupes WHERE lower(nom) = lower(%s) AND id IS DISTINCT FROM %s",
                    (nom, groupe_id))
        if cur.fetchone():
            raise CompteError(f"Un groupe « {nom} » existe déjà.")
        if groupe_id is None:
            cur.execute(
                "INSERT INTO manifestes_groupes (nom, description, permissions, modifie_le, modifie_par) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (nom, description.strip() or None, codes, _now(), auteur),
            )
            gid = cur.fetchone()[0]
            _journal(cur, auteur, "Groupe créé", f"{nom} : {', '.join(P.LABELS[c] for c in codes)}")
        else:
            cur.execute(
                "UPDATE manifestes_groupes SET nom = %s, description = %s, permissions = %s, "
                "modifie_le = %s, modifie_par = %s WHERE id = %s",
                (nom, description.strip() or None, codes, _now(), auteur, groupe_id),
            )
            if cur.rowcount == 0:
                raise CompteError("Ce groupe n'existe plus.")
            gid = groupe_id
            _assert_admin_reste_si_comptes(cur)
            _journal(cur, auteur, "Groupe modifié", f"{nom} : {', '.join(P.LABELS[c] for c in codes)}")
        return gid
    return _run(fn)


def _assert_admin_reste_si_comptes(cur) -> None:
    """Le garde-fou ne s'applique qu'une fois au moins un compte créé."""
    cur.execute("SELECT count(*) FROM manifestes_utilisateurs")
    if cur.fetchone()[0]:
        _assert_admin_reste(cur)


def delete_groupe(groupe_id: int, auteur: str) -> None:
    def fn(cur):
        cur.execute("SELECT count(*) FROM manifestes_utilisateurs WHERE groupe_id = %s", (groupe_id,))
        if cur.fetchone()[0]:
            raise CompteError("Ce groupe contient encore des utilisateurs : affectez-les d'abord à un autre groupe.")
        cur.execute("DELETE FROM manifestes_groupes WHERE id = %s RETURNING nom", (groupe_id,))
        row = cur.fetchone()
        if row:
            _journal(cur, auteur, "Groupe supprimé", row[0])
    _run(fn)


# ---------------------------------------------------------------------------
# Utilisateurs
# ---------------------------------------------------------------------------
_USER_COLS = """u.id, u.email, u.nom, u.prenom, coalesce(u.service, ''), u.groupe_id, g.nom,
                g.permissions, u.actif, u.doit_changer_mdp, u.derniere_connexion, u.cree_le"""


def _user_row(r) -> dict:
    return {"id": r[0], "email": r[1], "nom": r[2], "prenom": r[3], "service": r[4],
            "groupe_id": r[5], "groupe": r[6], "permissions": frozenset(P.clean(r[7])),
            "actif": r[8], "doit_changer_mdp": r[9], "derniere_connexion": r[10], "cree_le": r[11],
            "nom_affiche": display_name(r[2], r[3])}


def list_utilisateurs() -> list[dict]:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_USER_COLS} FROM manifestes_utilisateurs u "
                        "JOIN manifestes_groupes g ON g.id = u.groupe_id ORDER BY u.nom, u.prenom")
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_user_row(r) for r in rows]


def get_utilisateur(user_id: int) -> dict | None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_USER_COLS} FROM manifestes_utilisateurs u "
                        "JOIN manifestes_groupes g ON g.id = u.groupe_id WHERE u.id = %s", (user_id,))
            r = cur.fetchone()
    finally:
        conn.close()
    return _user_row(r) if r else None


def admin_exists() -> bool:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM manifestes_utilisateurs u JOIN manifestes_groupes g ON g.id = u.groupe_id
                   WHERE u.actif AND %s = ANY(g.permissions) LIMIT 1""", (P.ADMIN_PERM,))
            return cur.fetchone() is not None
    finally:
        conn.close()


def create_utilisateur(nom: str, prenom: str, email: str, service: str, groupe_id: int,
                       auteur: str, password: str | None = None) -> str:
    """Crée un compte. Sans `password`, génère un mot de passe provisoire
    (à changer à la 1re connexion) et le RETOURNE pour être remis à la personne."""
    nom, prenom = (nom or "").strip(), (prenom or "").strip()
    if not nom or not prenom:
        raise CompteError("Le nom et le prénom sont obligatoires.")
    e = check_email(email)
    provisoire = password is None
    pwd = temp_password() if provisoire else password
    if not provisoire:
        check_password(pwd)
    salt, h = _hash(pwd)

    def fn(cur):
        cur.execute("SELECT 1 FROM manifestes_utilisateurs WHERE email = %s", (e,))
        if cur.fetchone():
            raise CompteError(f"Un compte existe déjà pour {e}.")
        cur.execute("SELECT nom FROM manifestes_groupes WHERE id = %s", (groupe_id,))
        g = cur.fetchone()
        if not g:
            raise CompteError("Groupe introuvable.")
        cur.execute(
            """INSERT INTO manifestes_utilisateurs (email, nom, prenom, service, groupe_id, salt, password_hash,
                   doit_changer_mdp, actif, cree_le, cree_par)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)""",
            (e, nom.upper(), normalize_name(prenom), (service or "").strip() or None, groupe_id,
             salt, h, provisoire, _now(), auteur),
        )
        _journal(cur, auteur, "Utilisateur créé", f"{display_name(nom, prenom)} <{e}> → groupe {g[0]}")
    _run(fn)
    return pwd if provisoire else ""


def update_utilisateur(user_id: int, groupe_id: int, service: str, actif: bool, auteur: str) -> None:
    def fn(cur):
        cur.execute(
            "UPDATE manifestes_utilisateurs SET groupe_id = %s, service = %s, actif = %s WHERE id = %s "
            "RETURNING email",
            (groupe_id, (service or "").strip() or None, actif, user_id),
        )
        row = cur.fetchone()
        if not row:
            raise CompteError("Cet utilisateur n'existe plus.")
        _assert_admin_reste(cur)
        cur.execute("SELECT nom FROM manifestes_groupes WHERE id = %s", (groupe_id,))
        _journal(cur, auteur, "Utilisateur modifié",
                 f"{row[0]} → groupe {cur.fetchone()[0]}, {'actif' if actif else 'désactivé'}")
    _run(fn)


def reset_password(user_id: int, auteur: str) -> str:
    """Nouveau mot de passe provisoire (retourné), à changer à la prochaine connexion."""
    pwd = temp_password()
    salt, h = _hash(pwd)

    def fn(cur):
        cur.execute("UPDATE manifestes_utilisateurs SET salt = %s, password_hash = %s, doit_changer_mdp = TRUE "
                    "WHERE id = %s RETURNING email", (salt, h, user_id))
        row = cur.fetchone()
        if not row:
            raise CompteError("Cet utilisateur n'existe plus.")
        _journal(cur, auteur, "Mot de passe réinitialisé", row[0])
        return row[0]
    email = _run(fn)
    try:  # lève un éventuel blocage après échecs de connexion
        from security_utils import register_success
        register_success(f"login:{email}")
    except Exception:
        pass
    return pwd


def authenticate(email: str, password: str) -> dict | None:
    """Utilisateur si e-mail + mot de passe corrects ET compte actif, sinon None."""
    e = normalize_email(email)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, salt, password_hash, actif FROM manifestes_utilisateurs WHERE email = %s", (e,))
            r = cur.fetchone()
            if not r:
                _hash_password(password or "", "00" * 16)   # temps de réponse homogène
                return None
            uid, salt, h, actif = r
            if not (actif and secrets.compare_digest(_hash_password(password or "", salt), h)):
                return None
            cur.execute("UPDATE manifestes_utilisateurs SET derniere_connexion = %s WHERE id = %s", (_now(), uid))
        conn.commit()
    finally:
        conn.close()
    return get_utilisateur(uid)


def change_password(user_id: int, current: str | None, new: str) -> None:
    """Change son propre mot de passe. `current` obligatoire sauf à la 1re
    connexion (mot de passe provisoire déjà vérifié juste avant)."""
    check_password(new)

    def fn(cur):
        cur.execute("SELECT salt, password_hash, doit_changer_mdp, email FROM manifestes_utilisateurs WHERE id = %s",
                    (user_id,))
        r = cur.fetchone()
        if not r:
            raise CompteError("Compte introuvable.")
        salt, h, doit, email = r
        if current is None and not doit:
            raise CompteError("Saisissez votre mot de passe actuel.")
        if current is not None and not secrets.compare_digest(_hash_password(current, salt), h):
            raise CompteError("Mot de passe actuel incorrect.")
        if secrets.compare_digest(_hash_password(new, salt), h):
            raise CompteError("Choisissez un mot de passe différent de l'actuel.")
        ns, nh = _hash(new)
        cur.execute("UPDATE manifestes_utilisateurs SET salt = %s, password_hash = %s, doit_changer_mdp = FALSE "
                    "WHERE id = %s", (ns, nh, user_id))
        _journal(cur, email, "Mot de passe changé", email)
    _run(fn)

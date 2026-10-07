"""
Utilitaires de sécurité — comparaison de secrets en temps constant, limitation
des essais, validation des fichiers uploadés et messages d'erreur sûrs.

Aucune dépendance au parsing ni à la base : module volontairement autonome.
"""
import hmac
import logging
import threading
import time
from pathlib import Path

import streamlit as st

# ── Paramètres ────────────────────────────────────────────────────────────
SOFT_ATTEMPTS = 3                # 3 échecs cumulés → blocage temporaire
LOCK_SECONDS = 15 * 60           # durée du blocage temporaire (15 min)
HARD_ATTEMPTS = 5                # 5 échecs cumulés → blocage définitif
_FOREVER = float("inf")          # levé uniquement par un redémarrage de l'app (admin)
MAX_UPLOAD_MB = 25
ALLOWED_UPLOAD_EXT = ("pdf", "xlsx", "xls", "ods")

_log = logging.getLogger("terra.security")


# ── Comparaison en temps constant ─────────────────────────────────────────
def secrets_match(supplied: str, expected: str) -> bool:
    """Compare deux secrets sans fuite par le temps de réponse.
    Faux si l'un des deux est vide."""
    if not supplied or not expected:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


# ── Limitation des essais ─────────────────────────────────────────────────
# Deux niveaux : st.session_state (cette session) ET un registre commun à tout
# le processus Streamlit. Le second empêche de contourner la limite en ouvrant
# un nouvel onglet / une nouvelle session.
@st.cache_resource
def _global_store() -> dict:
    return {"lock": threading.Lock(), "data": {}}


def _now() -> float:
    return time.time()


def _read(key: str) -> tuple[int, float]:
    """(nombre d'échecs, instant de fin de blocage) — le plus défavorable des deux niveaux."""
    store = _global_store()
    with store["lock"]:
        g_fails, g_until = store["data"].get(key, (0, 0.0))
    s_fails, s_until = st.session_state.get(f"_rl_{key}", (0, 0.0))
    return max(g_fails, s_fails), max(g_until, s_until)


def _write(key: str, fails: int, until: float) -> None:
    store = _global_store()
    with store["lock"]:
        if fails == 0 and until == 0.0:
            store["data"].pop(key, None)
        else:
            store["data"][key] = (fails, until)
    st.session_state[f"_rl_{key}"] = (fails, until)


def lock_remaining(key: str) -> float:
    """Secondes de blocage restantes (0 si non bloqué ; inf si définitif).
    Un blocage temporaire expiré garde le compteur d'échecs (cumul jusqu'à 5)."""
    fails, until = _read(key)
    if until == _FOREVER:
        return _FOREVER
    remaining = int(until - _now())
    if remaining <= 0:
        if until:
            _write(key, fails, 0.0)
        return 0
    return remaining


def register_failure(key: str) -> int:
    """Enregistre un échec ; renvoie le nombre d'essais restants avant le prochain blocage."""
    fails, until = _read(key)
    fails += 1
    if fails >= HARD_ATTEMPTS:
        _write(key, fails, _FOREVER)
        _log.warning("Blocage DÉFINITIF après %d échecs (clé=%s)", fails, key.split(":")[0])
        return 0
    if fails >= SOFT_ATTEMPTS:
        _write(key, fails, _now() + LOCK_SECONDS)
        _log.warning("Blocage de %d min après %d échecs (clé=%s)", LOCK_SECONDS // 60, fails, key.split(":")[0])
        return 0
    _write(key, fails, 0.0)
    return SOFT_ATTEMPTS - fails


def register_success(key: str) -> None:
    _write(key, 0, 0.0)


def lock_message(key: str) -> str | None:
    """Message utilisateur si la clé est bloquée, sinon None."""
    remaining = lock_remaining(key)
    if remaining <= 0:
        return None
    if remaining == _FOREVER:
        return "Accès bloqué après trop d'échecs. Contactez l'administrateur."
    minutes = max(1, (remaining + 59) // 60)
    return f"Trop d'essais. Réessayez dans environ {minutes} min."


def guarded_check(key: str, check) -> tuple[bool, str | None]:
    """Exécute `check()` (renvoie bool) sous limitation d'essais.

    Renvoie (ok, message_erreur). Si la clé est bloquée, `check` n'est PAS appelé."""
    msg = lock_message(key)
    if msg:
        return False, msg
    if check():
        register_success(key)
        return True, None
    left = register_failure(key)
    if left == 0:
        return False, lock_message(key) or "Trop d'essais. Réessayez plus tard."
    return False, f"Identifiants incorrects. Il reste {left} essai(s) avant blocage temporaire."


# ── Fichiers uploadés ─────────────────────────────────────────────────────
# Signatures d'en-tête attendues par extension (le contenu doit correspondre à l'extension).
_MAGIC = {
    "pdf": (b"%PDF",),
    "xlsx": (b"PK\x03\x04",),
    "ods": (b"PK\x03\x04",),
    "xls": (b"\xd0\xcf\x11\xe0", b"PK\x03\x04"),   # xls binaire (OLE2) ; certains .xls sont en réalité des xlsx
}


def validate_upload(uploaded) -> str | None:
    """None si le fichier est acceptable, sinon un message d'erreur lisible.

    Contrôle : extension autorisée, taille ≤ MAX_UPLOAD_MB, contenu cohérent
    avec l'extension (en-tête de fichier)."""
    ext = Path(uploaded.name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_UPLOAD_EXT:
        return f"« {uploaded.name} » : type non accepté (autorisés : {', '.join(ALLOWED_UPLOAD_EXT)})."
    size = getattr(uploaded, "size", None)
    if size is None:
        size = len(uploaded.getbuffer())
    if size > MAX_UPLOAD_MB * 1024 * 1024:
        return f"« {uploaded.name} » dépasse la taille maximale de {MAX_UPLOAD_MB} Mo."
    head = bytes(uploaded.getbuffer()[:8])
    if not any(head.startswith(sig) for sig in _MAGIC[ext]):
        return f"« {uploaded.name} » : le contenu ne correspond pas à son extension (.{ext})."
    return None


def checked_upload(uploaded):
    """Fichier unique : le renvoie s'il est valide, sinon affiche l'erreur et renvoie None."""
    if uploaded is None:
        return None
    err = validate_upload(uploaded)
    if err:
        st.error(err)
        return None
    return uploaded


def filter_uploads(files) -> list:
    """Garde les fichiers valides, affiche une erreur pour chacun des autres."""
    if not files:
        return []
    if not isinstance(files, (list, tuple)):
        files = [files]
    ok = []
    for f in files:
        err = validate_upload(f)
        if err:
            st.error(err)
        else:
            ok.append(f)
    return ok


# ── Erreurs sans détail technique ─────────────────────────────────────────
GENERIC_ERROR = "Une erreur est survenue. Réessayez ; si le problème persiste, contactez l'administrateur."


def log_error(context: str, exc: Exception) -> None:
    """Journalise côté serveur le contexte et le TYPE de l'exception seulement :
    jamais son message (qui peut contenir URL, clé, chemin ou données)."""
    _log.error("%s : %s", context, type(exc).__name__)


def safe_error(context: str, exc: Exception, user_message: str = GENERIC_ERROR) -> None:
    """Journalise (voir log_error) et affiche un message neutre à l'utilisateur."""
    log_error(context, exc)
    st.error(user_message)

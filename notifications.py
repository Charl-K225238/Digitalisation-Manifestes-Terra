"""
Notifications e-mail (Avis & retours) — envoi SMTP via le serveur de messagerie TERRA.

Secrets (tous facultatifs : sans SMTP_HOST ou AVIS_EMAIL_TO, rien n'est envoyé
et l'app fonctionne normalement — l'avis reste enregistré dans l'app) :
    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD (si le relais exige
    une authentification), SMTP_FROM (adresse d'expédition), SMTP_STARTTLS (true),
    AVIS_EMAIL_TO, AVIS_EMAIL_CC (adresses séparées par des virgules),
    APP_URL (lien vers l'app dans le message, facultatif).
Les adresses sont dans les secrets, jamais dans le code (dépôt public).

L'envoi se fait en arrière-plan : la publication d'un avis n'attend jamais le
serveur de messagerie, et une panne de messagerie n'empêche pas de publier.
"""
import logging
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import streamlit as st

_log = logging.getLogger("manifestes.notifications")
_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")


def _s(key: str, default=None):
    try:
        v = st.secrets.get(key, default)
    except Exception:
        return default
    return v if v not in ("", None) else default


def _addrs(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        value = ",".join(value)
    return [a.strip() for a in str(value).replace(";", ",").split(",") if a.strip()]


def _one_line(text: str, limit: int = 120) -> str:
    """Texte sûr pour un en-tête (pas de retour à la ligne = pas d'injection d'en-tête)."""
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def config() -> dict | None:
    """Configuration SMTP lue dans les secrets, ou None si l'envoi n'est pas configuré."""
    host, to = _s("SMTP_HOST"), _addrs(_s("AVIS_EMAIL_TO"))
    if not host or not to:
        return None
    return {
        "host": host, "port": int(_s("SMTP_PORT", 587)),
        "user": _s("SMTP_USER"), "password": _s("SMTP_PASSWORD"),
        "from": _s("SMTP_FROM") or _s("SMTP_USER"),
        "starttls": str(_s("SMTP_STARTTLS", "true")).strip().lower() in ("true", "1", "oui", "yes"),
        "to": to, "cc": _addrs(_s("AVIS_EMAIL_CC")), "app_url": _s("APP_URL"),
    }


def build_avis_message(cfg: dict, *, auteur: str, service: str, categorie: str | None, message: str,
                       est_reponse: bool, sujet_parent: str | None = None, reply_to: str | None = None) -> EmailMessage:
    nature = "Réponse" if est_reponse else (categorie or "Avis")
    msg = EmailMessage()
    msg["Subject"] = _one_line(f"[Manifestes Terra] {nature} — {auteur}")
    msg["From"] = formataddr(("Manifestes Terra", cfg["from"]))
    msg["To"] = ", ".join(cfg["to"])
    if cfg["cc"]:
        msg["Cc"] = ", ".join(cfg["cc"])
    if reply_to and _EMAIL_RE.match(reply_to.strip()):
        msg["Reply-To"] = reply_to.strip()
    msg["Message-ID"] = make_msgid(domain="manifestes.terra")
    lignes = [
        f"{'Nouvelle réponse' if est_reponse else 'Nouvelle demande'} déposée dans Avis & retours.",
        "",
        f"Auteur    : {auteur}",
        f"Service   : {service or '—'}",
    ]
    if est_reponse and sujet_parent:
        lignes.append(f"En réponse à : {_one_line(sujet_parent, 200)}")
    elif categorie:
        lignes.append(f"Catégorie : {categorie}")
    lignes += ["", "Message :", "-" * 40, str(message or "").strip(), "-" * 40, ""]
    if cfg.get("app_url"):
        lignes.append(f"Ouvrir l'application : {cfg['app_url']}")
    lignes.append("Le suivi (statut, soutiens, réponses) se fait dans l'application, onglet Avis & retours.")
    msg.set_content("\n".join(lignes))
    return msg


def _send(cfg: dict, msg: EmailMessage) -> None:
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["starttls"]:
                smtp.starttls(context=ssl.create_default_context())
            if cfg["user"] and cfg["password"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
    except Exception as exc:          # jamais d'impact sur l'app ; détail technique non journalisé
        _log.error("Envoi e-mail avis impossible : %s", type(exc).__name__)


def notify_avis(**kwargs) -> bool:
    """Envoie la notification en arrière-plan. False si l'envoi n'est pas configuré."""
    cfg = config()
    if not cfg:
        return False
    # L'auteur ne reçoit pas sa propre notification (ex. Charlie qui répond).
    auteur_mail = (kwargs.get("reply_to") or "").strip().lower()
    cfg["to"] = [a for a in cfg["to"] if a.lower() != auteur_mail]
    cfg["cc"] = [a for a in cfg["cc"] if a.lower() != auteur_mail]
    if not cfg["to"]:
        cfg["to"], cfg["cc"] = cfg["cc"], []
    if not cfg["to"]:
        return False
    msg = build_avis_message(cfg, **kwargs)
    threading.Thread(target=_send, args=(cfg, msg), daemon=True).start()
    return True

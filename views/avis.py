"""
Page Avis & Retours — chat structuré ET suivi de demandes.

Chaque message racine est une "demande" catégorisée (Fonctionnement /
Interface / Nouvelle fonctionnalité / Discussion) avec un statut de
traitement (Nouveau / En cours / Résolu / Refusé), soutenable par les pairs
et discutable en fil de réponses — pensé pour prioriser et suivre les
évolutions de l'application dans la durée, pas juste collecter des avis
ponctuels.

Visibilité : TOUS les messages (racines et réponses) sont visibles par tous
les utilisateurs, sans restriction par service/rôle — seul le changement de
statut d'une demande est réservé au service Data / rôle Analyste Data.
"""
import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import importlib as _importlib
import tracking as _tracking_mod
_importlib.reload(_tracking_mod)
del _importlib, _tracking_mod

from tracking import (
    load_user_identity,
    read_avis,
    save_avis,
    update_avis,
    update_avis_statut,
    toggle_soutien,
    read_soutiens,
    normalize_name,
    CATEGORIES_AVIS,
    STATUTS_AVIS,
)
from ui_helpers import help_expander, APP_VERSION

CATEGORY_LABEL = {
    "Fonctionnement": "🔧 Fonctionnement",
    "Interface": "🎨 Interface",
    "Fonctionnalité": "✨ Nouvelle fonctionnalité",
    "Discussion": "💬 Discussion / Autre",
}
STATUT_LABEL = {
    "Nouveau": "🆕 Nouveau",
    "En cours": "🔄 En cours",
    "Résolu": "✅ Résolu",
    "Refusé": "🚫 Refusé",
}
STATUT_COLOR = {
    "Nouveau": "#2a78d6",
    "En cours": "#eda100",
    "Résolu": "#0ca30c",
    "Refusé": "#e34948",
}

# ---------------------------------------------------------------------------
# Identité
# ---------------------------------------------------------------------------
identity = st.session_state.get("identity") or load_user_identity()

if not identity:
    st.title("💬 Avis & Retours")
    st.warning(
        "Votre identité n'est pas encore enregistrée. "
        "Rendez-vous sur la page **📦 Structuration des manifestes** pour la saisir une première fois."
    )
    st.stop()

auteur       = identity["name"]
service      = identity["service"]
role         = identity["role"]
auteur_norm  = normalize_name(auteur)
is_data      = service == "Data" or role == "Analyste Data"

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("💬 Avis & Retours")
st.caption(
    "Un espace d'échange ET de suivi : chaque nouvelle demande est catégorisée, "
    "peut être soutenue par vos collègues, discutée en fil de réponses, et suivie "
    "d'un statut jusqu'à sa résolution. Tous les messages sont visibles par toute l'équipe."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
- **Nouvelle demande** : choisissez une catégorie (Fonctionnement, Interface,
  Nouvelle fonctionnalité, ou Discussion pour tout le reste) et décrivez votre
  point — c'est ce qui alimente le suivi des évolutions futures de l'app.
- **👍 Soutenir** un message indique qu'il vous concerne aussi, sans avoir à
  répéter la même demande — utile pour prioriser.
- **↩️ Répondre** ouvre un fil de discussion sous la demande.
- **✏️ Modifier** n'est possible que sur vos propres messages.
- Le **statut** (🆕 Nouveau → 🔄 En cours → ✅ Résolu / 🚫 Refusé) est mis à
  jour par l'équipe Data au fil du traitement des demandes.
        """
    )

st.info(f"Connecté en tant que **{auteur}** — {service} / {role}", icon="🧑‍💻")

st.divider()

# ---------------------------------------------------------------------------
# Formulaire — nouvelle demande
# ---------------------------------------------------------------------------
with st.expander("✏️ Nouvelle demande / commentaire", expanded=True):
    categorie_choice = st.selectbox(
        "Catégorie",
        CATEGORIES_AVIS,
        format_func=lambda c: CATEGORY_LABEL.get(c, c),
        key="nouvelle_avis_categorie",
        help="Fonctionnement = un comportement de l'app ne fait pas ce qu'il devrait. "
             "Interface = ergonomie/affichage. Nouvelle fonctionnalité = quelque chose "
             "qui n'existe pas encore. Discussion = tout le reste.",
    )
    nouveau_msg = st.text_area(
        "Votre message",
        placeholder="Décrivez un problème, suggérez une amélioration, posez une question…",
        height=120,
        key="nouveau_avis_msg",
    )
    if st.button("📨 Envoyer", type="primary", key="btn_envoyer_avis"):
        msg = nouveau_msg.strip()
        if not msg:
            st.warning("Le message ne peut pas être vide.")
        else:
            save_avis(auteur=auteur, service=service, role=role, message=msg,
                       parent_id=None, categorie=categorie_choice, version_app=APP_VERSION)
            st.success("Demande enregistrée.")
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Chargement des données
# ---------------------------------------------------------------------------
df_all = read_avis()

if df_all.empty:
    st.info("Aucun message pour l'instant — soyez le premier à en laisser un !")
    st.stop()

df_roots   = df_all[df_all["parent_id"].isna()].copy()
df_replies = df_all[df_all["parent_id"].notna()].copy()
# Tous les messages sont visibles par tous — pas de filtre par service/rôle.

soutiens_df = read_soutiens()
soutiens_par_id = (
    soutiens_df.groupby("avis_id")["auteur_normalise"].apply(set).to_dict()
    if not soutiens_df.empty else {}
)


def _nb_soutiens(avis_id: int) -> int:
    return len(soutiens_par_id.get(int(avis_id), set()))


def _je_soutiens(avis_id: int) -> bool:
    return auteur_norm in soutiens_par_id.get(int(avis_id), set())


# ---------------------------------------------------------------------------
# Résumé rapide (sur l'ensemble, indépendant des filtres) — vue d'ensemble
# utile pour prioriser les mises à jour futures.
# ---------------------------------------------------------------------------
_counts = df_roots["statut"].value_counts()
st.caption(
    "📊 " + " · ".join(
        f"{STATUT_LABEL[s]} : {int(_counts.get(s, 0))}" for s in STATUTS_AVIS
    )
)

# ---------------------------------------------------------------------------
# Filtres
# ---------------------------------------------------------------------------
col_search, col_cat, col_tri = st.columns([2.2, 2.3, 1.5])
with col_search:
    q_avis = st.text_input(
        "🔍 Rechercher", placeholder="Mot-clé, auteur…", key="recherche_avis",
    )
with col_cat:
    cat_filtre = st.multiselect(
        "Catégorie", CATEGORIES_AVIS, format_func=lambda c: CATEGORY_LABEL.get(c, c),
        placeholder="Toutes les catégories", key="filtre_categorie",
    )
with col_tri:
    tri = st.selectbox("Trier par", ["Plus récents", "Plus soutenus"], key="tri_avis")

masquer_closes = st.checkbox(
    "Masquer les demandes clôturées (Résolu / Refusé)", value=False, key="masquer_closes",
)

dff = df_roots.copy()
if q_avis:
    q = q_avis.strip().lower()
    mask = (
        dff["message"].fillna("").str.lower().str.contains(q, regex=False)
        | dff["auteur"].fillna("").str.lower().str.contains(q, regex=False)
    )
    dff = dff[mask]
if cat_filtre:
    dff = dff[dff["categorie"].isin(cat_filtre)]
if masquer_closes:
    dff = dff[~dff["statut"].isin(["Résolu", "Refusé"])]

if tri == "Plus soutenus":
    dff = dff.assign(_n_soutiens=dff["id"].apply(_nb_soutiens))
    dff = dff.sort_values(["_n_soutiens", "horodatage"], ascending=[False, False])
else:
    dff = dff.sort_values("horodatage", ascending=False)

# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
n_racines = len(dff)
st.subheader(f"Demandes ({n_racines})")
if len(df_all) > len(df_roots):
    st.caption(f"{len(df_all)} messages au total dont {len(df_replies)} réponse(s).")

if dff.empty:
    st.info("Aucun message ne correspond à ces filtres.")
    st.stop()


def _badge(svc: str, rl: str) -> str:
    parts = [p for p in (svc, rl) if p]
    return f" · {' / '.join(parts)}" if parts else ""


def _date_str(ts) -> str:
    if pd.isna(ts):
        return "—"
    local = ts.tz_convert("Africa/Abidjan") if ts.tzinfo else ts
    return local.strftime("%d/%m/%Y %H:%M")


def _statut_badge(statut: str) -> str:
    color = STATUT_COLOR.get(statut, "#888")
    label = STATUT_LABEL.get(statut, statut)
    return (
        f"<span style='background:{color}1a;color:{color};padding:2px 8px;"
        f"border-radius:10px;font-size:0.8rem;font-weight:600'>{label}</span>"
    )


def _soutien_button(avis_id: int, key_prefix: str):
    n = _nb_soutiens(avis_id)
    mine = _je_soutiens(avis_id)
    label = f"{'❤️' if mine else '🤍'} {n}"
    if st.button(label, key=f"{key_prefix}_{avis_id}", help="Soutenir ce message"):
        toggle_soutien(avis_id, auteur)
        st.rerun()


for _, root in dff.iterrows():
    root_id   = int(root["id"])
    is_mine   = root["auteur"] == auteur
    edit_key  = f"edit_open_{root_id}"
    reply_key = f"reply_open_{root_id}"

    with st.container(border=True):
        # En-tête : catégorie + statut + auteur + date
        col_badges, col_actions = st.columns([3, 2])
        with col_badges:
            st.markdown(
                f"{CATEGORY_LABEL.get(root['categorie'], root['categorie'])} · "
                + _statut_badge(root["statut"]),
                unsafe_allow_html=True,
            )
            st.markdown(
                f"**{root['auteur']}**{_badge(root['service'], root['role'])}  \n"
                f"<small style='color:#888'>{_date_str(root['horodatage'])}</small>",
                unsafe_allow_html=True,
            )
        with col_actions:
            btn_soutien, btn_reply, btn_edit = st.columns(3)
            with btn_soutien:
                _soutien_button(root_id, "soutien_root")
            with btn_reply:
                if st.button("↩️", key=f"btn_reply_{root_id}", help="Répondre",
                             use_container_width=True):
                    st.session_state[reply_key] = not st.session_state.get(reply_key, False)
                    st.session_state[edit_key]  = False
            with btn_edit:
                if is_mine:
                    if st.button("✏️", key=f"btn_edit_{root_id}", help="Modifier",
                                 use_container_width=True):
                        st.session_state[edit_key]  = not st.session_state.get(edit_key, False)
                        st.session_state[reply_key] = False

        # Corps du message — ou formulaire d'édition
        if st.session_state.get(edit_key, False):
            edited_text = st.text_area(
                "Modifier votre message", value=root["message"], height=100,
                key=f"edit_text_{root_id}",
            )
            c1, c2 = st.columns([1, 5])
            with c1:
                if st.button("💾 Enregistrer", type="primary", key=f"btn_save_edit_{root_id}"):
                    txt = edited_text.strip()
                    if txt:
                        update_avis(root_id, txt)
                        st.session_state[edit_key] = False
                        st.rerun()
                    else:
                        st.warning("Le message ne peut pas être vide.")
            with c2:
                if st.button("Annuler", key=f"btn_cancel_edit_{root_id}"):
                    st.session_state[edit_key] = False
                    st.rerun()
        else:
            st.markdown(root["message"])

        # Changement de statut — réservé au service Data / rôle Analyste Data
        if is_data:
            new_statut = st.selectbox(
                "Statut", STATUTS_AVIS, index=STATUTS_AVIS.index(root["statut"])
                if root["statut"] in STATUTS_AVIS else 0,
                format_func=lambda s: STATUT_LABEL.get(s, s),
                key=f"statut_select_{root_id}", label_visibility="collapsed",
            )
            if new_statut != root["statut"]:
                update_avis_statut(root_id, new_statut)
                st.rerun()

        # Réponses
        replies_here = df_replies[df_replies["parent_id"] == root_id].sort_values("horodatage")
        for _, rep in replies_here.iterrows():
            rep_id = int(rep["id"])
            st.markdown(
                f"&nbsp;&nbsp;&nbsp;&nbsp;↪ **{rep['auteur']}**{_badge(rep['service'], rep['role'])}  "
                f"<small style='color:#888'>{_date_str(rep['horodatage'])}</small>",
                unsafe_allow_html=True,
            )
            col_rep_msg, col_rep_soutien = st.columns([6, 1])
            with col_rep_msg:
                st.markdown(
                    f"<div style='margin-left:2rem;padding:6px 10px;"
                    f"border-left:3px solid #ddd;color:#444'>{rep['message']}</div>",
                    unsafe_allow_html=True,
                )
            with col_rep_soutien:
                _soutien_button(rep_id, "soutien_rep")

        # Formulaire de réponse
        if st.session_state.get(reply_key, False):
            st.divider()
            rep_text = st.text_area(
                f"Votre réponse à {root['auteur']}", height=90,
                key=f"rep_text_{root_id}", placeholder="Tapez votre réponse…",
            )
            r1, r2 = st.columns([1, 5])
            with r1:
                if st.button("Envoyer", type="primary", key=f"btn_send_rep_{root_id}"):
                    txt = rep_text.strip()
                    if txt:
                        save_avis(auteur=auteur, service=service, role=role,
                                   message=txt, parent_id=root_id)
                        st.session_state[reply_key] = False
                        st.rerun()
                    else:
                        st.warning("La réponse ne peut pas être vide.")
            with r2:
                if st.button("Annuler", key=f"btn_cancel_rep_{root_id}"):
                    st.session_state[reply_key] = False
                    st.rerun()

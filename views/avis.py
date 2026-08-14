"""
Page Avis & Retours — commentaires des agents sur l'application.

Fonctionnement :
- L'auteur est pré-rempli depuis l'identité persistée (une seule saisie).
- N'importe qui peut poster un commentaire ou répondre à un commentaire existant.
- Chaque auteur peut modifier son propre commentaire (racine uniquement).
- Vue filtrée par rôle : le service "Data" ou rôle "Analyste Data" voit TOUT ;
  les autres voient leurs propres messages + tous les commentaires racines.
"""
import pathlib
import sys

import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tracking import load_user_identity, read_avis, save_avis, update_avis

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

auteur  = identity["name"]
service = identity["service"]
role    = identity["role"]

# Un analyste data (service "Data" OU rôle "Analyste Data") voit tout
is_data = service == "Data" or role == "Analyste Data"

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("💬 Avis & Retours")
st.caption(
    "Partagez vos remarques, suggestions ou questions sur l'application. "
    "Vos retours aident à améliorer l'outil pour toute l'équipe."
)
st.info(f"Connecté en tant que **{auteur}** — {service} / {role}", icon="🧑‍💻")

st.divider()

# ---------------------------------------------------------------------------
# Formulaire — nouveau commentaire
# ---------------------------------------------------------------------------
with st.expander("✏️ Laisser un commentaire", expanded=True):
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
            save_avis(auteur=auteur, service=service, role=role, message=msg, parent_id=None)
            st.success("Commentaire enregistré.")
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Chargement et filtrage des avis
# ---------------------------------------------------------------------------
df_all = read_avis()

if df_all.empty:
    st.info("Aucun commentaire pour l'instant — soyez le premier à laisser un avis !")
    st.stop()

# Séparation racines / réponses
df_roots   = df_all[df_all["parent_id"].isna()].copy()
df_replies = df_all[df_all["parent_id"].notna()].copy()

# Filtre de visibilité pour les non-Data :
# - racines = toutes (publiques)  |  réponses = seulement les siennes
if not is_data:
    df_replies = df_replies[df_replies["auteur"] == auteur]

# Tri du plus récent au plus ancien
df_roots = df_roots.sort_values("horodatage", ascending=False)

# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
n_racines = len(df_roots)
st.subheader(f"Commentaires ({n_racines})")
if is_data and len(df_all) > n_racines:
    st.caption(f"Vue complète — {len(df_all)} messages dont {len(df_replies)} réponses.")

q_avis = st.text_input(
    "🔍 Rechercher", placeholder="Mot-clé, auteur…",
    key="recherche_avis",
)
if q_avis:
    q = q_avis.strip().lower()
    mask = (
        df_roots["message"].fillna("").str.lower().str.contains(q)
        | df_roots["auteur"].fillna("").str.lower().str.contains(q)
    )
    df_roots = df_roots[mask]

if df_roots.empty:
    st.info("Aucun commentaire ne correspond à votre recherche.")
    st.stop()


def _badge(svc: str, rl: str) -> str:
    parts = [p for p in (svc, rl) if p]
    return f" · {' / '.join(parts)}" if parts else ""


def _date_str(ts) -> str:
    import pandas as pd
    if pd.isna(ts):
        return "—"
    local = ts.tz_convert("Africa/Abidjan") if ts.tzinfo else ts
    return local.strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# Boucle d'affichage
# ---------------------------------------------------------------------------
for _, root in df_roots.iterrows():
    root_id   = int(root["id"])
    is_mine   = root["auteur"] == auteur
    edit_key  = f"edit_open_{root_id}"
    reply_key = f"reply_open_{root_id}"

    with st.container(border=True):
        # En-tête
        col_meta, col_actions = st.columns([3, 1])
        with col_meta:
            st.markdown(
                f"**{root['auteur']}**{_badge(root['service'], root['role'])}  \n"
                f"<small style='color:#888'>{_date_str(root['horodatage'])}</small>",
                unsafe_allow_html=True,
            )
        with col_actions:
            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                if st.button("↩️", key=f"btn_reply_{root_id}", help="Répondre",
                             use_container_width=True):
                    st.session_state[reply_key] = not st.session_state.get(reply_key, False)
                    st.session_state[edit_key]  = False   # ferme l'édition si ouverte
            with btn_col2:
                # Le bouton Modifier n'est visible que pour l'auteur
                if is_mine:
                    if st.button("✏️", key=f"btn_edit_{root_id}", help="Modifier",
                                 use_container_width=True):
                        st.session_state[edit_key]  = not st.session_state.get(edit_key, False)
                        st.session_state[reply_key] = False

        # Corps du commentaire — ou formulaire d'édition
        if st.session_state.get(edit_key, False):
            edited_text = st.text_area(
                "Modifier votre message",
                value=root["message"],
                height=100,
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

        # Réponses
        replies_here = df_replies[df_replies["parent_id"] == root_id].sort_values("horodatage")
        for _, rep in replies_here.iterrows():
            st.markdown(
                f"&nbsp;&nbsp;&nbsp;&nbsp;↪ **{rep['auteur']}**{_badge(rep['service'], rep['role'])}  "
                f"<small style='color:#888'>{_date_str(rep['horodatage'])}</small>",
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='margin-left:2rem;padding:6px 10px;"
                f"border-left:3px solid #ddd;color:#444'>{rep['message']}</div>",
                unsafe_allow_html=True,
            )

        # Formulaire de réponse
        if st.session_state.get(reply_key, False):
            st.divider()
            rep_text = st.text_area(
                f"Votre réponse à {root['auteur']}",
                height=90,
                key=f"rep_text_{root_id}",
                placeholder="Tapez votre réponse…",
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

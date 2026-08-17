"""
Page Génération MASQUE / TYPE ISO — à partir du Loading Report Grimaldi.

L'agent charge un ou plusieurs fichiers Loading Report (Etat Définitif .xls/.xlsx),
sélectionne un navire/voyage, VÉRIFIE et AJUSTE si besoin les données extraites
(port, destination, compte d'escale — certains LOCODE ne sont pas encore connus
de l'application et doivent être complétés manuellement), puis génère :
  - le fichier MASQUE TCS EXPORT (CSV cp1252/CRLF, format logiciel interne)
  - le fichier TYPE ISO (CSV cp1252/CRLF, même logiciel)
"""
import io
import pathlib
import re
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loading_report_parser import (
    parse_loading_report,
    list_voyages,
    generate_masque_tcs,
    generate_type_iso,
    to_windows_csv_bytes,
)
from ui_helpers import help_expander
# tracking importé en lazy (à l'intérieur de la section archive uniquement)
# pour éviter la KeyError: 'ui_helpers' en Python 3.14 lors du hot-reload :
# quand tracking.py ET loading_report.py sont rechargés simultanément,
# un import de tracking au niveau module corrompt temporairement sys.modules.

# ---------------------------------------------------------------------------
# En-tête
# ---------------------------------------------------------------------------
st.title("📋 Génération MASQUE / TYPE ISO")
st.caption(
    "Chargez un ou plusieurs Loading Report (Etat Définitif .xls/.xlsx) → "
    "sélection du navire/voyage → vérification et ajustement des données → "
    "export MASQUE TCS EXPORT + TYPE ISO au format exact du logiciel interne."
)

with help_expander("ℹ️ Comment utiliser cette page ?"):
    st.markdown(
        """
- **1 · Chargez** un ou plusieurs Loading Report (Etat Définitif). Vous pouvez
  en charger plusieurs à la fois — un par navire, ou plusieurs pour le même navire.
- **2 · Sélectionnez** le navire/voyage à traiter (choix automatique s'il n'y en a qu'un).
- **3 · Vérifiez et ajustez** le tableau : certains ports/destinations peuvent
  ne pas être reconnus automatiquement (affichés tels quels, en code brut) —
  corrigez-les directement dans le tableau avant export. C'est aussi ici que
  vous complétez le compte d'escale.
- **4 · Téléchargez** les fichiers MASQUE TCS EXPORT et TYPE ISO, prêts à
  être importés dans le logiciel interne (encodage et séparateurs identiques
  aux fichiers de référence).
- **5 · Archivez** le traitement pour le retrouver et re-télécharger les fichiers
  depuis l'onglet **Archives → Loading Reports**.
        """
    )

st.divider()

# ---------------------------------------------------------------------------
# 1 · Upload des fichiers Loading Report
# ---------------------------------------------------------------------------
st.subheader("1 · Charger les Loading Report")
uploaded_files = st.file_uploader(
    "📂 Fichiers Etat Définitif (.xls / .xlsx)",
    type=["xls", "xlsx"],
    accept_multiple_files=True,
    help="Vous pouvez charger plusieurs fichiers à la fois (plusieurs navires, "
         "ou plusieurs parties d'un même navire).",
)

if not uploaded_files:
    st.info(
        "⬆ Chargez au moins un fichier Loading Report pour commencer. "
        "Les formats **.xls** et **.xlsx** sont acceptés."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Parsing de tous les fichiers chargés — chaque fichier est isolé pour que
# l'échec d'un seul n'empêche pas de traiter les autres.
# ---------------------------------------------------------------------------
df_all = []
parse_errors = []
file_results = []  # résumé par fichier affiché quand plusieurs fichiers chargés

for uf in uploaded_files:
    try:
        df_parsed = parse_loading_report(uf.getvalue(), uf.name)
        df_parsed["_source_file"] = uf.name
        df_all.append(df_parsed)
        file_results.append({
            "Fichier": uf.name,
            "Statut": "✅",
            "Lignes": len(df_parsed),
            "Remarque": "",
        })
    except ValueError as e:
        parse_errors.append(f"**{uf.name}** : {e}")
        file_results.append({
            "Fichier": uf.name,
            "Statut": "❌",
            "Lignes": 0,
            "Remarque": str(e),
        })
    except Exception as e:
        # Filet de sécurité — tout bug inattendu doit être visible pour
        # l'agent, jamais silencieux (phase d'adoption : chaque bug compte).
        parse_errors.append(f"**{uf.name}** : erreur inattendue — {e}")
        file_results.append({
            "Fichier": uf.name,
            "Statut": "❌",
            "Lignes": 0,
            "Remarque": f"erreur inattendue — {e}",
        })

if parse_errors:
    for err in parse_errors:
        st.error(err, icon="🚫")

if not df_all:
    st.stop()

df_total = pd.concat(df_all, ignore_index=True)

nb_ok = len(uploaded_files) - len(parse_errors)
st.success(
    f"✅ {nb_ok} fichier(s) chargé(s) avec succès — {len(df_total)} ligne(s) au total."
)

# Résumé par fichier (uniquement quand plusieurs fichiers chargés)
if len(uploaded_files) > 1:
    st.dataframe(
        pd.DataFrame(file_results),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Statut": st.column_config.TextColumn(width="small"),
            "Lignes": st.column_config.NumberColumn(width="small"),
        },
    )

# ---------------------------------------------------------------------------
# 2 · Sélection du navire / voyage
# ---------------------------------------------------------------------------
st.divider()
st.subheader("2 · Sélectionner un navire / voyage")

voyages = list_voyages(df_total)
if not voyages:
    st.warning("Aucun voyage détecté dans les fichiers chargés.")
    st.stop()

# Affiche le fichier source dans le libellé quand plusieurs fichiers chargés
# (permet de distinguer deux voyages identiques issus de fichiers différents).
show_file_in_label = len(uploaded_files) > 1


def _voyage_label(v: dict) -> str:
    navire_disp = (v["navire"] or "").strip() or "(navire non détecté)"
    voyage_disp = (v["voyage"] or "").strip() or "(voyage non détecté)"
    date_disp = f" — {v['date_arrivee']}" if v["date_arrivee"] else ""
    file_disp = ""
    if show_file_in_label and v.get("_source_file"):
        # Nom de fichier sans extension, pour un libellé concis
        stem = pathlib.Path(v["_source_file"]).stem
        file_disp = f"  [{stem}]"
    return (
        f"{navire_disp} · {voyage_disp}{date_disp}"
        f" — {v['nb_conteneurs']} conteneur(s){file_disp}"
    )


voyage_options = {_voyage_label(v): v for v in voyages}

if len(voyage_options) == 1:
    selected_label = list(voyage_options.keys())[0]
    st.info(f"📍 Voyage détecté automatiquement : **{selected_label}**")
else:
    selected_label = st.selectbox(
        "Voyage à traiter",
        list(voyage_options.keys()),
        help="Sélectionnez le navire/voyage pour lequel générer les fichiers.",
    )

selected_v = voyage_options[selected_label]

# Filtrage — inclut _source_file pour différencier deux fichiers
# contenant le même navire/voyage (e.g. deux escales différentes).
mask = (
    (df_total["navire"] == selected_v["navire"]) &
    (df_total["voyage"] == selected_v["voyage"])
)
if selected_v.get("_source_file"):
    mask &= (df_total["_source_file"] == selected_v["_source_file"])
df_voyage = df_total[mask].reset_index(drop=True)

col1, col2, col3 = st.columns(3)
col1.metric("Conteneurs", len(df_voyage))
col2.metric("B/L distincts", selected_v["nb_bl_distincts"])
nb_vides = int((df_voyage["vp"] == "V").sum())
col3.metric("Vides / Pleins", f"{nb_vides} V / {len(df_voyage) - nb_vides} P")

# Détection de ports/destinations non reconnus (LOCODE absent de la table
# interne) — signalée explicitement par le parseur (colonnes *_resolved),
# PAS devinée par une regex sur la forme du texte : une regex confondrait
# une ville légitimement décodée comme 'DAKAR' ou le libellé 'OPTION' avec
# un vrai code non résolu (même forme de texte).
unresolved_mask = pd.Series(False, index=df_voyage.index)
if "pod_resolved" in df_voyage.columns:
    unresolved_mask |= ~df_voyage["pod_resolved"]
if "destination_resolved" in df_voyage.columns:
    unresolved_mask |= ~df_voyage["destination_resolved"]
nb_unresolved = int(unresolved_mask.sum())
if nb_unresolved:
    # Pas de double icône : icon= fournit l'icône, pas le texte.
    st.warning(
        f"{nb_unresolved} ligne(s) ont un port/destination non reconnu "
        "(affiché comme code brut, ex. 'ITTTA') — à corriger manuellement "
        "dans le tableau ci-dessous avant export.",
        icon="⚠️",
    )

# ---------------------------------------------------------------------------
# 3 · Vérification et ajustement des données (tableau éditable)
# ---------------------------------------------------------------------------
st.divider()
st.subheader("3 · Vérifier et ajuster les données")
st.caption(
    "Corrigez directement les cellules si besoin (port/destination non "
    "reconnu, compte d'escale, etc.) — l'export utilisera vos modifications."
)

col_cpt, col_arm = st.columns([2, 2])
with col_cpt:
    compte_escale = st.text_input(
        "Compte d'escale",
        value="",
        placeholder="Ex : 2540179",
        help="Numéro d'escale Grimaldi — obligatoire pour le fichier MASQUE TCS.",
    )
with col_arm:
    armateur = st.text_input(
        "Armateur",
        value="GRIMALDI ",
        help="Libellé armateur tel qu'attendu par le logiciel (espace final conservé, à ne pas retirer).",
    )

edit_cols = [
    "n_conteneur", "iso_num", "iso_code", "n_bl", "vp", "poids_kgs",
    "pol", "pod", "destination", "client",
]
display_names = {
    "n_conteneur": "Conteneur", "iso_num": "Taille", "iso_code": "ISO",
    "n_bl": "N° BL", "vp": "V/P", "poids_kgs": "Poids (kg)",
    "pol": "POL", "pod": "POD", "destination": "Destination", "client": "Client",
}
available_edit_cols = [c for c in edit_cols if c in df_voyage.columns]

editable_df = df_voyage[available_edit_cols].rename(columns=display_names)
edited_df = st.data_editor(
    editable_df,
    hide_index=True,
    use_container_width=True,
    num_rows="fixed",
    key="loading_report_editor",
    height=min(38 * (len(editable_df) + 1) + 3, 500),
)

# Ré-injection des colonnes éditées dans le DataFrame complet (navire/voyage/
# date/armt_bl restent ceux extraits automatiquement — non éditables ici).
df_final = df_voyage.copy()
inverse_names = {v: k for k, v in display_names.items()}
for disp_col, internal_col in inverse_names.items():
    if disp_col in edited_df.columns:
        df_final[internal_col] = edited_df[disp_col]

# ---------------------------------------------------------------------------
# 4 · Génération et téléchargement
# ---------------------------------------------------------------------------
st.divider()
st.subheader("4 · Générer les fichiers")

navire_safe = re.sub(r"[^\w]", "_", (selected_v["navire"] or "").strip()) or "NAVIRE"
voyage_safe = re.sub(r"[^\w]", "_", (selected_v["voyage"] or "").strip()) or "VOY"

col_masque, col_iso = st.columns(2)
masque_content = iso_content = None
masque_bytes = iso_bytes = None

with col_masque:
    if not compte_escale.strip():
        # Pas de double icône : icon= fournit l'icône, pas le texte.
        st.warning("Saisissez le compte d'escale pour générer le MASQUE TCS.", icon="⚠️")
    else:
        try:
            masque_content = generate_masque_tcs(df_final, compte_escale.strip(), armateur)
            masque_bytes, masque_warnings = to_windows_csv_bytes(masque_content)
            for w in masque_warnings:
                st.warning(f"MASQUE TCS — {w}", icon="⚠️")
            st.download_button(
                "⬇ MASQUE TCS EXPORT",
                data=masque_bytes,
                file_name=f"MASQUE_TCS_EXPORT_{navire_safe}_{voyage_safe}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True,
                help=f"Télécharge le fichier CSV MASQUE TCS EXPORT ({len(df_final)} lignes).",
            )
            st.caption(f"✅ {len(df_final)} conteneur(s) · encodage Windows-1252 (ANSI) · CRLF · séparateur `;`")
        except Exception as e:
            st.error(f"Erreur lors de la génération du MASQUE TCS : {e}", icon="🚫")

with col_iso:
    try:
        iso_content = generate_type_iso(df_final)
        iso_bytes, iso_warnings = to_windows_csv_bytes(iso_content)
        for w in iso_warnings:
            st.warning(f"TYPE ISO — {w}", icon="⚠️")
        st.download_button(
            "⬇ TYPE ISO",
            data=iso_bytes,
            file_name=f"TYPE_ISO_{navire_safe}_{voyage_safe}.csv",
            mime="text/csv",
            use_container_width=True,
            help=f"Télécharge le fichier CSV TYPE ISO ({len(df_final)} lignes).",
        )
        st.caption(f"✅ {len(df_final)} conteneur(s) · encodage Windows-1252 (ANSI) · CRLF · séparateur `;`")
    except Exception as e:
        st.error(f"Erreur lors de la génération du TYPE ISO : {e}", icon="🚫")

# ---------------------------------------------------------------------------
# Aperçu tableau des fichiers générés (remplace l'affichage ligne par ligne)
# ---------------------------------------------------------------------------
if masque_content or iso_content:
    st.divider()
    col_prev1, col_prev2 = st.columns(2)

    if masque_content:
        with col_prev1:
            with help_expander("📄 Aperçu MASQUE TCS EXPORT (5 premières lignes)"):
                _lines = masque_content.strip().split("\n")
                if len(_lines) > 1:
                    try:
                        df_prev = pd.read_csv(
                            io.StringIO("\n".join(_lines[:6])), sep=";"
                        )
                        st.dataframe(df_prev, hide_index=True, use_container_width=True)
                    except Exception:
                        st.code("\n".join(_lines[:6]), language=None)
                else:
                    st.code(masque_content, language=None)

    if iso_content:
        with col_prev2:
            with help_expander("📄 Aperçu TYPE ISO (5 premières lignes)"):
                _lines = iso_content.strip().split("\n")
                if len(_lines) > 1:
                    try:
                        # Retire le trailing semicolon (format TYPE ISO) avant parsing
                        cleaned = "\n".join(l.rstrip(";") for l in _lines[:6])
                        df_prev = pd.read_csv(
                            io.StringIO(cleaned), sep=";"
                        )
                        st.dataframe(df_prev, hide_index=True, use_container_width=True)
                    except Exception:
                        st.code("\n".join(_lines[:6]), language=None)
                else:
                    st.code(iso_content, language=None)

# ---------------------------------------------------------------------------
# 5 · Archivage — sauvegarde des fichiers générés dans l'historique.
# Accessible ensuite depuis Archives → Loading Reports pour consultation
# et re-téléchargement.
# ---------------------------------------------------------------------------
if masque_bytes or iso_bytes:
    st.divider()
    st.subheader("5 · Archiver ce traitement")

    # Clé de session unique par voyage pour éviter la double-soumission
    # si l'utilisateur clique deux fois sur le bouton.
    _archive_key = f"lr_archived_{selected_v['navire']}_{selected_v['voyage']}_{selected_v.get('_source_file', '')}"

    if st.session_state.get(_archive_key):
        st.success(
            "Traitement déjà archivé pour ce voyage. "
            "Retrouvez-le dans **Archives → Loading Reports**.",
            icon="✅",
        )
    else:
        # Import lazy — évite la KeyError: 'ui_helpers' en Python 3.14 lors du
        # hot-reload (tracking.py ET cette page modifiés dans le même commit).
        import importlib as _il
        _tracking = _il.import_module("tracking")
        identity = _tracking.load_user_identity()
        agent_name = identity.get("name", "") if identity else ""

        st.caption(
            "Enregistre les fichiers générés dans l'historique pour consultation "
            "et re-téléchargement ultérieur."
        )

        col_archive, col_info = st.columns([1, 2])
        with col_archive:
            do_archive = st.button(
                "📥 Archiver",
                type="primary",
                use_container_width=True,
                disabled=(not masque_bytes and not iso_bytes),
                help="Sauvegarde le MASQUE TCS et le TYPE ISO dans l'historique.",
            )
        with col_info:
            if not agent_name:
                st.info(
                    "Identité non configurée — l'archivage sera enregistré sans nom d'agent. "
                    "Configurez votre identité dans **Paramètres**.",
                    icon="ℹ️",
                )
            else:
                st.caption(f"Agent : **{agent_name}**")

        if do_archive:
            try:
                masque_path = None
                iso_path = None
                if masque_bytes:
                    masque_path = _tracking.save_masque_csv(masque_bytes)
                if iso_bytes:
                    iso_path = _tracking.save_iso_csv(iso_bytes)

                _tracking.log_loading_report(
                    agent=agent_name or "Inconnu",
                    navire=selected_v.get("navire") or "",
                    voyage=selected_v.get("voyage") or "",
                    compte_escale=compte_escale.strip(),
                    nb_conteneurs=len(df_final),
                    source_file=selected_v.get("_source_file") or "",
                    masque_path=masque_path,
                    iso_path=iso_path,
                )
                st.session_state[_archive_key] = True
                st.success(
                    "Traitement archivé avec succès. "
                    "Retrouvez-le dans **Archives → Loading Reports**.",
                    icon="✅",
                )
                st.rerun()
            except Exception as e:
                st.error(f"Erreur lors de l'archivage : {e}", icon="🚫")

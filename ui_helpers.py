"""Éléments d'interface partagés (style, aide, contrôle d'accès) entre les
pages de l'application.

Palette et typographie alignées sur un usage BI/corporate (Segoe UI), avec des
couleurs validées pour la lisibilité (contraste, distinction daltonisme).
"""
import pandas as pd
import streamlit as st

# Version affichée en indicatif dans l'app (sidebar) — à incrémenter à
# chaque livraison fonctionnelle notable, sert aussi de traçabilité pour le
# triage des avis (voir tracking.save_avis -> version_app).
APP_VERSION = "7.29.0"

# ── Charte TERRA (refonte 08/10/2026) ─────────────────────────────────────
# Vert et orange du logo. Le vert foncé est la couleur des actions et de la
# série principale (contraste suffisant sur blanc) ; l'orange sert à mettre
# en avant (survol, budget non atteint) et jamais pour du texte. Le rouge
# n'est plus une couleur de marque : il est réservé aux erreurs.
TERRA = {
    "green": "#0B7A2E",       # actions, série principale
    "green_logo": "#08942C",  # vert exact du logo (aplats, pas de texte)
    "green_light": "#5CBF7A", # au-delà du budget, série secondaire claire
    "orange": "#EF8100",      # mise en avant
    "ink": "#15301F",         # info-bulles, repère budget
    "text": "#1A1A1A",
    "muted": "#5E5B57",
    "border": "#E1E8E2",
    "bg": "#F3F6F1",
    "bg_soft": "#F7FAF6",
    "grid": "#E8EEE8",
    "n1": "#9DB0A2",          # année précédente
}

# Palette catégorielle (ordre fixe — ne jamais réordonner selon les filtres).
# Les clés historiques sont conservées pour ne pas casser les pages : elles
# désignent désormais un rôle (« blue » = série principale), plus une teinte.
PALETTE = {
    "blue": TERRA["green"],
    "orange": TERRA["orange"],
    "aqua": "#1F5F9E",
    "yellow": "#E0B000",
    "magenta": "#C2508A",
    "green": TERRA["green_light"],
    "violet": "#6B4FA8",
    "red": "#B3261E",
}
CATEGORICAL_SEQUENCE = [PALETTE["blue"], PALETTE["orange"], PALETTE["aqua"],
                         PALETTE["yellow"], PALETTE["green"], PALETTE["violet"]]

# Rampe séquentielle (une seule teinte, pour les grandeurs/classements)
SEQUENTIAL_GREEN = ["#E4F3E7", "#C2E3CA", "#93CDA2", "#5CB677", "#2E9A50", "#0B7A2E"]
SEQUENTIAL_BLUE = SEQUENTIAL_GREEN  # ancien nom, conservé pour compatibilité

STATUS = {"good": "#1E6B3A", "warning": "#E0B000", "serious": "#EF8100", "critical": "#B3261E"}

# Teintes douces des pastilles (fond, texte) — cartes, avatars, raccourcis
TONES = [("#E4F3E7", "#0B7A2E"), ("#FDEBD3", "#A85600"), ("#E8F1FB", "#1F5F9E"),
         ("#FFF4CC", "#7A5B00"), ("#E4F3E7", "#0B7A2E")]

FONT_FAMILY = "Segoe UI, Source Sans 3, -apple-system, BlinkMacSystemFont, sans-serif"

CSS = f"""
<style>
html, body, [class*="css"], [data-testid="stAppViewContainer"] {{
    font-family: {FONT_FAMILY};
}}
/* Cartes métriques natives (st.metric) au style des cartes TERRA */
div[data-testid="stMetric"] {{
    background: #ffffff;
    border: 1px solid {TERRA["border"]};
    border-radius: 12px;
    padding: 14px 16px 10px 16px;
    min-width: 0;
    height: auto !important;
}}
div[data-testid="stMetric"] * {{
    min-width: 0;
}}
div[data-testid="stMetricLabel"], div[data-testid="stMetricLabel"] *,
div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] *,
div[data-testid="stMetricDelta"], div[data-testid="stMetricDelta"] * {{
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: unset !important;
    height: auto !important;
}}
div[data-testid="stMetricLabel"] {{
    font-size: 0.8rem;
    color: {TERRA["muted"]};
}}
div[data-testid="stMetricValue"] {{
    font-size: 1.6rem;
    line-height: 1.2;
}}
div[data-testid="stMetricDelta"] {{
    font-size: 0.8rem;
}}
/* Menu latéral : titres de section en petites capitales, entrée active teintée */
[data-testid="stSidebarNav"] li div a {{
    font-size: 0.95rem;
    border-radius: 8px;
}}
[data-testid="stNavSectionHeader"] {{
    font-size: 0.7rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: #7C877F !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: {TERRA["green"]}1A;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{
    color: {TERRA["green"]} !important;
    font-weight: 600;
}}
.stTabs [data-baseweb="tab"] {{
    font-weight: 600;
}}
.stTabs [data-baseweb="tab-highlight"] {{
    background-color: {TERRA["green"]};
}}
div[data-testid="stExpander"] details summary p {{
    font-weight: 600;
}}

/* ── Composants TERRA (voir kpi_row, section_header, source_badge) ── */
.t-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 4px 0 12px; }}
.t-kpi {{ background: #fff; border: 1px solid {TERRA["border"]}; border-radius: 12px; padding: 14px 16px;
          display: flex; flex-direction: column; gap: 6px; min-width: 0; }}
.t-kpi-head {{ display: flex; align-items: center; gap: 10px; color: #3B3936; font-weight: 500; }}
.t-chip {{ width: 30px; height: 30px; border-radius: 8px; flex: none; display: flex; align-items: center; justify-content: center; }}
.t-kpi-val {{ font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; line-height: 1.2; }}
.t-delta {{ display: inline-flex; align-items: center; gap: 3px; font-weight: 600; font-size: 0.82rem; }}
.t-up {{ color: #1E6B3A; }} .t-down {{ color: #A3470E; }} .t-flat {{ color: #7C877F; }}
.t-bud {{ position: relative; height: 8px; background: #E3EAE4; border-radius: 4px; margin-top: 6px; }}
.t-bud-fill {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; }}
.t-bud-mark {{ position: absolute; top: -4px; bottom: -4px; width: 3px; border-radius: 2px; background: {TERRA["ink"]};
               box-shadow: 0 0 0 2px #fff; }}
.t-bud-txt {{ font-size: 0.78rem; color: {TERRA["muted"]}; }}
.t-sec {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 6px 0 2px; }}
.t-sec h3 {{ margin: 0; padding: 0; font-size: 1.1rem; font-weight: 600; }}
.t-sec .t-sub {{ color: {TERRA["muted"]}; font-size: 0.9rem; }}
.t-src {{ position: relative; display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px;
          border-radius: 50%; background: #EEF4EF; color: #4F6B57 !important; text-decoration: none !important; flex: none; }}
.t-src:hover, .t-src:focus-visible {{ background: #DCEADF; color: {TERRA["green"]} !important; }}
.t-src .t-tip {{ position: absolute; top: calc(100% + 8px); left: -6px; z-index: 50; width: max-content; max-width: 260px;
                 display: flex; flex-direction: column; gap: 2px; background: {TERRA["ink"]}; color: #fff; font-size: 12px;
                 line-height: 1.45; font-weight: 400; padding: 9px 11px; border-radius: 9px;
                 box-shadow: 0 8px 24px rgba(21,48,31,0.28); text-align: left; pointer-events: none;
                 opacity: 0; clip-path: inset(50%); transition: opacity .12s; }}
.t-src .t-tip b {{ font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: #9FD3AE; }}
.t-src .t-tip i {{ font-style: normal; color: #F2B566; font-size: 11px; margin-top: 2px; }}
.t-src:hover .t-tip, .t-src:focus-visible .t-tip {{ opacity: 1; clip-path: none; }}
.t-empty {{ background: #fff; border: 1px dashed #C9D4CB; border-radius: 12px; padding: 36px 24px; text-align: center;
            display: flex; flex-direction: column; align-items: center; gap: 6px; color: {TERRA["muted"]}; }}
.t-empty strong {{ color: {TERRA["text"]}; font-size: 1rem; }}
.t-list {{ display: flex; flex-direction: column; background: #fff; border: 1px solid #E3EAE4; border-radius: 12px; margin: 6px 0 14px; }}
.t-li {{ display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-top: 1px solid #EEF2EE; }}
.t-li:first-child {{ border-top: 0; }}
.t-li-main {{ display: flex; flex-direction: column; min-width: 0; flex: 1; }}
.t-li-main b {{ font-weight: 600; color: {TERRA["text"]}; font-size: 0.92rem; }}
.t-li-main span {{ color: {TERRA["muted"]}; font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.t-li-right {{ color: {TERRA["muted"]}; font-size: 0.82rem; white-space: nowrap; }}
.t-grid {{ border-collapse: separate; border-spacing: 4px; font-size: 13px; }}
.t-grid th {{ font-weight: 600; color: {TERRA["muted"]}; padding: 4px 6px; }}
.t-grid th.t-row {{ text-align: left; font-weight: 500; color: {TERRA["text"]}; white-space: nowrap; }}
.t-grid th.t-row small {{ display: block; font-size: 11px; color: #7C877F; font-weight: 400; }}
.t-grid th.t-row u {{ text-decoration: underline dotted #9AA59D; text-underline-offset: 3px; }}
.t-cell {{ text-align: center; height: 32px; min-width: 52px; border-radius: 6px; font-weight: 700; cursor: help; }}
.t-ok {{ background: #E4F3E7; color: #1E6B3A; border: 1px solid #93CDA2; }}
.t-todo {{ background: #FDEBD3; color: #8A4B00; border: 1px solid #F2B566; }}
.t-opt {{ background: #F3F6F1; color: #9AA59D; border: 1px solid #E1E8E2; }}
.t-tt {{ position: relative; outline: none; }}
.t-tt .t-tip2 {{ position: absolute; top: calc(100% + 6px); left: 0; z-index: 60; width: max-content; max-width: 300px;
                display: flex; flex-direction: column; gap: 3px; background: {TERRA["ink"]}; color: #fff; font-size: 12px;
                line-height: 1.45; font-weight: 400; padding: 10px 12px; border-radius: 9px; text-align: left;
                box-shadow: 0 8px 24px rgba(21,48,31,0.28); white-space: normal; pointer-events: none;
                opacity: 0; clip-path: inset(50%); transition: opacity .12s; }}
td.t-tt .t-tip2 {{ left: 50%; transform: translateX(-50%); }}
.t-tt .t-tip2 b {{ font-size: 11px; letter-spacing: .05em; text-transform: uppercase; color: #9FD3AE; }}
.t-tt .t-tip2 code {{ font-family: Consolas, monospace; font-size: 11px; color: #E8F1E9; background: rgba(255,255,255,0.08);
                     border-radius: 4px; padding: 1px 4px; }}
.t-tt .t-tip2 i {{ font-style: normal; color: #F2B566; }}
.t-tt:hover .t-tip2, .t-tt:focus-visible .t-tip2 {{ opacity: 1; clip-path: none; }}
.t-legend {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: {TERRA["muted"]}; margin: 4px 0 10px; }}
.t-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.t-legend em {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
.t-rappel {{ display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 14px; background: #FDEBD3;
             border: 1px solid #F6CB95; border-radius: 12px; color: #6B3A00; margin: 4px 0 12px; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def help_expander(title):
    """Bloc d'aide repliable, discret par défaut, avec des indications concrètes."""
    return st.expander(title, expanded=False)


def combo_with_custom(label, options, default_value="", key="combo",
                       custom_label="Autre (préciser)…", help=None):
    """Sélecteur "liste + saisie libre" : une liste déroulante alimentée par
    les valeurs déjà connues, plus un choix "Autre" qui révèle un champ texte.

    Permet à l'utilisateur d'utiliser une valeur existante EN UN CLIC, ou d'en
    saisir une nouvelle librement sans être bloqué par une liste figée — toute
    valeur personnalisée saisie une fois devient ensuite une suggestion pour
    les autres (voir tracking.get_known_services/get_known_roles). Retourne la
    valeur finale choisie ou saisie (str, espaces superflus retirés)."""
    opts = list(dict.fromkeys(o for o in options if o))  # dédoublonne, garde l'ordre
    full_opts = opts + [custom_label]
    if default_value and default_value in opts:
        default_idx = full_opts.index(default_value)
    elif default_value:
        default_idx = len(full_opts) - 1  # valeur inconnue -> "Autre", pré-remplie
    else:
        default_idx = 0
    choice = st.selectbox(label, full_opts, index=default_idx, key=f"{key}_select", help=help)
    if choice == custom_label:
        prefill = default_value if default_value not in opts else ""
        return st.text_input(
            f"Préciser « {label} »", value=prefill, key=f"{key}_custom",
        ).strip()
    return choice


def format_duree(sec):
    """Formate une durée en secondes de façon lisible, y compris pour les
    traitements quasi instantanés (extraction déterministe, souvent < 1s).
    Partagé entre le tableau de bord et l'archive pour un affichage cohérent."""
    if pd.isna(sec):
        return "—"
    if sec < 10:
        return f"{sec:.1f} s"
    return f"{sec:.0f} s"


# ---------------------------------------------------------------------------
# Contrôle d'accès par rôle — voir tracking.get_access_role/ACCESS_ROLES.
# Rôles : "agent" (défaut — pages de saisie uniquement), "analyste" (accès
# total + gestion des comptes), "direction" (tableau de bord + classification
# véhicules en lecture). Un rôle élevé nécessite un compte protégé par mot de
# passe personnel (voir views/profil.py) — sans ça, il reste "agent".
# ---------------------------------------------------------------------------
ACCESS_ROLE_LABELS = {
    "agent": "Agent",
    "analyste": "Analyste Data",
    "direction": "Direction",
}


def current_identity() -> dict | None:
    """Identité (nom/service/rôle métier) de la personne actuellement
    identifiée sur ce poste, ou None si personne ne s'est identifiée."""
    return st.session_state.get("identity")


def current_access_role() -> str:
    """Rôle d'ACCÈS (permissions) de la personne actuellement identifiée :
    "agent" si personne n'est identifiée. Mis en cache dans la session pour
    éviter une requête Supabase à chaque rerun Streamlit — le cache est
    invalidé automatiquement dès que le nom identifié change, et peut être
    forcé via invalidate_access_role_cache() après une promotion/modification
    de mot de passe pour la personne elle-même."""
    identity = st.session_state.get("identity")
    if not identity or not identity.get("name"):
        return "agent"
    cache = st.session_state.get("_access_role_cache")
    if cache and cache.get("name") == identity["name"]:
        return cache["role"]
    from tracking import get_access_role  # import différé — évite un cycle au chargement du module
    role = get_access_role(identity["name"])
    st.session_state["_access_role_cache"] = {"name": identity["name"], "role": role}
    return role


def invalidate_access_role_cache() -> None:
    """À appeler après un changement de mot de passe personnel ou de rôle
    d'accès (le sien ou celui d'un autre compte via la gestion des accès),
    pour que le prochain appel à current_access_role() relise Supabase."""
    st.session_state.pop("_access_role_cache", None)


# ── Réinitialisation de page en un clic (uploaders + résultats) ───────────
def upl_key(base: str) -> str:
    """Clé d'un file_uploader qu'on peut « vider » : changer la clé recrée le
    widget vide (un file_uploader ne peut pas être vidé autrement)."""
    return f"{base}__{st.session_state.get('_upl_seq_' + base, 0)}"


def reset_page_button(bases, state_keys=(), key: str = "reset_page", label: str = "Tout réinitialiser",
                      has_content: bool = True):
    """Bouton unique qui vide les fichiers chargés (uploaders `bases`, clés
    obtenues via upl_key) et supprime les résultats gardés en session
    (`state_keys`), puis relance la page. N'affiche rien s'il n'y a rien à
    réinitialiser (has_content=False)."""
    if not has_content:
        return False
    if st.button(label, key=key, icon=":material/restart_alt:",
                 help="Vide les fichiers chargés et efface les résultats affichés."):
        for b in bases:
            st.session_state["_upl_seq_" + b] = st.session_state.get("_upl_seq_" + b, 0) + 1
        for k in state_keys:
            st.session_state.pop(k, None)
        st.rerun()
    return False



# ===========================================================================
# Composants visuels TERRA (refonte 08/10/2026) — à utiliser dans les pages
# à la place des emojis, des st.metric isolés et des styles de graphique
# recopiés page par page. Tout est en HTML/SVG statique : aucun JavaScript.
# ===========================================================================
import html as _html

import plotly.graph_objects as _go
import plotly.io as _pio

# Icônes (tracés SVG 24×24, trait) — mêmes dessins que la maquette validée.
ICONS = {
    "home": "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5M10 21v-6h4v6",
    "file_plus": "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M12 11v6M9 14h6",
    "file": "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zM14 3v5h5M8 13h8M8 17h5",
    "grid": "M4 4h16v16H4zM4 10h16M10 4v16",
    "table": "M4 5h16v14H4zM4 10h16M4 15h16M10 5v14",
    "chart": "M4 20h16M7 16v-6M12 16V6M17 16v-4",
    "trend": "M4 19h16M5 15l4-5 4 3 6-7M15 6h4v4",
    "archive": "M3 5h18v4H3zM5 9v11h14V9M10 13h4",
    "ship": "M3 15h18l-2.5 5h-13zM6 15V9h12v6M12 4v5M9 6h6",
    "anchor": "M12 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM12 8v13M5 13a7 7 0 0 0 14 0M8 11h8",
    "car": "M3 17v-5l2.5-5h13L21 12v5zM3 12h18M7 17v2M17 17v2",
    "container": "M3 7h18v10H3zM7 7v10M11 7v10M15 7v10",
    "tag": "M3 12V4h8l10 10-8 8zM8 8h.01",
    "globe": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18",
    "database": "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"
                "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    "check": "M5 12l4 4 10-10",
    "alert": "M12 3 2 20h20zM12 9v5M12 17h.01",
    "clock": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
    "upload": "M12 15V4M7 9l5-5 5 5M5 20h14",
    "download": "M12 4v11M7 10l5 5 5-5M5 20h14",
    "edit": "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
    "up": "M12 19V5M6 11l6-6 6 6",
    "down": "M12 5v14M6 13l6 6 6-6",
    "lock": "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
    "search": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
    "eye_off": "M3 3l18 18M10.6 6.1A9 9 0 0 1 21 12a14 14 0 0 1-2.4 3.2M6.6 6.6A14 14 0 0 0 3 12a9 9 0 0 0 12.4 5.4",
}


def icon(name: str, size: int = 16, color: str = "currentColor", stroke: float = 1.8) -> str:
    """Icône SVG en ligne (chaîne HTML). Remplace les emojis dans les blocs
    st.markdown(..., unsafe_allow_html=True). Pour un bouton ou un menu,
    préférer les icônes Material natives de Streamlit (":material/nom:")."""
    d = ICONS.get(name, ICONS["file"])
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{d}"></path></svg>')


def _fr(n) -> str:
    """Nombre au format français (espace fine comme séparateur de milliers)."""
    try:
        return f"{float(n):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def source_badge(source: str, link: str | None = None, action: str = "Cliquer pour ouvrir") -> str:
    """Pastille « source » : une icône ronde ; au survol, une info-bulle dit
    d'où vient la donnée. `link` : URL d'une page de l'app (ex. "stats_flash")."""
    tip = (f'<span class="t-tip" role="tooltip"><b>Source</b><span>{_html.escape(source)}</span>'
           + (f'<i>{_html.escape(action)}</i>' if link else '') + '</span>')
    label = _html.escape("Source : " + source)
    if link:
        return (f'<a class="t-src" href="{_html.escape(link)}" target="_self" aria-label="{label}">'
                f'{icon("database", 14)}{tip}</a>')
    return f'<span class="t-src" tabindex="0" aria-label="{label}">{icon("database", 14)}{tip}</span>'


def section_header(title: str, subtitle: str | None = None, source: str | None = None,
                   link: str | None = None) -> None:
    """Titre de bloc + sous-titre discret + pastille source (facultative)."""
    sub = f'<span class="t-sub">{_html.escape(subtitle)}</span>' if subtitle else ""
    badge = source_badge(source, link) if source else ""
    st.markdown(f'<div class="t-sec"><h3>{_html.escape(title)}</h3>{sub}{badge}</div>',
                unsafe_allow_html=True)


def budget_text(value, budget) -> str:
    """« atteint » si égal, « dépassé de X » au-dessus, « reste X » en dessous."""
    if budget in (None, 0) or pd.isna(budget):
        return "Aucun budget"
    if value == budget:
        return f"Budget {_fr(budget)} · atteint"
    if value > budget:
        return f"Budget {_fr(budget)} · dépassé de {_fr(value - budget)}"
    return f"Budget {_fr(budget)} · reste {_fr(budget - value)}"


def kpi_card(label: str, value, previous=None, budget=None, icon_name: str = "chart", tone: int = 0,
             previous_label: str = "vs N-1", fmt=None) -> str:
    """Carte indicateur (chaîne HTML) : valeur, écart vs N-1, barre budget avec
    repère. À regrouper avec kpi_row([...]) pour un alignement en grille."""
    bg, fg = TONES[tone % len(TONES)]
    shown = fmt(value) if fmt else _fr(value)
    parts = [f'<div class="t-kpi"><div class="t-kpi-head"><span class="t-chip" style="background:{bg};color:{fg}">'
             f'{icon(icon_name, 17)}</span>{_html.escape(label)}</div><div class="t-kpi-val">{shown}</div>']
    if previous not in (None, 0) and not pd.isna(previous) and value is not None and not pd.isna(value):
        p = (value - previous) / previous * 100
        cls, arrow = ("t-up", "up") if p >= 0 else ("t-down", "down")
        pct = f'{"+" if p >= 0 else "−"}{abs(p):.1f}'.replace(".", ",")
        parts.append(f'<span class="t-delta {cls}">{icon(arrow, 13, stroke=2.2)}{pct} % '
                     f'{_html.escape(previous_label)}</span>')
    if budget not in (None, 0) and not pd.isna(budget) and value is not None and not pd.isna(value):
        top = max(value, budget)
        fill = TERRA["green"] if value >= budget else TERRA["orange"]
        parts.append(f'<div class="t-bud"><div class="t-bud-fill" style="width:{value / top * 88:.1f}%;background:{fill}"></div>'
                     f'<div class="t-bud-mark" style="left:calc({budget / top * 88:.1f}% - 1px)"></div></div>'
                     f'<span class="t-bud-txt">{budget_text(value, budget)}</span>')
    parts.append("</div>")
    return "".join(parts)


def kpi_row(cards: list[str]) -> None:
    """Affiche des cartes kpi_card() en grille adaptative (une seule ligne de
    code HTML : un seul rendu, pas un st.columns par carte)."""
    st.markdown(f'<div class="t-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def vue_switch(key: str, default: str = "Graphique") -> bool:
    """Bascule Graphique / Tableau. Retourne True pour « Graphique »."""
    choice = st.segmented_control(
        "Affichage", ["Graphique", "Tableau"], default=default, key=key,
        format_func=lambda o: (":material/bar_chart: " if o == "Graphique" else ":material/table_rows: ") + o,
        label_visibility="collapsed")
    return (choice or default) == "Graphique"


def empty_state(title: str, text: str = "", icon_name: str = "table") -> None:
    """Bloc vide explicite (au lieu d'un tableau vide ou d'un st.info générique)."""
    st.markdown(f'<div class="t-empty">{icon(icon_name, 28, "#7C877F", 1.6)}<strong>{_html.escape(title)}</strong>'
                f'<span>{_html.escape(text)}</span></div>', unsafe_allow_html=True)


# ── Modèle Plotly « terra » ────────────────────────────────────────────────
# Usage : fig.update_layout(template="terra") ou PLOT_LAYOUT ci-dessous.
# Info-bulles sombres et concises ; utiliser hover_lines() pour le contenu.
_pio.templates["terra"] = _go.layout.Template(
    layout=dict(
        font=dict(family=FONT_FAMILY, color=TERRA["text"], size=13),
        colorway=CATEGORICAL_SEQUENCE,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        title=dict(x=0, font=dict(size=15, color=TERRA["text"])),
        margin=dict(t=56, l=10, r=10, b=10),
        hoverlabel=dict(bgcolor=TERRA["ink"], bordercolor=TERRA["ink"],
                        font=dict(family=FONT_FAMILY, color="#FFFFFF", size=12), align="left"),
        legend=dict(orientation="h", y=-0.15, x=0, font=dict(color=TERRA["muted"], size=12)),
        xaxis=dict(showgrid=False, linecolor="#C9D4CB", tickfont=dict(color=TERRA["muted"]), title=dict(text="")),
        yaxis=dict(gridcolor=TERRA["grid"], zeroline=False, tickfont=dict(color=TERRA["muted"]),
                   tickformat=",.0f", separatethousands=True),
        separators=", ",
        bargap=0.35,
    ),
    data=dict(bar=[_go.Bar(marker=dict(cornerradius=4))]),
)
PLOT_TEMPLATE = "plotly_white+terra"


def hover_lines(title: str, lines: list[tuple[str, str]], insight: str | None = None) -> str:
    """Construit un hovertemplate court et lisible :
    titre en gras, lignes « libellé  valeur », ligne de lecture en orange.
    Les valeurs peuvent contenir des variables Plotly (%{y:,.0f}, %{customdata[0]})."""
    body = "<br>".join(f"<span style='color:#C9D6CC'>{l}</span>  <b>{v}</b>" for l, v in lines)
    tail = f"<br><span style='color:#F2B566'>{insight}</span>" if insight else ""
    return f"<b>{title}</b><br>{body}{tail}<extra></extra>"


# ── État des données Stats Flash (grille + rappel) ─────────────────────────
def etat_donnees_html(e: dict, donnees: dict) -> str:
    """Grille « donnée × mois » avec info-bulles (voir donnees_dispo.etat)."""
    import stats_flash_builder as _sfb
    esc_ = _html.escape
    head = "".join(f"<th scope='col'>{_sfb.MOIS_COURT[m - 1]}</th>" for m in e["mois"])
    rows = []
    for cle, cells in e["lignes"].items():
        lab, sub, ou, fichier, apport = donnees[cle]
        a = str(e["annee"])
        fichier = fichier.replace("<AAAA-1>", str(e["annee"] - 1)).replace("<AAAA>", a)
        ou = ou.replace("<AAAA>", a)
        tip = (f"<span class='t-tip2' role='tooltip'><b>Où le trouver</b><span>{esc_(ou)}</span>"
               + (f"<span>Nom du fichier : <code>{esc_(fichier)}</code></span>" if fichier != "—" else "")
               + f"<i>{esc_(apport)}</i></span>")
        tds = "".join(
            f"<td class='t-cell t-{c['statut']} t-tt' tabindex='0'>"
            f"{'✓' if c['statut'] == 'ok' else '!' if c['statut'] == 'todo' else '–'}"
            f"<span class='t-tip2' role='tooltip'><b>{esc_(c['titre'])}</b>"
            + "".join(f"<span>{esc_(c[k])}</span>" for k in ("l1", "l2") if c.get(k))
            + (f"<i>{esc_(c['l3'])}</i>" if c.get("l3") else "") + "</span></td>"
            for c in cells)
        rows.append(f"<tr><th scope='row' class='t-row t-tt' tabindex='0'><u>{esc_(lab)}</u><small>{esc_(sub)}</small>"
                    f"{tip}</th>{tds}</tr>")
    legend = ("<div class='t-legend'><span><em class='t-ok'></em>Disponible</span>"
              "<span><em class='t-todo'></em>À compléter</span><span><em class='t-opt'></em>Facultatif</span>"
              "<span>Survolez une case pour le détail, et le nom d'une donnée pour son dossier SharePoint.</span></div>")
    return (f"<div><table class='t-grid'><thead><tr>"
            f"<th scope='col' style='text-align:left'>Donnée</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody>"
            f"</table></div>{legend}")


def rappel_donnees(e: dict, ou: str = "l'onglet « Charger un mois » de Stats Flash") -> None:
    """Bandeau de rappel : données à compléter (rien si tout est disponible)."""
    if not e or not e.get("manquants"):
        return
    n = len(e["manquants"])
    quoi = "; ".join(m["quoi"] for m in e["manquants"])
    st.markdown(f"<div class='t-rappel' role='status'>{icon('alert', 18)}<span><b>Rappel · {n} donnée(s) à compléter.</b> "
                f"{_html.escape(quoi)}. Les blocs concernés restent masqués tant qu'elles manquent. "
                f"Voir {_html.escape(ou)}.</span></div>", unsafe_allow_html=True)

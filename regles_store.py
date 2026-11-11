"""
regles_store.py — Règles apprises des comparaisons au pré-masque agent (PR B2).

Tables (créées à la main dans l'éditeur SQL, voir supabase_schema.sql) :
  manifestes_regles_apprises, manifestes_comparaisons, manifestes_ecarts_structure.
Rien n'est jamais supprimé : une règle se désactive / se réactive, et chaque
changement est daté et signé. Une base indisponible n'empêche jamais de produire
le pré-masque : les règles ne s'appliquent simplement pas.
"""
import time
from datetime import datetime, timezone

import tracking

_CACHE = {"t": 0.0, "regles": []}
_TTL = 60                       # secondes : une règle validée sert au plus tard 1 min après
SEUIL_STRUCTURE = 3             # 3 surcharges sur la même colonne -> écart de structure


def _now():
    return datetime.now(timezone.utc)


def regles_actives() -> list:
    """Règles actives (dicts), mises en cache 60 s."""
    if time.monotonic() - _CACHE["t"] < _TTL:
        return _CACHE["regles"]
    try:
        conn = tracking._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT id, niveau, colonne, chassis, valeur_app, valeur
                               FROM manifestes_regles_apprises WHERE active ORDER BY id""")
                cols = [d[0] for d in cur.description]
                _CACHE["regles"] = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        # tables pas encore créées / base indisponible : aucune règle pendant 60 s,
        # sans retenter la connexion à chaque pré-masque.
        _CACHE["regles"] = []
    _CACHE["t"] = time.monotonic()
    return _CACHE["regles"]


def _compter(ids) -> None:
    if not ids:
        return
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE manifestes_regles_apprises
                           SET utilisations = utilisations + 1, derniere_utilisation = %s
                           WHERE id = ANY(%s)""", (_now(), list(ids)))
        conn.commit()
    finally:
        conn.close()


regles_actives.compter = _compter      # appelé par premasque_ipaki après application


def vider_cache() -> None:
    _CACHE["t"] = 0.0


def enregistrer_regles(regles, auteur, navire="", voyage="", format_manifeste="") -> list:
    """Enregistre les règles acceptées (doublons actifs ignorés). Renvoie les ids créés,
    puis ouvre un écart de structure si une colonne cumule trop de surcharges."""
    ids = []
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            for rg in regles:
                cle = (int(rg["Niveau"]), rg["Colonne"], rg.get("Châssis") or "",
                       rg.get("Si l'app donne") or "", str(rg["Mettre"]))
                # règle incomplète (sans valeur de départ, ou surcharge sans châssis) : ignorée
                if (cle[0] in (1, 2) and not cle[3]) or (cle[0] == 3 and not cle[2]) or not cle[4]:
                    continue
                cur.execute("""SELECT id FROM manifestes_regles_apprises
                               WHERE active AND niveau=%s AND colonne=%s AND chassis=%s
                                 AND valeur_app=%s AND valeur=%s""", cle)
                if cur.fetchone():
                    continue
                cur.execute("""INSERT INTO manifestes_regles_apprises
                               (niveau, colonne, chassis, valeur_app, valeur, format_manifeste,
                                navire, voyage, auteur, horodatage, active, utilisations, journal)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,0,%s) RETURNING id""",
                            cle + (format_manifeste, navire, voyage, auteur, _now(),
                                   f"{_now():%d/%m/%Y %H:%M} créée par {auteur}"))
                ids.append(cur.fetchone()[0])
            # surcharges ponctuelles répétées sur une colonne -> signal pour corriger le parser
            cur.execute("""SELECT colonne, COUNT(*) FROM manifestes_regles_apprises
                           WHERE active AND niveau = 3 GROUP BY colonne HAVING COUNT(*) >= %s""",
                        (SEUIL_STRUCTURE,))
            for colonne, n in cur.fetchall():
                cur.execute("""SELECT 1 FROM manifestes_ecarts_structure
                               WHERE colonne=%s AND statut='ouvert' AND origine='auto'""", (colonne,))
                if not cur.fetchone():
                    cur.execute("""INSERT INTO manifestes_ecarts_structure
                                   (horodatage, navire, voyage, colonne, description, statut, origine, auteur)
                                   VALUES (%s,%s,%s,%s,%s,'ouvert','auto',%s)""",
                                (_now(), navire, voyage, colonne,
                                 f"{n} surcharges ponctuelles actives sur « {colonne} » : "
                                 "le parser lit mal cette colonne, à corriger par une PR.", auteur))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    vider_cache()
    return ids


def lister_regles():
    import pandas as pd
    conn = tracking._connect()
    try:
        return pd.read_sql_query("""SELECT id, active, niveau, colonne, chassis, valeur_app, valeur,
                                           format_manifeste, navire, voyage, auteur, horodatage,
                                           utilisations, derniere_utilisation, journal
                                    FROM manifestes_regles_apprises ORDER BY id DESC""", conn)
    finally:
        conn.close()


def changer_etat(regle_id: int, active: bool, auteur: str) -> None:
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE manifestes_regles_apprises
                           SET active=%s, journal = journal || %s WHERE id=%s""",
                        (active, f"\n{_now():%d/%m/%Y %H:%M} {'réactivée' if active else 'désactivée'} par {auteur}",
                         int(regle_id)))
        conn.commit()
    finally:
        conn.close()
    vider_cache()


def enregistrer_comparaison(res: dict, navire, voyage, auteur, nb_regles=0) -> None:
    """Trace d'une comparaison : compteurs seulement, aucune donnée client."""
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO manifestes_comparaisons
                           (horodatage, navire, voyage, auteur, retrouves, absents_agent, absents_app,
                            concordance, ecarts, regles_enregistrees)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (_now(), navire, voyage, auteur, res["retrouves"], len(res["absents_agent"]),
                         len(res["absents_app"]), res["concordance"],
                         int((res["ecarts"]["Classement"] != "ignoré").sum()), nb_regles))
        conn.commit()
    finally:
        conn.close()


def lister_ecarts_structure():
    import pandas as pd
    conn = tracking._connect()
    try:
        return pd.read_sql_query("""SELECT id, statut, horodatage, navire, voyage, colonne, description,
                                           origine, auteur FROM manifestes_ecarts_structure
                                    ORDER BY id DESC""", conn)
    finally:
        conn.close()


def changer_statut_ecart(ecart_id: int, statut: str) -> None:
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE manifestes_ecarts_structure SET statut=%s WHERE id=%s", (statut, int(ecart_id)))
        conn.commit()
    finally:
        conn.close()

"""Stockage Supabase de l'onglet « Opérations navire » (Reporting navire).

Tables (créées à la main dans l'éditeur SQL, voir supabase_schema.sql) :
  manifestes_ops_operateurs, manifestes_ops_regles, manifestes_ops_historique.
Aucune ligne véhicule n'est stockée : l'historique ne garde que des totaux.
Une base indisponible n'empêche jamais de produire le formulaire.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import tracking

OPERATEURS_DEFAUT = [("Z40", "EUKOR"), ("Z1M", "GLOVIS")]


def _now():
    return datetime.now(timezone.utc)


def _requete(sql, params=(), lecture=True):
    conn = tracking._connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if lecture:
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.commit()
        return None
    finally:
        conn.close()


# ---------------------------------------------------------------- opérateurs
def operateurs() -> list[dict]:
    """[{code, libelle}] ; liste par défaut si la base est indisponible."""
    try:
        rows = _requete("SELECT code, libelle FROM manifestes_ops_operateurs WHERE actif ORDER BY libelle")
        return rows or [{"code": c, "libelle": l} for c, l in OPERATEURS_DEFAUT]
    except Exception:
        return [{"code": c, "libelle": l} for c, l in OPERATEURS_DEFAUT]


def ajouter_operateur(code: str, libelle: str, auteur: str) -> None:
    code, libelle = code.strip().upper(), libelle.strip().upper()
    if not code or not libelle:
        raise ValueError("Code et libellé obligatoires")
    _requete("""INSERT INTO manifestes_ops_operateurs (code, libelle, actif, auteur, horodatage)
                VALUES (%s, %s, TRUE, %s, %s)
                ON CONFLICT (code) DO UPDATE SET libelle = EXCLUDED.libelle, actif = TRUE,
                    auteur = EXCLUDED.auteur, horodatage = EXCLUDED.horodatage""",
             (code, libelle, auteur, _now()), lecture=False)


# ---------------------------------------------------------------- règles
def regles(type_regle: str) -> dict[str, str]:
    """type_regle : 'client' ou 'exploitant'. Renvoie {clé -> code opérateur}."""
    try:
        rows = _requete("SELECT cle, operateur FROM manifestes_ops_regles WHERE type = %s", (type_regle,))
        return {r["cle"]: r["operateur"] for r in rows}
    except Exception:
        return {}


def enregistrer_regles(type_regle: str, choix: dict[str, tuple[str, str]], auteur: str) -> None:
    """choix : {clé -> (libellé lu dans le fichier, code opérateur)}. Une ligne par clé (mise à jour)."""
    for cle, (libelle, op) in choix.items():
        _requete("""INSERT INTO manifestes_ops_regles (type, cle, libelle, operateur, auteur, horodatage)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (type, cle) DO UPDATE SET operateur = EXCLUDED.operateur,
                        libelle = EXCLUDED.libelle, auteur = EXCLUDED.auteur, horodatage = EXCLUDED.horodatage""",
                 (type_regle, cle, libelle, op, auteur, _now()), lecture=False)


# ---------------------------------------------------------------- historique
def enregistrer_historique(navire, voyage, n_dossier, totaux: dict, nb_alertes: int, auteur: str) -> None:
    """Une ligne par navire + voyage : une nouvelle génération remplace la précédente."""
    _requete("""INSERT INTO manifestes_ops_historique
                    (navire, voyage, n_dossier, debarques, tonnes_debarques, gc_tonnes, charges, shifting,
                     alertes, totaux, auteur, horodatage)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (navire, voyage) DO UPDATE SET n_dossier = EXCLUDED.n_dossier,
                    debarques = EXCLUDED.debarques, tonnes_debarques = EXCLUDED.tonnes_debarques,
                    gc_tonnes = EXCLUDED.gc_tonnes, charges = EXCLUDED.charges, shifting = EXCLUDED.shifting,
                    alertes = EXCLUDED.alertes, totaux = EXCLUDED.totaux, auteur = EXCLUDED.auteur,
                    horodatage = EXCLUDED.horodatage""",
             (navire, voyage, n_dossier or "", totaux["debarques"], totaux["tonnes_debarques"],
              totaux["gc_tonnes"], totaux["charges"], totaux["shifting"], nb_alertes,
              json.dumps(totaux["cases"]), auteur, _now()), lecture=False)


def historique(limite: int = 500) -> list[dict]:
    try:
        return _requete("""SELECT horodatage, navire, voyage, n_dossier, debarques, tonnes_debarques,
                                  gc_tonnes, charges, shifting, alertes, auteur
                           FROM manifestes_ops_historique ORDER BY horodatage DESC LIMIT %s""", (limite,))
    except Exception:
        return []

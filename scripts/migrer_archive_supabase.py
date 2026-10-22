"""
Copie TOUT le bucket Supabase « manifestes-archive » vers un dossier local,
en gardant la même arborescence (sources/, exports/, stats/…) : les chemins
enregistrés en base restent donc valables avec ARCHIVE_DIR.

Usage (une seule fois, lors de la sortie de Supabase) :

    export SUPABASE_URL="https://xxxx.supabase.co"
    export SUPABASE_SERVICE_KEY="..."
    python scripts/migrer_archive_supabase.py /opt/manifestes/archive

Relançable sans risque : les fichiers déjà copiés (même taille) sont sautés.
Le script ne modifie ni ne supprime rien côté Supabase.
"""
import os
import pathlib
import sys

import requests

BUCKET = "manifestes-archive"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("Définir SUPABASE_URL et SUPABASE_SERVICE_KEY (variables d'environnement).")
        return 1
    dest_root = pathlib.Path(sys.argv[1]).expanduser().resolve()
    headers = {"Authorization": f"Bearer {key}", "apikey": key}

    def lister(prefix: str) -> list[dict]:
        items, offset = [], 0
        while True:
            r = requests.post(f"{base}/storage/v1/object/list/{BUCKET}", headers=headers, timeout=60,
                              json={"prefix": prefix, "limit": 1000, "offset": offset})
            r.raise_for_status()
            page = r.json()
            items += page
            if len(page) < 1000:
                return items
            offset += 1000

    copies = sautes = erreurs = 0
    a_visiter = [""]
    while a_visiter:
        prefix = a_visiter.pop()
        for it in lister(prefix):
            rel = f"{prefix}{it['name']}"
            if it.get("id") is None:                       # sous-dossier
                a_visiter.append(rel + "/")
                continue
            dest = (dest_root / rel).resolve()
            if dest_root not in dest.parents:
                print(f"  ignoré (chemin suspect) : {rel}")
                continue
            taille = (it.get("metadata") or {}).get("size")
            if dest.is_file() and taille is not None and dest.stat().st_size == taille:
                sautes += 1
                continue
            try:
                r = requests.get(f"{base}/storage/v1/object/{BUCKET}/{rel}", headers=headers, timeout=120)
                r.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                copies += 1
                if copies % 50 == 0:
                    print(f"  … {copies} fichiers copiés")
            except Exception as exc:
                erreurs += 1
                print(f"  ERREUR {rel} : {exc}")

    print(f"Terminé : {copies} copiés, {sautes} déjà présents, {erreurs} erreur(s) -> {dest_root}")
    return 0 if erreurs == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

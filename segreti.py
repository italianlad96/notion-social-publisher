#!/usr/bin/env python3
"""Copia le chiavi del file .env nei segreti del repository GitHub, da cui le legge il lavoro programmato.

Da rilanciare ogni volta che un token cambia (per esempio dopo linkedin_login.py).
Uso:
  python3 segreti.py --repo utente/nome-repo            # imposta i segreti
  python3 segreti.py --repo utente/nome-repo --elenco   # mostra solo i nomi, non cambia niente
I valori passano da standard input a `gh`, quindi non compaiono nei comandi né a video.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

CHIAVI = [
    "NOTION_TOKEN", "NOTION_DATA_SOURCE_ID",
    "META_APP_ID", "META_APP_SECRET", "META_PAGE_ID", "META_IG_USER_ID", "META_PAGE_TOKEN",
    "LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN", "LINKEDIN_TOKEN_SCADE",
    "GOOGLE_SA_KEY_B64", "NOTION_UTENTE_ID", "FUSO_ORARIO",
]


def leggi_env(percorso: Path) -> dict:
    valori = {}
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        if "=" in riga and not riga.strip().startswith("#"):
            k, _, v = riga.partition("=")
            valori[k.strip()] = v.strip().strip("\"'")
    return valori


def main(argv=None, esegui=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="utente/nome-repo")
    ap.add_argument("--elenco", action="store_true", help="mostra i nomi senza impostare niente")
    ap.add_argument("--env", default=str(Path(__file__).resolve().parent / ".env"))
    args = ap.parse_args(argv)
    valori = leggi_env(Path(args.env))
    mancanti = [k for k in CHIAVI if not valori.get(k)]
    for k in CHIAVI:
        if valori.get(k):
            print(f"  {k}" + ("" if args.elenco else " ..."), end="")
            if not args.elenco:
                r = esegui(["gh", "secret", "set", k, "--repo", args.repo], input=valori[k].encode(), capture_output=True)
                if r.returncode != 0:
                    print(f" ERRORE: {r.stderr.decode(errors='replace').strip()[:150]}")
                    return 1
                print(" ok", end="")
            print()
    if mancanti:
        print(f"Non presenti nel .env (saltati): {', '.join(mancanti)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

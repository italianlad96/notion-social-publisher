#!/usr/bin/env python3
"""Controllo del mattino: per ogni post affidato al sistema scrive nel campo «Controllo» se è tutto pronto o cosa manca,
guardando anche dentro la cartella Drive. Quando compare un problema nuovo lascia un commento sulla riga.

Esce con 1 se qualcosa va sistemato (nel lavoro su GitHub questo manda anche l'email di riserva).
Uso: python3 controlla.py            (scrive in Notion)
     python3 controlla.py --solo-elenco   (dice cosa scriverebbe, non tocca niente)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from publisher import config, drive, media, notion
from publisher.env import carica_env
from publisher.model import Riga
from publisher.plan import candidata, decidi
from pubblica import leggi_righe


def _quando(r: Riga) -> str:
    return r.data.astimezone(ZoneInfo(config.TZ)).strftime("il %d/%m alle %H:%M") if r.data else "senza data"


def problemi_cartella(r: Riga, tok_fn=drive.token) -> List[str]:
    """Cosa non va nella cartella Drive (vuoto = va bene). Non scarica niente, guarda solo i nomi."""
    if r.media or not r.cartella_drive:
        return []
    try:
        elenco = drive.elenca(tok_fn(), drive.id_cartella(r.cartella_drive))
    except drive.ErroreDrive as e:
        return [str(e)]
    _, guai = media.scegli(r.formato, elenco)
    return guai


def messaggio(r: Riga, ora: datetime, tok_fn=drive.token) -> Optional[str]:
    """Il testo del campo Controllo per una riga affidata al sistema (None = la riga non è affidata al sistema)."""
    if not candidata(r):
        return None
    d = decidi(r, ora)
    if d.azione == "scaduto":
        return f"Da sistemare: doveva uscire {_quando(r)} e sono passate più di 48 ore. Cambia la data o spunta «Pubblica subito»."
    if d.azione == "chiudere":
        return "Già uscito ovunque: il sistema chiude la riga al prossimo giro."
    guai = [m for lista in d.problemi.values() for m in lista]
    guai += problemi_cartella(r, tok_fn)
    if guai:
        return "Da sistemare: " + "; ".join(dict.fromkeys(guai)) + "."
    dove = ", ".join(config.NOMI.get(p, p) for p in d.piattaforme)
    if r.pubblica_subito:
        return f"Tutto pronto: esce al prossimo giro (entro 20 minuti) su {dove}."
    return f"Tutto pronto: esce {_quando(r)} su {dove}."


def main(argv=None, ora=None, tok_fn=drive.token) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo-elenco", action="store_true", help="dice cosa scriverebbe, senza toccare Notion")
    args = ap.parse_args(argv)
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        print("Manca NOTION_TOKEN.", file=sys.stderr)
        return 2
    adesso = ora or datetime.now(ZoneInfo(config.TZ))
    utente = os.environ.get("NOTION_UTENTE_ID", "")
    try:
        pagine = notion.pagine_attive(token)
        righe = leggi_righe(token, pagine, False)
    except RuntimeError as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 2
    da_sistemare = 0
    for r in righe:
        testo = messaggio(r, adesso, tok_fn)
        if testo is None:
            continue
        problema = testo.startswith("Da sistemare")
        da_sistemare += problema
        print(f"  {r.titolo[:44]:<44}  {testo}")
        if args.solo_elenco or testo == r.controllo:
            continue
        try:
            notion.aggiorna(token, r.id, {"Controllo": notion.p_testo(testo)})
            if problema:
                notion.commenta(token, r.id, f"controllo su «{r.titolo}»: {testo[len('Da sistemare: '):]}", utente)
        except RuntimeError as e:
            print(f"    (non scritto in Notion: {e})")
    return 1 if da_sistemare else 0


if __name__ == "__main__":
    carica_env()
    sys.exit(main())

#!/usr/bin/env python3
"""Pubblica i post programmati della tabella Contenuti. Senza --esegui è una simulazione: dice cosa farebbe.

Il sistema pubblica solo le righe con Stato «Programmato» alla loro data (senza ora: alle 9), oppure quelle con la
spunta «Pubblica subito» (Stato «Pronto» o «Programmato»). Il testo è nella pagina, sotto il titolo «Didascalia»;
i file nella cartella Drive indicata nella riga.

Uso:
  python3 pubblica.py                         # simulazione
  python3 pubblica.py --esegui                # pubblica davvero ciò che tocca
  python3 pubblica.py --esegui --prova        # chiama le piattaforme ma niente diventa pubblico e niente si scrive in Notion
  python3 pubblica.py --esegui --id <pagina>  # solo quella riga
  python3 pubblica.py --ora 2026-11-04T09:20:00+01:00   # finge un'altra ora
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from publisher import config, notion, run
from publisher.env import carica_env
from publisher.model import righe_da_pagine
from publisher.plan import Decisione, candidata, pianifica

ETICHETTE = {
    "pubblica": "ESCE ORA",
    "attesa": "PROGRAMMATO",
    "manuale": "A MANO",
    "scaduto": "SCADUTO",
    "chiudere": "DA CHIUDERE",
    "problema": "PROBLEMA",
    "ignora": "-",
}


def _dettaglio(d: Decisione) -> str:
    if d.azione == "manuale":
        return "«Pronto»: si pubblica a mano (o spunta «Pubblica subito»)"
    if d.azione == "scaduto":
        return "la data è passata da più di 48 ore: non esce"
    if d.azione == "chiudere":
        return "già uscito ovunque: la riga va chiusa"
    parti = []
    if d.piattaforme:
        parti.append(", ".join(config.NOMI.get(p, p) for p in d.piattaforme))
    for p, lista in d.problemi.items():
        nome = config.NOMI.get(p, p) if p != "tutte" else "tutte"
        parti.append(f"{nome}: {'; '.join(lista)}")
    if d.riga.pubblica_subito:
        parti.append("pubblica subito")
    return " | ".join(parti)


def riga_report(d: Decisione) -> str:
    r = d.riga
    quando = r.data.astimezone(ZoneInfo(config.TZ)).strftime("%d/%m %H:%M") if r.data else "senza data"
    return f"  {ETICHETTE[d.azione]:<11} {quando:<11}  {r.titolo[:42]:<42}  {_dettaglio(d)}"


def leggi_righe(token: str, pagine, da_fixture: bool):
    """Le righe, con i testi letti dalla pagina per quelle affidate al sistema."""
    righe = righe_da_pagine(pagine)
    out = []
    for pagina, r in zip(pagine, righe):
        if candidata(r):
            testi = pagina.get("_testi", {}) if da_fixture else notion.testi_pagina(token, r.id)
            r = replace(r, didascalia=testi.get("didascalia", ""), testo_linkedin=testi.get("testo linkedin", ""))
        out.append(r)
    return out


def main(argv=None, ora=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", help="file JSON con una risposta di Notion, al posto della rete")
    ap.add_argument("--ora", help="ora di riferimento ISO (default: adesso)")
    ap.add_argument("--rigorosa", action="store_true", help="esce con 1 se c'è almeno un problema")
    ap.add_argument("--esegui", action="store_true", help="pubblica davvero ciò che tocca (senza, solo simulazione)")
    ap.add_argument("--prova", action="store_true", help="con --esegui: niente diventa pubblico e niente si scrive in Notion")
    ap.add_argument("--id", help="con --esegui: solo questa pagina Notion")
    args = ap.parse_args(argv)
    if args.esegui and args.fixture:
        print("--esegui non si usa con --fixture.", file=sys.stderr)
        return 2

    adesso = datetime.fromisoformat(args.ora) if args.ora else (ora or datetime.now(ZoneInfo(config.TZ)))
    if adesso.tzinfo is None:
        adesso = adesso.replace(tzinfo=ZoneInfo(config.TZ))

    token = os.environ.get("NOTION_TOKEN", "")
    try:
        if args.fixture:
            with open(args.fixture, encoding="utf-8") as f:
                dati = json.load(f)
            pagine = dati["results"] if isinstance(dati, dict) else dati
        else:
            if not token:
                print("Manca NOTION_TOKEN (o usa --fixture).", file=sys.stderr)
                return 2
            pagine = notion.pagine_attive(token)
        righe = leggi_righe(token, pagine, bool(args.fixture))
    except RuntimeError as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 2

    decisioni = [d for d in pianifica(righe, adesso) if d.azione != "ignora"]
    modo = ("PROVA (niente di pubblico)" if args.prova else "PUBBLICO DAVVERO") if args.esegui else "SIMULAZIONE, non pubblica niente"
    print(f"{modo}. Ora di riferimento: {adesso:%d/%m/%Y %H:%M} ({config.TZ})")
    print(f"{len(decisioni)} righe «Pronto» o «Programmato»\n")
    for d in decisioni:
        print(riga_report(d))
    conteggio = {}
    for d in decisioni:
        conteggio[d.azione] = conteggio.get(d.azione, 0) + 1
    print("\nRiepilogo: " + ", ".join(f"{n} {ETICHETTE[a].lower()}" for a, n in sorted(conteggio.items())))
    con_problemi = [d for d in decisioni if d.problemi or d.azione in ("scaduto", "chiudere", "problema")]

    if args.esegui:
        servono = ["META_PAGE_TOKEN", "META_PAGE_ID", "META_IG_USER_ID", "GOOGLE_SA_KEY_B64"]
        if any("linkedin" in d.riga.piattaforme for d in decisioni if d.azione == "pubblica"):
            servono += ["LINKEDIN_ACCESS_TOKEN", "LINKEDIN_PERSON_URN"]
        mancano = [v for v in servono if not os.environ.get(v)]
        if mancano:
            print(f"Mancano nel .env: {', '.join(mancano)}", file=sys.stderr)
            return 2
        ctx = run.Contesto(
            notion_token=token, page_token=os.environ["META_PAGE_TOKEN"],
            page_id=os.environ["META_PAGE_ID"], ig_id=os.environ["META_IG_USER_ID"],
            prova=args.prova, solo_id=args.id,
            linkedin_token=os.environ.get("LINKEDIN_ACCESS_TOKEN", ""), persona_urn=os.environ.get("LINKEDIN_PERSON_URN", ""),
            linkedin_scade=os.environ.get("LINKEDIN_TOKEN_SCADE", ""), utente_id=os.environ.get("NOTION_UTENTE_ID", ""),
        )
        print()
        if run.esegui(decisioni, ctx):
            return 1
    return 1 if args.rigorosa and con_problemi else 0


if __name__ == "__main__":
    carica_env()
    sys.exit(main())

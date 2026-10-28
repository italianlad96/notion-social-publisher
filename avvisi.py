#!/usr/bin/env python3
"""Controllo giornaliero delle scadenze: dice se un token sta per scadere o non vale più.

Esce con 1 se c'è qualcosa da fare (nel lavoro programmato su GitHub questo manda l'email di errore).
Controlla il token LinkedIn (data in LINKEDIN_TOKEN_SCADE) e quello di Meta (scadenza e «accesso ai dati»,
letti da Meta stessa). Serve nel .env: META_APP_ID, META_APP_SECRET, META_PAGE_TOKEN e, se si pubblica su LinkedIn, LINKEDIN_TOKEN_SCADE.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from typing import List, Optional

from publisher import meta
from publisher.env import carica_env

SOGLIA_GIORNI = 14


def _scadenza(nome: str, data: date, oggi: date, rimedio: str) -> Optional[str]:
    giorni = (data - oggi).days
    if giorni < 0:
        return f"{nome} è scaduto il {data:%d/%m/%Y}. {rimedio}"
    if giorni <= SOGLIA_GIORNI:
        return f"{nome} scade fra {giorni} giorni ({data:%d/%m/%Y}). {rimedio}"
    return None


def valuta_scadenze(oggi: date, linkedin_scade: str = "", dati_meta: Optional[dict] = None) -> List[str]:
    """Le cose da fare. `dati_meta` è la risposta di debug_token (None = non controllato)."""
    da_fare: List[str] = []
    if linkedin_scade:
        try:
            d = date.fromisoformat(linkedin_scade)
        except ValueError:
            da_fare.append("LINKEDIN_TOKEN_SCADE non è una data nel formato AAAA-MM-GG.")
        else:
            m = _scadenza("Il token LinkedIn", d, oggi, "Rilancia linkedin_login.py e poi segreti.py.")
            if m:
                da_fare.append(m)
    if dati_meta is not None:
        if not dati_meta.get("is_valid"):
            da_fare.append("Il token di Meta non è più valido: rigenera il token della Pagina (Graph API Explorer) e rilancia segreti.py.")
        for chiave, nome in (("expires_at", "Il token di Meta"), ("data_access_expires_at", "L'accesso ai dati di Meta")):
            ts = dati_meta.get(chiave) or 0
            if ts:
                d = datetime.fromtimestamp(ts, timezone.utc).date()
                m = _scadenza(nome, d, oggi, "Rifai il login dell'app Meta (Graph API Explorer) e rilancia segreti.py.")
                if m:
                    da_fare.append(m)
    return da_fare


def dati_meta(app_id: str, segreto: str, token: str) -> dict:
    return meta.chiama("GET", "debug_token", f"{app_id}|{segreto}", {"input_token": token}).get("data", {})


def main(oggi: Optional[date] = None) -> int:
    oggi = oggi or datetime.now(timezone.utc).date()
    da_fare: List[str] = []
    meta_dati = None
    chiavi = [os.environ.get(v) for v in ("META_APP_ID", "META_APP_SECRET", "META_PAGE_TOKEN")]
    if all(chiavi):
        try:
            meta_dati = dati_meta(*chiavi)
        except meta.ErroreMeta as e:
            da_fare.append(f"Non riesco a controllare il token di Meta: {e}")
    else:
        da_fare.append("Mancano META_APP_ID, META_APP_SECRET o META_PAGE_TOKEN: il token di Meta non è controllabile.")
    da_fare += valuta_scadenze(oggi, os.environ.get("LINKEDIN_TOKEN_SCADE", ""), meta_dati)
    if da_fare:
        print("Da sistemare:")
        for riga in da_fare:
            print(f" - {riga}")
        return 1
    scade = os.environ.get("LINKEDIN_TOKEN_SCADE", "")
    print(f"Tutto in ordine. Token LinkedIn fino al {scade or 'non usato'}; Meta valido.")
    return 0


if __name__ == "__main__":
    carica_env()
    sys.exit(main())

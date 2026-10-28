"""Decide che cosa fare di ogni riga: pubblicare, aspettare, lasciare a mano, segnalare un problema.

Regola di fondo: il sistema tocca solo le righe con Stato «Programmato», oppure con la spunta «Pubblica subito»
e Stato «Pronto» o «Programmato». «Pronto» da solo vuol dire: approvato, si pubblica a mano.
Funzioni pure: non toccano la rete, quindi si provano con qualunque «ora» e qualunque riga."""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List
from urllib.parse import parse_qs, urlparse

from . import config
from .model import Riga, piattaforme_fatte

VIDEO = {".mp4", ".mov"}
JPEG = {".jpg", ".jpeg"}


@dataclass
class Decisione:
    riga: Riga
    # pubblica = tocca a lei adesso; attesa = data futura; manuale = «Pronto», si pubblica a mano;
    # scaduto = la data è passata da più di 48 ore; chiudere = tutto già pubblicato ma lo Stato non è «Pubblicato»;
    # problema = niente può uscire; ignora = né programmata né pronta.
    azione: str
    piattaforme: List[str] = field(default_factory=list)  # quelle che possono uscire
    problemi: Dict[str, List[str]] = field(default_factory=dict)  # per piattaforma, o "tutte"


def candidata(r: Riga) -> bool:
    """La riga è affidata al sistema?"""
    return r.stato == config.PROGRAMMATO or (r.pubblica_subito and r.stato in (config.PRONTO, config.PROGRAMMATO))


def _estensione(url: str) -> str:
    """L'estensione dal percorso dell'indirizzo; per gli indirizzi di Drive, che non ce l'hanno, dal parametro «nome»."""
    u = urlparse(url)
    est = posixpath.splitext(u.path.lower())[1]
    if not est:
        est = posixpath.splitext(parse_qs(u.query).get("nome", [""])[0].lower())[1]
    return est


def _problemi_media(riga: Riga, p: str) -> List[str]:
    media = riga.media
    est = [_estensione(u) for u in media]
    video = [e in VIDEO for e in est]
    jpeg = [e in JPEG for e in est]
    f = riga.formato
    if f == "Reel":
        if len(media) > 2 or not video[0] or (len(media) == 2 and not jpeg[1]):
            return ["Reel: servono il video e, se c'è, la copertina, in quest'ordine"]
        return []
    if f == "Post":
        if len(media) != 1 or not jpeg[0]:
            return ["Post: serve una sola immagine"]
        return []
    if f == "Carosello":
        if p == "linkedin":
            return ["i caroselli su LinkedIn non sono ancora supportati"]
        if not config.CAROSELLO_MIN <= len(media) <= config.CAROSELLO_MAX:
            return [f"carosello: da {config.CAROSELLO_MIN} a {config.CAROSELLO_MAX} file, ce ne sono {len(media)}"]
        if p == "facebook" and any(video):
            return ["Facebook: il carosello con video non è supportato"]
        if not all(j or v for j, v in zip(jpeg, video)):
            return ["le slide devono essere immagini o video"]
        return []
    return [f"formato «{f or 'vuoto'}» non riconosciuto"]


def problemi(riga: Riga, p: str) -> List[str]:
    """Cosa impedisce di pubblicare questa riga su questa piattaforma (lista vuota = si può).

    I file si controllano qui solo se sono già resi pubblici su Drive (campo Media); quelli ancora nella cartella
    li controlla il giro del mattino e, di nuovo, la pubblicazione."""
    if p == "linkedin_pagina":
        return ["la pagina aziendale LinkedIn non è supportata"]
    if p not in config.SUPPORTATE:
        return [f"piattaforma «{p}» non supportata"]
    if riga.formato == "Storia":
        return ["le Storie non sono automatiche"]
    out: List[str] = []
    testo = (riga.testo_linkedin or riga.didascalia) if p == "linkedin" else riga.didascalia
    if not testo.strip():
        out.append("manca il testo: scrivilo nella pagina sotto il titolo «Didascalia»")
    limite = config.LIMITE_TESTO.get(p)
    if limite and len(testo) > limite:
        out.append(f"testo di {len(testo)} caratteri, il massimo è {limite}")
    if riga.media:
        out += _problemi_media(riga, p)
    elif not riga.cartella_drive:
        out.append("manca il link alla cartella Drive con i file")
    elif riga.formato == "Carosello" and p == "linkedin":
        out.append("i caroselli su LinkedIn non sono ancora supportati")
    return out


def decidi(r: Riga, ora: datetime) -> Decisione:
    if not candidata(r):
        return Decisione(r, "manuale" if r.stato == config.PRONTO else "ignora")
    if not r.piattaforme:
        return Decisione(r, "problema", [], {"tutte": ["scegli almeno una piattaforma"]})
    fatte = piattaforme_fatte(r.esito)
    da_fare = [p for p in r.piattaforme if p not in fatte]
    if not da_fare:
        return Decisione(r, "chiudere")
    if not r.pubblica_subito:
        if r.data is None:
            return Decisione(r, "problema", [], {"tutte": ["manca la data di pubblicazione"]})
        if ora - r.data > config.FINESTRA:
            return Decisione(r, "scaduto", [], {})
    ok: List[str] = []
    guai: Dict[str, List[str]] = {}
    for p in da_fare:
        pr = problemi(r, p)
        if pr:
            guai[p] = pr
        else:
            ok.append(p)
    if not r.pubblica_subito and ora < r.data:
        return Decisione(r, "attesa", ok, guai)
    return Decisione(r, "pubblica" if ok else "problema", ok, guai)


def pianifica(righe: List[Riga], ora: datetime) -> List[Decisione]:
    decisioni = [decidi(r, ora) for r in righe]
    decisioni.sort(key=lambda d: (d.riga.data is None, d.riga.data or ora))
    return decisioni

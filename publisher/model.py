"""Una riga della tabella Contenuti, letta dalla risposta dell'API di Notion."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from . import config


@dataclass
class Riga:
    id: str
    url: str
    titolo: str
    formato: str
    stato: str
    piattaforme: List[str]
    data: Optional[datetime]  # ora di uscita già risolta e con fuso; None se manca
    solo_giorno: bool
    didascalia: str  # dalla sezione «Didascalia» del corpo della pagina (si legge a parte)
    testo_linkedin: str  # dalla sezione «Testo LinkedIn», facoltativa
    media: List[str] = field(default_factory=list)  # indirizzi pubblici dei file su Drive mentre si pubblica (campo tecnico «Media»)
    esito: str = ""  # campo «Dati tecnici»: una riga per piattaforma, letta dal sistema
    sorgenti: str = ""
    pubblica_subito: bool = False
    cartella_drive: str = ""
    controllo: str = ""


def _testo(prop) -> str:
    if not prop:
        return ""
    for chiave in ("rich_text", "title"):
        if prop.get(chiave):
            return "".join(t.get("plain_text", "") for t in prop[chiave])
    return ""


def _nome(prop, chiave: str) -> str:
    valore = (prop or {}).get(chiave)
    return valore.get("name", "") if valore else ""


def _multi(prop) -> List[str]:
    return [o["name"] for o in ((prop or {}).get("multi_select") or [])]


def _data(prop) -> Tuple[Optional[datetime], bool]:
    d = (prop or {}).get("date")
    if not d or not d.get("start"):
        return None, False
    inizio = d["start"].replace("Z", "+00:00")
    if len(inizio) == 10:  # solo il giorno: esce all'ora predefinita
        giorno = date.fromisoformat(inizio)
        quando = datetime.combine(giorno, time(config.ORA_PREDEFINITA), tzinfo=ZoneInfo(config.TZ))
        return quando, True
    quando = datetime.fromisoformat(inizio)
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=ZoneInfo(d.get("time_zone") or config.TZ))
    return quando, False


def righe_da_pagine(pagine) -> List[Riga]:
    return [riga_da_pagina(p) for p in pagine]


def riga_da_pagina(pagina) -> Riga:
    p = pagina.get("properties", {})
    quando, solo_giorno = _data(p.get("Data di pubblicazione"))
    media = [r.strip() for r in _testo(p.get("Media")).splitlines() if r.strip()]
    return Riga(
        id=pagina.get("id", ""),
        url=pagina.get("url", ""),
        titolo=_testo(p.get("Contenuto")),
        formato=_nome(p.get("Formato"), "select"),
        stato=_nome(p.get("Stato"), "status"),
        piattaforme=[config.PIATTAFORME.get(n, n) for n in _multi(p.get("Piattaforme"))],
        data=quando,
        solo_giorno=solo_giorno,
        didascalia="",
        testo_linkedin="",
        media=media,
        esito=_testo(p.get("Dati tecnici")),
        sorgenti=_testo(p.get("Sorgenti")),
        pubblica_subito=bool((p.get("Pubblica subito") or {}).get("checkbox")),
        cartella_drive=((p.get("Cartella Drive") or {}).get("url") or "").strip(),
        controllo=_testo(p.get("Controllo")),
    )


def _righe_esito(esito: str):
    for riga in esito.splitlines():
        chiave, _, resto = riga.partition(":")
        if chiave.strip():
            yield chiave.strip().lower(), resto.strip()


def esito_di(esito: str, piattaforma: str) -> str:
    """Il testo dopo «piattaforma:» nei Dati tecnici, vuoto se non c'è."""
    for chiave, resto in _righe_esito(esito):
        if chiave == piattaforma:
            return resto
    return ""


def imposta_esito(esito: str, piattaforma: str, testo: str) -> str:
    """Sostituisce (o aggiunge) la riga di una piattaforma nei Dati tecnici, lasciando le altre."""
    nuova = f"{piattaforma}: {testo}"
    righe, messa = [], False
    for riga in esito.splitlines():
        if riga.partition(":")[0].strip().lower() == piattaforma:
            if not messa:
                righe.append(nuova)
                messa = True
        elif riga.strip():
            righe.append(riga)
    if not messa:
        righe.append(nuova)
    return "\n".join(righe)


def contenitore_di(esito: str, piattaforma: str) -> str:
    """L'id del contenitore Instagram in corso, scritto come «instagram: contenitore <id>»."""
    resto = esito_di(esito, piattaforma)
    return resto.split()[1] if resto.lower().startswith("contenitore ") and len(resto.split()) > 1 else ""


def link_pubblicati(esito: str) -> list:
    """I link dei post già pubblicati, nell'ordine in cui compaiono."""
    out = []
    for _, resto in _righe_esito(esito):
        if resto.lower().startswith("pubblicato"):
            parti = resto.split()
            if len(parti) > 1:
                out.append(parti[1])
    return out


def piattaforme_fatte(esito: str) -> set:
    """Piattaforme già pubblicate secondo i Dati tecnici (una riga ciascuna: «instagram: pubblicato <link> <ora>»).

    Gli errori e i contenitori in corso non contano come fatti: servono a ritentare senza duplicare."""
    fatte = set()
    for riga in esito.splitlines():
        chiave, _, resto = riga.partition(":")
        if chiave.strip() and resto.strip().lower().startswith("pubblicato"):
            fatte.add(chiave.strip().lower())
    return fatte


def esito_leggibile(esito: str) -> str:
    """Il campo «Esito» per le persone, ricavato dai Dati tecnici."""
    righe = []
    for chiave, resto in _righe_esito(esito):
        nome = config.NOMI.get(chiave, chiave.capitalize())
        parti = resto.split()
        if resto.lower().startswith("pubblicato"):
            quando = ""
            if len(parti) > 2:
                try:
                    t = datetime.fromisoformat(parti[2]).astimezone(ZoneInfo(config.TZ))
                    quando = f" il {t:%d/%m} alle {t:%H:%M}"
                except ValueError:
                    pass
            righe.append(f"{nome}: pubblicato{quando}" + (f" · {parti[1]}" if len(parti) > 1 else ""))
        elif resto.lower().startswith("contenitore"):
            righe.append(f"{nome}: in elaborazione, riprova da solo al giro successivo")
        elif resto.lower().startswith("errore"):
            righe.append(f"{nome}: non uscito, {resto[len('errore'):].strip()}")
    return "\n".join(righe)

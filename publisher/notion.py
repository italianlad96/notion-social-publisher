"""Lettura e scrittura della tabella Contenuti con l'API di Notion (solo libreria standard)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from . import config
from .media import spezza_testo

PAGINE = "https://api.notion.com/v1/pages"


def _chiama(url: str, token: str, corpo: Optional[dict], tentativi: int = 4, metodo: str = "POST") -> dict:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    intestazioni = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": config.NOTION_VERSION,
        "Content-Type": "application/json",
    }
    for n in range(tentativi):
        richiesta = urllib.request.Request(url, data=dati, headers=intestazioni, method=metodo)
        try:
            with urllib.request.urlopen(richiesta, timeout=30) as risposta:
                return json.load(risposta)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and n < tentativi - 1:
                time.sleep(float(e.headers.get("Retry-After") or 2 ** n))
                continue
            raise RuntimeError(f"Notion ha risposto {e.code}: {e.read().decode(errors='replace')[:500]}") from None
        except urllib.error.URLError as e:
            if n < tentativi - 1:
                time.sleep(2 ** n)
                continue
            raise RuntimeError(f"Notion non raggiungibile: {e.reason}") from None
    raise RuntimeError("Notion: tentativi esauriti")


# ------------------------------------------------------------------ proprietà

def p_testo(testo: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": p}} for p in spezza_testo(testo)]}


def p_stato(nome: str) -> dict:
    return {"status": {"name": nome}}


def aggiorna(token: str, pagina_id: str, proprieta: Dict[str, dict]) -> None:
    _chiama(f"{PAGINE}/{pagina_id}", token, {"properties": proprieta}, metodo="PATCH")


def scrivi_media(token: str, pagina_id: str, indirizzi: List[str]) -> None:
    aggiorna(token, pagina_id, {"Media": p_testo("\n".join(indirizzi))})


def scrivi_esito(token: str, pagina_id: str, tecnici: str) -> None:
    """Scrive i Dati tecnici (una riga per piattaforma) e l'Esito leggibile che ne deriva."""
    from .model import esito_leggibile
    aggiorna(token, pagina_id, {"Dati tecnici": p_testo(tecnici), "Esito": p_testo(esito_leggibile(tecnici))})


def commenta(token: str, pagina_id: str, testo: str, utente_id: str = "") -> None:
    """Lascia un commento sulla riga; con `utente_id` la persona viene menzionata e riceve la notifica."""
    testo_rt = [{"type": "text", "text": {"content": p}} for p in spezza_testo(testo)]
    corpo = {"parent": {"page_id": pagina_id}, "rich_text": testo_rt}
    if utente_id:
        menzione = [{"type": "mention", "mention": {"type": "user", "user": {"id": utente_id}}},
                    {"type": "text", "text": {"content": " "}}]
        try:
            _chiama("https://api.notion.com/v1/comments", token, {**corpo, "rich_text": menzione + testo_rt})
            return
        except RuntimeError as e:
            # senza il permesso di leggere gli utenti Notion rifiuta la menzione: il commento parte lo stesso, senza
            if "Could not find user" not in str(e):
                raise
    _chiama("https://api.notion.com/v1/comments", token, corpo)


# ------------------------------------------------------------------ lettura

def pagine_attive(token: str) -> List[dict]:
    """Le pagine che il sistema guarda: Stato «Pronto», «Programmato» o «Da sistemare»."""
    url = f"https://api.notion.com/v1/data_sources/{config.data_source_id()}/query"
    filtro = {"or": [{"property": "Stato", "status": {"equals": s}}
                     for s in (config.PRONTO, config.PROGRAMMATO, config.DA_SISTEMARE)]}
    corpo = {"filter": filtro, "page_size": 100}
    pagine: List[dict] = []
    while True:
        risposta = _chiama(url, token, corpo)
        pagine += risposta["results"]
        if not risposta.get("has_more"):
            return pagine
        corpo["start_cursor"] = risposta["next_cursor"]


def blocchi(token: str, pagina_id: str) -> List[dict]:
    out: List[dict] = []
    cursore = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{pagina_id}/children?page_size=100" + (f"&start_cursor={cursore}" if cursore else "")
        risposta = _chiama(url, token, None, metodo="GET")
        out += risposta.get("results", [])
        if not risposta.get("has_more"):
            return out
        cursore = risposta.get("next_cursor")


TITOLI = ("heading_1", "heading_2", "heading_3")
TESTI = ("paragraph", "bulleted_list_item", "numbered_list_item", "quote")


def _plain(rich) -> str:
    return "".join(t.get("plain_text", "") for t in rich or [])


def sezioni(lista: List[dict]) -> Dict[str, str]:
    """Il testo sotto ogni titolo del corpo della pagina, con i titoli in minuscolo come chiave.

    I paragrafi si separano con una riga vuota; le voci di elenco consecutive vanno a capo semplice."""
    out: Dict[str, str] = {}
    corrente: Optional[str] = None
    pezzi: List[tuple] = []

    def chiudi():
        if corrente is None:
            return
        testo = ""
        for i, (tipo, t) in enumerate(pezzi):
            if i:
                testo += "\n" if tipo.endswith("list_item") and pezzi[i - 1][0] == tipo else "\n\n"
            testo += t
        out[corrente] = testo.strip()

    for b in lista:
        tipo = b.get("type", "")
        if tipo in TITOLI:
            chiudi()
            corrente, pezzi = _plain(b[tipo].get("rich_text")).strip().lower(), []
        elif corrente is not None and tipo in TESTI:
            t = _plain(b[tipo].get("rich_text"))
            if not t.strip():
                continue
            if tipo == "bulleted_list_item":
                t = f"• {t}"
            pezzi.append((tipo, t))
    chiudi()
    return out


def testi_pagina(token: str, pagina_id: str) -> Dict[str, str]:
    """Didascalia e testo LinkedIn dalle sezioni della pagina."""
    s = sezioni(blocchi(token, pagina_id))
    return {"didascalia": s.get("didascalia", ""), "testo linkedin": s.get("testo linkedin", "")}

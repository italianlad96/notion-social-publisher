"""Pubblicazione su Instagram e Facebook (Pagina) con la Graph API di Meta, solo libreria standard.

Instagram: si crea un «contenitore» (Reel, immagine o carosello), si aspetta che Meta lo elabori, poi lo si pubblica.
Il contenitore si segnala subito (callback `salva`), così un riavvio riprende lo stesso e non pubblica due volte.
Facebook: foto, video o più foto in un solo post. In modalità `prova` niente diventa pubblico: Instagram si ferma al contenitore
pronto, Facebook crea l'oggetto non pubblicato e lo cancella."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, List, Optional

from .plan import VIDEO, _estensione

GRAPH = "https://graph.facebook.com/v26.0"
dormi = time.sleep  # sostituibile nelle prove
TRANSITORI = {1, 2, 4, 17, 32, 613}  # errori che di solito passano da soli (rate limit, errore generico)


class ErroreMeta(RuntimeError):
    def __init__(self, messaggio: str, codice: Optional[int] = None, http: Optional[int] = None):
        super().__init__(messaggio)
        self.codice, self.http = codice, http

    @property
    def token_non_valido(self) -> bool:
        return self.codice == 190


@dataclass
class Risultato:
    stato: str  # pubblicato | in_corso | prova_ok
    dettaglio: str = ""  # link del post, o id del contenitore se in corso


def chiama(metodo: str, percorso: str, token: str, params: Optional[dict] = None, ritenta: bool = True) -> dict:
    """Una chiamata alla Graph API. Le scritture che pubblicano si fanno con ritenta=False: un doppione è peggio di un errore."""
    p = dict(params or {})
    p["access_token"] = token
    corpo = urllib.parse.urlencode(p).encode() if metodo == "POST" else None
    url = f"{GRAPH}/{percorso}"
    if corpo is None:
        url += "?" + urllib.parse.urlencode(p)
    tentativi = 3 if ritenta else 1
    for n in range(tentativi):
        richiesta = urllib.request.Request(url, data=corpo, method=metodo)
        try:
            with urllib.request.urlopen(richiesta, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode() or "{}").get("error", {})
            except ValueError:
                err = {}
            codice = err.get("code")
            if n < tentativi - 1 and (e.code >= 500 or codice in TRANSITORI):
                dormi(2 ** (n + 1))
                continue
            testo = err.get("error_user_msg") or err.get("message") or f"HTTP {e.code}"
            raise ErroreMeta(f"Meta {e.code}/{codice}: {testo}", codice, e.code) from None
        except urllib.error.URLError as e:
            if n < tentativi - 1:
                dormi(2 ** (n + 1))
                continue
            raise ErroreMeta(f"Meta non raggiungibile: {e.reason}") from None
    raise ErroreMeta("Meta: tentativi esauriti")


def _stato(contenitore: str, token: str) -> str:
    return chiama("GET", contenitore, token, {"fields": "status_code"}).get("status_code", "")


def attendi(contenitore: str, token: str, max_secondi: float) -> str:
    """Aspetta che Meta finisca di elaborare. Restituisce FINISHED, IN_PROGRESS (tempo scaduto), ERROR o EXPIRED."""
    passato, stato = 0.0, ""
    while True:
        stato = _stato(contenitore, token)
        if stato in ("FINISHED", "ERROR", "EXPIRED") or passato >= max_secondi:
            return stato
        dormi(8)
        passato += 8


# ---------------------------------------------------------------- Instagram

def _crea_contenitore(ig_id: str, token: str, riga, max_attesa: float) -> str:
    testo, media = riga.didascalia, riga.media
    if riga.formato == "Reel":
        p = {"media_type": "REELS", "video_url": media[0], "caption": testo}
        if len(media) > 1:
            p["cover_url"] = media[1]
        return chiama("POST", f"{ig_id}/media", token, p)["id"]
    if riga.formato == "Post":
        return chiama("POST", f"{ig_id}/media", token, {"image_url": media[0], "caption": testo})["id"]
    figli = []
    for u in media:
        if _estensione(u) in VIDEO:
            p = {"media_type": "VIDEO", "video_url": u, "is_carousel_item": "true"}
        else:
            p = {"image_url": u, "is_carousel_item": "true"}
        figli.append(chiama("POST", f"{ig_id}/media", token, p)["id"])
    for f in figli:
        stato = attendi(f, token, max_attesa)
        if stato != "FINISHED":
            raise ErroreMeta(f"elemento del carosello non pronto ({stato or 'sconosciuto'})")
    return chiama("POST", f"{ig_id}/media", token, {"media_type": "CAROUSEL", "children": ",".join(figli), "caption": testo})["id"]


def instagram(ig_id: str, token: str, riga, salva: Callable[[str], None], contenitore_noto: Optional[str] = None,
              prova: bool = False, max_attesa: float = 540) -> Risultato:
    contenitore = None
    if contenitore_noto:
        try:
            if _stato(contenitore_noto, token) in ("FINISHED", "IN_PROGRESS"):
                contenitore = contenitore_noto  # riprende quello di prima: niente doppioni
        except ErroreMeta:
            contenitore = None
    if contenitore is None:
        contenitore = _crea_contenitore(ig_id, token, riga, max_attesa)
        salva(f"contenitore {contenitore}")
    stato = attendi(contenitore, token, max_attesa)
    if stato == "IN_PROGRESS":
        return Risultato("in_corso", contenitore)
    if stato != "FINISHED":
        raise ErroreMeta(f"Instagram non ha elaborato i file ({stato or 'stato sconosciuto'})")
    if prova:
        return Risultato("prova_ok", contenitore)
    limite = chiama("GET", f"{ig_id}/content_publishing_limit", token, {"fields": "quota_usage,config"}).get("data", [{}])[0]
    if limite and limite.get("quota_usage", 0) >= limite.get("config", {}).get("quota_total", 100):
        raise ErroreMeta("limite giornaliero di pubblicazione su Instagram raggiunto")
    media_id = chiama("POST", f"{ig_id}/media_publish", token, {"creation_id": contenitore}, ritenta=False)["id"]
    try:
        link = chiama("GET", media_id, token, {"fields": "permalink"}).get("permalink", "")
    except ErroreMeta:
        link = ""
    return Risultato("pubblicato", link or media_id)


# ----------------------------------------------------------------- Facebook

def _cancella(oggetto: str, token: str) -> None:
    chiama("DELETE", oggetto, token)


def _permalink(oggetto: str, token: str) -> str:
    try:
        return chiama("GET", oggetto, token, {"fields": "permalink_url"}).get("permalink_url", "") or ""
    except ErroreMeta:
        return ""


def facebook(page_id: str, token: str, riga, prova: bool = False) -> Risultato:
    testo, media = riga.didascalia, riga.media
    pubblicato = "false" if prova else "true"
    creati: List[str] = []
    try:
        if riga.formato == "Reel":
            oggetto = chiama("POST", f"{page_id}/videos", token,
                             {"file_url": media[0], "description": testo, "published": pubblicato}, ritenta=False)["id"]
            creati.append(oggetto)
        elif riga.formato == "Post":
            r = chiama("POST", f"{page_id}/photos", token, {"url": media[0], "caption": testo, "published": pubblicato}, ritenta=False)
            oggetto = r.get("post_id") or r["id"]
            creati.append(r["id"])
        else:  # carosello di sole immagini: più foto non pubblicate allegate a un solo post
            foto = []
            for u in media:
                f = chiama("POST", f"{page_id}/photos", token, {"url": u, "published": "false"})["id"]
                foto.append(f)
                creati.append(f)
            oggetto = chiama("POST", f"{page_id}/feed", token, {
                "message": testo,
                "attached_media": json.dumps([{"media_fbid": f} for f in foto]),
                "published": pubblicato,
            }, ritenta=False)["id"]
            creati.append(oggetto)
        if prova:
            return Risultato("prova_ok", oggetto)
        return Risultato("pubblicato", _permalink(oggetto, token) or oggetto)
    finally:
        if prova:
            for o in reversed(creati):
                try:
                    _cancella(o, token)
                except ErroreMeta:
                    pass

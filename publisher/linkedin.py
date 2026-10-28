"""Pubblicazione sul profilo personale LinkedIn con l'API gratuita «Share on LinkedIn» (ugcPosts), solo libreria standard.

Testo, un'immagine o un video. Per immagine e video si registra il file, lo si carica, poi si crea il post.
LinkedIn non ha un modo di creare un post senza pubblicarlo e non accetta una chiave anti-doppione:
la creazione del post non si ritenta mai da sola. In modalità `prova` ci si ferma dopo il caricamento del file,
senza creare il post."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Tuple

from .meta import Risultato
from .plan import _estensione, VIDEO

API = "https://api.linkedin.com"
dormi = time.sleep
MIN_ASSET_ATTESA = 180  # secondi massimi di attesa dell'elaborazione del video


class ErroreLinkedIn(RuntimeError):
    def __init__(self, messaggio: str, http: Optional[int] = None):
        super().__init__(messaggio)
        self.http = http

    @property
    def token_non_valido(self) -> bool:
        return self.http == 401


def _intest(token: str, extra: Optional[dict] = None) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Restli-Protocol-Version": "2.0.0", **(extra or {})}


def chiama(metodo: str, percorso: str, token: str, corpo: Optional[dict] = None, ritenta: bool = True) -> Tuple[dict, dict]:
    """Una chiamata JSON all'API. Restituisce (corpo della risposta, intestazioni)."""
    dati = json.dumps(corpo).encode() if corpo is not None else None
    extra = {"Content-Type": "application/json"} if corpo is not None else {}
    tentativi = 3 if ritenta else 1
    for n in range(tentativi):
        richiesta = urllib.request.Request(f"{API}{percorso}", data=dati, headers=_intest(token, extra), method=metodo)
        try:
            with urllib.request.urlopen(richiesta, timeout=60) as r:
                testo = r.read().decode()
                return (json.loads(testo) if testo.strip() else {}), dict(r.headers)
        except urllib.error.HTTPError as e:
            if n < tentativi - 1 and e.code in (429, 500, 502, 503, 504):
                dormi(2 ** (n + 1))
                continue
            dettaglio = e.read().decode(errors="replace")[:300]
            if e.code == 401:
                raise ErroreLinkedIn("token LinkedIn scaduto o non valido: rilancia linkedin_login.py", 401) from None
            raise ErroreLinkedIn(f"LinkedIn {e.code}: {dettaglio}", e.code) from None
        except urllib.error.URLError as e:
            if n < tentativi - 1:
                dormi(2 ** (n + 1))
                continue
            raise ErroreLinkedIn(f"LinkedIn non raggiungibile: {e.reason}") from None
    raise ErroreLinkedIn("LinkedIn: tentativi esauriti")


def scarica(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        raise ErroreLinkedIn(f"non riesco a scaricare il file da caricare: {e}") from None


def carica_binario(url_caricamento: str, token: str, dati: bytes) -> None:
    richiesta = urllib.request.Request(url_caricamento, data=dati, method="PUT",
                                       headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"})
    for n in range(3):
        try:
            with urllib.request.urlopen(richiesta, timeout=300):
                return
        except urllib.error.HTTPError as e:
            if n < 2 and e.code in (429, 500, 502, 503, 504):
                dormi(2 ** (n + 1))
                continue
            raise ErroreLinkedIn(f"caricamento del file su LinkedIn: {e.code} {e.read().decode(errors='replace')[:200]}", e.code) from None
        except urllib.error.URLError as e:
            if n < 2:
                dormi(2 ** (n + 1))
                continue
            raise ErroreLinkedIn(f"caricamento del file su LinkedIn: {e.reason}") from None


def registra_file(persona_urn: str, token: str, ricetta: str) -> Tuple[str, str]:
    """(indirizzo di caricamento, urn del file) per una ricetta feedshare-image o feedshare-video."""
    corpo = {"registerUploadRequest": {
        "recipes": [f"urn:li:digitalmediaRecipe:{ricetta}"],
        "owner": persona_urn,
        "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}],
    }}
    dati, _ = chiama("POST", "/v2/assets?action=registerUpload", token, corpo)
    try:
        valore = dati["value"]
        url = valore["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        return url, valore["asset"]
    except KeyError:
        raise ErroreLinkedIn("risposta inattesa alla registrazione del file") from None


def attendi_file(asset_urn: str, token: str, max_secondi: float = MIN_ASSET_ATTESA) -> None:
    """Aspetta che LinkedIn finisca di elaborare il video, se lo dice; se non lo dice si procede."""
    identificativo = asset_urn.rsplit(":", 1)[-1]
    passato = 0.0
    while True:
        try:
            dati, _ = chiama("GET", f"/v2/assets/{identificativo}", token)
        except ErroreLinkedIn:
            return  # non si può leggere lo stato: si prova comunque a creare il post
        stati = [r.get("status") for r in dati.get("recipes", [])]
        if not stati or all(s == "AVAILABLE" for s in stati):
            return
        if any(s in ("CLIENT_ERROR", "SERVER_ERROR", "FAILED") for s in stati):
            raise ErroreLinkedIn(f"LinkedIn non ha elaborato il file ({', '.join(map(str, stati))})")
        if passato >= max_secondi:
            raise ErroreLinkedIn("LinkedIn sta ancora elaborando il video: riprovo al prossimo giro")
        dormi(5)
        passato += 5


def link_del_post(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


def cancella(token: str, urn: str) -> None:
    chiama("DELETE", f"/v2/ugcPosts/{urllib.parse.quote(urn, safe='')}", token)


def pubblica(persona_urn: str, token: str, riga, prova: bool = False, visibilita: str = "PUBLIC") -> Risultato:
    testo = riga.testo_linkedin or riga.didascalia
    media = riga.media
    contenuto = {"shareCommentary": {"text": testo}, "shareMediaCategory": "NONE"}
    if riga.formato == "Carosello":
        raise ErroreLinkedIn("i caroselli su LinkedIn non sono supportati")
    if media:
        e_video = _estensione(media[0]) in VIDEO
        url_carico, asset = registra_file(persona_urn, token, "feedshare-video" if e_video else "feedshare-image")
        carica_binario(url_carico, token, scarica(media[0]))
        if e_video:
            attendi_file(asset, token)
        contenuto["shareMediaCategory"] = "VIDEO" if e_video else "IMAGE"
        contenuto["media"] = [{"status": "READY", "media": asset}]
    if prova:
        return Risultato("prova_ok", "file caricato, post non creato")
    corpo = {
        "author": persona_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": contenuto},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibilita},
    }
    dati, intestazioni = chiama("POST", "/v2/ugcPosts", token, corpo, ritenta=False)
    urn = {k.lower(): v for k, v in intestazioni.items()}.get("x-restli-id") or dati.get("id")
    if not urn:
        raise ErroreLinkedIn("LinkedIn non ha restituito l'identificativo del post")
    return Risultato("pubblicato", link_del_post(urn))

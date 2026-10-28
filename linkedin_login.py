#!/usr/bin/env python3
"""Login con LinkedIn per pubblicare sul profilo personale: apre la pagina di consenso, riceve il codice sul computer,
lo scambia con un token e lo salva nel file .env insieme all'identificativo della persona.

Il token dura circa 60 giorni e con il prodotto gratuito non si rinnova da solo: questo script si rilancia alla scadenza.
Serve nel .env: LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET. L'indirizzo http://localhost:8765/callback va aggiunto
fra gli «Authorized redirect URLs» dell'app, nella scheda Auth.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from publisher.env import carica_env

PORTA = 8765
REDIRECT = f"http://localhost:{PORTA}/callback"
SCOPE = "openid profile w_member_social"
ENV = Path(__file__).resolve().parent / ".env"


def url_autorizzazione(client_id: str, stato: str) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": stato, "scope": SCOPE}
    return "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(q)


def estrai_codice(query: str, stato_atteso: str) -> str:
    """Il codice dalla richiesta di ritorno; errore se c'è un rifiuto o se lo stato non corrisponde."""
    q = urllib.parse.parse_qs(query)
    if "error" in q:
        raise RuntimeError(f"LinkedIn ha risposto: {q['error'][0]} {q.get('error_description', [''])[0]}")
    if q.get("state", [""])[0] != stato_atteso:
        raise RuntimeError("lo stato non corrisponde: la richiesta non è partita da questo script")
    if not q.get("code"):
        raise RuntimeError("LinkedIn non ha mandato il codice")
    return q["code"][0]


def salva_env(percorso: Path, valori: dict) -> None:
    """Aggiorna o aggiunge chiavi nel file .env lasciando le altre righe com'erano."""
    righe = percorso.read_text(encoding="utf-8").splitlines() if percorso.exists() else []
    righe = [r for r in righe if r.partition("=")[0] not in valori]
    righe += [f"{k}={v}" for k, v in valori.items()]
    percorso.write_text("\n".join(righe) + "\n", encoding="utf-8")
    percorso.chmod(0o600)


def _json(richiesta: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(richiesta, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LinkedIn {e.code}: {e.read().decode(errors='replace')[:300]}") from None


def scambia_codice(codice: str, client_id: str, client_secret: str) -> dict:
    corpo = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": codice, "client_id": client_id,
        "client_secret": client_secret, "redirect_uri": REDIRECT,
    }).encode()
    return _json(urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=corpo, method="POST",
                                        headers={"Content-Type": "application/x-www-form-urlencoded"}))


def chi_sono(token: str) -> dict:
    return _json(urllib.request.Request("https://api.linkedin.com/v2/userinfo", headers={"Authorization": f"Bearer {token}"}))


def aspetta_codice(stato: str, timeout: int = 300) -> str:
    risultato = {}

    class Gestore(BaseHTTPRequestHandler):
        def do_GET(self):
            parti = urllib.parse.urlparse(self.path)
            if parti.path != "/callback":
                self.send_response(404); self.end_headers(); return
            try:
                risultato["codice"] = estrai_codice(parti.query, stato)
                messaggio = "Fatto: puoi chiudere questa pagina e tornare al terminale."
            except RuntimeError as e:
                risultato["errore"] = str(e)
                messaggio = f"Errore: {e}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(messaggio.encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", PORTA), Gestore)
    server.timeout = 2
    fine = time.monotonic() + timeout
    while not risultato and time.monotonic() < fine:
        server.handle_request()  # richieste estranee (l'icona del sito) non interrompono l'attesa
    server.server_close()
    if "errore" in risultato:
        raise RuntimeError(risultato["errore"])
    if "codice" not in risultato:
        raise RuntimeError("nessuna risposta da LinkedIn entro il tempo")
    return risultato["codice"]


def main() -> int:
    carica_env()
    cid, segreto = os.environ.get("LINKEDIN_CLIENT_ID"), os.environ.get("LINKEDIN_CLIENT_SECRET")
    if not cid or not segreto:
        print("Mancano LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET nel .env.", file=sys.stderr)
        return 2
    stato = secrets.token_urlsafe(16)
    url = url_autorizzazione(cid, stato)
    print("Apro la pagina di consenso di LinkedIn nel browser...")
    if "--senza-browser" in sys.argv or not webbrowser.open(url):
        print(url)
    try:
        codice = aspetta_codice(stato)
        risposta = scambia_codice(codice, cid, segreto)
        token = risposta["access_token"]
        persona = chi_sono(token)
    except (RuntimeError, KeyError) as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 1
    scade = datetime.now(timezone.utc) + timedelta(seconds=int(risposta.get("expires_in", 0)))
    salva_env(ENV, {
        "LINKEDIN_ACCESS_TOKEN": token,
        "LINKEDIN_PERSON_URN": f"urn:li:person:{persona['sub']}",
        "LINKEDIN_TOKEN_SCADE": scade.strftime("%Y-%m-%d"),
    })
    print(f"Fatto: collegato come {persona.get('name', '?')}. Il token scade il {scade:%d/%m/%Y}.")
    print("Salvati nel .env: LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN, LINKEDIN_TOKEN_SCADE")
    return 0


if __name__ == "__main__":
    sys.exit(main())

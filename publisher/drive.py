"""Le cartelle Google Drive dei post, con un account di servizio: elenco dei file e, al momento di pubblicare, il
permesso «chiunque con il link» sul singolo file, che Instagram e Facebook scaricano da lì e che si toglie subito dopo.

La chiave dell'account di servizio sta in GOOGLE_SA_KEY_B64 (il file JSON in base64). La firma del token si fa con
`openssl`, presente su macOS, Linux e sui server di GitHub, così non serve nessuna libreria esterna.
La cartella va condivisa come **Editor** con l'indirizzo dell'account di servizio (per cambiare i permessi dei file)."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

SCOPE = "https://www.googleapis.com/auth/drive"
API = "https://www.googleapis.com/drive/v3"
# Indirizzo che serve il file senza pagine in mezzo, anche oltre i 25 MB (confirm=t salta l'avviso antivirus);
# «nome» lo ignora Google e serve a noi per riconoscere il tipo di file dall'indirizzo.
PUBBLICO = "https://drive.usercontent.google.com/download"
RE_CARTELLA = re.compile(r"(?:/folders/|[?&]id=)([A-Za-z0-9_-]{10,})")


class ErroreDrive(RuntimeError):
    pass


def chiave_da_env() -> dict:
    valore = os.environ.get("GOOGLE_SA_KEY_B64", "")
    if not valore:
        raise ErroreDrive("Manca GOOGLE_SA_KEY_B64 (la chiave dell'account di servizio Google).")
    try:
        return json.loads(base64.b64decode(valore))
    except ValueError:
        raise ErroreDrive("GOOGLE_SA_KEY_B64 non è una chiave valida.") from None


def id_cartella(link: str) -> str:
    """L'id della cartella da un link di Drive (o l'id stesso)."""
    link = (link or "").strip()
    m = RE_CARTELLA.search(link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", link):
        return link
    raise ErroreDrive("il campo «Cartella Drive» non contiene il link di una cartella")


def _b64url(dati: bytes) -> str:
    return base64.urlsafe_b64encode(dati).rstrip(b"=").decode()


def _firma(testo: bytes, chiave_privata: str) -> bytes:
    fd, pem = tempfile.mkstemp(suffix=".pem")
    try:
        os.chmod(pem, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(chiave_privata)
        r = subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem], input=testo, capture_output=True)
        if r.returncode != 0:
            raise ErroreDrive(f"firma del token non riuscita: {r.stderr.decode(errors='replace')[:200]}")
        return r.stdout
    finally:
        os.unlink(pem)


def _json(richiesta: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(richiesta, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="replace")[:300]
        if e.code == 404:
            raise ErroreDrive("la cartella Drive non si trova o non è condivisa con il sistema") from None
        raise ErroreDrive(f"Google Drive {e.code}: {corpo}") from None
    except urllib.error.URLError as e:
        raise ErroreDrive(f"Google Drive non raggiungibile: {e.reason}") from None


def token(chiave: Optional[dict] = None) -> str:
    chiave = chiave or chiave_da_env()
    ora = int(time.time())
    intestazione = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    richiesta = _b64url(json.dumps({
        "iss": chiave["client_email"], "scope": SCOPE, "aud": chiave["token_uri"], "iat": ora, "exp": ora + 3600,
    }).encode())
    da_firmare = f"{intestazione}.{richiesta}".encode()
    jwt = f"{intestazione}.{richiesta}.{_b64url(_firma(da_firmare, chiave['private_key']))}"
    corpo = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt}).encode()
    risposta = _json(urllib.request.Request(chiave["token_uri"], data=corpo, method="POST"))
    if "access_token" not in risposta:
        raise ErroreDrive("Google non ha dato il token di accesso")
    return risposta["access_token"]


def elenca(tok: str, cartella: str) -> List[dict]:
    """I file della cartella, in ordine di nome. Si ignorano sottocartelle e file che iniziano con «_» o «.»."""
    q = f"'{cartella}' in parents and trashed = false"
    params = {"q": q, "fields": "files(id,name,mimeType,size),nextPageToken", "pageSize": "200", "orderBy": "name",
              "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
    file: List[dict] = []
    while True:
        url = f"{API}/files?{urllib.parse.urlencode(params)}"
        risposta = _json(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}))
        file += risposta.get("files", [])
        if not risposta.get("nextPageToken"):
            break
        params["pageToken"] = risposta["nextPageToken"]
    utili = [f for f in file if f.get("mimeType") != "application/vnd.google-apps.folder" and not f["name"].startswith(("_", "."))]
    return sorted(utili, key=lambda f: f["name"].lower())


def link_pubblico(file_id: str, nome: str) -> str:
    return f"{PUBBLICO}?{urllib.parse.urlencode({'id': file_id, 'export': 'download', 'confirm': 't', 'nome': nome})}"


def id_da_link(link: str) -> str:
    """L'id del file da un indirizzo pubblico fatto da link_pubblico (vuoto se non è uno dei nostri)."""
    u = urllib.parse.urlparse(link)
    if u.hostname != urllib.parse.urlparse(PUBBLICO).hostname:
        return ""
    return urllib.parse.parse_qs(u.query).get("id", [""])[0]


def _permessi(tok: str, file_id: str) -> List[dict]:
    url = f"{API}/files/{file_id}/permissions?fields=permissions(id,type,role)&supportsAllDrives=true"
    return _json(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})).get("permissions", [])


def rendi_pubblico(tok: str, file_id: str, nome: str) -> str:
    """Dà al file il permesso «chiunque con il link» (solo lettura, non cercabile) e restituisce l'indirizzo pubblico."""
    if not any(p.get("type") == "anyone" for p in _permessi(tok, file_id)):
        url = f"{API}/files/{file_id}/permissions?supportsAllDrives=true"
        corpo = json.dumps({"type": "anyone", "role": "reader"}).encode()
        try:
            _json(urllib.request.Request(url, data=corpo, method="POST",
                                         headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}))
        except ErroreDrive as e:
            if "403" in str(e):
                raise ErroreDrive(f"il sistema non può rendere pubblico {nome}: sulla cartella Drive l'account di servizio "
                                  "deve essere Editor, non Visualizzatore") from None
            raise
    return link_pubblico(file_id, nome)


def rendi_privati(tok: str, link: List[str]) -> None:
    """Toglie il permesso «chiunque con il link» dai file dei nostri indirizzi pubblici (gli altri si ignorano)."""
    for file_id in filter(None, (id_da_link(u) for u in link)):
        for p in _permessi(tok, file_id):
            if p.get("type") != "anyone":
                continue
            url = f"{API}/files/{file_id}/permissions/{p['id']}?supportsAllDrives=true"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {tok}"}), timeout=60):
                    pass
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise ErroreDrive(f"Google Drive {e.code}: non riesco a rimettere privato il file {file_id}") from None
            except urllib.error.URLError as e:
                raise ErroreDrive(f"Google Drive non raggiungibile: {e.reason}") from None


def scarica(tok: str, file_id: str, destinazione: Path) -> Path:
    url = f"{API}/files/{file_id}?alt=media&supportsAllDrives=true"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}), timeout=300) as r:
            destinazione.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        raise ErroreDrive(f"download da Drive non riuscito ({e.code})") from None
    except urllib.error.URLError as e:
        raise ErroreDrive(f"Google Drive non raggiungibile: {e.reason}") from None
    return destinazione

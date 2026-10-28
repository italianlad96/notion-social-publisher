import base64
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

from publisher import drive


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Cartella(unittest.TestCase):
    def test_link_e_id(self):
        for link in ("https://drive.google.com/drive/folders/1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543",
                     "https://drive.google.com/drive/u/0/folders/1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543?usp=sharing",
                     "https://drive.google.com/open?id=1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543",
                     " 1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543 "):
            self.assertEqual(drive.id_cartella(link), "1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543", link)

    def test_link_sbagliati(self):
        for link in ("", "https://example.com", "ciao", None):
            with self.assertRaises(drive.ErroreDrive):
                drive.id_cartella(link)


class Token(unittest.TestCase):
    """Firma vera con una chiave RSA generata al momento, verificata con la chiave pubblica."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        subprocess.run(["openssl", "genrsa", "-out", str(self.tmp / "k.pem"), "2048"], check=True, capture_output=True)
        subprocess.run(["openssl", "rsa", "-in", str(self.tmp / "k.pem"), "-pubout", "-out", str(self.tmp / "p.pem")],
                       check=True, capture_output=True)
        self.chiave = {"client_email": "sa@progetto.iam.gserviceaccount.com", "token_uri": "https://oauth2.googleapis.com/token",
                       "private_key": (self.tmp / "k.pem").read_text()}

    def test_jwt_firmato_e_scambiato(self):
        visto = {}

        def finta(req, timeout=None):
            visto["req"] = req
            return io.BytesIO(b'{"access_token": "ya29.x", "expires_in": 3599}')

        with mock.patch("urllib.request.urlopen", finta):
            self.assertEqual(drive.token(self.chiave), "ya29.x")
        req = visto["req"]
        self.assertEqual(req.full_url, "https://oauth2.googleapis.com/token")
        corpo = urllib.parse.parse_qs(req.data.decode())
        self.assertEqual(corpo["grant_type"], ["urn:ietf:params:oauth:grant-type:jwt-bearer"])
        testa, dati, firma = corpo["assertion"][0].split(".")
        self.assertEqual(json.loads(_b64d(testa)), {"alg": "RS256", "typ": "JWT"})
        claims = json.loads(_b64d(dati))
        self.assertEqual((claims["iss"], claims["scope"], claims["exp"] - claims["iat"]),
                         ("sa@progetto.iam.gserviceaccount.com", drive.SCOPE, 3600))
        (self.tmp / "firma.bin").write_bytes(_b64d(firma))
        verifica = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(self.tmp / "p.pem"), "-signature",
                                   str(self.tmp / "firma.bin")], input=f"{testa}.{dati}".encode(), capture_output=True)
        self.assertEqual(verifica.returncode, 0, verifica.stdout + verifica.stderr)

    def test_chiave_privata_non_resta_su_disco(self):
        prima = set(Path(tempfile.gettempdir()).glob("*.pem"))
        with mock.patch("urllib.request.urlopen", lambda req, timeout=None: io.BytesIO(b'{"access_token": "x"}')):
            drive.token(self.chiave)
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("*.pem")), prima)

    def test_chiave_mancante_o_rotta(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(drive.ErroreDrive):
                drive.chiave_da_env()
        with mock.patch.dict("os.environ", {"GOOGLE_SA_KEY_B64": "!!non base64 json!!"}):
            with self.assertRaises(drive.ErroreDrive):
                drive.chiave_da_env()


class Elenco(unittest.TestCase):
    def test_filtra_ordina_e_segue_le_pagine(self):
        risposte = [
            {"files": [{"id": "1", "name": "02.jpg", "mimeType": "image/jpeg"},
                       {"id": "2", "name": "_bozza.png", "mimeType": "image/png"},
                       {"id": "3", "name": "Sottocartella", "mimeType": "application/vnd.google-apps.folder"}], "nextPageToken": "p2"},
            {"files": [{"id": "4", "name": "01.png", "mimeType": "image/png"}, {"id": "5", "name": ".DS_Store", "mimeType": "x"}]},
        ]
        url_visti = []

        def finta(req, timeout=None):
            url_visti.append(req.full_url)
            self.assertEqual(req.get_header("Authorization"), "Bearer T")
            return io.BytesIO(json.dumps(risposte.pop(0)).encode())

        with mock.patch("urllib.request.urlopen", finta):
            file = drive.elenca("T", "CARTELLA123456")
        self.assertEqual([f["name"] for f in file], ["01.png", "02.jpg"])
        self.assertIn(urllib.parse.quote("'CARTELLA123456' in parents and trashed = false"), url_visti[0].replace("+", "%20"))
        self.assertIn("pageToken=p2", url_visti[1])

    def test_cartella_non_condivisa(self):
        def finta(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 404, "x", {}, io.BytesIO(b"{}"))

        with mock.patch("urllib.request.urlopen", finta):
            with self.assertRaisesRegex(drive.ErroreDrive, "condivisa"):
                drive.elenca("T", "CARTELLA123456")

    def test_scarica(self):
        with tempfile.TemporaryDirectory() as t:
            dest = Path(t) / "x.jpg"
            with mock.patch("urllib.request.urlopen", lambda req, timeout=None: io.BytesIO(b"DATI")):
                drive.scarica("T", "id1", dest)
            self.assertEqual(dest.read_bytes(), b"DATI")


class Pubblico(unittest.TestCase):
    """Il permesso «chiunque con il link» sul singolo file, messo al momento di pubblicare e tolto dopo."""

    def test_link_e_id(self):
        link = drive.link_pubblico("1AbCdEfGhIjKlMnOpQrStUvWxYz0123456", "il video.mp4")
        self.assertTrue(link.startswith("https://drive.usercontent.google.com/download?"))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        self.assertEqual((q["id"], q["export"], q["confirm"], q["nome"]), (["1AbCdEfGhIjKlMnOpQrStUvWxYz0123456"], ["download"], ["t"], ["il video.mp4"]))
        self.assertEqual(drive.id_da_link(link), "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456")
        for altro in ("https://blob.example/reel.mp4", "https://drive.google.com/uc?export=download&id=abc", ""):
            self.assertEqual(drive.id_da_link(altro), "", altro)

    def _server(self, permessi, log):
        def finta(req, timeout=None):
            log.append((req.get_method(), req.full_url, req.data))
            if req.get_method() == "GET":
                return io.BytesIO(json.dumps({"permissions": permessi}).encode())
            if req.get_method() == "POST":
                return io.BytesIO(b'{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}')
            return io.BytesIO(b"")
        return finta

    def test_rendi_pubblico_crea_il_permesso_una_volta_sola(self):
        log = []
        with mock.patch("urllib.request.urlopen", self._server([{"id": "1", "type": "user", "role": "owner"}], log)):
            link = drive.rendi_pubblico("T", "idf", "reel.mp4")
        self.assertEqual([m for m, _, _ in log], ["GET", "POST"])
        self.assertEqual(json.loads(log[1][2]), {"type": "anyone", "role": "reader"})
        self.assertEqual(drive.id_da_link(link), "idf")
        log.clear()
        with mock.patch("urllib.request.urlopen", self._server([{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}], log)):
            drive.rendi_pubblico("T", "idf", "reel.mp4")
        self.assertEqual([m for m, _, _ in log], ["GET"])  # già pubblico: non si rifà

    def test_rendi_pubblico_senza_permesso_spiega_cosa_fare(self):
        def finta(req, timeout=None):
            if req.get_method() == "GET":
                return io.BytesIO(b'{"permissions": []}')
            raise urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(b'{"error": "insufficientFilePermissions"}'))
        with mock.patch("urllib.request.urlopen", finta):
            with self.assertRaisesRegex(drive.ErroreDrive, "Editor"):
                drive.rendi_pubblico("T", "idf", "reel.mp4")

    def test_rendi_privati_toglie_solo_anyone_e_solo_sui_nostri_link(self):
        log = []
        permessi = [{"id": "1", "type": "user", "role": "owner"}, {"id": "anyoneWithLink", "type": "anyone", "role": "reader"}]
        with mock.patch("urllib.request.urlopen", self._server(permessi, log)):
            drive.rendi_privati("T", [drive.link_pubblico("idf", "a.jpg"), "https://blob.example/x.jpg"])
        self.assertEqual([(m, u.split("/files/")[1].split("?")[0]) for m, u, _ in log], [("GET", "idf/permissions"), ("DELETE", "idf/permissions/anyoneWithLink")])

    def test_rendi_privati_errore_diventa_erroredrive(self):
        def finta(req, timeout=None):
            if req.get_method() == "GET":
                return io.BytesIO(b'{"permissions": [{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}]}')
            raise urllib.error.HTTPError(req.full_url, 500, "x", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", finta):
            with self.assertRaisesRegex(drive.ErroreDrive, "500"):
                drive.rendi_privati("T", [drive.link_pubblico("idf", "a.jpg")])


if __name__ == "__main__":
    unittest.main()

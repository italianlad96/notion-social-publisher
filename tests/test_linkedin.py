import io
import json
import unittest
import urllib.error
from datetime import date
from unittest import mock

from publisher import linkedin
from publisher.linkedin import ErroreLinkedIn
from tests.helpers import riga_t
from tests.helpers import REEL, pagina

TOKEN, PERSONA = "T", "urn:li:person:abc"
CARICO = "https://api.linkedin.com/mediaUpload/xyz/feedshare-uploadedImage/0?x=1"
ASSET = "urn:li:digitalmediaAsset:C5522AQ"


def riga(formato="Post", media=("https://b/x.jpg",), testo="Il testo", li=""):
    return riga_t(pagina(formato=formato, media=media, didascalia=testo, testo_linkedin=li))


class Finta:
    """LinkedIn finta: registra le chiamate JSON e risponde con ciò che serve."""

    def __init__(self, stati_asset=None, errori=None, urn="urn:li:share:777", intest=None):
        self.chiamate, self.caricati, self.scaricati = [], [], []
        self.stati = list(stati_asset or [[{"status": "AVAILABLE"}]])
        self.errori, self.urn = errori or {}, urn
        self.intest = intest if intest is not None else {"X-RestLi-Id": urn}

    def chiama(self, metodo, percorso, token, corpo=None, ritenta=True):
        self.chiamate.append((metodo, percorso, corpo, ritenta))
        for (m, p), e in self.errori.items():
            if metodo == m and percorso.startswith(p):
                raise e
        if percorso.startswith("/v2/assets?action=registerUpload"):
            return {"value": {"uploadMechanism": {"com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {"uploadUrl": CARICO}}, "asset": ASSET}}, {}
        if metodo == "GET" and percorso.startswith("/v2/assets/"):
            recipes = self.stati.pop(0) if len(self.stati) > 1 else self.stati[0]
            return {"recipes": recipes}, {}
        if metodo == "POST" and percorso == "/v2/ugcPosts":
            return {}, self.intest
        if metodo == "DELETE":
            return {}, {}
        raise AssertionError(f"chiamata non prevista {metodo} {percorso}")

    def percorsi(self):
        return [(m, p) for m, p, _, _ in self.chiamate]


class Base(unittest.TestCase):
    def usa(self, finta):
        for nome, valore in (("chiama", finta.chiama), ("scarica", lambda u: finta.scaricati.append(u) or b"BYTES"),
                             ("carica_binario", lambda u, t, d: finta.caricati.append((u, t, d))), ("dormi", mock.Mock())):
            p = mock.patch.object(linkedin, nome, valore)
            p.start()
            self.addCleanup(p.stop)
        self.dormi = linkedin.dormi
        return finta

    def corpo_post(self, f):
        return [c for c in f.chiamate if c[1] == "/v2/ugcPosts"][0]


class Pubblica(Base):
    def test_solo_testo(self):
        f = self.usa(Finta())
        res = linkedin.pubblica(PERSONA, TOKEN, riga("Post", ()), )
        self.assertEqual((res.stato, res.dettaglio), ("pubblicato", "https://www.linkedin.com/feed/update/urn:li:share:777/"))
        _, _, corpo, ritenta = self.corpo_post(f)
        self.assertFalse(ritenta)
        self.assertEqual(corpo["author"], PERSONA)
        self.assertEqual(corpo["lifecycleState"], "PUBLISHED")
        self.assertEqual(corpo["visibility"], {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"})
        c = corpo["specificContent"]["com.linkedin.ugc.ShareContent"]
        self.assertEqual(c, {"shareCommentary": {"text": "Il testo"}, "shareMediaCategory": "NONE"})
        self.assertEqual(f.caricati, [])

    def test_il_testo_linkedin_ha_la_precedenza(self):
        f = self.usa(Finta())
        linkedin.pubblica(PERSONA, TOKEN, riga("Post", (), li="Per LinkedIn"))
        self.assertEqual(self.corpo_post(f)[2]["specificContent"]["com.linkedin.ugc.ShareContent"]["shareCommentary"]["text"], "Per LinkedIn")

    def test_immagine_registra_carica_e_allega(self):
        f = self.usa(Finta())
        linkedin.pubblica(PERSONA, TOKEN, riga())
        reg = f.chiamate[0]
        self.assertEqual(reg[2]["registerUploadRequest"]["recipes"], ["urn:li:digitalmediaRecipe:feedshare-image"])
        self.assertEqual(reg[2]["registerUploadRequest"]["owner"], PERSONA)
        self.assertEqual(f.scaricati, ["https://b/x.jpg"])
        self.assertEqual(f.caricati, [(CARICO, TOKEN, b"BYTES")])
        c = self.corpo_post(f)[2]["specificContent"]["com.linkedin.ugc.ShareContent"]
        self.assertEqual((c["shareCommentary"]["text"], c["shareMediaCategory"], c["media"]), ("Il testo", "IMAGE", [{"status": "READY", "media": ASSET}]))
        self.assertNotIn("GET", [m for m, _ in f.percorsi()])  # le immagini non hanno elaborazione da aspettare

    def test_video_aspetta_l_elaborazione(self):
        f = self.usa(Finta(stati_asset=[[{"status": "PROCESSING"}], [{"status": "PROCESSING"}], [{"status": "AVAILABLE"}]]))
        linkedin.pubblica(PERSONA, TOKEN, riga("Reel", REEL))
        self.assertEqual(f.chiamate[0][2]["registerUploadRequest"]["recipes"], ["urn:li:digitalmediaRecipe:feedshare-video"])
        self.assertEqual(f.scaricati, [REEL[0]])  # la copertina non si usa
        self.assertEqual(self.dormi.call_count, 2)
        self.assertEqual(self.corpo_post(f)[2]["specificContent"]["com.linkedin.ugc.ShareContent"]["shareMediaCategory"], "VIDEO")
        ordine = f.percorsi()
        self.assertLess(ordine.index(("GET", "/v2/assets/C5522AQ")), ordine.index(("POST", "/v2/ugcPosts")))

    def test_video_in_errore_non_crea_il_post(self):
        f = self.usa(Finta(stati_asset=[[{"status": "FAILED"}]]))
        with self.assertRaisesRegex(ErroreLinkedIn, "non ha elaborato"):
            linkedin.pubblica(PERSONA, TOKEN, riga("Reel", REEL))
        self.assertNotIn(("POST", "/v2/ugcPosts"), f.percorsi())

    def test_video_ancora_in_elaborazione_dopo_il_tempo(self):
        f = self.usa(Finta(stati_asset=[[{"status": "PROCESSING"}]]))
        with self.assertRaisesRegex(ErroreLinkedIn, "ancora elaborando"):
            linkedin.pubblica(PERSONA, TOKEN, riga("Reel", REEL))
        self.assertNotIn(("POST", "/v2/ugcPosts"), f.percorsi())

    def test_stato_del_file_illeggibile_si_prova_comunque(self):
        f = self.usa(Finta(errori={("GET", "/v2/assets/"): ErroreLinkedIn("LinkedIn 403", 403)}))
        res = linkedin.pubblica(PERSONA, TOKEN, riga("Reel", REEL))
        self.assertEqual(res.stato, "pubblicato")

    def test_prova_carica_il_file_ma_non_crea_il_post(self):
        f = self.usa(Finta())
        res = linkedin.pubblica(PERSONA, TOKEN, riga(), prova=True)
        self.assertEqual(res.stato, "prova_ok")
        self.assertEqual(len(f.caricati), 1)
        self.assertNotIn(("POST", "/v2/ugcPosts"), f.percorsi())

    def test_carosello_non_supportato_senza_chiamate(self):
        f = self.usa(Finta())
        with self.assertRaisesRegex(ErroreLinkedIn, "caroselli"):
            linkedin.pubblica(PERSONA, TOKEN, riga("Carosello", ("https://b/1.jpg", "https://b/2.jpg")))
        self.assertEqual(f.chiamate, [])

    def test_visibilita_ai_collegamenti(self):
        f = self.usa(Finta())
        linkedin.pubblica(PERSONA, TOKEN, riga("Post", ()), visibilita="CONNECTIONS")
        self.assertEqual(self.corpo_post(f)[2]["visibility"], {"com.linkedin.ugc.MemberNetworkVisibility": "CONNECTIONS"})

    def test_identificativo_in_intestazione_con_maiuscole_diverse(self):
        self.usa(Finta(intest={"x-restli-id": "urn:li:ugcPost:5"}))
        self.assertEqual(linkedin.pubblica(PERSONA, TOKEN, riga("Post", ())).dettaglio, "https://www.linkedin.com/feed/update/urn:li:ugcPost:5/")

    def test_senza_identificativo_e_un_errore(self):
        self.usa(Finta(intest={}))
        with self.assertRaisesRegex(ErroreLinkedIn, "identificativo"):
            linkedin.pubblica(PERSONA, TOKEN, riga("Post", ()))

    def test_errore_di_creazione_si_propaga(self):
        self.usa(Finta(errori={("POST", "/v2/ugcPosts"): ErroreLinkedIn("LinkedIn 422: no", 422)}))
        with self.assertRaisesRegex(ErroreLinkedIn, "422"):
            linkedin.pubblica(PERSONA, TOKEN, riga("Post", ()))

    def test_registrazione_con_risposta_inattesa(self):
        with mock.patch.object(linkedin, "chiama", lambda *a, **k: ({"value": {}}, {})):
            with self.assertRaisesRegex(ErroreLinkedIn, "inattesa"):
                linkedin.registra_file(PERSONA, TOKEN, "feedshare-image")

    def test_cancella_codifica_l_urn(self):
        f = self.usa(Finta())
        linkedin.cancella(TOKEN, "urn:li:share:777")
        self.assertEqual(f.percorsi(), [("DELETE", "/v2/ugcPosts/urn%3Ali%3Ashare%3A777")])


class Rete(unittest.TestCase):
    def http(self, codice, corpo=b"{}"):
        return urllib.error.HTTPError("u", codice, "x", {}, io.BytesIO(corpo))

    def test_401_dice_cosa_fare(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http(401)):
            with self.assertRaises(ErroreLinkedIn) as c:
                linkedin.chiama("GET", "/v2/x", TOKEN)
        self.assertTrue(c.exception.token_non_valido)
        self.assertIn("linkedin_login.py", str(c.exception))

    def test_503_si_ritenta_e_senza_ritenta_no(self):
        esiti = [self.http(503), io.BytesIO(b'{"ok": 1}')]

        def finta(req, timeout=None):
            e = esiti.pop(0)
            if isinstance(e, Exception):
                raise e
            e.headers = {}
            return e

        with mock.patch("urllib.request.urlopen", finta), mock.patch.object(linkedin, "dormi"):
            dati, _ = linkedin.chiama("GET", "/v2/x", TOKEN)
        self.assertEqual(dati, {"ok": 1})
        n = []

        def sempre(req, timeout=None):
            n.append(1)
            raise self.http(503)

        with mock.patch("urllib.request.urlopen", sempre), mock.patch.object(linkedin, "dormi"):
            with self.assertRaises(ErroreLinkedIn):
                linkedin.chiama("POST", "/v2/ugcPosts", TOKEN, {"a": 1}, ritenta=False)
        self.assertEqual(len(n), 1)

    def test_il_token_va_nell_intestazione_non_nell_indirizzo(self):
        viste = []

        class Risp(io.BytesIO):
            headers = {}

        def finta(req, timeout=None):
            viste.append(req)
            return Risp(b"{}")

        with mock.patch("urllib.request.urlopen", finta):
            linkedin.chiama("POST", "/v2/ugcPosts", "SEGRETO", {"a": 1})
        self.assertEqual(viste[0].get_header("Authorization"), "Bearer SEGRETO")
        self.assertEqual(viste[0].get_header("X-restli-protocol-version"), "2.0.0")
        self.assertNotIn("SEGRETO", viste[0].full_url)


if __name__ == "__main__":
    unittest.main()

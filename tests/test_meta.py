import io
import json
import unittest
import urllib.error
from unittest import mock

from publisher import meta
from publisher.meta import ErroreMeta
from tests.helpers import riga_t
from tests.helpers import REEL, SLIDE, pagina

TOKEN = "T"
IG, PAGE = "ig1", "pg1"


class Grafo:
    """Una Graph API finta: registra le chiamate e risponde con ciò che serve al test."""

    def __init__(self, stati=None, quota=0, permalink="https://instagram.com/p/xyz", errori=None):
        self.chiamate = []
        self.stati = dict(stati or {})  # id contenitore -> lista di stati successivi (l'ultimo resta)
        self.quota, self.permalink = quota, permalink
        self.errori = errori or {}  # (metodo, suffisso del percorso) -> eccezione
        self.n = 0

    def nuovo(self, prefisso="c"):
        self.n += 1
        return f"{prefisso}{self.n}"

    def __call__(self, metodo, percorso, token, params=None, ritenta=True):
        self.chiamate.append((metodo, percorso, dict(params or {}), ritenta))
        for (m, suff), exc in self.errori.items():
            if metodo == m and percorso.endswith(suff):
                raise exc
        if metodo == "POST" and percorso.endswith("/media"):
            return {"id": self.nuovo("c")}
        if metodo == "POST" and percorso.endswith("/media_publish"):
            return {"id": "m99"}
        if metodo == "POST" and percorso.endswith(("/videos", "/photos", "/feed")):
            return {"id": self.nuovo("f"), "post_id": "pg1_p1"} if percorso.endswith("/photos") else {"id": self.nuovo("f")}
        if metodo == "DELETE":
            return {"success": True}
        if metodo == "GET" and percorso.endswith("content_publishing_limit"):
            return {"data": [{"quota_usage": self.quota, "config": {"quota_total": 100}}]}
        if metodo == "GET" and (params or {}).get("fields") == "status_code":
            coda = self.stati.get(percorso, ["FINISHED"])
            return {"status_code": coda.pop(0) if len(coda) > 1 else coda[0]}
        if metodo == "GET" and (params or {}).get("fields") == "permalink":
            return {"permalink": self.permalink}
        if metodo == "GET" and (params or {}).get("fields") == "permalink_url":
            return {"permalink_url": "https://facebook.com/post"}
        raise AssertionError(f"chiamata non prevista: {metodo} {percorso} {params}")

    def percorsi(self, metodo=None):
        return [(m, p) for m, p, _, _ in self.chiamate if metodo is None or m == metodo]


def riga(formato="Reel", media=REEL, testo="Il testo"):
    return riga_t(pagina(formato=formato, media=media, didascalia=testo))


class Base(unittest.TestCase):
    def usa(self, grafo):
        p = mock.patch.object(meta, "chiama", grafo)
        p.start()
        self.addCleanup(p.stop)
        d = mock.patch.object(meta, "dormi")
        self.dormi = d.start()
        self.addCleanup(d.stop)
        return grafo


class InstagramFlusso(Base):
    def test_reel_ordine_delle_chiamate_e_contenitore_salvato_prima_di_pubblicare(self):
        g = self.usa(Grafo())
        eventi = []
        orig = g.__call__

        salva = lambda t: eventi.append(("salva", t))
        res = meta.instagram(IG, TOKEN, riga(), salva)
        self.assertEqual((res.stato, res.dettaglio), ("pubblicato", "https://instagram.com/p/xyz"))
        creazione = g.chiamate[0]
        self.assertEqual(creazione[:2], ("POST", f"{IG}/media"))
        self.assertEqual(creazione[2], {"media_type": "REELS", "video_url": REEL[0], "caption": "Il testo", "cover_url": REEL[1]})
        pubblicazione = [c for c in g.chiamate if c[1].endswith("/media_publish")][0]
        self.assertEqual(pubblicazione[2], {"creation_id": "c1"})
        self.assertFalse(pubblicazione[3])  # la pubblicazione non si ritenta da sola
        self.assertEqual(eventi, [("salva", "contenitore c1")])

    def test_il_contenitore_si_salva_prima_della_pubblicazione(self):
        g = self.usa(Grafo())
        ordine = []
        g_call = g.__call__

        def spia(metodo, percorso, token, params=None, ritenta=True):
            if percorso.endswith("/media_publish"):
                ordine.append("pubblica")
            return g_call(metodo, percorso, token, params, ritenta)

        with mock.patch.object(meta, "chiama", spia):
            meta.instagram(IG, TOKEN, riga(), lambda t: ordine.append("salva"))
        self.assertEqual(ordine, ["salva", "pubblica"])

    def test_reel_senza_copertina(self):
        g = self.usa(Grafo())
        meta.instagram(IG, TOKEN, riga(media=(REEL[0],)), lambda t: None)
        self.assertNotIn("cover_url", g.chiamate[0][2])

    def test_post_singolo(self):
        g = self.usa(Grafo())
        meta.instagram(IG, TOKEN, riga("Post", ("https://b/x.jpg",)), lambda t: None)
        self.assertEqual(g.chiamate[0][2], {"image_url": "https://b/x.jpg", "caption": "Il testo"})

    def test_carosello_con_video_e_ordine_dei_figli(self):
        g = self.usa(Grafo())
        media = ("https://b/01.jpg", "https://b/02.jpg", "https://b/03.mp4")
        meta.instagram(IG, TOKEN, riga("Carosello", media), lambda t: None)
        creazioni = [c[2] for c in g.chiamate if c[0] == "POST" and c[1].endswith("/media")]
        self.assertEqual(creazioni[0], {"image_url": "https://b/01.jpg", "is_carousel_item": "true"})
        self.assertEqual(creazioni[2], {"media_type": "VIDEO", "video_url": "https://b/03.mp4", "is_carousel_item": "true"})
        self.assertEqual(creazioni[3], {"media_type": "CAROUSEL", "children": "c1,c2,c3", "caption": "Il testo"})
        stati = [p for m, p in g.percorsi("GET") if p in ("c1", "c2", "c3")]
        self.assertEqual(stati[:3], ["c1", "c2", "c3"])  # tutti i figli controllati prima del carosello

    def test_carosello_con_elemento_in_errore(self):
        g = self.usa(Grafo(stati={"c2": ["ERROR"]}))
        with self.assertRaisesRegex(ErroreMeta, "elemento del carosello"):
            meta.instagram(IG, TOKEN, riga("Carosello", SLIDE[:3]), lambda t: None)
        self.assertEqual([p for m, p in g.percorsi("POST") if p.endswith("media_publish")], [])

    def test_prova_si_ferma_al_contenitore_pronto(self):
        g = self.usa(Grafo())
        res = meta.instagram(IG, TOKEN, riga(), lambda t: None, prova=True)
        self.assertEqual(res.stato, "prova_ok")
        self.assertEqual([p for m, p in g.percorsi("POST") if p.endswith("media_publish")], [])

    def test_riprende_il_contenitore_di_prima(self):
        g = self.usa(Grafo())
        salvati = []
        res = meta.instagram(IG, TOKEN, riga(), salvati.append, contenitore_noto="c77")
        self.assertEqual(res.stato, "pubblicato")
        self.assertEqual(salvati, [])
        self.assertEqual([p for m, p in g.percorsi("POST") if p.endswith("/media")], [])
        self.assertEqual([c[2] for c in g.chiamate if c[1].endswith("media_publish")], [{"creation_id": "c77"}])

    def test_contenitore_scaduto_se_ne_crea_uno_nuovo(self):
        g = self.usa(Grafo(stati={"c77": ["EXPIRED"]}))
        salvati = []
        res = meta.instagram(IG, TOKEN, riga(), salvati.append, contenitore_noto="c77")
        self.assertEqual(res.stato, "pubblicato")
        self.assertEqual(salvati, ["contenitore c1"])

    def test_contenitore_noto_che_non_si_trova_se_ne_crea_uno_nuovo(self):
        g = self.usa(Grafo(errori={("GET", "c77"): ErroreMeta("Meta 400/100: non esiste", 100, 400)}))
        salvati = []
        meta.instagram(IG, TOKEN, riga(), salvati.append, contenitore_noto="c77")
        self.assertEqual(salvati, ["contenitore c1"])

    def test_elaborazione_lenta_resta_in_corso_senza_errore(self):
        g = self.usa(Grafo(stati={"c1": ["IN_PROGRESS"]}))
        res = meta.instagram(IG, TOKEN, riga(), lambda t: None, max_attesa=16)
        self.assertEqual((res.stato, res.dettaglio), ("in_corso", "c1"))
        self.assertEqual([p for m, p in g.percorsi("POST") if p.endswith("media_publish")], [])
        self.assertEqual(self.dormi.call_count, 2)

    def test_attende_finche_finisce(self):
        g = self.usa(Grafo(stati={"c1": ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]}))
        res = meta.instagram(IG, TOKEN, riga(), lambda t: None)
        self.assertEqual(res.stato, "pubblicato")
        self.assertEqual(self.dormi.call_count, 2)

    def test_elaborazione_in_errore(self):
        self.usa(Grafo(stati={"c1": ["ERROR"]}))
        with self.assertRaisesRegex(ErroreMeta, "non ha elaborato"):
            meta.instagram(IG, TOKEN, riga(), lambda t: None)

    def test_quota_esaurita_non_pubblica(self):
        g = self.usa(Grafo(quota=100))
        with self.assertRaisesRegex(ErroreMeta, "limite giornaliero"):
            meta.instagram(IG, TOKEN, riga(), lambda t: None)
        self.assertEqual([p for m, p in g.percorsi("POST") if p.endswith("media_publish")], [])

    def test_quota_a_99_pubblica(self):
        self.usa(Grafo(quota=99))
        self.assertEqual(meta.instagram(IG, TOKEN, riga(), lambda t: None).stato, "pubblicato")

    def test_errore_in_pubblicazione_si_propaga(self):
        self.usa(Grafo(errori={("POST", f"{IG}/media_publish"): ErroreMeta("Meta 400/9007: non pronto", 9007, 400)}))
        with self.assertRaisesRegex(ErroreMeta, "9007"):
            meta.instagram(IG, TOKEN, riga(), lambda t: None)

    def test_senza_permalink_resta_l_id_del_post(self):
        self.usa(Grafo(errori={("GET", "m99"): ErroreMeta("Meta 500", None, 500)}))
        self.assertEqual(meta.instagram(IG, TOKEN, riga(), lambda t: None).dettaglio, "m99")


class FacebookFlusso(Base):
    def test_reel_come_video_della_pagina(self):
        g = self.usa(Grafo())
        res = meta.facebook(PAGE, TOKEN, riga())
        self.assertEqual(res.stato, "pubblicato")
        c = g.chiamate[0]
        self.assertEqual(c[:2], ("POST", f"{PAGE}/videos"))
        self.assertEqual(c[2], {"file_url": REEL[0], "description": "Il testo", "published": "true"})
        self.assertFalse(c[3])

    def test_post_con_foto(self):
        g = self.usa(Grafo())
        meta.facebook(PAGE, TOKEN, riga("Post", ("https://b/x.jpg",)))
        self.assertEqual(g.chiamate[0][2], {"url": "https://b/x.jpg", "caption": "Il testo", "published": "true"})

    def test_carosello_di_foto_in_un_solo_post(self):
        g = self.usa(Grafo())
        meta.facebook(PAGE, TOKEN, riga("Carosello", SLIDE[:3]))
        foto = [c for c in g.chiamate if c[1].endswith("/photos")]
        self.assertTrue(all(c[2]["published"] == "false" for c in foto))
        feed = [c for c in g.chiamate if c[1].endswith("/feed")][0]
        self.assertEqual(json.loads(feed[2]["attached_media"]), [{"media_fbid": "f1"}, {"media_fbid": "f2"}, {"media_fbid": "f3"}])
        self.assertEqual(feed[2]["published"], "true")
        self.assertFalse(feed[3])

    def test_prova_crea_non_pubblicato_e_cancella_tutto(self):
        g = self.usa(Grafo())
        res = meta.facebook(PAGE, TOKEN, riga("Carosello", SLIDE[:2]), prova=True)
        self.assertEqual(res.stato, "prova_ok")
        feed = [c for c in g.chiamate if c[1].endswith("/feed")][0]
        self.assertEqual(feed[2]["published"], "false")
        cancellati = [p for m, p in g.percorsi("DELETE")]
        self.assertEqual(sorted(cancellati), ["f1", "f2", "f3"])  # le due foto e il post

    def test_prova_cancella_anche_se_a_meta_qualcosa_fallisce(self):
        g = self.usa(Grafo(errori={("POST", f"{PAGE}/feed"): ErroreMeta("Meta 400/100: no", 100, 400)}))
        with self.assertRaises(ErroreMeta):
            meta.facebook(PAGE, TOKEN, riga("Carosello", SLIDE[:2]), prova=True)
        self.assertEqual(sorted(p for m, p in g.percorsi("DELETE")), ["f1", "f2"])

    def test_errore_di_cancellazione_in_prova_non_nasconde_il_risultato(self):
        self.usa(Grafo(errori={("DELETE", "f1"): ErroreMeta("Meta 400", None, 400)}))
        self.assertEqual(meta.facebook(PAGE, TOKEN, riga(), prova=True).stato, "prova_ok")


class Rete(unittest.TestCase):
    def http(self, codice_http, codice_meta, messaggio="boh"):
        corpo = json.dumps({"error": {"code": codice_meta, "message": messaggio}}).encode()
        return urllib.error.HTTPError("u", codice_http, "x", {}, io.BytesIO(corpo))

    def test_errore_transitorio_si_ritenta_poi_riesce(self):
        esiti = [self.http(400, 4), io.BytesIO(b'{"id": "1"}')]

        def finta(req, timeout=None):
            e = esiti.pop(0)
            if isinstance(e, Exception):
                raise e
            return e

        with mock.patch("urllib.request.urlopen", finta), mock.patch.object(meta, "dormi"):
            self.assertEqual(meta.chiama("GET", "x", TOKEN), {"id": "1"})

    def test_senza_ritenta_un_solo_tentativo(self):
        n = []

        def finta(req, timeout=None):
            n.append(1)
            raise self.http(500, None)

        with mock.patch("urllib.request.urlopen", finta), mock.patch.object(meta, "dormi"):
            with self.assertRaises(ErroreMeta):
                meta.chiama("POST", "x", TOKEN, ritenta=False)
        self.assertEqual(len(n), 1)

    def test_token_non_valido_si_riconosce_e_non_si_ritenta(self):
        n = []

        def finta(req, timeout=None):
            n.append(1)
            raise self.http(400, 190, "token scaduto")

        with mock.patch("urllib.request.urlopen", finta), mock.patch.object(meta, "dormi"):
            with self.assertRaises(ErroreMeta) as c:
                meta.chiama("GET", "x", TOKEN)
        self.assertTrue(c.exception.token_non_valido)
        self.assertEqual(len(n), 1)

    def test_il_token_va_nel_corpo_dei_post_e_nell_indirizzo_dei_get(self):
        viste = []

        def finta(req, timeout=None):
            viste.append(req)
            return io.BytesIO(b"{}")

        with mock.patch("urllib.request.urlopen", finta):
            meta.chiama("POST", "x/media", "SEGRETO", {"a": "1"})
            meta.chiama("GET", "x", "SEGRETO", {"fields": "id"})
        self.assertIn(b"access_token=SEGRETO", viste[0].data)
        self.assertNotIn("SEGRETO", viste[0].full_url)
        self.assertIsNone(viste[1].data)
        self.assertIn("access_token=SEGRETO", viste[1].full_url)

    def test_risposta_non_json_in_errore(self):
        def finta(req, timeout=None):
            raise urllib.error.HTTPError("u", 502, "x", {}, io.BytesIO(b"<html>"))

        with mock.patch("urllib.request.urlopen", finta), mock.patch.object(meta, "dormi"):
            with self.assertRaisesRegex(ErroreMeta, "502"):
                meta.chiama("GET", "x", TOKEN)


if __name__ == "__main__":
    unittest.main()

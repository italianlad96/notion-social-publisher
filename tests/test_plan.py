import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from publisher import config
from publisher.model import esito_leggibile, piattaforme_fatte, riga_da_pagina
from publisher.plan import candidata, decidi, pianifica
from tests.helpers import CARTELLA, REEL, SLIDE, pagina, riga_t

ROMA = ZoneInfo("Europe/Rome")


def alle(g, h, m=0):
    return datetime(2026, 11, g, h, m, tzinfo=ROMA)


def azione(ora, **kw):
    return decidi(riga_t(pagina(**kw)), ora)


OK = dict(piattaforme=("Instagram", "Facebook"), didascalia="Testo", media=REEL)


class Orari(unittest.TestCase):
    def test_solo_giorno_esce_alle_nove(self):
        self.assertEqual(azione(alle(9, 8, 59), **OK).azione, "attesa")
        self.assertEqual(azione(alle(9, 9, 0), **OK).azione, "pubblica")

    def test_confine_delle_48_ore(self):
        due = alle(9, 9, 0)
        self.assertEqual(azione(due + timedelta(hours=48), **OK).azione, "pubblica")
        self.assertEqual(azione(due + timedelta(hours=48, seconds=1), **OK).azione, "scaduto")

    def test_ora_legale_e_solare(self):
        self.assertEqual(riga_da_pagina(pagina(data="2026-10-24")).data.utcoffset(), timedelta(hours=2))
        self.assertEqual(riga_da_pagina(pagina(data="2026-10-26")).data.utcoffset(), timedelta(hours=1))

    def test_data_con_ora_offset_e_Z(self):
        r = riga_da_pagina(pagina(data="2026-11-09T18:30:00.000+01:00"))
        self.assertEqual(r.data, datetime(2026, 11, 9, 17, 30, tzinfo=timezone.utc))
        self.assertEqual(riga_da_pagina(pagina(data="2026-11-09T08:00:00.000Z")).data.utcoffset(), timedelta(0))
        self.assertEqual(riga_da_pagina(pagina(data="2026-11-09T10:00:00", time_zone="America/New_York")).data.utcoffset(), timedelta(hours=-5))


class Stati(unittest.TestCase):
    ORA = alle(9, 9, 5)

    def test_programmato_esce(self):
        self.assertEqual(azione(self.ORA, **OK).azione, "pubblica")

    def test_pronto_resta_a_mano_anche_con_le_piattaforme(self):
        self.assertEqual(azione(self.ORA, stato="Pronto", **OK).azione, "manuale")

    def test_pubblica_subito_vale_per_pronto_e_programmato_anche_in_anticipo(self):
        for stato in ("Pronto", "Programmato"):
            d = azione(alle(1, 10), stato=stato, pubblica_subito=True, **OK)
            self.assertEqual(d.azione, "pubblica", stato)

    def test_pubblica_subito_non_tocca_gli_altri_stati(self):
        for stato in ("Idea", "Da approvare", "Da sistemare", "Pubblicato", "In lavorazione"):
            self.assertEqual(azione(self.ORA, stato=stato, pubblica_subito=True, **OK).azione, "ignora", stato)

    def test_stati_non_affidati_si_ignorano(self):
        for stato in ("Idea", "Da approvare", "Da sistemare", "Pubblicato", None):
            self.assertEqual(azione(self.ORA, stato=stato, **OK).azione, "ignora", stato)

    def test_candidata(self):
        self.assertTrue(candidata(riga_t(pagina(stato="Programmato"))))
        self.assertFalse(candidata(riga_t(pagina(stato="Pronto"))))
        self.assertTrue(candidata(riga_t(pagina(stato="Pronto", pubblica_subito=True))))


class Scelte(unittest.TestCase):
    ORA = alle(9, 9, 5)

    def test_senza_piattaforme_e_un_problema(self):
        d = azione(self.ORA, piattaforme=(), didascalia="x", media=REEL)
        self.assertEqual(d.azione, "problema")
        self.assertIn("piattaforma", d.problemi["tutte"][0])

    def test_senza_data_problema_ma_con_subito_esce(self):
        self.assertEqual(azione(self.ORA, data=None, **OK).azione, "problema")
        self.assertEqual(azione(self.ORA, data=None, pubblica_subito=True, **OK).azione, "pubblica")

    def test_scaduto_ma_con_subito_esce(self):
        self.assertEqual(azione(alle(20, 9), **OK).azione, "scaduto")
        self.assertEqual(azione(alle(20, 9), pubblica_subito=True, **OK).azione, "pubblica")

    def test_esito_parziale_e_chiusura(self):
        d = azione(self.ORA, esito="instagram: pubblicato https://i/p 2026-11-09T08:05+00:00", **OK)
        self.assertEqual(d.piattaforme, ["facebook"])
        d = azione(self.ORA, esito="instagram: pubblicato a\nfacebook: pubblicato b", **OK)
        self.assertEqual(d.azione, "chiudere")

    def test_errore_non_conta_come_fatto(self):
        self.assertEqual(piattaforme_fatte("instagram: errore x\nfacebook: contenitore 1\n: pubblicato"), set())

    def test_file_dalla_cartella_drive(self):
        self.assertEqual(azione(self.ORA, piattaforme=("Instagram",), didascalia="x", cartella_drive=CARTELLA).azione, "pubblica")
        d = azione(self.ORA, piattaforme=("Instagram",), didascalia="x")
        self.assertEqual(d.azione, "problema")
        self.assertIn("cartella Drive", d.problemi["instagram"][0])

    def test_carosello_su_linkedin_si_vede_anche_senza_file(self):
        d = azione(self.ORA, formato="Carosello", piattaforme=("Instagram", "LinkedIn profilo"), didascalia="x", cartella_drive=CARTELLA)
        self.assertEqual(d.piattaforme, ["instagram"])
        self.assertIn("linkedin", d.problemi)

    def test_problemi_si_vedono_anche_in_attesa(self):
        d = azione(alle(6, 12), piattaforme=("Instagram",), media=REEL)
        self.assertEqual(d.azione, "attesa")
        self.assertIn("Didascalia", d.problemi["instagram"][0])

    def test_ordine(self):
        a = riga_t(pagina(data="2026-11-10", id="b"))
        b = riga_t(pagina(data="2026-11-09", id="a"))
        c = riga_t(pagina(data=None, id="c"))
        self.assertEqual([d.riga.id for d in pianifica([c, a, b], self.ORA)], ["a", "b", "c"])


class Validazione(unittest.TestCase):
    ORA = alle(9, 9, 5)

    def prob(self, p="Instagram", **kw):
        base = dict(piattaforme=(p,), didascalia="x", media=REEL)
        base.update(kw)
        return azione(self.ORA, **base).problemi.get(config.PIATTAFORME[p], [])

    def test_testo(self):
        self.assertEqual(self.prob(), [])
        self.assertTrue(self.prob(didascalia="  \n"))
        self.assertEqual(self.prob(didascalia="a" * 2200), [])
        self.assertTrue(self.prob(didascalia="a" * 2201))

    def test_linkedin_testo_proprio_o_didascalia(self):
        post = dict(formato="Post", media=("https://b/x.jpg",))
        self.assertEqual(self.prob("LinkedIn profilo", **post), [])
        self.assertEqual(self.prob("LinkedIn profilo", didascalia="", testo_linkedin="solo LI", **post), [])
        self.assertTrue(self.prob("LinkedIn profilo", didascalia="", **post))
        self.assertTrue(self.prob("LinkedIn profilo", testo_linkedin="a" * 3001, **post))

    def test_reel_post_carosello(self):
        self.assertTrue(self.prob(media=("https://b/c.jpg", "https://b/v.mp4")))
        self.assertEqual(self.prob(media=("https://b/V.MP4?x=.png",)), [])
        self.assertTrue(self.prob(formato="Post", media=("https://b/x.png",)))
        self.assertEqual(self.prob(formato="Carosello", media=SLIDE), [])
        self.assertTrue(self.prob(formato="Carosello", media=SLIDE[:1]))
        self.assertTrue(self.prob(formato="Carosello", media=tuple(f"https://b/{i}.jpg" for i in range(21))))
        mix = ("https://b/1.jpg", "https://b/2.jpg", "https://b/3.mp4")
        self.assertEqual(self.prob("Instagram", formato="Carosello", media=mix), [])
        self.assertTrue(self.prob("Facebook", formato="Carosello", media=mix))
        self.assertTrue(self.prob(formato="Storia"))
        self.assertTrue(self.prob("LinkedIn pagina"))

    def test_indirizzi_di_drive_si_riconoscono_dal_nome(self):
        # gli indirizzi pubblici di Drive non hanno l'estensione nel percorso: sta nel parametro «nome»
        from publisher.drive import link_pubblico
        reel = (link_pubblico("v1", "Video.mp4"), link_pubblico("c1", "copertina.jpg"))
        self.assertEqual(self.prob(media=reel), [])
        self.assertTrue(self.prob(media=(link_pubblico("c1", "copertina.jpg"), link_pubblico("v1", "x.mp4"))))
        self.assertEqual(self.prob(formato="Carosello", media=tuple(link_pubblico(f"s{i}", f"{i:02d}.jpg") for i in range(1, 7))), [])
        self.assertTrue(self.prob(formato="Post", media=(link_pubblico("p1", "x.png"),)))


class EsitoLeggibile(unittest.TestCase):
    def test_testo_per_le_persone(self):
        t = esito_leggibile("instagram: pubblicato https://i/p/1 2026-11-04T08:12+00:00\nfacebook: errore Meta 400: no\nlinkedin: contenitore 9")
        self.assertIn("Instagram: pubblicato il 04/11 alle 09:12 · https://i/p/1", t)
        self.assertIn("Facebook: non uscito, Meta 400: no", t)
        self.assertIn("LinkedIn profilo: in elaborazione", t)
        self.assertEqual(esito_leggibile(""), "")
        self.assertIn("Instagram: pubblicato · x", esito_leggibile("instagram: pubblicato x non-una-data"))


if __name__ == "__main__":
    unittest.main()

import io
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

import controlla
from publisher import drive, notion
from tests.helpers import CARTELLA, REEL, pagina, riga_t

ORA = datetime(2026, 11, 2, 7, 0, tzinfo=ZoneInfo("Europe/Rome"))


def msg(**kw):
    return controlla.messaggio(riga_t(pagina(**kw)), ORA, tok_fn=lambda: "GT")


class Messaggio(unittest.TestCase):
    def test_tutto_pronto_dice_quando_e_dove(self):
        self.assertEqual(msg(data="2026-11-04", piattaforme=("Instagram",), didascalia="x", media=REEL),
                         "Tutto pronto: esce il 04/11 alle 09:00 su Instagram.")

    def test_pubblica_subito(self):
        self.assertIn("prossimo giro", msg(stato="Pronto", pubblica_subito=True, didascalia="x", media=REEL))

    def test_non_affidate_al_sistema(self):
        for stato in ("Pronto", "Idea", "Pubblicato", "Da sistemare"):
            self.assertIsNone(msg(stato=stato, didascalia="x", media=REEL), stato)

    def test_problemi_in_parole_semplici(self):
        m = msg(data="2026-11-04", media=REEL)
        self.assertTrue(m.startswith("Da sistemare: "))
        self.assertIn("Didascalia", m)
        self.assertIn("piattaforma", msg(data="2026-11-04", piattaforme=(), didascalia="x", media=REEL))
        self.assertIn("48 ore", msg(data="2026-10-30", didascalia="x", media=REEL))

    def test_guarda_dentro_la_cartella_drive(self):
        with mock.patch.object(drive, "elenca", return_value=[{"id": "1", "name": "a.mp4"}, {"id": "2", "name": "b.mp4"}]):
            m = msg(data="2026-11-04", didascalia="x", cartella_drive=CARTELLA)
        self.assertIn("un solo video", m)
        with mock.patch.object(drive, "elenca", return_value=[{"id": "1", "name": "a.mp4"}]):
            self.assertTrue(msg(data="2026-11-04", didascalia="x", cartella_drive=CARTELLA).startswith("Tutto pronto"))
        with mock.patch.object(drive, "elenca", side_effect=drive.ErroreDrive("la cartella Drive non si trova o non è condivisa con il sistema")):
            self.assertIn("non è condivisa", msg(data="2026-11-04", didascalia="x", cartella_drive=CARTELLA))

    def test_messaggi_ripetuti_una_volta_sola(self):
        m = msg(data="2026-11-04", piattaforme=("Instagram", "Facebook"), didascalia="", media=REEL)
        self.assertEqual(m.count("manca il testo"), 1)


class Main(unittest.TestCase):
    def esegui(self, pagine, *argv):
        out = io.StringIO()
        with mock.patch.dict("os.environ", {"NOTION_TOKEN": "t", "NOTION_UTENTE_ID": "U"}), \
             mock.patch.object(notion, "pagine_attive", return_value=pagine), \
             mock.patch.object(notion, "testi_pagina", side_effect=lambda t, i: next(p["_testi"] for p in pagine if p["id"] == i)), \
             mock.patch.object(notion, "aggiorna") as agg, mock.patch.object(notion, "commenta") as com, redirect_stdout(out):
            codice = controlla.main(list(argv), ora=ORA, tok_fn=lambda: "GT")
        return codice, agg, com, out.getvalue()

    def test_scrive_solo_se_cambia_e_commenta_solo_i_problemi(self):
        ok = pagina(id="1", data="2026-11-04", didascalia="x", media=REEL)
        uguale = pagina(id="2", data="2026-11-04", didascalia="x", media=REEL, controllo="Tutto pronto: esce il 04/11 alle 09:00 su Instagram.")
        male = pagina(id="3", data="2026-11-04", media=REEL)
        mano = pagina(id="4", stato="Pronto", didascalia="x", media=REEL)
        codice, agg, com, _ = self.esegui([ok, uguale, male, mano])
        self.assertEqual(codice, 1)
        self.assertEqual(sorted(c.args[1] for c in agg.call_args_list), ["1", "3"])
        self.assertEqual([c.args[1] for c in com.call_args_list], ["3"])
        self.assertEqual(com.call_args.args[3], "U")

    def test_problema_gia_segnalato_non_ricommenta(self):
        male = pagina(id="3", data="2026-11-04", media=REEL)
        testo = controlla.messaggio(riga_t(male), ORA, tok_fn=lambda: "GT")
        male = pagina(id="3", data="2026-11-04", media=REEL, controllo=testo)
        codice, agg, com, _ = self.esegui([male])
        self.assertEqual(codice, 1)
        agg.assert_not_called()
        com.assert_not_called()

    def test_solo_elenco_non_tocca_niente(self):
        codice, agg, com, out = self.esegui([pagina(id="3", data="2026-11-04", media=REEL)], "--solo-elenco")
        agg.assert_not_called()
        com.assert_not_called()
        self.assertIn("Da sistemare", out)

    def test_tutto_in_ordine_esce_con_zero(self):
        codice, *_ = self.esegui([pagina(id="1", data="2026-11-04", didascalia="x", media=REEL)])
        self.assertEqual(codice, 0)


if __name__ == "__main__":
    unittest.main()

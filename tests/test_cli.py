import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import pubblica
from publisher import notion, run
from tests.helpers import REEL, SLIDE, pagina


def esegui(pagine, *args):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"results": pagine}, f)
    out = io.StringIO()
    with redirect_stdout(out):
        codice = pubblica.main(["--fixture", f.name, *args])
    return codice, out.getvalue()


class Cli(unittest.TestCase):
    ORA = "2026-11-09T09:20:00+01:00"

    def test_scenario_completo(self):
        pagine = [
            pagina(titolo="Esce adesso", piattaforme=("Instagram", "Facebook"), didascalia="x", media=REEL, id="1"),
            pagina(titolo="Programmato domani", data="2026-11-10", didascalia="x", media=REEL, id="2"),
            pagina(titolo="A mano", stato="Pronto", didascalia="x", media=REEL, id="3"),
            pagina(titolo="Senza testo", media=REEL, id="4"),
            pagina(titolo="Vecchio", data="2026-11-01", didascalia="x", media=REEL, id="5"),
            pagina(titolo="Subito", stato="Pronto", data="2026-12-01", pubblica_subito=True, didascalia="x", media=REEL, id="6"),
            pagina(titolo="Idea", stato="Idea", id="7"),
        ]
        codice, testo = esegui(pagine, "--ora", self.ORA)
        self.assertEqual(codice, 0)
        righe = {t: next((l for l in testo.splitlines() if t in l), "") for t in ("Esce adesso", "Programmato domani", "A mano", "Senza testo", "Vecchio", "Subito", "Idea")}
        self.assertIn("ESCE ORA", righe["Esce adesso"])
        self.assertIn("PROGRAMMATO", righe["Programmato domani"])
        self.assertIn("A MANO", righe["A mano"])
        self.assertIn("PROBLEMA", righe["Senza testo"])
        self.assertIn("Didascalia", righe["Senza testo"])
        self.assertIn("SCADUTO", righe["Vecchio"])
        self.assertIn("ESCE ORA", righe["Subito"])
        self.assertEqual(righe["Idea"], "")  # le righe non affidate al sistema non compaiono

    def test_rigorosa(self):
        self.assertEqual(esegui([pagina(didascalia="x", media=REEL)], "--ora", self.ORA, "--rigorosa")[0], 0)
        self.assertEqual(esegui([pagina(media=REEL)], "--ora", self.ORA, "--rigorosa")[0], 1)

    def test_tabella_vuota_e_senza_token(self):
        self.assertIn("0 righe", esegui([], "--ora", self.ORA)[1])
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(pubblica.main([]), 2)

    def test_esegui_con_fixture_e_vietato(self):
        self.assertEqual(pubblica.main(["--esegui", "--fixture", "x.json"]), 2)

    def test_esegui_senza_chiavi_meta_si_ferma_prima(self):
        with mock.patch.dict("os.environ", {"NOTION_TOKEN": "t"}, clear=True), \
             mock.patch.object(notion, "pagine_attive", return_value=[]), \
             mock.patch.object(run, "esegui") as e, redirect_stdout(io.StringIO()):
            self.assertEqual(pubblica.main(["--esegui"]), 2)
        e.assert_not_called()

    def test_errore_di_notion_esce_con_2(self):
        with mock.patch.dict("os.environ", {"NOTION_TOKEN": "t"}), \
             mock.patch.object(notion, "pagine_attive", side_effect=RuntimeError("Notion ha risposto 404")):
            self.assertEqual(pubblica.main([]), 2)

    def test_testi_letti_solo_per_le_righe_del_sistema(self):
        pagine = [pagina(id="1", didascalia="x", media=REEL), pagina(id="2", stato="Pronto", media=REEL), pagina(id="3", stato="Idea")]
        letti = []
        with mock.patch.dict("os.environ", {"NOTION_TOKEN": "t"}), \
             mock.patch.object(notion, "pagine_attive", return_value=pagine), \
             mock.patch.object(notion, "testi_pagina", side_effect=lambda t, i: letti.append(i) or {"didascalia": "x"}), \
             redirect_stdout(io.StringIO()):
            pubblica.main(["--ora", self.ORA])
        self.assertEqual(letti, ["1"])


if __name__ == "__main__":
    unittest.main()

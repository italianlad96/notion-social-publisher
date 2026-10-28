import unittest
from unittest import mock

from publisher import config, notion


def bl(tipo, testo=""):
    return {"type": tipo, tipo: {"rich_text": [{"plain_text": testo}] if testo else []}}


class Sezioni(unittest.TestCase):
    def test_didascalia_con_paragrafi_e_altre_sezioni(self):
        blocchi = [
            bl("paragraph", "prima di ogni titolo: si ignora"),
            bl("heading_2", "Slide, in ordine"), bl("image"),
            bl("heading_2", "Didascalia"), bl("paragraph", "Prima riga.\nStesso paragrafo."), bl("paragraph", ""),
            bl("paragraph", "Secondo paragrafo."),
            bl("heading_3", "Prima di pubblicare"), bl("bulleted_list_item", "uno"), bl("bulleted_list_item", "due"),
        ]
        s = notion.sezioni(blocchi)
        self.assertEqual(s["didascalia"], "Prima riga.\nStesso paragrafo.\n\nSecondo paragrafo.")
        self.assertEqual(s["prima di pubblicare"], "• uno\n• due")
        self.assertEqual(s["slide, in ordine"], "")
        self.assertNotIn("prima di ogni titolo", " ".join(s.values()))

    def test_titolo_con_maiuscole_spazi_e_livelli(self):
        for livello in ("heading_1", "heading_2", "heading_3"):
            s = notion.sezioni([bl(livello, "  DIDASCALIA "), bl("paragraph", "x")])
            self.assertEqual(s["didascalia"], "x", livello)

    def test_elenco_numerato_e_citazione_dopo_paragrafo(self):
        s = notion.sezioni([bl("heading_2", "Didascalia"), bl("paragraph", "a"), bl("numbered_list_item", "b"),
                            bl("numbered_list_item", "c"), bl("quote", "d")])
        self.assertEqual(s["didascalia"], "a\n\nb\nc\n\nd")

    def test_pagina_senza_sezioni(self):
        self.assertEqual(notion.sezioni([]), {})
        self.assertEqual(notion.sezioni([bl("paragraph", "solo testo")]), {})


class Chiamate(unittest.TestCase):
    def setUp(self):
        self.chiamate = []

        def finta(url, token, corpo, tentativi=4, metodo="POST"):
            self.chiamate.append((url, corpo, metodo))
            return self.risposte.pop(0) if getattr(self, "risposte", None) else {}

        p = mock.patch.object(notion, "_chiama", finta)
        p.start()
        self.addCleanup(p.stop)

    def test_commento_con_menzione(self):
        notion.commenta("t", "pag", "«Reel» è uscito.", "utente-1")
        url, corpo, metodo = self.chiamate[0]
        self.assertEqual((url, metodo), ("https://api.notion.com/v1/comments", "POST"))
        self.assertEqual(corpo["parent"], {"page_id": "pag"})
        self.assertEqual(corpo["rich_text"][0], {"type": "mention", "mention": {"type": "user", "user": {"id": "utente-1"}}})
        self.assertEqual(corpo["rich_text"][-1]["text"]["content"], "«Reel» è uscito.")

    def test_menzione_rifiutata_il_commento_parte_lo_stesso(self):
        chiamate = []

        def finta(url, token, corpo, tentativi=4, metodo="POST"):
            chiamate.append(corpo)
            if corpo["rich_text"][0]["type"] == "mention":
                raise RuntimeError('Notion ha risposto 404: {"message":"Could not find user with ID: u"}')
            return {}

        with mock.patch.object(notion, "_chiama", finta):
            notion.commenta("t", "pag", "ciao", "u")
        self.assertEqual([c["rich_text"][0]["type"] for c in chiamate], ["mention", "text"])

    def test_altri_errori_del_commento_non_si_nascondono(self):
        with mock.patch.object(notion, "_chiama", side_effect=RuntimeError("Notion ha risposto 403: restricted")):
            with self.assertRaises(RuntimeError):
                notion.commenta("t", "pag", "ciao", "u")

    def test_commento_senza_menzione(self):
        notion.commenta("t", "pag", "ciao")
        self.assertEqual([r["type"] for r in self.chiamate[0][1]["rich_text"]], ["text"])

    def test_testi_della_pagina_con_piu_pagine_di_blocchi(self):
        self.risposte = [
            {"results": [bl("heading_2", "Didascalia"), bl("paragraph", "uno")], "has_more": True, "next_cursor": "c2"},
            {"results": [bl("paragraph", "due"), bl("heading_2", "Testo LinkedIn"), bl("paragraph", "li")], "has_more": False},
        ]
        t = notion.testi_pagina("t", "pag")
        self.assertEqual(t, {"didascalia": "uno\n\ndue", "testo linkedin": "li"})
        self.assertEqual(self.chiamate[0][2], "GET")
        self.assertIsNone(self.chiamate[0][1])
        self.assertIn("start_cursor=c2", self.chiamate[1][0])

    def test_pagine_attive_tre_stati_e_paginazione(self):
        self.risposte = [{"results": [{"id": "a"}], "has_more": True, "next_cursor": "x"}, {"results": [{"id": "b"}], "has_more": False}]
        pagine = notion.pagine_attive("t")
        self.assertEqual([p["id"] for p in pagine], ["a", "b"])
        filtro = self.chiamate[0][1]["filter"]["or"]
        self.assertEqual({f["status"]["equals"] for f in filtro}, {config.PRONTO, config.PROGRAMMATO, config.DA_SISTEMARE})
        self.assertEqual(self.chiamate[1][1]["start_cursor"], "x")

    def test_scrivi_esito_scrive_tecnici_e_leggibile(self):
        notion.scrivi_esito("t", "pag", "instagram: pubblicato https://i/p 2026-11-04T08:12+00:00")
        url, corpo, metodo = self.chiamate[0]
        self.assertEqual(metodo, "PATCH")
        self.assertTrue(url.endswith("/pages/pag"))
        props = corpo["properties"]
        self.assertIn("instagram: pubblicato", props["Dati tecnici"]["rich_text"][0]["text"]["content"])
        self.assertIn("Instagram: pubblicato il 04/11", props["Esito"]["rich_text"][0]["text"]["content"])

    def test_testo_vuoto_svuota_il_campo(self):
        self.assertEqual(notion.p_testo(""), {"rich_text": []})


if __name__ == "__main__":
    unittest.main()

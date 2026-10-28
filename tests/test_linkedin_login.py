import stat
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import linkedin_login as ll


class Autorizzazione(unittest.TestCase):
    def test_indirizzo_con_i_parametri_giusti(self):
        url = ll.url_autorizzazione("CID", "ST")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(q["client_id"], ["CID"])
        self.assertEqual(q["state"], ["ST"])
        self.assertEqual(q["redirect_uri"], ["http://localhost:8765/callback"])
        self.assertEqual(q["scope"], ["openid profile w_member_social"])
        self.assertEqual(q["response_type"], ["code"])

    def test_codice_ok(self):
        self.assertEqual(ll.estrai_codice("code=ABC&state=ST", "ST"), "ABC")

    def test_stato_diverso_si_rifiuta(self):
        with self.assertRaisesRegex(RuntimeError, "stato"):
            ll.estrai_codice("code=ABC&state=ALTRO", "ST")
        with self.assertRaisesRegex(RuntimeError, "stato"):
            ll.estrai_codice("code=ABC", "ST")

    def test_rifiuto_dell_utente(self):
        with self.assertRaisesRegex(RuntimeError, "user_cancelled"):
            ll.estrai_codice("error=user_cancelled_authorize&error_description=annullato&state=ST", "ST")

    def test_senza_codice(self):
        with self.assertRaisesRegex(RuntimeError, "codice"):
            ll.estrai_codice("state=ST", "ST")


class Attesa(unittest.TestCase):
    def lancia(self, stato, timeout, richieste):
        import threading, time, urllib.request, urllib.error
        esito = {}

        def server():
            try:
                esito["codice"] = ll.aspetta_codice(stato, timeout)
            except RuntimeError as e:
                esito["errore"] = str(e)

        t = threading.Thread(target=server)
        t.start()
        time.sleep(0.5)
        for path in richieste:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{ll.PORTA}{path}", timeout=5).read()
            except urllib.error.HTTPError:
                pass
        t.join(timeout + 5)
        return esito

    def test_una_richiesta_estranea_prima_non_interrompe_l_attesa(self):
        esito = self.lancia("ST", 10, ["/favicon.ico", "/callback?code=XYZ&state=ST"])
        self.assertEqual(esito, {"codice": "XYZ"})

    def test_stato_sbagliato_e_un_errore(self):
        esito = self.lancia("ST", 10, ["/callback?code=XYZ&state=ALTRO"])
        self.assertIn("stato", esito["errore"])

    def test_scaduto_il_tempo_senza_risposta(self):
        esito = self.lancia("ST", 3, [])
        self.assertIn("nessuna risposta", esito["errore"])


class Env(unittest.TestCase):
    def test_aggiorna_aggiunge_e_non_tocca_il_resto(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / ".env"
            p.write_text("A=1\nLINKEDIN_ACCESS_TOKEN=vecchio\nB=2\n")
            ll.salva_env(p, {"LINKEDIN_ACCESS_TOKEN": "nuovo", "LINKEDIN_PERSON_URN": "urn:li:person:x"})
            righe = p.read_text().splitlines()
            self.assertEqual(righe, ["A=1", "B=2", "LINKEDIN_ACCESS_TOKEN=nuovo", "LINKEDIN_PERSON_URN=urn:li:person:x"])
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_file_che_non_esiste(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / ".env"
            ll.salva_env(p, {"X": "1"})
            self.assertEqual(p.read_text(), "X=1\n")


if __name__ == "__main__":
    unittest.main()

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from unittest import mock

import avvisi
import segreti
from publisher import meta

OGGI = date(2026, 12, 1)


def ts(d):
    return int(datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp())


class Scadenze(unittest.TestCase):
    def test_linkedin_lontano_nessun_avviso(self):
        self.assertEqual(avvisi.valuta_scadenze(OGGI, "2026-12-25"), [])  # 24 giorni

    def test_linkedin_soglia_esatta(self):
        self.assertEqual(avvisi.valuta_scadenze(OGGI, "2026-12-16"), [])  # 15 giorni: ancora presto
        r = avvisi.valuta_scadenze(OGGI, "2026-12-15")  # 14 giorni: avvisa
        self.assertEqual(len(r), 1)
        self.assertIn("14 giorni", r[0])
        self.assertIn("linkedin_login.py", r[0])

    def test_linkedin_ultimo_giorno_e_scaduto(self):
        self.assertIn("0 giorni", avvisi.valuta_scadenze(OGGI, "2026-12-01")[0])
        self.assertIn("scaduto il 30/11/2026", avvisi.valuta_scadenze(OGGI, "2026-11-30")[0])

    def test_linkedin_non_usato_o_data_sbagliata(self):
        self.assertEqual(avvisi.valuta_scadenze(OGGI, ""), [])
        self.assertIn("AAAA-MM-GG", avvisi.valuta_scadenze(OGGI, "25/12/2026")[0])

    def test_meta_valido_senza_scadenza(self):
        self.assertEqual(avvisi.valuta_scadenze(OGGI, "", {"is_valid": True, "expires_at": 0, "data_access_expires_at": ts(date(2027, 1, 24))}), [])

    def test_meta_accesso_ai_dati_in_scadenza(self):
        r = avvisi.valuta_scadenze(OGGI, "", {"is_valid": True, "expires_at": 0, "data_access_expires_at": ts(date(2026, 12, 10))})
        self.assertEqual(len(r), 1)
        self.assertIn("accesso ai dati", r[0].lower())
        self.assertIn("9 giorni", r[0])

    def test_meta_token_non_valido(self):
        r = avvisi.valuta_scadenze(OGGI, "", {"is_valid": False})
        self.assertIn("non è più valido", r[0])

    def test_meta_token_con_scadenza_vicina(self):
        r = avvisi.valuta_scadenze(OGGI, "", {"is_valid": True, "expires_at": ts(date(2026, 12, 5)), "data_access_expires_at": 0})
        self.assertIn("Il token di Meta scade", r[0])

    def test_meta_non_controllato_non_inventa_problemi(self):
        self.assertEqual(avvisi.valuta_scadenze(OGGI, "2026-12-25", None), [])

    def test_piu_problemi_insieme(self):
        r = avvisi.valuta_scadenze(OGGI, "2026-12-02", {"is_valid": False})
        self.assertEqual(len(r), 2)


class Main(unittest.TestCase):
    def esegui(self, env, risposta=None, errore=None):
        out = io.StringIO()
        with mock.patch.dict("os.environ", env, clear=True), redirect_stdout(out):
            with mock.patch.object(avvisi, "dati_meta", side_effect=errore, return_value=risposta):
                codice = avvisi.main(OGGI)
        return codice, out.getvalue()

    CHIAVI = {"META_APP_ID": "1", "META_APP_SECRET": "s", "META_PAGE_TOKEN": "t"}

    def test_tutto_in_ordine(self):
        codice, testo = self.esegui({**self.CHIAVI, "LINKEDIN_TOKEN_SCADE": "2026-12-25"}, {"is_valid": True, "expires_at": 0})
        self.assertEqual(codice, 0)
        self.assertIn("Tutto in ordine", testo)

    def test_problema_esce_con_1(self):
        codice, testo = self.esegui({**self.CHIAVI, "LINKEDIN_TOKEN_SCADE": "2026-12-05"}, {"is_valid": True})
        self.assertEqual(codice, 1)
        self.assertIn("Da sistemare", testo)

    def test_meta_non_raggiungibile_e_un_problema(self):
        codice, testo = self.esegui({**self.CHIAVI}, errore=meta.ErroreMeta("Meta 500", None, 500))
        self.assertEqual(codice, 1)
        self.assertIn("Non riesco a controllare", testo)

    def test_chiavi_mancanti_sono_un_problema(self):
        codice, testo = self.esegui({})
        self.assertEqual(codice, 1)
        self.assertIn("Mancano", testo)


class Segreti(unittest.TestCase):
    def test_i_valori_passano_da_stdin_e_mai_negli_argomenti(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as t:
            env = pathlib.Path(t) / ".env"
            env.write_text('NOTION_TOKEN=segreto1\nMETA_PAGE_ID="123"\nALTRO=non_va\n# commento=x\n')
            chiamate = []

            def finta(cmd, input=None, capture_output=False):
                chiamate.append((cmd, input))
                return mock.Mock(returncode=0, stderr=b"")

            out = io.StringIO()
            with redirect_stdout(out):
                codice = segreti.main(["--repo", "u/r", "--env", str(env)], esegui=finta)
        self.assertEqual(codice, 0)
        nomi = [c[0][3] for c in chiamate]
        self.assertEqual(nomi, ["NOTION_TOKEN", "META_PAGE_ID"])
        self.assertEqual([c[1] for c in chiamate], [b"segreto1", b"123"])
        self.assertNotIn("segreto1", " ".join(" ".join(c[0]) for c in chiamate))
        self.assertNotIn("segreto1", out.getvalue())
        self.assertNotIn("ALTRO", nomi)
        self.assertIn("Non presenti", out.getvalue())

    def test_elenco_non_imposta_niente(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as t:
            env = pathlib.Path(t) / ".env"
            env.write_text("NOTION_TOKEN=x\n")
            finta = mock.Mock()
            with redirect_stdout(io.StringIO()):
                segreti.main(["--repo", "u/r", "--elenco", "--env", str(env)], esegui=finta)
        finta.assert_not_called()

    def test_errore_di_gh_ferma_e_non_mostra_il_valore(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as t:
            env = pathlib.Path(t) / ".env"
            env.write_text("NOTION_TOKEN=segretissimo\n")
            finta = mock.Mock(return_value=mock.Mock(returncode=1, stderr=b"HTTP 403"))
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(segreti.main(["--repo", "u/r", "--env", str(env)], esegui=finta), 1)
        self.assertNotIn("segretissimo", out.getvalue())
        self.assertIn("ERRORE", out.getvalue())


if __name__ == "__main__":
    unittest.main()

import unittest
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from publisher import drive, linkedin, meta, notion, run
from publisher.meta import ErroreMeta, Risultato
from publisher.plan import pianifica
from tests.helpers import CARTELLA, REEL, SLIDE, pagina, riga_t

ORA = datetime(2026, 11, 9, 9, 20, tzinfo=ZoneInfo("Europe/Rome"))
LINK_IG, LINK_FB = "https://instagram.com/p/abc", "https://facebook.com/post1"
ID = "aaaaaaaa-0000-0000-0000-000000000001"


def decisioni(**kw):
    base = dict(data="2026-11-09", piattaforme=("Instagram", "Facebook"), didascalia="Testo", media=REEL, id=ID, titolo="Reel prova")
    base.update(kw)
    return pianifica([riga_t(pagina(**base))], ORA)


def contesto(**kw):
    return run.Contesto(notion_token="NT", page_token="PT", page_id="PG", ig_id="IG", utente_id="U", **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.p = {
            "ig": mock.patch.object(meta, "instagram", return_value=Risultato("pubblicato", LINK_IG)),
            "fb": mock.patch.object(meta, "facebook", return_value=Risultato("pubblicato", LINK_FB)),
            "li": mock.patch.object(linkedin, "pubblica", return_value=Risultato("pubblicato", "https://linkedin.com/x")),
            "esito": mock.patch.object(notion, "scrivi_esito"),
            "aggiorna": mock.patch.object(notion, "aggiorna"),
            "commenta": mock.patch.object(notion, "commenta"),
            "media": mock.patch.object(notion, "scrivi_media"),
            "canc": mock.patch.object(drive, "rendi_privati"),
            "carica": mock.patch.object(drive, "rendi_pubblico", side_effect=lambda tok, fid, nome: drive.link_pubblico(fid, nome)),
            "token": mock.patch.object(drive, "token", return_value="GT"),
            "elenca": mock.patch.object(drive, "elenca", return_value=[{"id": "v", "name": "reel.mp4"}, {"id": "c", "name": "copertina.jpg"}]),
        }
        self.m = {k: v.start() for k, v in self.p.items()}
        self.addCleanup(mock.patch.stopall)
        self.out = []

    def vai(self, d, ctx=None):
        return run.esegui(d, ctx or contesto(), self.out.append)

    def props(self, n=-1):
        return self.m["aggiorna"].call_args_list[n].args[2]

    def stato_scritto(self):
        return [c.args[2]["Stato"]["status"]["name"] for c in self.m["aggiorna"].call_args_list if "Stato" in c.args[2]]


class Pubblicazione(Base):
    def test_tutto_bene_chiude_la_riga_e_commenta(self):
        self.assertEqual(self.vai(decisioni()), 0)
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])
        p = self.props()
        self.assertEqual(p["Link al post"], {"url": LINK_IG})
        self.assertEqual(p["Pubblica subito"], {"checkbox": False})
        self.assertEqual(p["Media"], {"rich_text": []})
        esito = p["Esito"]["rich_text"][0]["text"]["content"]
        self.assertIn("Instagram: pubblicato il", esito)
        self.assertIn("Facebook: pubblicato il", esito)
        self.m["canc"].assert_called_once_with("GT", list(REEL))
        (_, pag, testo, utente), _ = self.m["commenta"].call_args
        self.assertEqual((pag, utente), (ID, "U"))
        self.assertIn("è uscito", testo)
        self.assertIn(LINK_IG, testo)

    def test_una_piattaforma_fallisce_va_da_sistemare(self):
        self.m["fb"].side_effect = ErroreMeta("Meta 400/200: permesso negato", 200, 400)
        self.assertEqual(self.vai(decisioni()), 1)
        self.assertEqual(self.stato_scritto(), ["Da sistemare"])
        p = self.props()
        tecnici = p["Dati tecnici"]["rich_text"][0]["text"]["content"]
        self.assertIn(f"instagram: pubblicato {LINK_IG}", tecnici)
        self.assertIn("facebook: errore Meta 400/200", tecnici)
        self.assertIn("Facebook: non uscito", p["Esito"]["rich_text"][0]["text"]["content"])
        self.assertIn("Da sistemare: non uscito su Facebook", p["Controllo"]["rich_text"][0]["text"]["content"])
        testo = self.m["commenta"].call_args.args[2]
        self.assertIn("non è uscito", testo)
        self.assertIn("«Programmato»", testo)

    def test_rimesso_programmato_si_ritenta_solo_la_piattaforma_mancante(self):
        d = decisioni(esito=f"instagram: pubblicato {LINK_IG} 2026-11-09T08:05+00:00\nfacebook: errore boh")
        self.assertEqual(self.vai(d), 0)
        self.m["ig"].assert_not_called()
        self.m["fb"].assert_called_once()
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])

    def test_elaborazione_in_corso_non_cambia_lo_stato(self):
        self.m["ig"].return_value = Risultato("in_corso", "c55")
        self.assertEqual(self.vai(decisioni(piattaforme=("Instagram",))), 0)
        self.assertEqual(self.stato_scritto(), [])
        self.assertEqual(self.m["esito"].call_args.args[2], "instagram: contenitore c55")
        self.assertIn("in elaborazione", self.props()["Esito"]["rich_text"][0]["text"]["content"])

    def test_contenitore_passato_e_salvato_subito(self):
        def finta(ig_id, token, riga, salva, contenitore_noto=None, prova=False):
            self.noto = contenitore_noto
            salva("contenitore c9")
            raise ErroreMeta("Meta 500: boh", None, 500)

        self.m["ig"].side_effect = finta
        self.vai(decisioni(piattaforme=("Instagram",), esito="instagram: contenitore c8"))
        self.assertEqual(self.noto, "c8")
        self.assertEqual(self.m["esito"].call_args_list[0].args[2], "instagram: contenitore c9")

    def test_pubblica_subito_esce_prima_della_data(self):
        d = pianifica([riga_t(pagina(data="2026-11-20", stato="Pronto", pubblica_subito=True, didascalia="x", media=REEL, id=ID))], ORA)
        self.assertEqual(self.vai(d), 0)
        self.m["ig"].assert_called_once()
        self.assertEqual(self.props()["Pubblica subito"], {"checkbox": False})

    def test_gia_uscito_ovunque_si_chiude_senza_pubblicare(self):
        d = decisioni(esito=f"instagram: pubblicato {LINK_IG}\nfacebook: pubblicato {LINK_FB}")
        self.assertEqual(self.vai(d), 0)
        self.m["ig"].assert_not_called()
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])

    def test_drive_rifiuta_di_rimettere_privati_i_file_la_riga_si_chiude_lo_stesso(self):
        # 28/10/2026: dal server di GitHub l'archivio dei file (allora Vercel) ha risposto 403 e la riga era rimasta «Programmato»
        self.m["canc"].side_effect = drive.ErroreDrive("Google Drive 403: non riesco a rimettere privato il file v")
        self.assertEqual(self.vai(decisioni()), 0)
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])
        self.assertNotIn("Media", self.props())
        self.assertTrue(any("ancora pubblici su Drive, restano in Media" in r for r in self.out))
        self.m["commenta"].assert_called_once()

    def test_pronto_senza_spunta_non_si_tocca(self):
        self.vai(decisioni(stato="Pronto"))
        self.m["ig"].assert_not_called()
        self.m["aggiorna"].assert_not_called()

    def test_solo_la_pagina_richiesta(self):
        a = decisioni(id=ID)[0]
        b = decisioni(id="bbbbbbbb-0000-0000-0000-000000000002")[0]
        self.vai([a, b], contesto(solo_id="bbbbbbbb000000000000000000000002"))
        self.assertEqual(self.m["ig"].call_args.args[2].id, "bbbbbbbb-0000-0000-0000-000000000002")


class Problemi(Base):
    def test_scaduto_va_da_sistemare_con_commento(self):
        d = pianifica([riga_t(pagina(data="2026-11-01", didascalia="x", media=REEL, id=ID))], ORA)
        self.assertEqual(self.vai(d), 1)
        self.assertEqual(self.stato_scritto(), ["Da sistemare"])
        self.assertIn("48 ore", self.m["commenta"].call_args.args[2])
        self.m["ig"].assert_not_called()

    def test_senza_piattaforme_o_testo_va_da_sistemare(self):
        for kw in (dict(piattaforme=()), dict(didascalia="")):
            self.m["aggiorna"].reset_mock()
            self.vai(decisioni(**kw))
            self.assertEqual(self.stato_scritto(), ["Da sistemare"], kw)
        self.m["ig"].assert_not_called()

    def test_carosello_scelto_anche_per_linkedin_non_resta_a_ritentare(self):
        d = decisioni(formato="Carosello", media=SLIDE, piattaforme=("Instagram", "LinkedIn profilo"))
        self.assertEqual(self.vai(d, contesto(linkedin_token="LT", persona_urn="u")), 1)
        self.m["ig"].assert_called_once()
        self.m["li"].assert_not_called()
        self.assertEqual(self.stato_scritto(), ["Da sistemare"])
        self.assertIn("LinkedIn", self.m["commenta"].call_args.args[2])

    def test_token_linkedin_scaduto(self):
        ctx = contesto(linkedin_token="LT", persona_urn="u", linkedin_scade="2026-12-25", oggi=date(2026, 12, 26))
        d = decisioni(formato="Post", media=("https://b/x.jpg",), piattaforme=("LinkedIn profilo",))
        self.assertEqual(self.vai(d, ctx), 1)
        self.m["li"].assert_not_called()
        self.assertIn("scaduto il 2026-12-25", self.props()["Dati tecnici"]["rich_text"][0]["text"]["content"])

    def test_errore_inatteso_e_un_errore_non_un_crash(self):
        self.m["ig"].side_effect = KeyError("id")
        self.assertEqual(self.vai(decisioni(piattaforme=("Instagram",))), 1)
        self.assertEqual(self.stato_scritto(), ["Da sistemare"])

    def test_commento_che_non_parte_non_ferma_niente(self):
        self.m["commenta"].side_effect = RuntimeError("Notion 403: niente permesso di commentare")
        self.assertEqual(self.vai(decisioni()), 0)
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])
        self.assertIn("commento non lasciato", "\n".join(self.out))

    def test_esito_non_scritto_dopo_la_pubblicazione_lo_dice_e_chiude_comunque(self):
        self.m["esito"].side_effect = RuntimeError("Notion 500")
        self.assertEqual(self.vai(decisioni(piattaforme=("Instagram",))), 1)
        self.assertIn("pubblicato ma l'esito NON è stato scritto", "\n".join(self.out))
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])


class FileDaDrive(Base):
    def test_rende_pubblici_i_file_li_usa_e_li_rimette_privati(self):
        d = decisioni(media=(), cartella_drive=CARTELLA, piattaforme=("Instagram",))
        self.assertEqual(self.vai(d), 0)
        self.m["elenca"].assert_called_once_with("GT", "1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543")
        self.assertEqual([c.args[1:] for c in self.m["carica"].call_args_list], [("v", "reel.mp4"), ("c", "copertina.jpg")])
        urls = self.m["media"].call_args.args[2]
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(u.startswith("https://drive.usercontent.google.com/download?") for u in urls))
        self.assertEqual(self.m["ig"].call_args.args[2].media, urls)  # Instagram riceve gli indirizzi appena resi pubblici
        self.assertEqual(self.stato_scritto(), ["Pubblicato"])
        self.m["canc"].assert_called_once_with("GT", urls)  # alla chiusura tornano privati

    def test_immagine_png_nella_cartella_va_da_sistemare(self):
        self.m["elenca"].return_value = [{"id": "v", "name": "reel.mp4"}, {"id": "c", "name": "copertina.png"}]
        self.assertEqual(self.vai(decisioni(media=(), cartella_drive=CARTELLA, piattaforme=("Instagram",))), 1)
        self.m["ig"].assert_not_called()
        self.m["carica"].assert_not_called()
        self.assertIn("salva in JPG: copertina.png", self.props()["Controllo"]["rich_text"][0]["text"]["content"])

    def test_account_non_editor_va_da_sistemare_con_il_motivo(self):
        self.m["carica"].side_effect = drive.ErroreDrive("il sistema non può rendere pubblico reel.mp4: sulla cartella Drive l'account di servizio deve essere Editor, non Visualizzatore")
        self.assertEqual(self.vai(decisioni(media=(), cartella_drive=CARTELLA, piattaforme=("Instagram",))), 1)
        self.m["ig"].assert_not_called()
        self.assertIn("deve essere Editor", self.m["commenta"].call_args.args[2])

    def test_cartella_sbagliata_va_da_sistemare_senza_pubblicare(self):
        self.m["elenca"].return_value = [{"id": "1", "name": "a.mp4"}, {"id": "2", "name": "b.mp4"}]
        self.assertEqual(self.vai(decisioni(media=(), cartella_drive=CARTELLA)), 1)
        self.m["ig"].assert_not_called()
        self.m["carica"].assert_not_called()
        self.assertIn("un solo video", self.props()["Controllo"]["rich_text"][0]["text"]["content"])

    def test_drive_non_raggiungibile(self):
        self.m["elenca"].side_effect = drive.ErroreDrive("la cartella Drive non si trova o non è condivisa con il sistema")
        self.assertEqual(self.vai(decisioni(media=(), cartella_drive=CARTELLA)), 1)
        self.assertIn("non è condivisa", self.m["commenta"].call_args.args[2])

    def test_permesso_a_meta_rimette_privato_il_primo(self):
        uno = drive.link_pubblico("v", "reel.mp4")
        self.m["carica"].side_effect = [uno, drive.ErroreDrive("Google Drive 500: x")]
        self.vai(decisioni(media=(), cartella_drive=CARTELLA))
        self.m["canc"].assert_any_call("GT", [uno])
        self.m["ig"].assert_not_called()

    def test_da_sistemare_con_cartella_toglie_i_file_per_riprenderli_freschi(self):
        self.m["ig"].side_effect = ErroreMeta("Meta 400: no", None, 400)
        self.vai(decisioni(media=REEL, cartella_drive=CARTELLA, piattaforme=("Instagram",)))
        self.m["canc"].assert_called_once_with("GT", list(REEL))
        self.assertEqual(self.props()["Media"], {"rich_text": []})

    def test_da_sistemare_senza_cartella_tiene_i_file(self):
        self.m["ig"].side_effect = ErroreMeta("Meta 400: no", None, 400)
        self.vai(decisioni(media=REEL, piattaforme=("Instagram",)))
        self.m["canc"].assert_not_called()
        self.assertNotIn("Media", self.props())


class Prova(Base):
    def test_prova_non_scrive_niente_e_pulisce_i_file_presi_da_drive(self):
        self.m["ig"].return_value = Risultato("prova_ok", "c1")
        d = decisioni(media=(), cartella_drive=CARTELLA, piattaforme=("Instagram",))
        self.assertEqual(self.vai(d, contesto(prova=True)), 0)
        for nome in ("esito", "aggiorna", "commenta", "media"):
            self.m[nome].assert_not_called()
        self.m["canc"].assert_called_once()
        self.assertTrue(self.m["ig"].call_args.kwargs["prova"])

    def test_prova_con_errori_non_scrive_niente(self):
        self.m["ig"].side_effect = ErroreMeta("Meta 500", None, 500)
        self.vai(decisioni(), contesto(prova=True))
        self.vai(pianifica([riga_t(pagina(data="2026-11-01", didascalia="x", media=REEL, id=ID))], ORA), contesto(prova=True))
        for nome in ("esito", "aggiorna", "commenta"):
            self.m[nome].assert_not_called()


if __name__ == "__main__":
    unittest.main()

import shutil
import tempfile
import unittest
from pathlib import Path

from publisher.media import scegli, spezza_testo


def f(*nomi):
    return [{"id": n, "name": n, "mimeType": "x"} for n in nomi]


def nomi(lista):
    return [x["name"] for x in lista]


class Scegli(unittest.TestCase):
    def test_reel_video_e_copertina(self):
        scelti, guai = scegli("Reel", f("Copertina.jpg", "reel.mp4"))
        self.assertEqual((nomi(scelti), guai), (["reel.mp4", "Copertina.jpg"], []))
        self.assertEqual(nomi(scegli("Reel", f("reel.mov"))[0]), ["reel.mov"])

    def test_reel_sbagliati(self):
        for cartella, parola in ((f("a.mp4", "b.mp4"), "un solo video"), (f("a.jpg"), "un solo video"),
                                 (f("v.mp4", "copertina1.jpg", "copertina2.jpg"), "copertina"),
                                 (f("v.mp4", "foto.jpg"), "foto.jpg")):
            scelti, guai = scegli("Reel", cartella)
            self.assertEqual(scelti, [])
            self.assertTrue(any(parola in g for g in guai), guai)

    def test_carosello_in_ordine_con_video_e_limiti(self):
        scelti, guai = scegli("Carosello", f("01.jpg", "02.JPG", "03.mp4", "04.jpeg"))
        self.assertEqual((nomi(scelti), guai), (["01.jpg", "02.JPG", "03.mp4", "04.jpeg"], []))
        self.assertTrue(scegli("Carosello", f("01.jpg"))[1])
        self.assertTrue(scegli("Carosello", f(*[f"{i:02d}.jpg" for i in range(21)]))[1])
        self.assertEqual(scegli("Carosello", f(*[f"{i:02d}.jpg" for i in range(20)]))[1], [])

    def test_file_non_usabili_e_cartella_vuota(self):
        scelti, guai = scegli("Carosello", f("01.jpg", "02.jpg", "note.pdf", "foto.heic"))
        self.assertEqual(scelti, [])
        self.assertIn("note.pdf", guai[0])
        self.assertIn("vuota", scegli("Carosello", [])[1][0])

    def test_post_e_formati_non_automatici(self):
        self.assertEqual(nomi(scegli("Post", f("x.jpg"))[0]), ["x.jpg"])
        self.assertTrue(scegli("Post", f("x.jpg", "y.jpg"))[1])
        self.assertTrue(scegli("Post", f("x.jpg", "v.mp4"))[1])
        self.assertTrue(scegli("Storia", f("x.jpg"))[1])
        self.assertTrue(scegli("", f("x.jpg"))[1])

    def test_png_e_webp_si_segnalano_con_il_nome(self):
        # il sistema non converte più le immagini (28/10/2026): prende i file da Drive come sono
        scelti, guai = scegli("Carosello", f("01.png", "02.jpg", "03.jpg", "04.webp"))
        self.assertEqual(scelti, [])
        self.assertEqual(len(guai), 1)
        self.assertIn("salva in JPG: 01.png, 04.webp", guai[0])
        self.assertEqual(scegli("Post", f("x.png"))[0], [])


class Testo(unittest.TestCase):
    def test_spezza(self):
        righe = [f"https://x/{i:02d}-{'a' * 150}.jpg" for i in range(20)]
        pezzi = spezza_testo("\n".join(righe), 1900)
        self.assertTrue(len(pezzi) > 1 and all(len(p) <= 1900 for p in pezzi))
        self.assertEqual("".join(pezzi), "\n".join(righe))
        self.assertEqual(spezza_testo(""), [])
        self.assertEqual(spezza_testo("a" * 3000, 1900), ["a" * 3000])


if __name__ == "__main__":
    unittest.main()

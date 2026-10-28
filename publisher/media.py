"""I file di un post: quali prendere dalla cartella Drive e in che ordine.

Regole della cartella (una per post), pensate per chi non conosce il sistema:
- Reel: un solo video; se c'è un'immagine che si chiama «copertina…», diventa la copertina.
- Carosello: tutte le immagini e i video, in ordine di nome (01, 02, 03…), da 2 a 20.
- Post: una sola immagine.
I file che iniziano con «_» o «.» si ignorano (bozze, note). Le immagini devono essere JPG: Instagram non accetta
PNG e WebP, e il sistema non le converte (prende i file da Drive così come sono)."""
from __future__ import annotations

import posixpath
from typing import List, Tuple

IMMAGINI = {".jpg", ".jpeg"}
DA_CONVERTIRE = {".png", ".webp"}
VIDEO = {".mp4", ".mov"}


def _est(nome: str) -> str:
    return posixpath.splitext(nome.lower())[1]


def scegli(formato: str, file: List[dict]) -> Tuple[List[dict], List[str]]:
    """Dai file della cartella (già in ordine di nome) a quelli da pubblicare, in ordine. Restituisce (file, problemi)."""
    immagini = [f for f in file if _est(f["name"]) in IMMAGINI]
    video = [f for f in file if _est(f["name"]) in VIDEO]
    da_convertire = [f["name"] for f in file if _est(f["name"]) in DA_CONVERTIRE]
    altri = [f["name"] for f in file if f not in immagini and f not in video and f["name"] not in da_convertire]
    problemi: List[str] = []
    if da_convertire:
        problemi.append(f"le immagini devono essere JPG, salva in JPG: {', '.join(da_convertire)}")
    if altri:
        problemi.append(f"file che il sistema non sa usare: {', '.join(altri)} (servono JPG, MP4 o MOV)")
    if not file:
        return [], ["la cartella Drive è vuota"]
    if formato == "Reel":
        copertine = [f for f in immagini if f["name"].lower().startswith("copertina")]
        if len(video) != 1:
            problemi.append(f"per un Reel serve un solo video nella cartella, ce ne sono {len(video)}")
        if len(copertine) > 1:
            problemi.append("ci sono più immagini «copertina»: tienine una")
        estranee = [f["name"] for f in immagini if f not in copertine]
        if estranee:
            problemi.append(f"in un Reel le immagini diverse dalla copertina non si usano: {', '.join(estranee)}")
        return (video[:1] + copertine[:1]) if not problemi else [], problemi
    if formato == "Post":
        if len(immagini) != 1 or video:
            problemi.append("per un Post serve una sola immagine nella cartella")
        return immagini[:1] if not problemi else [], problemi
    if formato == "Carosello":
        scelti = [f for f in file if f in immagini or f in video]
        if not 2 <= len(scelti) <= 20:
            problemi.append(f"un carosello vuole da 2 a 20 file, nella cartella ce ne sono {len(scelti)}")
        return scelti if not problemi else [], problemi
    return [], [f"il formato «{formato or 'vuoto'}» non si pubblica in automatico"]


def spezza_testo(testo: str, massimo: int = 1900) -> List[str]:
    """Divide un testo in pezzi da massimo `massimo` caratteri, solo a capo di riga (Notion: 2000 per pezzo)."""
    pezzi, corrente = [], ""
    for riga in testo.splitlines(keepends=True):
        if corrente and len(corrente) + len(riga) > massimo:
            pezzi.append(corrente)
            corrente = ""
        corrente += riga
    if corrente:
        pezzi.append(corrente)
    return pezzi

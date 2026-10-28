"""Costruisce pagine nella forma che restituisce l'API di Notion, per provare il codice senza rete."""
from dataclasses import replace

from publisher.model import riga_da_pagina


def _rt(testo):
    return {"type": "rich_text", "rich_text": [{"type": "text", "plain_text": testo, "text": {"content": testo}}] if testo else []}


def pagina(titolo="Reel prova", formato="Reel", stato="Programmato", data="2026-11-09", piattaforme=("Instagram",),
           didascalia="", testo_linkedin="", media=(), esito="", time_zone=None, id="p1", sorgenti="",
           pubblica_subito=False, cartella_drive="", controllo=""):
    props = {
        "Contenuto": {"type": "title", "title": [{"plain_text": titolo}]},
        "Formato": {"type": "select", "select": {"name": formato} if formato else None},
        "Stato": {"type": "status", "status": {"name": stato} if stato else None},
        "Data di pubblicazione": {"type": "date", "date": {"start": data, "end": None, "time_zone": time_zone} if data else None},
        "Piattaforme": {"type": "multi_select", "multi_select": [{"name": n} for n in piattaforme]},
        "Media": _rt("\n".join(media)),
        "Dati tecnici": _rt(esito),
        "Sorgenti": _rt(sorgenti),
        "Pubblica subito": {"type": "checkbox", "checkbox": pubblica_subito},
        "Cartella Drive": {"type": "url", "url": cartella_drive or None},
        "Controllo": _rt(controllo),
    }
    # i testi stanno nel corpo della pagina: nelle prove viaggiano accanto alle proprietà
    return {"object": "page", "id": id, "url": f"https://notion.so/{id}", "properties": props,
            "_testi": {"didascalia": didascalia, "testo linkedin": testo_linkedin}}


def riga_t(p):
    """Come riga_da_pagina, con i testi del corpo della pagina già letti."""
    r = riga_da_pagina(p)
    t = p.get("_testi", {})
    return replace(r, didascalia=t.get("didascalia", ""), testo_linkedin=t.get("testo linkedin", ""))


REEL = ("https://blob.example/reel.mp4", "https://blob.example/cover.jpg")
SLIDE = tuple(f"https://blob.example/{i:02d}.jpg" for i in range(1, 7))
CARTELLA = "https://drive.google.com/drive/folders/1ZyXwVuTsRqPoNmLkJiHgFeDcBa9876543"

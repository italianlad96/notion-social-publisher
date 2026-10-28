"""Impostazioni del sistema di pubblicazione: tutto ciò che si può voler cambiare sta qui."""
import os
from datetime import timedelta


def data_source_id() -> str:
    """La tabella Contenuti di Notion (data source), dal .env o dai segreti del lavoro programmato (vedi .env.example)."""
    valore = os.environ.get("NOTION_DATA_SOURCE_ID", "")
    if not valore:
        raise RuntimeError("Manca NOTION_DATA_SOURCE_ID (l'id della tabella Contenuti).")
    return valore

# Versione dell'API con gli endpoint dei data source.
NOTION_VERSION = "2025-09-03"

# Fuso orario delle date scritte in Notion e degli orari stampati (FUSO_ORARIO nel .env, se diverso).
TZ = os.environ.get("FUSO_ORARIO") or "Europe/Rome"
# Ora di uscita quando in Notion la data non ha l'ora.
ORA_PREDEFINITA = 9
# Si pubblica solo ciò che aveva la data nelle ultime 48 ore: più vecchio non esce, si avvisa.
FINESTRA = timedelta(hours=48)

# Stati della tabella Contenuti. Il sistema pubblica solo «Programmato» (o una riga con «Pubblica subito»).
PRONTO, PROGRAMMATO, DA_SISTEMARE, PUBBLICATO = "Pronto", "Programmato", "Da sistemare", "Pubblicato"

# Nome dell'opzione in Notion -> chiave interna.
PIATTAFORME = {
    "Instagram": "instagram",
    "Facebook": "facebook",
    "LinkedIn profilo": "linkedin",
    "LinkedIn pagina": "linkedin_pagina",
}
NOMI = {chiave: nome for nome, chiave in PIATTAFORME.items()}

# Piattaforme che il sistema sa pubblicare (la pagina aziendale LinkedIn richiede la Community Management API: non è supportata).
SUPPORTATE = ("instagram", "facebook", "linkedin")

# Limiti di lunghezza del testo.
LIMITE_TESTO = {"instagram": 2200, "linkedin": 3000}
CAROSELLO_MIN, CAROSELLO_MAX = 2, 20

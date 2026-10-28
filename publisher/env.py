"""Legge il file .env del progetto (token e percorsi). Non sovrascrive ciò che è già nell'ambiente."""
from __future__ import annotations

import os
from pathlib import Path


def carica_env(percorso=None) -> None:
    p = Path(percorso) if percorso else Path(__file__).resolve().parent.parent / ".env"
    if not p.is_file():
        return
    for riga in p.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, _, valore = riga.partition("=")
        os.environ.setdefault(chiave.strip(), valore.strip().strip("\"'"))

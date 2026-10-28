"""Esegue le decisioni: rende pubblici i file della cartella Drive, pubblica su ogni piattaforma, scrive in Notion cosa
è successo con parole semplici e lascia un commento sulla riga.

Esiti per riga:
- tutto uscito: Stato «Pubblicato», link, Esito, commento con i link, file di nuovo privati su Drive;
- qualcosa non è uscito: Stato «Da sistemare», Esito con il motivo, commento; si sistema e si rimette «Programmato»
  (le piattaforme già uscite non si ripubblicano);
- Instagram sta ancora elaborando un video: si riprende al giro dopo, senza cambiare lo Stato."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import config, drive, linkedin, media, meta, notion
from .model import Riga, contenitore_di, esito_leggibile, imposta_esito, link_pubblicati, piattaforme_fatte
from .plan import Decisione, candidata, problemi


@dataclass
class Contesto:
    notion_token: str
    page_token: str = ""
    page_id: str = ""
    ig_id: str = ""
    prova: bool = False  # niente si pubblica e niente si scrive in Notion (i file su Drive tornano privati subito)
    solo_id: Optional[str] = None
    linkedin_token: str = ""
    persona_urn: str = ""
    linkedin_scade: str = ""  # AAAA-MM-GG
    oggi: date = field(default_factory=date.today)
    utente_id: str = ""  # chi menzionare nei commenti


class ErrorePost(RuntimeError):
    """Un problema del post (file, testo), da sistemare a mano."""


def _chiave(i: str) -> str:
    return i.replace("-", "")[-32:]


def _ora(t: datetime) -> str:
    return t.astimezone(ZoneInfo(config.TZ)).strftime("%d/%m alle %H:%M")


def _nomi(piattaforme: List[str]) -> str:
    return ", ".join(config.NOMI.get(p, p) for p in piattaforme)


def prendi_file(r: Riga, ctx: Contesto) -> List[str]:
    """Sceglie i file nella cartella Drive e li rende pubblici il tempo di pubblicare. Restituisce gli indirizzi."""
    tok = drive.token()
    elenco = drive.elenca(tok, drive.id_cartella(r.cartella_drive))
    scelti, guai = media.scegli(r.formato, elenco)
    if guai:
        raise ErrorePost("; ".join(guai))
    pubblici: List[str] = []
    try:
        for f in scelti:
            pubblici.append(drive.rendi_pubblico(tok, f["id"], f["name"]))
        if not ctx.prova:
            notion.scrivi_media(ctx.notion_token, r.id, pubblici)
    except Exception:
        drive.rendi_privati(tok, pubblici)
        raise
    return pubblici


def _privati(link: List[str]) -> None:
    drive.rendi_privati(drive.token(), link)


def _commenta(ctx: Contesto, r: Riga, testo: str, stampa: Callable[[str], None]) -> None:
    if ctx.prova:
        return
    try:
        notion.commenta(ctx.notion_token, r.id, testo, ctx.utente_id)
    except RuntimeError as e:
        stampa(f"  (commento non lasciato: {e})")


def da_sistemare(r: Riga, ctx: Contesto, motivo: str, stampa: Callable[[str], None], tecnici: Optional[str] = None) -> None:
    """Porta la riga a «Da sistemare», scrive il motivo e lascia un commento."""
    stampa(f"  DA SISTEMARE: {motivo}")
    if ctx.prova:
        return
    props = {"Stato": notion.p_stato(config.DA_SISTEMARE), "Controllo": notion.p_testo(f"Da sistemare: {motivo}"),
             "Pubblica subito": {"checkbox": False}}
    if tecnici is not None:
        props["Dati tecnici"] = notion.p_testo(tecnici)
        props["Esito"] = notion.p_testo(esito_leggibile(tecnici))
    # i file tornano privati: al prossimo tentativo si riprendono freschi dalla cartella
    if r.cartella_drive and r.media:
        try:
            _privati(r.media)
            props["Media"] = notion.p_testo("")
        except RuntimeError:
            pass
    try:
        notion.aggiorna(ctx.notion_token, r.id, props)
    except RuntimeError as e:
        stampa(f"  ERRORE: non riesco a scrivere in Notion ({e})")
    _commenta(ctx, r, f"«{r.titolo}» non è uscito: {motivo}. Quando è sistemato, rimetti lo Stato su «Programmato».", stampa)


def _chiudi(r: Riga, ctx: Contesto, tecnici: str, stampa: Callable[[str], None]) -> int:
    link = (link_pubblicati(tecnici) or [""])[0]
    adesso = datetime.now(timezone.utc)
    props = {
        "Stato": notion.p_stato(config.PUBBLICATO),
        "Esito": notion.p_testo(esito_leggibile(tecnici)),
        "Dati tecnici": notion.p_testo(tecnici),
        "Controllo": notion.p_testo(f"Pubblicato il {_ora(adesso)}"),
        "Media": notion.p_testo(""),
        "Pubblica subito": {"checkbox": False},
    }
    if link:
        props["Link al post"] = {"url": link}
    # il post è già uscito: se Drive non lascia rimettere privati i file la riga si chiude lo stesso, e Media li ricorda
    if r.media:
        try:
            _privati(r.media)
        except RuntimeError as e:
            stampa(f"  (file ancora pubblici su Drive, restano in Media: {str(e)[:120]})")
            del props["Media"]
    try:
        notion.aggiorna(ctx.notion_token, r.id, props)
    except RuntimeError as e:
        stampa(f"  ERRORE nel chiudere la riga: {e}")
        return 1
    stampa("  riga chiusa: Stato «Pubblicato»")
    _commenta(ctx, r, f"«{r.titolo}» è uscito.\n{esito_leggibile(tecnici)}", stampa)
    return 0


def esegui(decisioni: List[Decisione], ctx: Contesto, stampa: Callable[[str], None] = print) -> int:
    """Restituisce il numero di errori."""
    errori = 0
    for d in decisioni:
        r = d.riga
        if ctx.solo_id and _chiave(r.id) != _chiave(ctx.solo_id):
            continue
        if not candidata(r):
            continue
        if d.azione == "scaduto":
            stampa(f"\n{r.titolo}")
            da_sistemare(r, ctx, f"doveva uscire il {_ora(r.data)} e sono passate più di 48 ore. Cambia la data o spunta «Pubblica subito»", stampa)
            errori += 1
            continue
        if d.azione == "problema":
            stampa(f"\n{r.titolo}")
            motivi = "; ".join(m for lista in d.problemi.values() for m in lista)
            da_sistemare(r, ctx, motivi, stampa)
            errori += 1
            continue
        if d.azione == "chiudere":  # uscito ovunque in un giro precedente, ma la riga non era stata chiusa
            stampa(f"\n{r.titolo}")
            if not ctx.prova:
                errori += _chiudi(r, ctx, r.esito, stampa)
            continue
        if d.azione != "pubblica":
            continue
        stampa(f"\n{r.titolo}")
        esito = r.esito
        prova_caricati: List[str] = []

        # 1. i file: se non sono già pubblici (giro precedente interrotto), si prendono dalla cartella Drive
        if not r.media:
            try:
                urls = prendi_file(r, ctx)
            except (ErrorePost, drive.ErroreDrive, RuntimeError) as e:
                errori += 1
                da_sistemare(r, ctx, f"file: {e}", stampa)
                continue
            r = replace(r, media=urls)
            if ctx.prova:
                prova_caricati = urls
        # tutte le piattaforme scelte e non ancora uscite: quelle con un problema finiscono negli errori,
        # così la riga va «Da sistemare» invece di restare a ritentare per sempre
        piattaforme = [p for p in r.piattaforme if p not in piattaforme_fatte(esito)]
        guai = {p: problemi(r, p) for p in piattaforme}
        guai = {p: g for p, g in guai.items() if g}

        def scrivi(piattaforma: str, testo: str) -> None:
            nonlocal esito
            esito = imposta_esito(esito, piattaforma, testo)
            if not ctx.prova:
                notion.scrivi_esito(ctx.notion_token, r.id, esito)

        in_corso = False
        for p in piattaforme:
            if p in guai:
                errori += 1
                stampa(f"  {config.NOMI.get(p, p)}: ERRORE {'; '.join(guai[p])}")
                esito = imposta_esito(esito, p, f"errore {'; '.join(guai[p])}"[:300])
                continue
            try:
                if p == "instagram":
                    res = meta.instagram(ctx.ig_id, ctx.page_token, r, lambda t: scrivi("instagram", t),
                                         contenitore_noto=contenitore_di(esito, "instagram"), prova=ctx.prova)
                elif p == "facebook":
                    res = meta.facebook(ctx.page_id, ctx.page_token, r, prova=ctx.prova)
                elif p == "linkedin":
                    if ctx.linkedin_scade and ctx.linkedin_scade < ctx.oggi.isoformat():
                        raise linkedin.ErroreLinkedIn(f"token LinkedIn scaduto il {ctx.linkedin_scade}: rilancia linkedin_login.py")
                    res = linkedin.pubblica(ctx.persona_urn, ctx.linkedin_token, r, prova=ctx.prova)
                else:
                    stampa(f"  {config.NOMI.get(p, p)}: non supportata, salto")
                    continue
            except (RuntimeError, KeyError, IndexError) as e:  # ErroreMeta, ErroreLinkedIn ed errori di Notion
                errori += 1
                stampa(f"  {config.NOMI.get(p, p)}: ERRORE {e!s}")
                esito = imposta_esito(esito, p, f"errore {e!s}"[:300])
                continue
            if res.stato == "pubblicato":
                stampa(f"  {config.NOMI.get(p, p)}: pubblicato {res.dettaglio}")
                try:
                    scrivi(p, f"pubblicato {res.dettaglio} {datetime.now(timezone.utc).isoformat(timespec='minutes')}")
                except RuntimeError as e:
                    errori += 1
                    stampa(f"  ATTENZIONE: pubblicato ma l'esito NON è stato scritto in Notion ({e}). "
                           f"Scrivilo a mano nei Dati tecnici: «{p}: pubblicato {res.dettaglio}»")
            elif res.stato == "in_corso":
                in_corso = True
                stampa(f"  {config.NOMI.get(p, p)}: Meta sta ancora elaborando, riprendo al prossimo giro")
                try:
                    scrivi(p, f"contenitore {res.dettaglio}")
                except RuntimeError:
                    pass
            else:
                stampa(f"  {config.NOMI.get(p, p)}: prova riuscita, niente pubblicato")

        if ctx.prova:
            if prova_caricati:
                _privati(prova_caricati)
            continue
        fatte = piattaforme_fatte(esito)
        if all(p in fatte for p in r.piattaforme):
            errori += _chiudi(r, ctx, esito, stampa)
        elif any(esito_di_errore(esito, p) for p in r.piattaforme):
            mancanti = [p for p in r.piattaforme if p not in fatte]
            motivi = "; ".join(f"{config.NOMI.get(p, p)}: {esito_di_errore(esito, p)}" for p in mancanti if esito_di_errore(esito, p))
            da_sistemare(r, ctx, f"non uscito su {_nomi(mancanti)} ({motivi})", stampa, tecnici=esito)
        elif in_corso:
            try:
                notion.aggiorna(ctx.notion_token, r.id, {"Esito": notion.p_testo(esito_leggibile(esito))})
            except RuntimeError:
                pass
    return errori


def esito_di_errore(esito: str, p: str) -> str:
    from .model import esito_di
    resto = esito_di(esito, p)
    return resto[len("errore"):].strip() if resto.lower().startswith("errore") else ""

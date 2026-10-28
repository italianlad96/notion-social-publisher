# notion-social-publisher

Pubblicare da Notion su Instagram, Facebook e LinkedIn, gratis.

Una tabella di Notion è il calendario editoriale. Quando una riga ha Stato «Programmato» e la sua data arriva, il sistema prende i file dalla cartella Google Drive del post, pubblica su Instagram, Facebook e, se vuoi, sul tuo profilo LinkedIn, e scrive in Notion com'è andata. Non c'è nessun servizio a pagamento in mezzo: Python con la sola libreria standard, GitHub Actions per far girare il codice, cron-job.org per l'orario, Google Drive per i file.

Questo repository è un **template**: con «Use this template» ne crei una copia tua, la configuri in sette passi e la lasci girare. Se usi Claude Code, la sezione [Installazione con Claude Code](#installazione-con-claude-code) dice all'agente cosa può fare da solo e dove deve fermarsi.

## Come si usa, una volta installato

1. Una riga per post nella tabella Contenuti. Il testo si scrive **nella pagina** della riga, sotto un titolo «Didascalia» (facoltativo: un secondo titolo «Testo LinkedIn»).
2. I file stanno in **una cartella Google Drive per post**, dentro la cartella madre condivisa con il sistema. Reel: un video e, se c'è, un'immagine che si chiama «copertina…». Carosello: i file in ordine di nome (01, 02, …), da 2 a 20, immagini o video. Post: una sola immagine. Le immagini devono essere JPG. I file che iniziano con «_» o «.» si ignorano.
3. Nella riga: il link della cartella in «Cartella Drive», la data in «Data di pubblicazione» (senza ora = alle 9), le «Piattaforme».
4. Stato **«Programmato»**: esce da solo alla data. Per farlo uscire al prossimo giro: spunta «Pubblica subito» (con Stato «Pronto» o «Programmato»).

Ogni mattina il sistema scrive in «Controllo» se è tutto pronto o cosa manca; quando pubblica scrive «Esito» e «Link al post», porta lo Stato a «Pubblicato» e lascia un commento sulla riga. Se qualcosa non esce lo Stato diventa «Da sistemare»: sistemi e rimetti «Programmato» (le piattaforme già uscite non si ripubblicano). «Pronto» da solo vuol dire: approvato, si pubblica a mano.

I file su Drive restano privati: il sistema dà al singolo file il permesso «chiunque con il link» solo il tempo di pubblicare, poi lo toglie.

## Prerequisiti

- **Python 3.9 o più recente** e `openssl` sulla riga di comando (ci sono già su macOS e Linux; su Windows usa WSL). Nessun pacchetto da installare.
- **`gh`**, la riga di comando di GitHub (`gh auth login` fatto): serve solo a copiare i segreti.
- **Un account Instagram professionale** (Business o Creator) **collegato a una Pagina Facebook** di cui sei amministratore. Senza il collegamento l'API di Instagram non pubblica.
- Un account Google con cui creare un progetto su Google Cloud (gratuito), uno Notion, uno GitHub e uno su cron-job.org (gratuito, senza carta di credito).
- Per LinkedIn (facoltativo): una Pagina LinkedIn qualsiasi a cui associare l'app. Si pubblica solo sul **profilo personale**.

Tempo: circa un'ora e mezza, quasi tutta nei pannelli di Meta e Google. Le chiavi vanno nel file `.env` (copia di `.env.example`, ignorato da git): ogni passo dice quali righe compila.

## Installazione in sette passi

### 1. La tabella Contenuti in Notion

Crea una tabella (database) con queste proprietà, con **questi nomi esatti**:

| Proprietà | Tipo in Notion | Chi la compila |
|---|---|---|
| Contenuto | Titolo | tu: il titolo del post |
| Formato | Selezione: `Reel`, `Carosello`, `Post` | tu |
| Stato | **Stato** (non Selezione): `Pronto`, `Programmato`, `Da sistemare`, `Pubblicato` | tu; il sistema lo porta a «Pubblicato» o «Da sistemare» |
| Data di pubblicazione | Data | tu (senza ora = alle 9) |
| Piattaforme | Selezione multipla: `Instagram`, `Facebook`, `LinkedIn profilo` | tu; vuota = il post non è automatico |
| Cartella Drive | URL | tu: il link della cartella del post |
| Pubblica subito | Casella di controllo | tu; il sistema la toglie dopo |
| Controllo | Testo | il sistema: tutto pronto, o cosa manca |
| Esito | Testo | il sistema: una riga per piattaforma |
| Link al post | URL | il sistema |
| Dati tecnici | Testo | il sistema: non toccare |
| Media | Testo | il sistema: non toccare |

Alla proprietà Stato puoi aggiungere altre opzioni (per esempio `Idea`): il sistema guarda solo le quattro sopra. Il testo del post sta nel corpo della pagina: un titolo (di qualunque livello) che dice `Didascalia` e sotto il testo; i paragrafi vanno a capo con una riga vuota, gli elenchi puntati diventano «•». Un secondo titolo `Testo LinkedIn` è facoltativo: se manca, LinkedIn usa la Didascalia.

### 2. L'integrazione Notion

1. Sul portale sviluppatori di Notion, [app.notion.com/developers/connections](https://app.notion.com/developers/connections), crea una **connessione interna** (Notion le chiamava «integrazioni») per il tuo spazio di lavoro; serve essere proprietari dello spazio. Capacità: *Read content*, *Update content*, *Insert comments* e, se vuoi essere menzionato nei commenti, *User information without email addresses*. Il token è nella scheda **Configuration** (comincia con `ntn_`): va in `NOTION_TOKEN`.
2. Apri la tabella Contenuti in Notion, menu `•••` in alto a destra, **Connessioni** (o *Aggiungi connessioni*), cerca la connessione e aggiungila. Finché non è collegata, l'API risponde con un errore.
3. Prendi l'**id del data source**, che non è l'id della tabella. Dallo stesso menu `•••` della tabella: **Gestisci origini dati** (*Manage data sources*), poi *Copia ID origine dati*. In alternativa dall'API: l'id della tabella è la sequenza di 32 caratteri nel link della tabella (prima di `?v=`), e con quello:

```bash
curl -s https://api.notion.com/v1/databases/<id-tabella> -H "Authorization: Bearer $NOTION_TOKEN" -H "Notion-Version: 2025-09-03" | python3 -c 'import json,sys; print(json.load(sys.stdin)["data_sources"][0]["id"])'
```

   Il risultato va in `NOTION_DATA_SOURCE_ID`. (Dal 2025 una tabella Notion può avere più origini dati: il sistema legge la prima.)
4. Facoltativo, per la menzione nei commenti: il tuo id utente da `curl -s https://api.notion.com/v1/users -H "Authorization: Bearer $NOTION_TOKEN" -H "Notion-Version: 2025-09-03"` (cerca il tuo nome nella risposta, campo `id`). Va in `NOTION_UTENTE_ID`. Senza, i commenti arrivano lo stesso, senza menzione.

### 3. La cartella Drive e l'account di servizio

1. Su Google Drive crea una **cartella madre** (per esempio «Post da pubblicare»): dentro ci andrà una sottocartella per post.
2. Su [console.cloud.google.com](https://console.cloud.google.com) crea un progetto, poi **API e servizi > Libreria**: abilita *Google Drive API*.
3. **IAM e amministrazione > Account di servizio > Crea account di servizio**: un nome qualsiasi, nessun ruolo. Apri l'account creato, scheda **Chiavi > Aggiungi chiave > Crea nuova chiave > JSON**: il file si scarica una volta sola. Se il pulsante è bloccato da un criterio dell'organizzazione (succede negli account Google Workspace aziendali creati dopo maggio 2024, non in un account Gmail), un amministratore deve esentare il progetto, oppure usa un progetto di un account personale.
4. Metti il file in `GOOGLE_SA_KEY_B64` su una riga sola:

```bash
base64 -i chiave.json | tr -d '\n'
```

   (su Linux `base64 -w0 chiave.json`). Poi cancella il file scaricato.
5. Torna su Drive: condividi la cartella madre con l'indirizzo email dell'account di servizio (lo trovi nel JSON, campo `client_email`, finisce con `.iam.gserviceaccount.com`) come **Editor**. Non Visualizzatore: il sistema deve poter cambiare i permessi dei singoli file. Le sottocartelle ereditano il permesso. Una chiave appena creata può impiegare un minuto a diventare valida.

### 4. L'app Meta e il token della Pagina

1. Su [developers.facebook.com/apps](https://developers.facebook.com/apps) crea un'app. Casi d'uso: *Manage everything on your Page* e *Manage messaging & content on Instagram* (nel pannello in italiano: gestire la Pagina e i contenuti di Instagram); in alternativa un'app di tipo Business con il prodotto *Facebook Login*. L'app può restare in **modalità sviluppo**: per chi ha un ruolo nell'app (amministratore, sviluppatore, tester) i permessi valgono senza App Review, ed è così che questo sistema pubblica. App Review serve solo se altre persone devono autorizzare la tua app.
2. **Impostazioni dell'app > Di base**: copia *ID app* in `META_APP_ID` e *Chiave segreta* in `META_APP_SECRET`.
3. Apri il [Graph API Explorer](https://developers.facebook.com/tools/explorer), scegli la tua app e aggiungi i permessi `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `business_management`. *Genera token di accesso*: nel consenso autorizza **solo** la Pagina e l'account Instagram che useranno il sistema.
4. Il token appena generato dura un'ora. Allungalo a 60 giorni e poi prendi il token della Pagina, che non scade:

```bash
curl -s "https://graph.facebook.com/v26.0/oauth/access_token?grant_type=fb_exchange_token&client_id=$META_APP_ID&client_secret=$META_APP_SECRET&fb_exchange_token=<token-di-un-ora>"
curl -s "https://graph.facebook.com/v26.0/me/accounts?access_token=<token-a-60-giorni>"
```

   La seconda risposta elenca le Pagine autorizzate: `id` va in `META_PAGE_ID`, `access_token` in `META_PAGE_TOKEN`.
5. L'id dell'account Instagram:

```bash
curl -s "https://graph.facebook.com/v26.0/$META_PAGE_ID?fields=instagram_business_account&access_token=$META_PAGE_TOKEN"
```

   Il valore di `instagram_business_account.id` va in `META_IG_USER_ID`. Se la risposta non ha quel campo, l'account Instagram non è professionale o non è collegato alla Pagina: si sistema nelle impostazioni della Pagina, *Account collegati*. Se la Pagina richiede la *Page Publishing Authorization* (Meta lo chiede ad alcune Pagine con molti follower), va completata dal pannello della Pagina prima che l'API possa pubblicare.

Il token della Pagina non scade, ma Meta fissa una scadenza all'**accesso ai dati** (circa 90 giorni dal consenso): `avvisi.py` controlla ogni mattina e avvisa 14 giorni prima; si rinnova rifacendo i punti 3 e 4.

#### 4 bis. LinkedIn, profilo personale (facoltativo)

1. Su [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps) crea un'app associata a una tua Pagina LinkedIn. Scheda **Products**: aggiungi *Share on LinkedIn* e *Sign In with LinkedIn using OpenID Connect* (entrambi senza revisione).
2. Scheda **Auth**: *Client ID* in `LINKEDIN_CLIENT_ID`, *Primary Client Secret* in `LINKEDIN_CLIENT_SECRET`; fra gli *Authorized redirect URLs* aggiungi `http://localhost:8765/callback`.
3. Dal computer: `python3 linkedin_login.py`. Si apre la pagina di consenso, il codice torna in locale e lo script scrive da solo `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_PERSON_URN` e `LINKEDIN_TOKEN_SCADE` nel `.env`. Il token dura circa 60 giorni e il prodotto gratuito non lo rinnova: alla scadenza si rilancia lo script e poi `segreti.py`.

### 5. Il repository e i segreti

1. Su GitHub, **Use this template > Create a new repository**. Scegli **privato**, per due motivi: i registri dei lavori di GitHub stampano titoli e date dei post, cioè il calendario non ancora uscito; e in un repository pubblico GitHub spegne i lavori programmati dopo 60 giorni senza commit. Un repository privato ha 2.000 minuti gratuiti al mese e il sistema ne usa circa 1.300-1.500. Il repository nuovo parte da un solo commit, senza la storia del template.
2. Clona il repository sul computer, copia `.env.example` in `.env` e compila le righe dei passi 2, 3 e 4. Il file resta sul computer (è in `.gitignore`).
3. Controlla che tutto sia a posto, senza toccare niente in rete:

```bash
python3 -m unittest -q
python3 pubblica.py
```

   La seconda riga è una simulazione: legge la tabella vera e stampa cosa farebbe adesso (con una tabella vuota: `0 righe`).
4. Copia le chiavi nei segreti del repository (i valori passano da standard input a `gh`, non compaiono nei comandi):

```bash
python3 segreti.py --repo <utente>/<nome-repo>
```

5. Nella scheda **Actions** del repository i due lavori programmati sono già attivi: *Pubblica* (il giro di pubblicazione) e *Controlli* (ogni mattina alle 6 UTC: scadenza dei token e campo «Controllo»). Se GitHub chiede di abilitare i workflow, abilitali.

### 6. L'orario con cron-job.org

Il cron di GitHub Actions da solo non è puntuale e può saltare giri interi. L'orario vero lo dà [cron-job.org](https://cron-job.org), che ogni 20 minuti chiama il lavoro *Pubblica*; il cron di GitHub resta come riserva.

1. Su GitHub, **Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token**: accesso al **solo repository** del sistema, permesso *Actions: Read and write* (Metadata si aggiunge da solo). Copia il token: cron-job.org lo userà come intestazione, non va nel `.env`.
2. Su cron-job.org, **Create cronjob**:
   - *URL*: `https://api.github.com/repos/<utente>/<nome-repo>/actions/workflows/pubblica.yml/dispatches`
   - *Schedule*: personalizzato, minuti `7,27,47`, ore da `6` a `19`, tutti i giorni (controlla che il fuso dell'account sia il tuo, in *Settings*).
   - Scheda *Advanced*, *Request method*: `POST`.
   - *Headers*, quattro righe:

     | Chiave | Valore |
     |---|---|
     | `Accept` | `application/vnd.github+json` |
     | `Authorization` | `Bearer <token-a-grana-fine>` |
     | `X-GitHub-Api-Version` | `2022-11-28` |
     | `Content-Type` | `application/json` |

   - *Request body*: `{"ref":"main"}` (il nome del ramo principale del tuo repository).
3. Salva e lancia una prova dal pannello (**Test run**): GitHub risponde `204 No Content` (o `200` con l'id del giro, nelle versioni più recenti dell'API) e nella scheda Actions compare un giro di *Pubblica* avviato da `workflow_dispatch`. Un altro codice vuol dire token sbagliato (401), permessi insufficienti (403) o ramo o nome del workflow sbagliato (404 o 422).

Il token a grana fine ha una scadenza (al massimo un anno): segnati di rinnovarlo.

### 7. La prima prova, senza pubblicare niente

1. In Notion prepara una riga vera: Formato, Didascalia nella pagina, cartella Drive con i file, Piattaforme, Stato «Programmato» e la spunta «Pubblica subito».
2. Dal computer, in modalità prova: il sistema prende i file da Drive, li fa accettare a Instagram e Facebook (contenitori e oggetti non pubblicati, che poi cancella), rimette privati i file e **non scrive niente in Notion**:

```bash
python3 pubblica.py --esegui --prova --id <id-della-pagina>
```

   L'id della pagina è la sequenza di 32 caratteri alla fine del link della riga. Se qualcosa manca lo stampa in parole semplici (file che non va, testo assente, cartella non condivisa).
3. La stessa prova dal server di GitHub, che è dove girerà davvero:

```bash
gh workflow run pubblica.yml --repo <utente>/<nome-repo> -f prova=true -f id=<id-della-pagina>
```

   e poi `python3 controlla.py --solo-elenco` per vedere cosa scriverebbe il controllo del mattino.
4. Quando la prova passa, togli `--prova`: `python3 pubblica.py --esegui --id <id-della-pagina>` pubblica davvero quella riga. Da qui in poi non serve più il computer: alla data di ogni riga «Programmato» pensa cron-job.org.

## Comandi

```bash
python3 -m unittest -q                                   # prove automatiche, senza rete
python3 pubblica.py                                      # simulazione: cosa farebbe adesso
python3 pubblica.py --ora 2026-11-04T09:20:00+01:00      # simulazione a un'altra ora
python3 pubblica.py --esegui --prova [--id <pagina>]     # chiama le piattaforme, niente di pubblico, niente in Notion
python3 pubblica.py --esegui [--id <pagina>]             # pubblica davvero ciò che tocca
python3 controlla.py [--solo-elenco]                     # il controllo del mattino
python3 avvisi.py                                        # scadenza dei token
python3 linkedin_login.py                                # login LinkedIn (ogni 60 giorni circa)
python3 segreti.py --repo <utente>/<nome-repo>           # copia il .env nei segreti di GitHub
```

Impostazioni in `publisher/config.py`: ora di uscita quando la data non ha l'ora (9), finestra oltre la quale un post in ritardo non esce più (48 ore), nomi degli stati e delle piattaforme, limiti di lunghezza del testo. Il fuso orario si cambia con `FUSO_ORARIO` nel `.env`.

## Come pubblica

Prende i file dalla cartella Drive (account di servizio, firma del token con `openssl`) e dà a ognuno il permesso «chiunque con il link» il tempo di pubblicare: Instagram e Facebook li scaricano da `drive.usercontent.google.com`, che serve il file anche oltre i 25 MB; alla chiusura della riga tornano privati. Instagram: crea il contenitore, lo scrive subito nei «Dati tecnici» (un riavvio riprende lo stesso: niente doppioni), aspetta l'elaborazione e pubblica. Facebook: video della Pagina, foto, o più foto in un post. LinkedIn (profilo, API gratuita): testo con un'immagine o un video. Dopo ogni piattaforma scrive l'esito; quando tutte sono uscite porta lo Stato a «Pubblicato», scrive il link e rimette privati i file. Le pubblicazioni non si ritentano da sole dentro lo stesso giro: un doppione è peggio di un errore. Un solo giro alla volta (`concurrency` del workflow).

Un post con la data passata da più di 48 ore non esce: va «Da sistemare» con un commento, e si rimette in corsa cambiando la data o spuntando «Pubblica subito».

## Installazione con Claude Code

Questa sezione è scritta per un agente (Claude Code o simile) a cui una persona ha chiesto di installare il sistema. Leggila tutta prima di cominciare.

**Cosa puoi fare da solo**

- Creare la tabella Contenuti in Notion con il connettore Notion, con i nomi e i tipi esatti del passo 1 (Stato è una proprietà di tipo *Stato*, non Selezione). Se la tabella esiste già, confronta le proprietà e aggiungi solo quelle che mancano.
- Preparare il `.env` da `.env.example` e, per ogni valore, dire alla persona dove trovarlo. I token non passano mai dalla chat: la persona li incolla nel `.env` con un editor, tu non li chiedi e non li ripeti. Puoi verificare che una riga sia compilata (`grep -c '^NOTION_TOKEN=.' .env`), non stamparla.
- Lanciare le prove (`python3 -m unittest -q`), la simulazione (`python3 pubblica.py`) e, quando il `.env` è completo, la prova contro le piattaforme (`python3 pubblica.py --esegui --prova --id <pagina>`), e leggere gli errori che stampano.
- Prendere l'id del data source e l'id utente di Notion con i comandi `curl` del passo 2, una volta che `NOTION_TOKEN` è nel `.env`.
- Copiare i segreti su GitHub con `segreti.py` (serve `gh auth login` già fatto), lanciare `gh workflow run pubblica.yml -f prova=true` e leggere il registro del giro con `gh run view --log`.

**Dove devi fermarti e guidare la persona sul suo account**

Tre passaggi vivono in pannelli con il login della persona, dove tu non entri. In ognuno fermati, spiega un'azione alla volta con il valore esatto da inserire, e riprendi quando la persona dice di aver finito:

1. **Meta** (passo 4): creazione dell'app, permessi nel Graph API Explorer, consenso sulla Pagina e sull'account Instagram. Tu prepari i due comandi `curl` dello scambio del token con i valori già al posto giusto, la persona li lancia e incolla i risultati nel `.env`.
2. **Google** (passo 3): progetto Cloud, API di Drive, account di servizio, chiave JSON, condivisione della cartella come **Editor**. Tu dai il comando `base64` e controlli che `GOOGLE_SA_KEY_B64` sia una riga sola.
3. **cron-job.org** (passo 6): account, token GitHub a grana fine, creazione del lavoro con URL, intestazioni e corpo esatti. Tu scrivi i quattro header e l'URL già compilati con utente e nome del repository, la persona li incolla, poi tu verifichi su GitHub che il *Test run* abbia avviato un giro (`gh run list --workflow pubblica.yml`).

Anche l'integrazione Notion (passo 2, punti 1 e 2) la crea la persona nel suo spazio di lavoro: due minuti, poi incolla il token.

**Regole**

- Il primo giro vero si lancia solo con `--prova`, e il primo post pubblicato davvero lo decide la persona, con te che guardi il registro.
- Non cambiare i nomi delle proprietà di Notion né gli stati in `config.py` per «adattarli»: tutto il resto del codice e la guida li danno per fissi.
- Se una prova fallisce, prima leggi cosa stampa il comando (i messaggi sono in parole semplici e dicono cosa manca), poi guarda il codice.

## Cosa resta fuori

- **La pagina aziendale LinkedIn.** Richiede la Community Management API e una revisione di LinkedIn: l'opzione «LinkedIn pagina» in `config.py` esiste ma non è supportata. Si pubblica solo sul profilo personale, e lì **niente caroselli** (l'API gratuita accetta testo, un'immagine o un video).
- **TikTok.** Senza la revisione dell'app i post escono solo privati, e le linee guida di TikTok escludono per nome gli strumenti che caricano sugli account del proprio team.
- **La conversione delle immagini.** Le immagini devono essere già JPG: PNG e WebP finiscono «Da sistemare» con il nome del file. Il sistema prende i file da Drive così come sono.
- **Le Storie**, e in generale tutto ciò che non è Reel, Carosello o Post.
- **Il rinnovo automatico dei token.** `avvisi.py` avvisa 14 giorni prima; il rinnovo si fa a mano (passo 4 per Meta, `linkedin_login.py` per LinkedIn, poi `segreti.py`).
- **L'intestazione `X-GitHub-Api-Version: 2022-11-28`** di cron-job.org: GitHub la sostiene almeno fino a marzo 2028, poi va aggiornata.

Il codice è in italiano, nomi e commenti compresi, perché è pensato per essere letto da chi lo installa. Notion usa la versione `2025-09-03` dell'API, Meta la `v26.0`. Licenza MIT (file `LICENSE`).

I comandi e i nomi delle API in questa guida sono controllati sulla documentazione ufficiale di Notion, Google, Meta, LinkedIn e GitHub (ottobre 2026) e il sistema gira così in produzione da ottobre 2026. I nomi delle voci di menu dei pannelli possono cambiare: se un passo non torna, apri una issue con quello che vedi.

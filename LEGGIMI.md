# Assistente All2Points

Chat basata su Claude per il team All2Points, pagata con i crediti API della Console Anthropic. Gira sul computer di chi la usa, in una finestra sua, e si aggiorna da sola.

## Cosa resta sul computer e non va mai online
Tutto quello che è personale sta nella cartella **`All2Points Assistente`** dentro la cartella utente:
- chat, progetti, allegati e riassunti;
- il file regole;
- le impostazioni.

La **chiave API** e il codice dell'estensione Chrome sono nel portachiavi del sistema. Su GitHub c'è solo il codice dell'app, e gli aggiornamenti sostituiscono solo la sottocartella `app`.

## Installazione (una volta sola)
1. **Chiave API:** su platform.claude.com › Chiavi API › Crea chiave, con ambito «Workspace predefinito». Ognuno crea la sua. In «Limiti di spesa» si può mettere un tetto per persona.
2. **Node.js (LTS)** da nodejs.org e **Google Chrome**: servono per il browser automatico e per l'estensione DaVinci.
3. **Scarica l'installatore** ed eseguilo:
   - **Mac:** apri il Terminale e incolla questa riga (è il modo più semplice, macOS non la blocca):
     ```
     curl -LsSf https://astral.sh/uv/install.sh | sh && ~/.local/bin/uv run --script https://raw.githubusercontent.com/gianco98/all2points-assistente/main/avvia.py --installa
     ```
     In alternativa c'è `Installa (Mac).command`, ma macOS lo blocca: va sbloccato da Impostazioni di Sistema › Privacy e sicurezza › «Apri comunque».
   - **Windows:** `Installa (Windows).bat`. Se compare «Windows ha protetto il PC», scegli «Ulteriori informazioni › Esegui comunque».
4. **L'installatore pensa al resto:**
   - scarica l'app;
   - crea l'icona **Assistente All2Points** (Mac: Dock e Applicazioni; Windows: Scrivania e menu Start);
   - apre l'app.
5. **Impostazioni:** nome, chiave API, dischi esterni (es. `/Volumes/SSD 2` o `E:\`), browser e avvisi sul telefono (app **ntfy**).
6. **File regole:** metti «Regole di Gianco - correzioni.md» nella cartella `All2Points Assistente`.

## Uso quotidiano
- **Apri l'app** dall'icona. Si apre una finestra sua.
  - Se c'è una versione nuova, la scarica prima di aprirsi.
  - Se Claude sta lavorando, l'aggiornamento aspetta il prossimo avvio.
- **Chiudi la finestra** quando hai finito. Il motore si spegne da solo dopo 20 minuti senza finestre aperte.
- **Progetti:** uno per cliente o lavoro, ognuno con le sue chat e il suo `riassunto.md`.
  - **Progetto da una cartella esistente:** in «Nuovo progetto» scrivi anche il percorso di una cartella (un sito, un gioco Roblox, la cartella dei clienti). Claude lavora lì dentro come in Claude Code, con il `CLAUDE.md`, la memoria e le regole di quella cartella. Nell'elenco ha l'icona 📁. Si vedono solo le chat nate nell'app, non quelle di Claude Code nella stessa cartella.
  - Se in quella cartella gli hook di avvio di Claude Code sono lenti (es. graphify su una cartella grande), la prima risposta può tardare qualche minuto.
- **Chat:** restano salvate con tutto il contesto. Si riprendono anche dopo aver spento il computer.
- **Modelli:** Opus per montaggio e lavori difficili, Sonnet per il lavoro normale, Haiku per le cose semplici.
- **Permessi** (in alto, accanto al modello):
  - **Automatico** (predefinito): Claude valuta il rischio di ogni azione, fa da solo comandi e modifiche sicure e blocca quelle pericolose (cancellazioni pesanti, pubblicazioni…); chiede solo nei casi dubbi.
  - **Chiedi conferma**: comandi e modifiche ai file chiedono sempre «Consenti» o «Nega».
  - In tutte e due le modalità lettura, skill, DaVinci, browser e avvisi vanno da soli.
- **Passi:** quando Claude lavora con una lista di cose da fare, sotto il messaggio compare il riquadro «Passi», che si aggiorna da solo: ✓ fatto, ◐ in corso, ○ da fare.
- **Anteprima:** il bottone «Anteprima» in alto apre un pannello a destra con le pagine web (.html) e le immagini (.png, .jpg, .gif, .webp, .svg) che Claude crea nella chat; si apre da solo alla prima. Si vedono solo file della cartella del progetto. Per un sito già acceso sul tuo computer (es. `http://localhost:3000`) scrivi l'indirizzo nel campo e premi «Apri».
- **Versione:** è indicata in basso a sinistra.

## Browser
- **Chrome separato:** ha il suo profilo; i login si fanno una volta in quella finestra.
- **Il mio Chrome:** Claude lavora nel tuo Chrome con i login che hai già.
  - Serve la [Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm); il codice dell'estensione va incollato nelle Impostazioni.
  - Claude lavora solo nelle schede del gruppo che l'estensione gli assegna.
  - In Chrome disattiva «Chiedi dove salvare ciascun file», altrimenti i download si bloccano.

## Skill e connettori: quelli di chi usa l'app
L'app li cerca a ogni avvio **sul computer di chi la usa**: ognuno ha i suoi, nessun percorso è scritto nel codice.
- **Skill:** quelle in `~/.claude/skills`, i plugin di Claude Code e i plugin del tuo Claude Desktop (es. montaggio-davinci, meta-ads, pdf, docx). Restano fuori le poche skill che funzionano solo dentro Desktop.
- **Connettori di Claude Code:** i server MCP registrati per l'utente in Claude Code, es. **Roblox Studio** (Studio aperto) e agent-desktop.
- **Estensioni di Claude Desktop:** quelle attive, es. **DaVinci** e **Blender** (con Blender aperto e l'addon collegato). Valgono le versioni di Desktop per Mac, per Windows e del Microsoft Store.
- **Connettori con login dei plugin di Claude Desktop** (Notion, Figma, Canva, Slack, Asana, HubSpot…): in basso a sinistra hanno lo stato (● collegato, ◐ da collegare, ○ non disponibile). Su quelli da collegare premi **«Collega»**: si apre il browser, fai il login al servizio e il connettore si attiva nella chat aperta. Il login resta salvato sul tuo computer (lo stesso di `claude mcp login`), non online e non nel repo.
- **Gmail e Google Calendar** passano dal login di claude.ai: con una chiave API risultano «non disponibile».

In basso a sinistra c'è l'elenco di cosa l'app ha trovato. I connettori con login compaiono quando una chat è aperta.

## DaVinci
Usa l'estensione «DaVinci Resolve Studio» già installata in Claude Desktop. In DaVinci imposta Preferenze › Sistema › Generale › External scripting = Local.

## L'app che si migliora da sola
- Il progetto **«Assistente - sviluppo»** compare da solo se sul computer c'è **git**. È una copia di questo repo in `All2Points Assistente/sviluppo`.
- Lì chiedi a Claude cosa migliorare. Claude:
  1. modifica la copia, mai l'app in uso;
  2. prova la versione nuova su un'altra porta;
  3. ti mostra cosa cambia;
  4. pubblica (push) **solo dopo il tuo ok**.
- Al riavvio successivo l'app si aggiorna da sola, **anche sui computer degli altri**: per questo il push chiede sempre l'ok.
- Se una versione si rompe, scrivi «torna alla versione prima»: Claude annulla l'ultima modifica con `git revert` e la ripubblica dopo il tuo ok.
- Per pubblicare serve l'accesso in scrittura al repo su GitHub.

## Chiave API nuova
- Su platform.claude.com › API Keys › Create Key crea la chiave.
- Nell'app apri Impostazioni › Chiave API della Console, incollala e premi Salva. L'app la prova e sostituisce la vecchia nel portachiavi del sistema.
- Nelle Impostazioni vedi le ultime 4 cifre della chiave in uso. Se la chiave non vale più, l'app lo dice e apre le Impostazioni.

## Sicurezza
- Proteggi l'account GitHub di Gianco con la **verifica in due passaggi**: gli aggiornamenti arrivano da lì.
- Non approvare a occhi chiusi richieste strane di comandi o modifiche, soprattutto dopo che Claude ha navigato su siti sconosciuti.

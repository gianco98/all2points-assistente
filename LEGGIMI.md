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
- **Chat:** restano salvate con tutto il contesto. Si riprendono anche dopo aver spento il computer.
- **Modelli:** Opus per montaggio e lavori difficili, Sonnet per il lavoro normale, Haiku per le cose semplici.
- **Permessi** (in alto, accanto al modello):
  - **Automatico** (predefinito): Claude valuta il rischio di ogni azione, fa da solo comandi e modifiche sicure e blocca quelle pericolose (cancellazioni pesanti, pubblicazioni…); chiede solo nei casi dubbi.
  - **Chiedi conferma**: comandi e modifiche ai file chiedono sempre «Consenti» o «Nega».
  - In tutte e due le modalità lettura, skill, DaVinci, browser e avvisi vanno da soli.
- **Versione:** è indicata in basso a sinistra.

## Browser
- **Chrome separato:** ha il suo profilo; i login si fanno una volta in quella finestra.
- **Il mio Chrome:** Claude lavora nel tuo Chrome con i login che hai già.
  - Serve la [Playwright Extension](https://chromewebstore.google.com/detail/playwright-extension/mmlmfjhmonkocbjadbfplnigmagldckm); il codice dell'estensione va incollato nelle Impostazioni.
  - Claude lavora solo nelle schede del gruppo che l'estensione gli assegna.
  - In Chrome disattiva «Chiedi dove salvare ciascun file», altrimenti i download si bloccano.

## DaVinci
Usa l'estensione «DaVinci Resolve Studio» già installata in Claude Desktop. In DaVinci imposta Preferenze › Sistema › Generale › External scripting = Local.

## Sicurezza
- Proteggi l'account GitHub di Gianco con la **verifica in due passaggi**: gli aggiornamenti arrivano da lì.
- Non approvare a occhi chiusi richieste strane di comandi o modifiche, soprattutto dopo che Claude ha navigato su siti sconosciuti.

# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "claude-agent-sdk",
#   "keyring",
#   "fastapi",
#   "uvicorn",
#   "websockets",
#   "python-multipart",
# ]
# ///
"""Assistente All2Points: chat nel browser basata su Claude (Agent SDK), pagata con i crediti API.

Gira solo sul computer di chi la usa (http://127.0.0.1:8765). Ognuno del team usa la sua chiave.
"""

import asyncio
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import warnings
import webbrowser
from pathlib import Path

import keyring
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    delete_session,
    get_session_messages,
    list_sessions,
    rename_session,
    tool,
)
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

PORTA = 8765
ORIGINI = {f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"}
HOST_OK = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
WINDOWS = sys.platform == "win32"
CODICE = Path(__file__).resolve().parent
BASE = Path.home() / "All2Points Assistente"
PROGETTI = BASE / "progetti"
CONFIG = BASE / "config.json"
REGOLE = BASE / "Regole di Gianco - correzioni.md"
CLAUDE_APP = (
    Path(os.environ.get("APPDATA", "")) / "Claude"
    if WINDOWS
    else Path.home() / "Library" / "Application Support" / "Claude"
)
MODELLI = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
# Permessi: "auto" valuta il rischio di ogni azione, fa da solo quelle sicure e blocca quelle pericolose;
# "chiedi" chiede conferma per comandi e modifiche ai file.
PERMESSI = {"auto": "auto", "chiedi": "default"}
PLAYWRIGHT_MCP = "@playwright/mcp@0.0.83"
# Strumenti che non chiedono conferma: lettura, skill, DaVinci, browser e avvisi.
# Comandi e modifiche ai file chiedono sempre, con l'opzione "consenti sempre in questa chat".
SENZA_CONFERMA = (
    "Read", "Glob", "Grep", "Skill", "TodoWrite", "WebSearch", "WebFetch", "Task", "Agent",
    "mcp__davinci__", "mcp__browser__", "mcp__avvisi__",
)
KEYRING = ("all2points-assistente", "anthropic")
KEYRING_ESTENSIONE = ("all2points-assistente", "playwright-extension")

warnings.filterwarnings("ignore", message="can_use_tool will not be invoked")

# Finestre aperte e lavori in corso: servono per spegnere il motore quando non serve
# e per aggiornare l'app senza interrompere un lavoro.
ATTIVITA = {"finestre": 0, "lavori": 0, "ultima": time.monotonic()}
SPEGNI_DOPO_MINUTI = 20


def versione() -> str:
    try:
        return (CODICE / "VERSIONE").read_text(encoding="utf-8").strip()[:7]
    except OSError:
        return "sviluppo"


# ---------- configurazione ----------

def leggi_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_config(cfg: dict) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def prepara_cartelle() -> None:
    PROGETTI.mkdir(parents=True, exist_ok=True)
    cfg = leggi_config()
    if "avvisi_topic" not in cfg:
        cfg["avvisi_topic"] = "a2p-" + uuid.uuid4().hex[:16]
    cfg.setdefault("nome", "")
    cfg.setdefault("modello", "opus")
    cfg.setdefault("permessi", "auto")
    cfg.setdefault("cartelle_extra", [])
    cfg.setdefault("spesa_mese", {})
    salva_config(cfg)
    if not REGOLE.exists():
        modello_regole = CODICE / "Regole di Gianco - correzioni.md"
        if modello_regole.exists():
            shutil.copy(modello_regole, REGOLE)


def chiave_valida(chiave: str) -> bool:
    richiesta = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": chiave, "anthropic-version": "2023-06-01"},
    )
    try:
        urllib.request.urlopen(richiesta, timeout=20)
    except urllib.error.HTTPError as errore:
        return errore.code != 401
    except OSError:
        pass
    return True


def _file_segreti() -> Path:
    return BASE / ".segreti.json"


def leggi_segreto(voce: tuple[str, str]) -> str | None:
    """Portachiavi di sistema (Mac/Windows); se non c'è, un file leggibile solo dall'utente."""
    try:
        return keyring.get_password(*voce)
    except Exception:
        try:
            return json.loads(_file_segreti().read_text(encoding="utf-8")).get(voce[1])
        except (OSError, ValueError):
            return None


def salva_segreto(voce: tuple[str, str], valore: str) -> None:
    try:
        keyring.set_password(*voce, valore)
        return
    except Exception:
        pass
    try:
        dati = json.loads(_file_segreti().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dati = {}
    dati[voce[1]] = valore
    BASE.mkdir(parents=True, exist_ok=True)
    _file_segreti().write_text(json.dumps(dati), encoding="utf-8")
    os.chmod(_file_segreti(), 0o600)


def chiave() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or leggi_segreto(KEYRING)


def nome_sicuro(nome: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip().strip(".")
    return nome[:80]


def cartella_progetto(nome: str) -> Path:
    pulito = nome_sicuro(nome)
    if not pulito:
        raise HTTPException(400, "Nome progetto non valido")
    cartella = PROGETTI / pulito
    if not cartella.is_dir():
        raise HTTPException(404, "Progetto non trovato")
    return cartella


def registra_spesa(dollari: float) -> None:
    if dollari <= 0:
        return
    cfg = leggi_config()
    mese = time.strftime("%Y-%m")
    cfg.setdefault("spesa_mese", {})[mese] = round(cfg["spesa_mese"].get(mese, 0) + dollari, 4)
    salva_config(cfg)


def avvisa_telefono(testo: str, titolo: str = "Assistente All2Points") -> bool:
    topic = leggi_config().get("avvisi_topic")
    if not topic:
        return False
    richiesta = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=testo.encode("utf-8"),
        headers={"Title": titolo.encode("utf-8").decode("latin-1", "ignore")},
        method="POST",
    )
    try:
        urllib.request.urlopen(richiesta, timeout=15)
        return True
    except OSError:
        return False


# ---------- server MCP ----------

def trova_estensione_davinci() -> dict | None:
    """Comando dell'estensione "DaVinci Resolve Studio" installata in Claude Desktop."""
    for manifest_path in sorted((CLAUDE_APP / "Claude Extensions").glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        nomi = f"{manifest.get('name', '')} {manifest.get('display_name', '')}".lower()
        if "davinci" not in nomi and "resolve" not in nomi:
            continue

        cartella_ext = manifest_path.parent
        cfg = dict(manifest["server"]["mcp_config"])
        cfg.update(cfg.pop("platform_overrides", {}).get(sys.platform, {}))

        valori = {k: v.get("default") for k, v in manifest.get("user_config", {}).items()}
        for impostazioni in (CLAUDE_APP / "Claude Extensions Settings").glob("*.json"):
            if cartella_ext.name in impostazioni.stem or impostazioni.stem in cartella_ext.name:
                dati = json.loads(impostazioni.read_text(encoding="utf-8"))
                valori.update(dati.get("userConfig") or dati.get("user_config") or {})

        variabili = {
            "__dirname": str(cartella_ext),
            "HOME": str(Path.home()),
            "DESKTOP": str(Path.home() / "Desktop"),
            "DOCUMENTS": str(Path.home() / "Documents"),
            "DOWNLOADS": str(Path.home() / "Downloads"),
            "pathSeparator": os.sep,
            "/": os.sep,
        }

        def sostituisci(testo: str) -> str:
            def valore(m: re.Match) -> str:
                k = m.group(1)
                if k.startswith("user_config."):
                    v = valori.get(k.split(".", 1)[1])
                    return "" if v is None else (" ".join(map(str, v)) if isinstance(v, list) else str(v))
                return variabili.get(k, m.group(0))
            return re.sub(r"\$\{([^}]+)\}", valore, testo)

        comando = sostituisci(cfg["command"])
        if not shutil.which(comando) and not Path(comando).exists():
            return None
        return {
            "type": "stdio",
            "command": comando,
            "args": [sostituisci(a) for a in cfg.get("args", [])],
            "env": {k: sostituisci(str(v)) for k, v in cfg.get("env", {}).items()},
        }
    return None


def server_browser() -> dict | None:
    npx = shutil.which("npx")
    if not npx:
        return None
    scaricati = BASE / "browser" / "scaricati"
    scaricati.mkdir(parents=True, exist_ok=True)
    if leggi_config().get("browser_modo") == "mio":
        # Il Chrome di tutti i giorni, con i login già fatti, tramite la Playwright Extension.
        server = {"type": "stdio", "command": npx,
                  "args": ["-y", PLAYWRIGHT_MCP, "--extension", "--output-dir", str(scaricati)]}
        token = leggi_segreto(KEYRING_ESTENSIONE)
        if token:
            server["env"] = {"PLAYWRIGHT_MCP_EXTENSION_TOKEN": token}
        return server
    profilo = BASE / "browser" / "profilo"
    profilo.mkdir(parents=True, exist_ok=True)
    return {
        "type": "stdio",
        "command": npx,
        "args": ["-y", PLAYWRIGHT_MCP, "--browser", "chrome",
                 "--user-data-dir", str(profilo), "--output-dir", str(scaricati)],
    }


@tool("avvisa_telefono", "Manda un avviso sul telefono di chi usa l'assistente (es. lavoro lungo finito, serve una decisione).",
      {"messaggio": str})
async def strumento_avviso(args):
    ok = await asyncio.to_thread(avvisa_telefono, args["messaggio"])
    return {"content": [{"type": "text", "text": "Avviso inviato." if ok else "Avviso non inviato (rete o avvisi non configurati)."}]}


def stato_strumenti() -> dict:
    return {
        "davinci": trova_estensione_davinci() is not None,
        "browser": shutil.which("npx") is not None,
        "skill": (Path.home() / ".claude" / "skills").is_dir(),
    }


def istruzioni(progetto: Path) -> str:
    cfg = leggi_config()
    if cfg.get("browser_modo") == "mio":
        descrizione_browser = (
            "È il Chrome di tutti i giorni dell'utente, con i suoi login: lavori solo nelle schede del gruppo "
            "che l'estensione ti assegna e non chiudi le schede che non hai aperto tu. I file scaricati vanno "
            "nella cartella Download di Chrome: spostali tu dove servono. Se Chrome chiede dove salvare ogni "
            "file, chiedi all'utente di disattivare «Chiedi dove salvare ciascun file» nelle impostazioni di Chrome."
        )
    else:
        descrizione_browser = (
            f"È un Chrome separato con il suo profilo; i login fatti lì restano. I file scaricati finiscono in "
            f"{BASE / 'browser' / 'scaricati'}: spostali tu dove servono."
        )
    return f"""
Sei l'Assistente All2Points, basato su Claude, per lo studio All2Points (video, social, siti web).
Rispondi sempre in italiano, in modo chiaro e pratico. Chi ti scrive: {cfg.get('nome') or 'un membro del team'}.

Cartella del progetto «{progetto.name}»: {progetto}
- Prima di lavorare leggi i file .md della cartella del progetto (riassunti, note) e, per i video, il file regole: {REGOLE}. Le correzioni di Gianco valgono più delle skill.
- Gli allegati dell'utente sono in {progetto / 'allegati'}: leggili con Read quando te li indico.
- A fine lavoro, o quando te lo chiedo, aggiorna «riassunto.md» nella cartella del progetto: cosa è fatto, cosa manca, dove siamo rimasti, percorsi utili.
- Quando una correzione di Gianco vale in generale, aggiungila al file regole nella sezione giusta (skill regole-da-correzioni).

Strumenti:
- DaVinci Resolve: server MCP «davinci» (se collegato).
- Browser: server MCP «browser». {descrizione_browser}
  Le password non le inserisci mai: se serve un login, chiedi all'utente di farlo nella finestra del browser.
- Avvisi: lo strumento avvisa_telefono manda una notifica sul telefono. Usalo quando finisci un lavoro lungo o ti serve una decisione mentre l'utente non è al computer.
""".strip()


# ---------- app web ----------

app = FastAPI()
app.mount("/static", StaticFiles(directory=CODICE / "static"), name="static")


@app.middleware("http")
async def solo_locale(request: Request, call_next):
    # Blocca richieste da altri siti (DNS rebinding e richieste cross-origin).
    if request.headers.get("host") not in HOST_OK:
        return JSONResponse({"errore": "host non valido"}, status_code=403)
    origine = request.headers.get("origin")
    if origine and origine not in ORIGINI:
        return JSONResponse({"errore": "origine non valida"}, status_code=403)
    return await call_next(request)


@app.get("/")
async def pagina():
    return FileResponse(CODICE / "static" / "index.html")


@app.get("/api/stato")
async def stato():
    cfg = leggi_config()
    return {
        "chiave": bool(chiave()),
        "nome": cfg.get("nome", ""),
        "modello": cfg.get("modello", "opus"),
        "permessi": cfg.get("permessi", "auto"),
        "avvisi_topic": cfg.get("avvisi_topic"),
        "cartelle_extra": cfg.get("cartelle_extra", []),
        "browser_modo": cfg.get("browser_modo", "separato"),
        "estensione_token": bool(leggi_segreto(KEYRING_ESTENSIONE)),
        "spesa_mese": cfg.get("spesa_mese", {}).get(time.strftime("%Y-%m"), 0),
        "versione": versione(),
        "strumenti": await asyncio.to_thread(stato_strumenti),
        "base": str(BASE),
    }


@app.post("/api/impostazioni")
async def impostazioni(request: Request):
    dati = await request.json()
    cfg = leggi_config()
    if dati.get("chiave"):
        k = dati["chiave"].strip().strip("\"'")
        if not k.startswith("sk-ant-") or not await asyncio.to_thread(chiave_valida, k):
            raise HTTPException(400, "Chiave non valida: copiala di nuovo dalla Console.")
        salva_segreto(KEYRING, k)
    if dati.get("estensione_token"):
        salva_segreto(KEYRING_ESTENSIONE, dati["estensione_token"].strip())
    if dati.get("permessi") in PERMESSI:
        cfg["permessi"] = dati["permessi"]
    if dati.get("browser_modo") in ("separato", "mio"):
        cfg["browser_modo"] = dati["browser_modo"]
    for campo in ("nome", "modello"):
        if campo in dati:
            cfg[campo] = dati[campo]
    if "cartelle_extra" in dati:
        cfg["cartelle_extra"] = [c.strip() for c in dati["cartelle_extra"] if c.strip()]
    salva_config(cfg)
    return {"ok": True}


@app.post("/api/spegni")
async def spegni():
    if ATTIVITA["lavori"]:
        raise HTTPException(409, "Claude sta lavorando")
    threading.Timer(0.3, os._exit, args=[0]).start()
    return {"ok": True}


@app.post("/api/avviso-prova")
async def avviso_prova():
    ok = await asyncio.to_thread(avvisa_telefono, "Gli avvisi dell'Assistente All2Points funzionano.")
    return {"ok": ok}


@app.get("/api/progetti")
async def progetti():
    elenco = []
    for cartella in PROGETTI.iterdir():
        if cartella.is_dir():
            elenco.append({"nome": cartella.name, "modificato": cartella.stat().st_mtime})
    elenco.sort(key=lambda p: -p["modificato"])
    return elenco


@app.post("/api/progetti")
async def nuovo_progetto(request: Request):
    nome = nome_sicuro((await request.json()).get("nome", ""))
    if not nome:
        raise HTTPException(400, "Scrivi un nome per il progetto")
    (PROGETTI / nome / "allegati").mkdir(parents=True, exist_ok=True)
    return {"nome": nome}


@app.get("/api/chat")
async def chat(progetto: str):
    cartella = cartella_progetto(progetto)
    sessioni = await asyncio.to_thread(list_sessions, str(cartella), 100)
    return [
        {
            "id": s.session_id,
            "titolo": (s.custom_title or s.first_prompt or s.summary or "Chat")[:70],
            "modificata": s.last_modified,
        }
        for s in sessioni
    ]


@app.get("/api/chat/{sid}")
async def messaggi(sid: str, progetto: str):
    cartella = cartella_progetto(progetto)
    righe = []
    for m in await asyncio.to_thread(get_session_messages, sid, str(cartella)):
        if m.parent_tool_use_id:
            continue
        contenuto = (m.message or {}).get("content")
        if isinstance(contenuto, str):
            righe.append({"ruolo": m.type, "testo": contenuto})
            continue
        for blocco in contenuto or []:
            if blocco.get("type") == "text" and blocco.get("text", "").strip():
                righe.append({"ruolo": m.type, "testo": blocco["text"]})
            elif blocco.get("type") == "tool_use":
                righe.append({"ruolo": "strumento", "testo": riassumi_strumento(blocco.get("name", ""), blocco.get("input") or {})})
    return righe


@app.post("/api/chat/{sid}/rinomina")
async def rinomina(sid: str, progetto: str, request: Request):
    titolo = (await request.json()).get("titolo", "").strip()[:100]
    await asyncio.to_thread(rename_session, sid, titolo, str(cartella_progetto(progetto)))
    return {"ok": True}


@app.delete("/api/chat/{sid}")
async def elimina(sid: str, progetto: str):
    await asyncio.to_thread(delete_session, sid, str(cartella_progetto(progetto)))
    return {"ok": True}


@app.post("/api/allegati")
async def allegati(progetto: str, file: UploadFile = File(...)):
    cartella = cartella_progetto(progetto) / "allegati"
    cartella.mkdir(exist_ok=True)
    nome = nome_sicuro(file.filename or "allegato") or "allegato"
    destinazione = cartella / f"{time.strftime('%Y%m%d-%H%M%S')}-{nome}"
    with destinazione.open("wb") as uscita:
        shutil.copyfileobj(file.file, uscita)
    return {"percorso": str(destinazione), "nome": nome}


def riassumi_strumento(nome: str, dati: dict) -> str:
    etichette = {
        "Read": "Legge", "Write": "Scrive", "Edit": "Modifica", "Bash": "Comando",
        "Glob": "Cerca file", "Grep": "Cerca nel testo", "Skill": "Skill",
        "WebSearch": "Cerca sul web", "WebFetch": "Legge una pagina", "TodoWrite": "Aggiorna la lista",
        "Task": "Sotto-agente", "Agent": "Sotto-agente",
    }
    if nome.startswith("mcp__"):
        _, server, azione = (nome.split("__", 2) + ["", ""])[:3]
        etichetta = {"davinci": "DaVinci", "browser": "Browser", "avvisi": "Avviso"}.get(server, server)
        dettaglio = dati.get("url") or dati.get("element") or ""
        return f"{etichetta}: {azione.replace('_', ' ')} {dettaglio}".strip()
    dettaglio = (dati.get("command") or dati.get("file_path") or dati.get("pattern")
                 or dati.get("skill") or dati.get("query") or dati.get("url") or dati.get("description") or "")
    return f"{etichette.get(nome, nome)}: {str(dettaglio)[:160]}".strip(": ")


@app.websocket("/ws")
async def sessione(ws: WebSocket):
    if ws.headers.get("origin") not in ORIGINI or ws.headers.get("host") not in HOST_OK:
        await ws.close(code=1008)
        return
    await ws.accept()
    ATTIVITA["finestre"] += 1

    stato = {"client": None, "progetto": None, "consentiti": set(), "costo": 0.0, "lavoro": None}
    richieste: dict[str, asyncio.Future] = {}

    async def invia(**dati):
        try:
            await ws.send_json(dati)
        except Exception:
            pass

    async def chiedi_permesso(nome, dati, _contesto):
        if nome.startswith(SENZA_CONFERMA) or nome in stato["consentiti"]:
            return PermissionResultAllow()
        rid = uuid.uuid4().hex
        futuro = asyncio.get_running_loop().create_future()
        richieste[rid] = futuro
        await invia(tipo="permesso", id=rid, strumento=nome, dettaglio=riassumi_strumento(nome, dati),
                    completo=json.dumps(dati, ensure_ascii=False, indent=2)[:4000])
        risposta = await futuro
        if risposta == "sempre":
            stato["consentiti"].add(nome)
        if risposta in ("si", "sempre"):
            return PermissionResultAllow()
        return PermissionResultDeny(message="L'utente ha negato il permesso.")

    async def chiudi():
        for futuro in richieste.values():
            if not futuro.done():
                futuro.set_result("no")
        richieste.clear()
        if stato["lavoro"] and not stato["lavoro"].done():
            stato["lavoro"].cancel()
        if stato["client"]:
            try:
                await stato["client"].disconnect()
            except Exception:
                pass
        stato["client"] = None

    async def apri(progetto: str, sid: str | None, modello: str, permessi: str):
        await chiudi()
        cartella = cartella_progetto(progetto)
        (cartella / "allegati").mkdir(exist_ok=True)
        k = chiave()
        if not k:
            await invia(tipo="errore", testo="Manca la chiave API: aprila nelle Impostazioni.")
            return
        cfg = leggi_config()
        server = {"avvisi": create_sdk_mcp_server("avvisi", tools=[strumento_avviso])}
        davinci = await asyncio.to_thread(trova_estensione_davinci)
        if davinci:
            server["davinci"] = davinci
        browser = server_browser()
        if browser:
            server["browser"] = browser
        extra = [c for c in cfg.get("cartelle_extra", []) if Path(c).exists()]
        opzioni = ClaudeAgentOptions(
            model=MODELLI.get(modello, MODELLI["opus"]),
            cwd=str(cartella),
            system_prompt={"type": "preset", "preset": "claude_code", "append": istruzioni(cartella)},
            setting_sources=["user", "project"],
            skills="all",
            mcp_servers=server,
            can_use_tool=chiedi_permesso,
            permission_mode=PERMESSI.get(permessi, "auto"),
            include_partial_messages=True,
            resume=sid,
            add_dirs=[str(BASE), *extra],
            env={"ANTHROPIC_API_KEY": k},
        )
        client = ClaudeSDKClient(options=opzioni)
        await client.connect()
        stato.update(client=client, progetto=cartella, consentiti=set(), costo=0.0)
        await invia(tipo="pronto", davinci=bool(davinci), browser=bool(browser))

    async def esegui(testo: str):
        ATTIVITA["lavori"] += 1
        try:
            await _esegui(testo)
        finally:
            ATTIVITA["lavori"] -= 1
            ATTIVITA["ultima"] = time.monotonic()

    async def _esegui(testo: str):
        client = stato["client"]
        inizio = time.monotonic()
        costo_prima = stato["costo"]
        try:
            await client.query(testo)
            async for m in client.receive_response():
                if isinstance(m, StreamEvent):
                    if m.parent_tool_use_id:
                        continue
                    ev = m.event
                    if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                        await invia(tipo="testo", testo=ev["delta"]["text"])
                elif isinstance(m, AssistantMessage):
                    for b in m.content:
                        if isinstance(b, ToolUseBlock):
                            await invia(tipo="strumento", testo=riassumi_strumento(b.name, b.input), sotto=bool(m.parent_tool_use_id))
                elif isinstance(m, SystemMessage) and m.subtype == "init":
                    await invia(tipo="sessione", id=m.data.get("session_id"))
                elif isinstance(m, ResultMessage):
                    if m.total_cost_usd is not None:
                        stato["costo"] = m.total_cost_usd
                    registra_spesa(stato["costo"] - costo_prima)
                    await invia(tipo="fine", costo=stato["costo"], sessione=m.session_id,
                                errore=(m.result or m.subtype) if m.is_error else None,
                                spesa_mese=leggi_config().get("spesa_mese", {}).get(time.strftime("%Y-%m"), 0))
            if time.monotonic() - inizio > 120:
                await asyncio.to_thread(avvisa_telefono, f"Ho finito il lavoro su «{stato['progetto'].name}».")
        except asyncio.CancelledError:
            raise
        except Exception as errore:
            await invia(tipo="errore", testo=f"{type(errore).__name__}: {errore}")

    try:
        while True:
            dati = await ws.receive_json()
            tipo = dati.get("tipo")
            try:
                if tipo == "apri":
                    await apri(dati["progetto"], dati.get("sessione"), dati.get("modello", "opus"),
                               dati.get("permessi", leggi_config().get("permessi", "auto")))
                elif tipo == "messaggio" and stato["client"]:
                    if stato["lavoro"] and not stato["lavoro"].done():
                        await invia(tipo="errore", testo="Sto ancora lavorando: aspetta o premi Stop.")
                        continue
                    testo = dati.get("testo", "").strip()
                    if dati.get("allegati"):
                        testo += "\n\nAllegati (leggili con Read):\n" + "\n".join(f"- {p}" for p in dati["allegati"])
                    stato["lavoro"] = asyncio.create_task(esegui(testo))
                elif tipo == "stop" and stato["client"]:
                    for futuro in richieste.values():
                        if not futuro.done():
                            futuro.set_result("no")
                    await stato["client"].interrupt()
                elif tipo == "permessi" and stato["client"]:
                    await stato["client"].set_permission_mode(PERMESSI.get(dati.get("modo"), "auto"))
                elif tipo == "modello" and stato["client"]:
                    await stato["client"].set_model(MODELLI.get(dati.get("modello"), MODELLI["opus"]))
                elif tipo == "permesso":
                    futuro = richieste.pop(dati.get("id"), None)
                    if futuro and not futuro.done():
                        futuro.set_result(dati.get("risposta", "no"))
            except HTTPException as errore:
                await invia(tipo="errore", testo=errore.detail)
            except Exception as errore:
                await invia(tipo="errore", testo=f"{type(errore).__name__}: {errore}")
    except WebSocketDisconnect:
        pass
    finally:
        ATTIVITA["finestre"] -= 1
        ATTIVITA["ultima"] = time.monotonic()
        await chiudi()


def spegni_se_inattivo() -> None:
    """Con nessuna finestra aperta e nessun lavoro per 20 minuti, il motore si spegne da solo."""
    while True:
        time.sleep(60)
        fermo = time.monotonic() - ATTIVITA["ultima"] > SPEGNI_DOPO_MINUTI * 60
        if not ATTIVITA["finestre"] and not ATTIVITA["lavori"] and fermo:
            os._exit(0)


def avvia(apri_finestra=None) -> None:
    if sys.stdout is None or sys.stderr is None:
        # Avviato dall'icona, senza finestra del terminale: i messaggi vanno in un file.
        BASE.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(BASE / "motore.log", "a", encoding="utf-8", buffering=1)
    elif hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Se l'app viene avviata da dentro Claude Code, non deve ereditarne sessione e impostazioni.
    for variabile in [v for v in os.environ if v.startswith(("CLAUDE_CODE_", "CLAUDECODE", "CLAUDE_SESSION"))]:
        del os.environ[variabile]
    prepara_cartelle()
    print(f"Assistente All2Points {versione()}: http://127.0.0.1:{PORTA}")
    if not os.environ.get("A2P_NO_BROWSER"):
        threading.Timer(1.5, apri_finestra or (lambda: webbrowser.open(f"http://127.0.0.1:{PORTA}"))).start()
    threading.Thread(target=spegni_se_inattivo, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")


if __name__ == "__main__":
    avvia()

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
import subprocess
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
from fastapi.responses import HTMLResponse, JSONResponse
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

PORTA = int(os.environ.get("A2P_PORTA", "8765"))  # un'altra porta serve per provare una versione nuova
ORIGINI = {f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}"}
HOST_OK = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
WINDOWS = sys.platform == "win32"
CODICE = Path(__file__).resolve().parent
BASE = Path.home() / "All2Points Assistente"
PROGETTI = BASE / "progetti"
CONFIG = BASE / "config.json"
REGOLE = BASE / "Regole di Gianco - correzioni.md"
PLUGIN_DESKTOP = BASE / "plugin-desktop"
REPO = "gianco98/all2points-assistente"
SVILUPPO = BASE / "sviluppo"  # copia del repo in cui l'assistente migliora sé stesso
PROGETTO_SVILUPPO = "Assistente - sviluppo"
# Skill di Claude Desktop legate a strumenti che esistono solo lì (documenti, browser e computer di Desktop).
SKILL_SOLO_DESKTOP = {"docs", "google-workspace", "computer-use", "chrome-browser", "built-in-browser",
                      "setup-cowork", "morning", "schedule"}
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


def prepara_sviluppo() -> None:
    """Il progetto «Assistente - sviluppo»: una copia del repo dell'app dove Claude la migliora.
    Serve git; senza, il progetto non compare e l'app funziona come prima."""
    git = shutil.which("git")
    if not git:
        return
    if not (SVILUPPO / ".git").is_dir():
        if SVILUPPO.exists():
            return  # c'è già qualcosa con quel nome: non lo tocchiamo
        try:
            subprocess.run([git, "clone", "-q", f"https://github.com/{REPO}.git", str(SVILUPPO)],
                           timeout=180, check=True, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return
    progetto = PROGETTI / PROGETTO_SVILUPPO
    (progetto / "allegati").mkdir(parents=True, exist_ok=True)
    collegamento = progetto / "cartella.txt"
    if not collegamento.exists():
        collegamento.write_text(str(SVILUPPO), encoding="utf-8")


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


def cartella_lavoro(nome: str) -> Path:
    """Dove Claude lavora: la cartella vera collegata al progetto (es. Desktop\\claude code, con il suo
    CLAUDE.md e la sua memoria) oppure, se non ce n'è una, la cartella del progetto nell'app.
    Il collegamento sta in «cartella.txt» dentro il progetto: ognuno ha i suoi percorsi sul suo computer."""
    dati = cartella_progetto(nome)
    try:
        collegata = Path((dati / "cartella.txt").read_text(encoding="utf-8").strip())
    except OSError:
        return dati
    return collegata if collegata.is_dir() else dati


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

def cartelle_claude_desktop() -> list[Path]:
    """Dove il Claude Desktop di chi usa l'app tiene estensioni e plugin. Cambia da computer a computer:
    Mac, Windows con l'installatore (APPDATA) e Windows del Microsoft Store (LOCALAPPDATA/Claude-Data)."""
    if not WINDOWS:
        candidati = [Path.home() / "Library" / "Application Support" / "Claude"]
    else:
        locale = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        candidati = [Path(os.environ.get("APPDATA", "")) / "Claude",
                     *sorted(locale.glob("Claude-Data/*")),
                     *sorted(locale.glob("Packages/Claude_*/LocalCache/Roaming/Claude"))]
    return [c for c in candidati if (c / "Claude Extensions").is_dir() or (c / "rpm").is_dir()]


def trova_comando(nome: str) -> str | None:
    """Un programma nel PATH, in ~/.local/bin o, per uv, quello che Claude Desktop si porta dietro."""
    trovato = shutil.which(nome) or shutil.which(nome, path=str(Path.home() / ".local" / "bin"))
    if trovato or nome != "uv":
        return trovato
    for base in cartelle_claude_desktop():
        for uv in base.glob("uv-runtime/**/uv.exe" if WINDOWS else "uv-runtime/**/uv"):
            return str(uv)
    return None


def _nome_estensione(manifest: dict, cartella: Path) -> str:
    nomi = f"{manifest.get('name', '')} {manifest.get('display_name', '')}".lower()
    if "davinci" in nomi or "resolve" in nomi:
        return "davinci"
    if "blender" in nomi:
        return "blender"
    return re.sub(r"[^a-z0-9]+", "-", (manifest.get("name") or cartella.name).lower()).strip("-")[:30]


def trova_estensioni() -> dict[str, dict]:
    """Le estensioni attive nel Claude Desktop di chi usa l'app (DaVinci, Blender…), come server MCP."""
    server = {}
    for base in cartelle_claude_desktop():
        for manifest_path in sorted((base / "Claude Extensions").glob("*/manifest.json")):
            trovata = _estensione(base, manifest_path)
            if trovata:
                server.setdefault(*trovata)
    return server


def _estensione(base: Path, manifest_path: Path) -> tuple[str, dict] | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cfg = dict(manifest["server"]["mcp_config"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    cartella_ext = manifest_path.parent
    cfg.update(cfg.pop("platform_overrides", {}).get(sys.platform, {}))

    valori = {k: v.get("default") for k, v in manifest.get("user_config", {}).items()}
    for impostazioni in (base / "Claude Extensions Settings").glob("*.json"):
        if cartella_ext.name in impostazioni.stem or impostazioni.stem in cartella_ext.name:
            try:
                dati = json.loads(impostazioni.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if dati.get("isEnabled") is False:  # spenta in Claude Desktop: spenta anche qui
                return None
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
    argomenti = [sostituisci(a) for a in cfg.get("args", [])]
    if manifest["server"].get("type") == "uv" and comando == "uv" and argomenti[:1] == ["run"]:
        # Le estensioni «uv» (es. Blender) Desktop le avvia dentro la loro cartella.
        argomenti = ["run", "--directory", str(cartella_ext), *argomenti[1:]]
    trovato = trova_comando(comando) or (comando if Path(comando).exists() else None)
    if not trovato:
        return None
    return _nome_estensione(manifest, cartella_ext), {
        "type": "stdio",
        "command": trovato,
        "args": argomenti,
        "env": {k: sostituisci(str(v)) for k, v in cfg.get("env", {}).items()},
    }


def _piu_recente(file: list[Path]) -> Path | None:
    return max(file, key=lambda f: f.stat().st_mtime, default=None)


def plugin_desktop() -> list[dict]:
    """I plugin e le skill che il Claude Desktop di chi usa l'app scarica dal suo account
    (es. montaggio-davinci, meta-ads, pdf, docx): ognuno ha i suoi, sul suo computer."""
    plugin = []
    for base in cartelle_claude_desktop():
        elenco = _piu_recente(list(base.glob("rpm/*/*/manifest.json")))
        if elenco:
            try:
                voci = json.loads(elenco.read_text(encoding="utf-8")).get("plugins", [])
            except (OSError, ValueError):
                voci = []
            for voce in voci:
                cartella = elenco.parent / str(voce.get("id", ""))
                if voce.get("id") and (cartella / ".claude-plugin" / "plugin.json").exists():
                    plugin.append({"type": "local", "path": str(cartella)})
        skill = _piu_recente(list(base.glob("local-agent-mode-sessions/skills-plugin/*/*/manifest.json")))
        copia = _copia_skill_anthropic(skill.parent) if skill else None
        if copia:
            plugin.append({"type": "local", "path": str(copia)})
        if plugin:
            break  # un solo Claude Desktop per computer
    return plugin


def _copia_skill_anthropic(origine: Path) -> Path | None:
    """Le skill «anthropic-skills» (pdf, docx, xlsx…) senza quelle che usano strumenti solo di Desktop.
    Si copiano in una cartella dell'app perché un plugin si carica intero."""
    def lungo(p: Path) -> str:
        # Su Windows docx, pptx e xlsx superano i 260 caratteri di percorso: serve il prefisso \\?\
        return "\\\\?\\" + str(p.resolve()) if WINDOWS else str(p)

    destinazione = PLUGIN_DESKTOP / "anthropic-skills"
    firma = destinazione / "origine.txt"  # da dove e di quando è la copia: si rifà solo se Desktop le aggiorna
    try:
        attuale = f"{origine}\n{(origine / 'manifest.json').stat().st_mtime}"
        if firma.exists() and firma.read_text(encoding="utf-8") == attuale:
            return destinazione
        attive = {s["name"] for s in json.loads((origine / "manifest.json").read_text(encoding="utf-8"))["skills"]
                  if s.get("enabled", True)}
        shutil.rmtree(lungo(destinazione), ignore_errors=True)
        shutil.copytree(origine / ".claude-plugin", destinazione / ".claude-plugin")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for cartella in (origine / "skills").iterdir():
        if cartella.is_dir() and cartella.name in attive - SKILL_SOLO_DESKTOP:
            try:
                shutil.copytree(lungo(cartella), lungo(destinazione / "skills" / cartella.name))
            except OSError:
                continue  # una skill che non si copia non deve togliere le altre
    try:
        firma.write_text(attuale, encoding="utf-8")
    except OSError:
        pass
    return destinazione


def connettori_claude_code() -> list[str]:
    """I server MCP che il Claude Code di chi usa l'app ha registrato per l'utente (es. Roblox Studio):
    il motore li carica da solo, qui servono solo per mostrarli."""
    try:
        return sorted(json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8")).get("mcpServers", {}))
    except (OSError, ValueError, AttributeError):
        return []


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


NOMI_CONNETTORI = {"davinci": "DaVinci", "blender": "Blender", "browser": "Browser", "avvisi": "Avviso",
                   "Roblox_Studio": "Roblox Studio", "agent-desktop": "Desktop"}


def stato_strumenti() -> list[dict]:
    """Cosa trova l'app su questo computer: lo mostra in alto, uguale per chi la usa ma con i suoi strumenti."""
    estensioni = trova_estensioni()
    voci = [{"nome": "DaVinci", "ok": "davinci" in estensioni},
            {"nome": "Browser", "ok": shutil.which("npx") is not None},
            {"nome": "Skill", "ok": (Path.home() / ".claude" / "skills").is_dir()}]
    voci += [{"nome": NOMI_CONNETTORI.get(n, n), "ok": True} for n in estensioni if n != "davinci"]
    voci += [{"nome": NOMI_CONNETTORI.get(n, n), "ok": True} for n in connettori_claude_code()]
    return voci


# ---------- connettori con login (Notion, Figma, Canva… dai plugin di Claude Desktop) ----------

# Nomi scritti come li scrivono i servizi; gli altri si ricavano dal nome del server.
NOMI_SERVIZI = {"hubspot": "HubSpot", "amplitude-eu": "Amplitude EU", "similarweb": "Similarweb",
                "google calendar": "Google Calendar", "gmail": "Gmail"}
# Passano dal login di claude.ai: con una chiave API non si collegano.
SOLO_CLAUDE_AI = re.compile(r"gmail|google calendar", re.I)
ORDINE_STATI = {"ok": 0, "collego": 1, "login": 2, "attesa": 3, "no": 4, "chiave": 5}


def connettori_remoti(stato_mcp: dict) -> list[dict]:
    """I server MCP remoti (HTTP/SSE) caricati dal motore, uno per servizio, con il loro stato:
    ok = collegato, login = da collegare, attesa = si sta collegando, no = non disponibile,
    chiave = non disponibile con la chiave API."""
    voci: dict[str, dict] = {}
    for s in stato_mcp.get("mcpServers", []):
        cfg = s.get("config") or {}
        if cfg.get("type") not in ("http", "sse"):
            continue
        servizio = s["name"].rsplit(":", 1)[-1]
        if SOLO_CLAUDE_AI.search(servizio):
            stato = "chiave"
        else:
            stato = {"connected": "ok", "needs-auth": "login", "pending": "attesa"}.get(s.get("status"), "no")
        voce = {"nome": NOMI_SERVIZI.get(servizio, servizio.replace("-", " ").title()),
                "server": s["name"], "url": cfg.get("url") or "", "stato": stato, "motivo": s.get("error") or ""}
        # Lo stesso servizio può stare in più plugin: il login vale per indirizzo, si mostra una volta.
        chiave_voce = voce["url"] or voce["nome"]
        prima = voci.get(chiave_voce)
        if not prima or ORDINE_STATI[stato] < ORDINE_STATI[prima["stato"]]:
            voci[chiave_voce] = voce
    return sorted(voci.values(), key=lambda v: v["nome"].lower())


def cli_claude() -> str | None:
    """La CLI di Claude Code che l'Agent SDK porta con sé; se manca, quella installata."""
    import claude_agent_sdk
    inclusa = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if WINDOWS else "claude")
    return str(inclusa) if inclusa.exists() else trova_comando("claude")


def cartella_plugin(nome_plugin: str) -> str | None:
    for p in plugin_desktop():
        try:
            dati = json.loads((Path(p["path"]) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if dati.get("name") == nome_plugin:
            return p["path"]
    return None


def login_connettore(server: str) -> bool:
    """Il login OAuth di un server MCP con `claude mcp login`, che apre il browser e salva i token
    sul computer di chi usa l'app. Vuole un terminale vero: su Windows una console nascosta, su Mac uno pty."""
    cli = cli_claude()
    if not cli:
        return False
    parti = server.split(":")
    cartella = cartella_plugin(parti[1]) if parti[0] == "plugin" and len(parti) == 3 else None
    comando = [cli, *(["--plugin-dir", cartella] if cartella else []), "mcp", "login", server]
    padre = None
    if WINDOWS:
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 0  # nascosta
        processo = subprocess.Popen(comando, creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
    else:
        import pty
        padre, figlio = pty.openpty()
        processo = subprocess.Popen(comando, stdin=figlio, stdout=figlio, stderr=figlio, start_new_session=True)
        os.close(figlio)
    try:
        return processo.wait(timeout=300) == 0  # 5 minuti per fare il login nel browser
    except subprocess.TimeoutExpired:
        processo.kill()
        return False
    finally:
        if padre is not None:
            os.close(padre)


def istruzioni(progetto: Path, lavoro: Path) -> str:
    cfg = leggi_config()
    collegata = (
        f"\n- Lavori nella cartella collegata {lavoro}: valgono il suo CLAUDE.md, la sua memoria e le sue regole, "
        "come in Claude Code. Riassunti e allegati restano nella cartella del progetto qui sopra."
        if lavoro != progetto else ""
    )
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

Cartella del progetto «{progetto.name}»: {progetto}{collegata}
- Prima di lavorare leggi i file .md della cartella del progetto (riassunti, note) e, per i video, il file regole: {REGOLE}. Le correzioni di Gianco valgono più delle skill.
- Gli allegati dell'utente sono in {progetto / 'allegati'}: leggili con Read quando te li indico.
- A fine lavoro, o quando te lo chiedo, aggiorna «riassunto.md» nella cartella del progetto: cosa è fatto, cosa manca, dove siamo rimasti, percorsi utili.
- Quando una correzione di Gianco vale in generale, aggiungila al file regole nella sezione giusta (skill regole-da-correzioni).

Strumenti:
- DaVinci Resolve: server MCP «davinci» (se collegato).
- Altri connettori: quelli che chi ti usa ha messo in Claude Code e in Claude Desktop sul suo computer (es. Roblox Studio, Blender). Usali come in Claude Code. Per Roblox, prima di ogni lavoro chiama list_roblox_studios e list_roblox_skills e apri la skill Roblox che serve.
- Skill: hai le skill di chi ti usa (~/.claude/skills e i plugin del suo Claude Desktop). Apri quella giusta prima di lavorare, come in Claude Code.
- Browser: server MCP «browser». {descrizione_browser}
  Le password non le inserisci mai: se serve un login, chiedi all'utente di farlo nella finestra del browser.
- Avvisi: lo strumento avvisa_telefono manda una notifica sul telefono. Usalo quando finisci un lavoro lungo o ti serve una decisione mentre l'utente non è al computer.
{istruzioni_sviluppo() if lavoro == SVILUPPO else ""}
""".strip()


def istruzioni_sviluppo() -> str:
    """Come l'assistente migliora sé stesso: nella copia del repo, mai nell'app in uso."""
    return f"""
Questo è il progetto per migliorare l'app stessa. Stai lavorando in {SVILUPPO}, una copia del repo GitHub {REPO}.
L'app in uso sta in {CODICE}: non toccarla mai, la sostituisce l'aggiornamento automatico.
Regole, in quest'ordine:
1. Prima `git pull`, poi ripeti con parole tue cosa cambi e aspetta l'ok dell'utente.
2. Una modifica alla volta. L'app la usano più persone del team, ognuna sul suo computer (Windows o Mac): niente percorsi, nomi o chiavi di una persona nel codice. Tutto si cerca sul computer di chi la usa. Il repo è pubblico: mai segreti nei file.
3. Prova la versione nuova prima di proporla: avviala in background da {SVILUPPO} con le variabili A2P_PORTA=8790 e A2P_NO_BROWSER=1 (`uv run --script app.py`), controlla http://127.0.0.1:8790/api/stato e la funzione cambiata, poi spegnila con una POST a /api/spegni (header Origin: http://127.0.0.1:8790).
4. Mostra all'utente cosa cambia (`git diff --stat` e due righe per modifica) e chiedi l'ok per pubblicare.
5. Solo dopo l'ok: `git commit` con un messaggio in italiano che dice cosa cambia per chi usa l'app, poi `git push`. Di' all'utente di chiudere e riaprire l'app: si aggiorna da sola, anche sui computer degli altri.
6. Se una versione pubblicata si rompe: «torna alla versione prima» = `git revert` dell'ultimo commit, prova come al punto 3, push dopo l'ok.
7. Se il push fallisce per i permessi, chi usa l'app non ha accesso in scrittura al repo: dillo e lascia il commit in locale.
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
    # La versione negli indirizzi: dopo un aggiornamento il browser non usa il vecchio app.js dalla cache.
    v = versione()
    html = (CODICE / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/app.js", f"/static/app.js?v={v}").replace("/static/style.css", f"/static/style.css?v={v}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/api/stato")
async def stato():
    cfg = leggi_config()
    return {
        "chiave": bool(chiave()),
        "chiave_fine": (chiave() or "")[-4:],  # solo le ultime 4 cifre, per capire quale chiave è collegata
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
        # Le cartelle nascoste (es. .claude, creata dagli hook di Claude Code) non sono progetti.
        if cartella.is_dir() and nome_sicuro(cartella.name) == cartella.name:
            lavoro = cartella_lavoro(cartella.name)
            elenco.append({"nome": cartella.name, "modificato": cartella.stat().st_mtime,
                           "cartella": str(lavoro) if lavoro != cartella else None})
    elenco.sort(key=lambda p: -p["modificato"])
    return elenco


@app.post("/api/progetti")
async def nuovo_progetto(request: Request):
    dati = await request.json()
    nome = nome_sicuro(dati.get("nome", ""))
    if not nome:
        raise HTTPException(400, "Scrivi un nome per il progetto")
    collegata = str(dati.get("cartella") or "").strip().strip("\"'")
    if collegata and not Path(collegata).is_dir():
        raise HTTPException(400, "Questa cartella non esiste su questo computer")
    (PROGETTI / nome / "allegati").mkdir(parents=True, exist_ok=True)
    if collegata:
        (PROGETTI / nome / "cartella.txt").write_text(str(Path(collegata).resolve()), encoding="utf-8")
    return {"nome": nome}


def chat_dell_app(progetto: str) -> set[str] | None:
    """Per un progetto collegato a una cartella vera, le chat nate nell'app: le altre chat di Claude Code
    in quella cartella non si mostrano e non si possono eliminare da qui. None = progetto normale."""
    dati = cartella_progetto(progetto)
    if cartella_lavoro(progetto) == dati:
        return None
    try:
        return set((dati / "chat-app.txt").read_text(encoding="utf-8").split())
    except OSError:
        return set()


def ricorda_chat(progetto: Path, sid: str) -> None:
    file = progetto / "chat-app.txt"
    try:
        gia = set(file.read_text(encoding="utf-8").split())
    except OSError:
        gia = set()
    if sid and sid not in gia:
        with file.open("a", encoding="utf-8") as f:
            f.write(sid + "\n")


def chat_permessa(sid: str, progetto: str) -> None:
    ammesse = chat_dell_app(progetto)
    if ammesse is not None and sid not in ammesse:
        raise HTTPException(404, "Chat non trovata in questo progetto")


@app.get("/api/chat")
async def chat(progetto: str):
    ammesse = chat_dell_app(progetto)
    sessioni = await asyncio.to_thread(list_sessions, str(cartella_lavoro(progetto)), 100 if ammesse is None else 2000)
    if ammesse is not None:
        sessioni = [s for s in sessioni if s.session_id in ammesse]
    return [
        {
            "id": s.session_id,
            "titolo": (s.custom_title or s.first_prompt or s.summary or "Chat")[:70],
            "modificata": s.last_modified,
        }
        for s in sessioni[:100]
    ]


@app.get("/api/chat/{sid}")
async def messaggi(sid: str, progetto: str):
    chat_permessa(sid, progetto)
    cartella = cartella_lavoro(progetto)
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
    chat_permessa(sid, progetto)
    await asyncio.to_thread(rename_session, sid, titolo, str(cartella_lavoro(progetto)))
    return {"ok": True}


@app.delete("/api/chat/{sid}")
async def elimina(sid: str, progetto: str):
    chat_permessa(sid, progetto)
    await asyncio.to_thread(delete_session, sid, str(cartella_lavoro(progetto)))
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


CHIAVE_NON_VALIDA = ("La chiave API non è valida o è stata revocata. Creane una nuova su platform.claude.com › "
                     "API Keys › Create Key e incollala in Impostazioni › Chiave API della Console.")


def spiega_errore(testo: str) -> str:
    basso = str(testo).lower()
    if "invalid api key" in basso or "authentication_error" in basso or "invalid x-api-key" in basso:
        return CHIAVE_NON_VALIDA
    if "credit balance" in basso:
        return "Crediti API finiti: ricaricali su platform.claude.com › Billing."
    return str(testo)


def riassumi_strumento(nome: str, dati: dict) -> str:
    etichette = {
        "Read": "Legge", "Write": "Scrive", "Edit": "Modifica", "Bash": "Comando",
        "Glob": "Cerca file", "Grep": "Cerca nel testo", "Skill": "Skill",
        "WebSearch": "Cerca sul web", "WebFetch": "Legge una pagina", "TodoWrite": "Aggiorna la lista",
        "Task": "Sotto-agente", "Agent": "Sotto-agente",
    }
    if nome.startswith("mcp__"):
        _, server, azione = (nome.split("__", 2) + ["", ""])[:3]
        etichetta = NOMI_CONNETTORI.get(server, server)
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

    stato = {"client": None, "progetto": None, "consentiti": set(), "costo": 0.0, "lavoro": None,
             "connettori": [], "mcp": {}, "collego": set(), "controllo": None}
    richieste: dict[str, asyncio.Future] = {}
    compiti: set[asyncio.Task] = set()

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
        for compito in (stato["lavoro"], stato["controllo"]):
            if compito and not compito.done():
                compito.cancel()
        if stato["client"]:
            try:
                await stato["client"].disconnect()
            except Exception:
                pass
        stato["client"] = None

    async def apri(progetto: str, sid: str | None, modello: str, permessi: str):
        await chiudi()
        cartella = cartella_progetto(progetto)
        lavoro = cartella_lavoro(progetto)
        if sid and lavoro != cartella:
            chat_permessa(sid, progetto)
        (cartella / "allegati").mkdir(exist_ok=True)
        k = chiave()
        if not k:
            await invia(tipo="errore", testo="Manca la chiave API: aprila nelle Impostazioni.")
            return
        cfg = leggi_config()
        server = {"avvisi": create_sdk_mcp_server("avvisi", tools=[strumento_avviso])}
        estensioni = await asyncio.to_thread(trova_estensioni)
        server.update(estensioni)
        plugin = await asyncio.to_thread(plugin_desktop)
        davinci = estensioni.get("davinci")
        browser = server_browser()
        if browser:
            server["browser"] = browser
        extra = [c for c in cfg.get("cartelle_extra", []) if Path(c).exists()]
        opzioni = ClaudeAgentOptions(
            model=MODELLI.get(modello, MODELLI["opus"]),
            cwd=str(lavoro),
            system_prompt={"type": "preset", "preset": "claude_code", "append": istruzioni(cartella, lavoro)},
            setting_sources=["user", "project"],
            skills="all",
            mcp_servers=server,
            plugins=plugin,
            can_use_tool=chiedi_permesso,
            permission_mode=PERMESSI.get(permessi, "auto"),
            include_partial_messages=True,
            resume=sid,
            add_dirs=[str(BASE), *([str(cartella)] if lavoro != cartella else []), *extra],
            env={"ANTHROPIC_API_KEY": k},
        )
        client = ClaudeSDKClient(options=opzioni)
        await client.connect()
        stato.update(client=client, progetto=cartella, consentiti=set(), costo=0.0)
        await invia(tipo="pronto", davinci=bool(davinci), browser=bool(browser))
        stato["controllo"] = asyncio.create_task(controlla_connettori(client))

    async def leggi_connettori(client) -> None:
        stato["mcp"] = await client.get_mcp_status()
        voci = connettori_remoti(stato["mcp"])
        for v in voci:
            if v["server"] in stato["collego"] and v["stato"] != "ok":
                v["stato"] = "collego"
        stato["connettori"] = voci
        await invia(tipo="connettori", voci=voci)

    async def controlla_connettori(client) -> None:
        """Appena aperta la chat i server remoti si stanno ancora collegando: si guarda per un po'."""
        for _ in range(8):
            try:
                await leggi_connettori(client)
            except Exception:
                return
            if not any(v["stato"] == "attesa" for v in stato["connettori"]):
                return
            await asyncio.sleep(4)

    async def collega(server: str) -> None:
        voce = next((v for v in stato["connettori"] if v["server"] == server and v["stato"] == "login"), None)
        client = stato["client"]
        if not voce or not client:
            return
        stato["collego"].add(server)
        await leggi_connettori(client)
        try:
            ok = await asyncio.to_thread(login_connettore, server)
        finally:
            stato["collego"].discard(server)
        if ok and stato["client"] is client:
            # Il login vale per indirizzo: si ricollegano tutti i server con lo stesso servizio.
            for s in stato["mcp"].get("mcpServers", []):
                if (s.get("config") or {}).get("url") == voce["url"] and s.get("status") != "connected":
                    try:
                        await client.reconnect_mcp_server(s["name"])
                    except Exception:
                        pass
        if stato["client"] is client:
            await leggi_connettori(client)
            if not ok:
                await invia(tipo="errore", testo=f"Collegamento a {voce['nome']} non riuscito o annullato.")

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
                    ricorda_chat(stato["progetto"], m.data.get("session_id"))
                    await invia(tipo="sessione", id=m.data.get("session_id"))
                elif isinstance(m, ResultMessage):
                    if m.total_cost_usd is not None:
                        stato["costo"] = m.total_cost_usd
                    registra_spesa(stato["costo"] - costo_prima)
                    ricorda_chat(stato["progetto"], m.session_id)
                    await invia(tipo="fine", costo=stato["costo"], sessione=m.session_id,
                                errore=spiega_errore(m.result or m.subtype) if m.is_error else None,
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
                elif tipo == "collega" and stato["client"]:
                    compito = asyncio.create_task(collega(str(dati.get("server", ""))))
                    compiti.add(compito)  # un compito senza riferimenti può sparire a metà
                    compito.add_done_callback(compiti.discard)
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
    # Gli hook di avvio di Claude Code (es. graphify su una cartella grande) possono metterci minuti.
    os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "600000")
    prepara_cartelle()
    threading.Thread(target=prepara_sviluppo, daemon=True).start()
    print(f"Assistente All2Points {versione()}: http://127.0.0.1:{PORTA}")
    if not os.environ.get("A2P_NO_BROWSER"):
        threading.Timer(1.5, apri_finestra or (lambda: webbrowser.open(f"http://127.0.0.1:{PORTA}"))).start()
    threading.Thread(target=spegni_se_inattivo, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=PORTA, log_level="warning")


if __name__ == "__main__":
    avvia()

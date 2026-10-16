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
"""Avviatore dell'Assistente All2Points.

- con `--installa`: scarica l'app, crea l'icona (Dock/Applicazioni su Mac, Scrivania e Start su Windows) e la apre;
- senza argomenti (l'icona): scarica l'ultima versione se c'è, avvia il motore e apre la finestra dell'app.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "gianco98/all2points-assistente"
URL_VERSIONE = os.environ.get("A2P_URL_VERSIONE", f"https://api.github.com/repos/{REPO}/commits/main")
URL_ZIP = os.environ.get("A2P_URL_ZIP", f"https://github.com/{REPO}/archive/refs/heads/main.zip")
PORTA = 8765
INDIRIZZO = f"http://127.0.0.1:{PORTA}"
WINDOWS = sys.platform == "win32"
MAC = sys.platform == "darwin"
BASE = Path.home() / "All2Points Assistente"
APP = BASE / "app"
VERSIONE = APP / "VERSIONE"
NOME = "Assistente All2Points"


def log(testo: str) -> None:
    riga = f"{time.strftime('%d/%m %H:%M:%S')} {testo}"
    if sys.stdout:
        print(testo, flush=True)
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        with (BASE / "avvio.log").open("a", encoding="utf-8") as f:
            f.write(riga + "\n")
    except OSError:
        pass


# ---------- aggiornamento ----------

def versione_online() -> str | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(URL_VERSIONE, headers={"User-Agent": "a2p"}), timeout=10) as r:
            return json.load(r)["sha"]
    except Exception:
        return None


def versione_locale() -> str | None:
    try:
        return VERSIONE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def aggiorna(sha: str) -> bool:
    """Scarica la versione nuova in una cartella temporanea e la mette al posto di quella vecchia.
    Tocca solo la cartella `app`: chat, progetti, regole e impostazioni restano dove sono."""
    try:
        with urllib.request.urlopen(urllib.request.Request(URL_ZIP, headers={"User-Agent": "a2p"}), timeout=60) as r:
            dati = r.read()
        BASE.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="a2p-", dir=BASE))
        with zipfile.ZipFile(io.BytesIO(dati)) as z:
            z.extractall(tmp)
        radici = [p for p in tmp.iterdir() if p.is_dir()]
        nuova = radici[0] if len(radici) == 1 else tmp
        if not (nuova / "app.py").exists():
            raise RuntimeError("pacchetto scaricato non valido")
        (nuova / "VERSIONE").write_text(sha, encoding="utf-8")
        vecchia = BASE / "app-vecchia"
        shutil.rmtree(vecchia, ignore_errors=True)
        if APP.exists():
            # Su Windows una cartella in uso non si può rinominare: dopo lo spegnimento del motore
            # i file vengono rilasciati con un attimo di ritardo, quindi si riprova per qualche secondo.
            for tentativo in range(20):
                try:
                    APP.rename(vecchia)
                    break
                except OSError:
                    if tentativo == 19:
                        raise
                    time.sleep(0.5)
        shutil.move(str(nuova), str(APP))
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(vecchia, ignore_errors=True)
        log(f"Aggiornato alla versione {sha[:7]}")
        return True
    except Exception as errore:
        log(f"Aggiornamento non riuscito ({errore}): uso la versione che c'è")
        if not APP.exists() and (BASE / "app-vecchia").exists():
            (BASE / "app-vecchia").rename(APP)
        return False


# ---------- motore e finestra ----------

def motore_acceso() -> dict | None:
    try:
        with urllib.request.urlopen(f"{INDIRIZZO}/api/stato", timeout=3) as r:
            return json.load(r)
    except Exception:
        return None


def spegni_motore() -> bool:
    try:
        richiesta = urllib.request.Request(f"{INDIRIZZO}/api/spegni", method="POST")
        urllib.request.urlopen(richiesta, timeout=5)
    except Exception:
        return False
    for _ in range(30):
        if not motore_acceso():
            return True
        time.sleep(0.3)
    return False


def apri_finestra() -> None:
    """Apre l'app in una finestra sua (Chrome o Edge in modalità app); altrimenti nel browser."""
    argomenti = [f"--app={INDIRIZZO}", "--window-size=1280,860"]
    if MAC:
        for nome in ("Google Chrome", "Microsoft Edge", "Brave Browser"):
            if Path(f"/Applications/{nome}.app").exists():
                subprocess.Popen(["open", "-na", nome, "--args", *argomenti])
                return
        subprocess.Popen(["open", INDIRIZZO])
        return
    if WINDOWS:
        candidati = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft/Edge/Application/msedge.exe",
        ]
        for exe in candidati:
            if exe.exists():
                subprocess.Popen([str(exe), *argomenti])
                return
    import webbrowser
    webbrowser.open(INDIRIZZO)


def trova_uv() -> str | None:
    for nome in (["uvw", "uv"] if WINDOWS else ["uv"]):
        trovato = shutil.which(nome) or shutil.which(nome, path=str(Path.home() / ".local" / "bin"))
        if trovato:
            return trovato
    return None


def riavvia_da_app_aggiornata() -> None:
    """Dopo un aggiornamento riparte usando l'avviatore nuovo (che può avere novità)."""
    uv = trova_uv()
    if not uv:
        return
    subprocess.Popen([uv, "run", "--script", str(APP / "avvia.py"), "--dopo-aggiornamento"])
    sys.exit(0)


# ---------- icona ----------

def crea_collegamenti() -> None:
    uv = trova_uv()
    if not uv:
        log("Non trovo uv: icona non creata")
        return
    avvia = APP / "avvia.py"
    if MAC:
        destinazione = Path.home() / "Applications" / f"{NOME}.app"
        destinazione.parent.mkdir(exist_ok=True)
        shutil.rmtree(destinazione, ignore_errors=True)
        comando = f"'{uv}' run --script '{avvia}' > /dev/null 2>&1 &"
        script = f'do shell script "{comando}"'
        subprocess.run(["osacompile", "-o", str(destinazione), "-e", script], check=True)
        # Icona: dal PNG all'.icns con gli strumenti del Mac.
        try:
            png = APP / "static" / "logo-512.png"
            cartella = Path(tempfile.mkdtemp()) / "logo.iconset"
            cartella.mkdir()
            for lato in (16, 32, 128, 256, 512):
                subprocess.run(["sips", "-z", str(lato), str(lato), str(png), "--out", str(cartella / f"icon_{lato}x{lato}.png")],
                               check=True, capture_output=True)
                subprocess.run(["sips", "-z", str(lato * 2), str(lato * 2), str(png), "--out", str(cartella / f"icon_{lato}x{lato}@2x.png")],
                               check=True, capture_output=True)
            subprocess.run(["iconutil", "-c", "icns", str(cartella), "-o", str(destinazione / "Contents/Resources/applet.icns")],
                           check=True, capture_output=True)
            subprocess.run(["touch", str(destinazione)])
        except Exception as errore:
            log(f"Icona personalizzata non applicata: {errore}")
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(destinazione)], capture_output=True)
        # Nel Dock.
        subprocess.run(["defaults", "write", "com.apple.dock", "persistent-apps", "-array-add",
                        f"<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key>"
                        f"<string>{destinazione}</string><key>_CFURLStringType</key><integer>0</integer>"
                        f"</dict></dict></dict>"], capture_output=True)
        subprocess.run(["killall", "Dock"], capture_output=True)
        log(f"App creata in {destinazione} e aggiunta al Dock")
    elif WINDOWS:
        icona = APP / "static" / "logo.ico"
        posti = [
            Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop",
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        ]
        for cartella in posti:
            lnk = cartella / f"{NOME}.lnk"
            ps = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:A2P_LNK);"
                "$s.TargetPath=$env:A2P_UV;$s.Arguments=$env:A2P_ARGS;"
                "$s.WorkingDirectory=$env:A2P_DIR;$s.IconLocation=$env:A2P_ICO;$s.Save()"
            )
            env = dict(os.environ, A2P_LNK=str(lnk), A2P_UV=uv, A2P_ARGS=f'run --script "{avvia}"',
                       A2P_DIR=str(BASE), A2P_ICO=str(icona))
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], env=env, check=False)
        log("Icona creata sulla Scrivania e nel menu Start")


# ---------- avvio ----------

def completa_path() -> None:
    """Aperta dal Dock, l'app su Mac riceve un PATH ridotto (/usr/bin:/bin…) e non trova Node,
    che serve a DaVinci e al browser automatico. Si aggiungono le cartelle dove di solito sta."""
    cartelle = [Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    cartelle += sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin"), reverse=True)[:1]
    attuali = os.environ.get("PATH", "").split(os.pathsep)
    nuove = [str(c) for c in cartelle if c.is_dir() and str(c) not in attuali]
    if nuove:
        os.environ["PATH"] = os.pathsep.join(nuove + attuali)


def main() -> None:
    completa_path()
    # L'icona di Windows parte con la cartella app come cartella di lavoro: spostarsi fuori,
    # altrimenti Windows non permette di sostituirla durante l'aggiornamento.
    BASE.mkdir(parents=True, exist_ok=True)
    os.chdir(BASE)
    installa = "--installa" in sys.argv
    dopo_aggiornamento = "--dopo-aggiornamento" in sys.argv

    online = None if dopo_aggiornamento else versione_online()
    aggiornata = False
    if online and online != versione_locale():
        stato = motore_acceso()
        if stato and not spegni_motore():
            # Sta lavorando: si aggiorna al prossimo avvio.
            apri_finestra()
            return
        aggiornata = aggiorna(online)
    if not APP.exists():
        log("L'app non è installata e non riesco a scaricarla: controlla la connessione e riprova.")
        sys.exit(1)

    if installa:
        crea_collegamenti()
    if aggiornata:
        riavvia_da_app_aggiornata()

    if motore_acceso():
        apri_finestra()
        return

    sys.path.insert(0, str(APP))
    import app  # noqa: E402  (l'app aggiornata, appena scaricata)
    app.avvia(apri_finestra)


if __name__ == "__main__":
    main()

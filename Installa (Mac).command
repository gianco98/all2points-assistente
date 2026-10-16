#!/bin/bash
# Installa l'Assistente All2Points sul Mac. Serve una volta sola: poi si apre dall'icona e si aggiorna da solo.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "Installo l'Assistente All2Points..."
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh || { echo "Installazione di uv non riuscita: controlla la connessione."; read -rp "Premi Invio per chiudere."; exit 1; }
fi
uv run --script https://raw.githubusercontent.com/gianco98/all2points-assistente/main/avvia.py --installa
echo
echo "Fatto. D'ora in poi apri l'app dall'icona «Assistente All2Points» nel Dock o in Applicazioni."
read -rp "Premi Invio per chiudere questa finestra."

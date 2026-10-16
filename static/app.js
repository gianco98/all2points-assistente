// Assistente All2Points: interfaccia della chat.
const $ = (s) => document.querySelector(s);
const el = {
  progetto: $('#progetto'), elenco: $('#chat-elenco'), messaggi: $('#messaggi'), testo: $('#testo'),
  form: $('#scrivi'), invia: $('#invia'), stop: $('#stop'), modello: $('#modello'), costo: $('#costo'),
  titolo: $('#titolo-chat'), allegati: $('#allegati'), file: $('#file'), strumenti: $('#strumenti'),
  spesaMese: $('#spesa-mese'),
};

let stato = { progetto: null, sessione: null, lavoro: false, allegati: [], bolla: null, ws: null, pronto: false, inAttesa: [], coda: [] };

// ---- comandi dichiarativi per i <dialog> (fallback per browser senza Invoker Commands) ----
if (!('commandForElement' in HTMLButtonElement.prototype)) {
  document.addEventListener('click', (e) => {
    const b = e.target.closest('button[commandfor]');
    if (!b) return;
    const d = document.getElementById(b.getAttribute('commandfor'));
    const c = b.getAttribute('command');
    if (c === 'show-modal') d?.showModal();
    else if (c === 'close') d?.close();
  });
}

// ---- markdown essenziale, sicuro (prima si fa l'escape dell'HTML) ----
const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}
function markdown(testo) {
  const righe = esc(testo).split('\n');
  let html = '', lista = null, codice = false;
  const chiudiLista = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  for (const r of righe) {
    if (r.startsWith('```')) { chiudiLista(); html += codice ? '</code></pre>' : '<pre><code>'; codice = !codice; continue; }
    if (codice) { html += r + '\n'; continue; }
    let m;
    if ((m = r.match(/^(#{1,4})\s+(.*)/))) { chiudiLista(); const n = Math.min(m[1].length + 2, 6); html += `<h${n}>${inline(m[2])}</h${n}>`; }
    else if ((m = r.match(/^\s*[-*•]\s+(.*)/))) { if (lista !== 'ul') { chiudiLista(); html += '<ul>'; lista = 'ul'; } html += `<li>${inline(m[1])}</li>`; }
    else if ((m = r.match(/^\s*\d+[.)]\s+(.*)/))) { if (lista !== 'ol') { chiudiLista(); html += '<ol>'; lista = 'ol'; } html += `<li>${inline(m[1])}</li>`; }
    else if (r.trim() === '') { chiudiLista(); }
    else { chiudiLista(); html += `<p>${inline(r)}</p>`; }
  }
  chiudiLista();
  if (codice) html += '</code></pre>';
  return html;
}

// ---- API ----
async function api(percorso, opzioni = {}) {
  const r = await fetch(percorso, { headers: { 'Content-Type': 'application/json' }, ...opzioni });
  const dati = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(dati.detail || dati.errore || `Errore ${r.status}`);
  return dati;
}
const q = (p) => `progetto=${encodeURIComponent(p)}`;
const dollari = (n) => `${(n || 0).toFixed(2)} $`;

// ---- messaggi ----
function scorri() { el.messaggi.scrollTop = el.messaggi.scrollHeight; }
function aggiungi(classe, contenuto, html = false) {
  el.messaggi.querySelector('.vuoto')?.remove();
  const d = document.createElement('div');
  d.className = classe;
  if (html) d.innerHTML = contenuto; else d.textContent = contenuto;
  el.messaggi.append(d);
  scorri();
  return d;
}
function indicatore(acceso) {
  el.messaggi.querySelector('.lavoro')?.remove();
  if (acceso) aggiungi('lavoro', 'Claude sta lavorando');
}
function vuoto() {
  el.messaggi.innerHTML = `<div class="vuoto"><h2>Ciao${window.nomeUtente ? ', ' + esc(window.nomeUtente) : ''}!</h2>
  <p>Scrivi cosa ti serve: un montaggio in DaVinci, un testo, un controllo su un sito.
  Le chat restano salvate nel progetto e puoi riprenderle quando vuoi.</p></div>`;
}
function inLavoro(si) {
  stato.lavoro = si;
  el.invia.hidden = si;
  el.stop.hidden = !si;
  indicatore(si);
}

// ---- connessione ----
function connetti() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  stato.ws = ws;
  stato.pronto = false;
  ws.onmessage = (e) => ricevi(JSON.parse(e.data));
  ws.onclose = () => { stato.pronto = false; setTimeout(connetti, 1500); };
  // Prima connessione: manda quello che era in coda. Dopo una caduta: riapre la chat in corso.
  ws.onopen = () => {
    const coda = stato.coda.splice(0);
    if (coda.length) coda.forEach((d) => ws.send(JSON.stringify(d)));
    else if (stato.progetto) apriChat(stato.sessione);
  };
}
function invia(dati) {
  if (stato.ws?.readyState === 1) stato.ws.send(JSON.stringify(dati));
  else if (dati.tipo === 'apri') stato.coda = [dati];
}

function ricevi(m) {
  switch (m.tipo) {
    case 'pronto':
      stato.pronto = true;
      for (const d of stato.inAttesa.splice(0)) invia(d);
      break;
    case 'sessione':
      if (m.id && m.id !== stato.sessione) { stato.sessione = m.id; }
      break;
    case 'testo':
      indicatore(false);
      if (!stato.bolla) { stato.bolla = aggiungi('msg claude', ''); stato.bolla.dataset.md = ''; }
      stato.bolla.dataset.md += m.testo;
      stato.bolla.innerHTML = markdown(stato.bolla.dataset.md);
      scorri();
      break;
    case 'strumento':
      stato.bolla = null;
      indicatore(false);
      aggiungi('strumento' + (m.sotto ? ' sotto' : ''), '⚙ ' + m.testo);
      indicatore(true);
      break;
    case 'permesso':
      indicatore(false);
      mostraPermesso(m);
      break;
    case 'fine':
      stato.bolla = null;
      inLavoro(false);
      if (m.errore) aggiungi('msg claude errore', m.errore);
      el.costo.textContent = `Questa chat: ${dollari(m.costo)}`;
      el.spesaMese.textContent = `Speso questo mese: ${dollari(m.spesa_mese)}`;
      if (m.sessione) { stato.sessione = m.sessione; ultimaChat.salva(stato.progetto, m.sessione); }
      caricaChat();
      break;
    case 'errore':
      inLavoro(false);
      aggiungi('msg claude errore', m.testo);
      break;
  }
}

function mostraPermesso(m) {
  const nodo = $('#tpl-permesso').content.firstElementChild.cloneNode(true);
  nodo.querySelector('.dettaglio').textContent = m.dettaglio;
  nodo.querySelector('pre').textContent = m.completo;
  nodo.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    invia({ tipo: 'permesso', id: m.id, risposta: b.dataset.r });
    nodo.classList.add('risolto');
    nodo.querySelectorAll('button').forEach((x) => (x.disabled = true));
    nodo.querySelector('.dettaglio').textContent += b.dataset.r === 'no' ? ' — negato' : ' — consentito';
    indicatore(true);
  }));
  el.messaggi.append(nodo);
  scorri();
}

// ---- progetti e chat ----
async function caricaProgetti(scegli) {
  const elenco = await api('/api/progetti');
  el.progetto.innerHTML = '';
  if (!elenco.length) {
    await api('/api/progetti', { method: 'POST', body: JSON.stringify({ nome: 'Generale' }) });
    return caricaProgetti('Generale');
  }
  for (const p of elenco) el.progetto.append(new Option(p.nome, p.nome));
  const salvato = scegli || localStorage.getItem('a2p-progetto');
  if (salvato && elenco.some((p) => p.nome === salvato)) el.progetto.value = salvato;
  await cambiaProgetto();
}

// Ricorda l'ultima chat aperta di ogni progetto, così alla riapertura si riparte da lì.
const ultimaChat = {
  leggi: (p) => { try { return localStorage.getItem('a2p-chat-' + p); } catch { return null; } },
  salva: (p, sid) => { try { sid ? localStorage.setItem('a2p-chat-' + p, sid) : localStorage.removeItem('a2p-chat-' + p); } catch {} },
};

async function cambiaProgetto() {
  stato.progetto = el.progetto.value;
  try { localStorage.setItem('a2p-progetto', stato.progetto); } catch {}
  const chat = await caricaChat();
  const ultima = ultimaChat.leggi(stato.progetto);
  const trovata = chat.find((c) => c.id === ultima);
  apriChat(trovata ? trovata.id : null, trovata?.titolo);
}

async function caricaChat() {
  if (!stato.progetto) return [];
  const chat = await api(`/api/chat?${q(stato.progetto)}`);
  el.elenco.innerHTML = '';
  for (const c of chat) {
    const a = document.createElement('a');
    a.href = '#';
    a.innerHTML = `<span></span><button title="Elimina chat" aria-label="Elimina chat">✕</button>`;
    a.querySelector('span').textContent = c.titolo;
    a.title = c.titolo;
    if (c.id === stato.sessione) { a.setAttribute('aria-current', 'true'); el.titolo.textContent = c.titolo; }
    a.addEventListener('click', (e) => {
      e.preventDefault();
      if (e.target.closest('button')) return eliminaChat(c);
      if (!stato.lavoro) apriChat(c.id, c.titolo);
    });
    a.addEventListener('dblclick', () => rinominaChat(c));
    el.elenco.append(a);
  }
  return chat;
}

async function apriChat(sid, titolo) {
  stato.sessione = sid;
  ultimaChat.salva(stato.progetto, sid);
  stato.bolla = null;
  stato.pronto = false;
  el.costo.textContent = '';
  el.titolo.textContent = titolo || 'Nuova chat';
  el.elenco.querySelectorAll('a').forEach((a) => a.removeAttribute('aria-current'));
  vuoto();
  if (sid) {
    const righe = await api(`/api/chat/${sid}?${q(stato.progetto)}`);
    if (righe.length) el.messaggi.innerHTML = '';
    for (const r of righe) {
      if (r.ruolo === 'user') aggiungi('msg utente', r.testo.replace(/\n\nAllegati \(leggili con Read\):[\s\S]*$/, ' 📎'));
      else if (r.ruolo === 'assistant') aggiungi('msg claude', markdown(r.testo), true);
      else aggiungi('strumento', '⚙ ' + r.testo);
    }
    caricaChat();
  }
  invia({ tipo: 'apri', progetto: stato.progetto, sessione: sid, modello: el.modello.value });
}

async function eliminaChat(c) {
  if (!confirm(`Eliminare la chat «${c.titolo}»? Non si può annullare.`)) return;
  await api(`/api/chat/${c.id}?${q(stato.progetto)}`, { method: 'DELETE' });
  if (c.id === stato.sessione) apriChat(null);
  caricaChat();
}

async function rinominaChat(c) {
  const titolo = prompt('Nuovo nome della chat', c.titolo);
  if (!titolo) return;
  await api(`/api/chat/${c.id}/rinomina?${q(stato.progetto)}`, { method: 'POST', body: JSON.stringify({ titolo }) });
  caricaChat();
}

// ---- invio e allegati ----
async function caricaFile(files) {
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', f, f.name || 'screenshot.png');
    const r = await fetch(`/api/allegati?${q(stato.progetto)}`, { method: 'POST', body: fd });
    if (!r.ok) { aggiungi('msg claude errore', `Non riesco ad allegare ${f.name}`); continue; }
    const dati = await r.json();
    stato.allegati.push(dati);
  }
  mostraAllegati();
}
function mostraAllegati() {
  el.allegati.innerHTML = '';
  stato.allegati.forEach((a, i) => {
    const s = document.createElement('span');
    s.textContent = '📎 ' + a.nome;
    const x = document.createElement('button');
    x.type = 'button'; x.textContent = '✕'; x.setAttribute('aria-label', 'Togli allegato');
    x.onclick = () => { stato.allegati.splice(i, 1); mostraAllegati(); };
    s.append(x);
    el.allegati.append(s);
  });
}

el.form.addEventListener('submit', (e) => {
  e.preventDefault();
  const testo = el.testo.value.trim();
  if ((!testo && !stato.allegati.length) || stato.lavoro) return;
  const dati = { tipo: 'messaggio', testo: testo || 'Guarda gli allegati.', allegati: stato.allegati.map((a) => a.percorso) };
  aggiungi('msg utente', testo + (stato.allegati.length ? `\n📎 ${stato.allegati.map((a) => a.nome).join(', ')}` : ''));
  el.testo.value = '';
  stato.allegati = [];
  mostraAllegati();
  stato.bolla = null;
  inLavoro(true);
  if (stato.pronto) invia(dati); else stato.inAttesa.push(dati);
});
el.testo.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); el.form.requestSubmit(); }
});
el.stop.addEventListener('click', () => invia({ tipo: 'stop' }));
el.modello.addEventListener('change', () => invia({ tipo: 'modello', modello: el.modello.value }));
el.progetto.addEventListener('change', () => { if (!stato.lavoro) cambiaProgetto(); });
$('#nuova-chat').addEventListener('click', () => { if (!stato.lavoro) { apriChat(null); caricaChat(); } });
el.file.addEventListener('change', () => { caricaFile([...el.file.files]); el.file.value = ''; });
el.testo.addEventListener('paste', (e) => {
  const immagini = [...e.clipboardData.files];
  if (immagini.length) { e.preventDefault(); caricaFile(immagini); }
});
el.form.addEventListener('dragover', (e) => { e.preventDefault(); el.form.classList.add('trascina'); });
el.form.addEventListener('dragleave', () => el.form.classList.remove('trascina'));
el.form.addEventListener('drop', (e) => { e.preventDefault(); el.form.classList.remove('trascina'); caricaFile([...e.dataTransfer.files]); });

// ---- finestre ----
$('#form-progetto').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return;
  e.preventDefault();
  const nome = $('#nome-progetto').value.trim();
  try {
    const p = await api('/api/progetti', { method: 'POST', body: JSON.stringify({ nome }) });
    $('#dlg-progetto').close();
    $('#nome-progetto').value = '';
    await caricaProgetti(p.nome);
  } catch (err) { alert(err.message); }
});

async function caricaStato() {
  const s = await api('/api/stato');
  window.nomeUtente = s.nome;
  $('#imp-nome').value = s.nome;
  $('#imp-modello').value = s.modello;
  $('#imp-cartelle').value = s.cartelle_extra.join('\n');
  $('#imp-topic').textContent = s.avvisi_topic;
  $('#imp-chiave-stato').textContent = s.chiave ? 'Chiave salvata ✓' : 'Nessuna chiave salvata: incollala qui sopra.';
  document.querySelector(`input[name="browser"][value="${s.browser_modo}"]`).checked = true;
  $('#imp-token-stato').textContent = s.estensione_token
    ? 'Codice salvato ✓'
    : 'Senza codice, la prima volta che Claude usa il browser ti chiede di approvare il collegamento in Chrome.';
  if (!el.modello.dataset.toccato) el.modello.value = s.modello;
  el.spesaMese.textContent = `Speso questo mese: ${dollari(s.spesa_mese)}`;
  $('#versione').textContent = `Versione ${s.versione}`;
  const t = s.strumenti;
  el.strumenti.innerHTML = [['DaVinci', t.davinci], ['Browser', t.browser], ['Skill', t.skill]]
    .map(([n, ok]) => `<span class="${ok ? 'ok' : 'no'}" title="${ok ? 'Collegato' : 'Non disponibile su questo computer'}">${n}</span>`).join('');
  return s;
}
el.modello.addEventListener('change', () => (el.modello.dataset.toccato = '1'));

$('#form-impostazioni').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return;
  e.preventDefault();
  $('#imp-errore').textContent = '';
  try {
    await api('/api/impostazioni', { method: 'POST', body: JSON.stringify({
      nome: $('#imp-nome').value.trim(),
      chiave: $('#imp-chiave').value.trim(),
      modello: $('#imp-modello').value,
      cartelle_extra: $('#imp-cartelle').value.split('\n'),
      browser_modo: document.querySelector('input[name="browser"]:checked')?.value,
      estensione_token: $('#imp-token').value.trim(),
    }) });
    $('#imp-chiave').value = '';
    $('#imp-token').value = '';
    await caricaStato();
    $('#dlg-impostazioni').close();
    apriChat(stato.sessione);
  } catch (err) { $('#imp-errore').textContent = err.message; }
});
$('#prova-avviso').addEventListener('click', async () => {
  const r = await api('/api/avviso-prova', { method: 'POST' });
  alert(r.ok ? 'Avviso inviato: controlla il telefono.' : 'Avviso non inviato: controlla la connessione.');
});

// ---- avvio ----
(async () => {
  const s = await caricaStato();
  connetti();
  await caricaProgetti();
  if (!s.chiave) $('#dlg-impostazioni').showModal();
})();

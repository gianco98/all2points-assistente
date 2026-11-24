// Assistente All2Points: interfaccia della chat.
const $ = (s) => document.querySelector(s);
const el = {
  progetto: $('#progetto'), elenco: $('#chat-elenco'), messaggi: $('#messaggi'), testo: $('#testo'),
  form: $('#scrivi'), invia: $('#invia'), stop: $('#stop'), modello: $('#modello'), costo: $('#costo'),
  titolo: $('#titolo-chat'), allegati: $('#allegati'), file: $('#file'), strumenti: $('#strumenti'),
  spesaMese: $('#spesa-mese'), contesto: $('#contesto'),
  anteprima: $('#anteprima'), anteprimaFile: $('#anteprima-file'), anteprimaFrame: $('#anteprima-frame'),
  anteprimaMessaggio: $('#anteprima-messaggio'), anteprimaUrl: $('#anteprima-url'),
  coda: $('#coda'), avvisi: $('#avvisi'), schede: $('#schede'),
  main: $('main'), permessi: $('#permessi'), collegamento: $('#collegamento'), velo: $('#velo-lato'),
  menuModello: $('#menu-modello'), menuPermessi: $('#menu-permessi'), popStrumenti: $('#pop-strumenti'),
  apriStrumenti: $('#apri-strumenti'), strumentiConto: $('#strumenti-conto'), versione: $('#versione'),
};

// storicoInCorso: la cronologia della chat si sta caricando via HTTP; gli eventi dal vivo aspettano (buffer) per non finire cancellati.
// attaccato: la vista è in fondo, quindi i nuovi messaggi la fanno scorrere.
let stato = { progetto: null, sessione: null, chiave: null, lavoro: false, allegati: [], bolla: null, ws: null, pronto: false, inAttesa: [], coda: [], passi: null, inCorso: [], apertura: 0, storicoInCorso: false, buffer: [], attaccato: true, nuovi: false, elenchi: {}, costoTesto: '', contestoTesto: '' };
const TITOLO = 'Assistente All2Points';
const icona = (nome, classe = '') => `<svg class="ic ${classe}" aria-hidden="true"><use href="#i-${nome}"/></svg>`;

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
const dollari = (n) => (n > 0 && n < 0.01 ? '< 0.01 $' : `${(n || 0).toFixed(2)} $`);

// ---- messaggi ----
const giu = $('#giu');
function aggiornaGiu() {
  giu.hidden = stato.attaccato;
  giu.classList.toggle('con-testo', !stato.attaccato && stato.nuovi);
  giu.querySelector('.giu-testo').textContent = stato.nuovi ? 'Nuovi messaggi' : '';
  giu.setAttribute('aria-label', stato.nuovi ? 'Nuovi messaggi: vai in fondo' : 'Vai in fondo');
}
el.messaggi.addEventListener('scroll', () => {
  stato.attaccato = el.messaggi.scrollHeight - el.messaggi.scrollTop - el.messaggi.clientHeight < 80;
  if (stato.attaccato) stato.nuovi = false;
  aggiornaGiu();
}, { passive: true });
// Scorre in fondo solo se chi legge era già in fondo (o se lo chiede lui: invio, apertura chat). Altrimenti la vista resta ferma.
function scorri(forza = false) {
  if (forza) { stato.attaccato = true; stato.nuovi = false; }
  if (stato.attaccato) el.messaggi.scrollTop = el.messaggi.scrollHeight;
  else stato.nuovi = true;
  aggiornaGiu();
}
giu.addEventListener('click', () => {
  const ridotto = matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.messaggi.scrollTo({ top: el.messaggi.scrollHeight, behavior: ridotto ? 'auto' : 'smooth' });
});
// La chat vuota ha il saluto al centro e la casella subito sotto; con i messaggi la casella torna in basso.
new MutationObserver(() => {
  el.main.classList.toggle('vuota', !!el.messaggi.querySelector(':scope > .vuoto'));
}).observe(el.messaggi, { childList: true });

function aggiungi(classe, contenuto, html = false) {
  el.messaggi.querySelector('.vuoto')?.remove();
  const d = document.createElement('div');
  d.className = classe;
  if (html) d.innerHTML = contenuto; else d.textContent = contenuto;
  el.messaggi.append(d);
  scorri();
  return d;
}
// Strumenti usati: righe compatte; più di 3 di fila stanno in un blocco «N azioni» che si apre e si chiude.
function aggiungiStrumento(testo, sotto = false) {
  el.messaggi.querySelector('.vuoto')?.remove();
  let blocco = el.messaggi.lastElementChild;
  if (!blocco?.classList.contains('blocco-azioni')) {
    blocco = document.createElement('div');
    blocco.className = 'blocco-azioni';
    const testa = document.createElement('button');
    testa.type = 'button';
    testa.className = 'blocco-testa';
    testa.hidden = true;
    testa.setAttribute('aria-expanded', 'false');
    testa.addEventListener('click', () => {
      const aperto = blocco.classList.toggle('aperto');
      testa.setAttribute('aria-expanded', String(aperto));
    });
    const righe = document.createElement('div');
    righe.className = 'blocco-righe';
    blocco.append(testa, righe);
    el.messaggi.append(blocco);
  }
  const riga = document.createElement('div');
  riga.className = 'strumento' + (sotto ? ' sotto' : '');
  riga.innerHTML = icona('terminale');
  const t = document.createElement('span');
  t.textContent = testo;
  riga.title = testo;
  riga.append(t);
  const righe = blocco.querySelector('.blocco-righe');
  righe.append(riga);
  const n = righe.children.length;
  const testa = blocco.querySelector('.blocco-testa');
  blocco.classList.toggle('compatto', n > 3);
  testa.hidden = n <= 3;
  testa.innerHTML = `${icona('chevron-dx')}<span>${n} azioni</span>`;
  scorri();
}
// Riquadro «Passi»: la lista di Claude, aggiornata sul posto. Crea il riquadro se non c'è, altrimenti lo riscrive.
function disegnaPassi(passi, nodo) {
  if (!nodo) {
    el.messaggi.querySelector('.vuoto')?.remove();
    nodo = document.createElement('div');
    nodo.className = 'passi';
    const titolo = document.createElement('strong');
    titolo.textContent = 'Passi';
    nodo.append(titolo, document.createElement('ul'));
    el.messaggi.append(nodo);
  }
  nodo.querySelector('ul').replaceChildren(...passi.map((p) => {
    const li = document.createElement('li');
    li.className = p.stato;
    li.textContent = p.testo;
    return li;
  }));
  return nodo;
}
function indicatore(acceso) {
  el.messaggi.querySelector('.lavoro')?.remove();
  if (!acceso) return;
  el.messaggi.querySelector('.vuoto')?.remove();
  const d = document.createElement('div');
  d.className = 'lavoro';
  d.innerHTML = '<i></i><i></i><i></i><span class="sr">Claude sta lavorando</span>';
  el.messaggi.append(d);
  scorri();
}
function vuoto() {
  const nome = window.nomeUtente ? `, ${esc(window.nomeUtente)}` : '';
  el.messaggi.innerHTML = `<div class="vuoto">${icona('marchio', 'vuoto-marchio')}<h2>Ciao${nome}</h2>
  <p>Scrivi cosa ti serve: un montaggio in DaVinci, un testo, un controllo su un sito.</p></div>`;
}
function inLavoro(si) {
  stato.lavoro = si;
  el.stop.hidden = !si;
  el.invia.title = si ? 'Claude sta lavorando: il messaggio va in coda' : 'Invia';
  indicatore(si);
  segniInCorso();
}
// Chat al lavoro: l'elenco globale arriva dal motore, vale per qualsiasi chat di qualsiasi progetto.
function segniInCorso() {
  const qui = stato.inCorso.filter((x) => x.progetto === stato.progetto);
  el.elenco.querySelectorAll('a').forEach((a) => {
    const lavora = a.dataset.sid ? qui.some((x) => x.sessione === a.dataset.sid) : false;
    a.classList.toggle('in-corso', lavora || (a.dataset.corrente === '1' && stato.lavoro));
  });
  const progetti = new Set(stato.inCorso.map((x) => x.progetto));
  for (const o of el.progetto.options) o.text = o.dataset.base + (progetti.has(o.value) ? ' ●' : '');
  schede.disegna();
}
// «Collegamento…»: il motore della chat si sta avviando. Si può scrivere lo stesso: il messaggio parte quando è pronto.
function aggiornaCollegamento() {
  el.collegamento.hidden = stato.pronto || !stato.progetto;
}
function aggiornaInvia() {
  el.invia.disabled = !el.testo.value.trim() && !stato.allegati.length;
}
// Riquadro «In coda»: i messaggi scritti mentre Claude lavora.
function disegnaCoda(coda) {
  el.coda.hidden = !coda.length;
  const titolo = document.createElement('strong');
  titolo.textContent = 'In coda';
  const voci = coda.map((c) => {
    const riga = document.createElement('div');
    riga.className = 'coda-voce';
    const testo = document.createElement('span');
    testo.textContent = c.testo;
    const bottone = (etichetta, aiuto, tipo, classe) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = classe;
      if (etichetta) b.textContent = etichetta; else { b.innerHTML = icona('x'); b.setAttribute('aria-label', aiuto); }
      b.title = aiuto;
      b.addEventListener('click', () => invia({ tipo, id: c.id }));
      return b;
    };
    riga.append(testo,
      bottone('Aggiungi al lavoro', 'Claude lo legge al prossimo passo senza fermarsi', 'manda_ora', 'secondario'),
      bottone('Ferma e manda', 'Interrompe il lavoro e manda subito questo messaggio', 'ferma_e_manda', 'secondario'),
      bottone('', 'Togli dalla coda', 'togli', 'ib'));
    return riga;
  });
  el.coda.replaceChildren(titolo, ...voci);
}

// ---- menu a comparsa (modello, permessi, strumenti) ----
let menuAperto = null;
function chiudiMenu(rendiFuoco = false) {
  if (!menuAperto) return;
  const { ancora, nodo, creato } = menuAperto;
  menuAperto = null;
  if (creato) nodo.remove(); else nodo.hidden = true;
  ancora.setAttribute('aria-expanded', 'false');
  if (rendiFuoco) ancora.focus();
}
function posizionaMenu(ancora, nodo, su) {
  const r = ancora.getBoundingClientRect();
  nodo.style.visibility = 'hidden';
  nodo.style.left = nodo.style.right = nodo.style.top = nodo.style.bottom = 'auto';
  const l = nodo.offsetWidth;
  let sinistra = su === 'lato' ? r.left : r.right - l;
  sinistra = Math.max(8, Math.min(sinistra, innerWidth - l - 8));
  nodo.style.left = `${sinistra}px`;
  if (su) nodo.style.bottom = `${innerHeight - r.top + 8}px`; else nodo.style.top = `${r.bottom + 8}px`;
  nodo.style.visibility = '';
}
function apriMenu(ancora, nodo, { su = false, creato = false } = {}) {
  const stessa = menuAperto?.ancora === ancora;
  chiudiMenu();
  if (stessa) return;
  if (creato) document.body.append(nodo); else nodo.hidden = false;
  ancora.setAttribute('aria-expanded', 'true');
  posizionaMenu(ancora, nodo, su);
  menuAperto = { ancora, nodo, creato };
  nodo.querySelector('[aria-checked="true"], .menu-voce')?.focus();
}
document.addEventListener('pointerdown', (e) => {
  if (menuAperto && !menuAperto.nodo.contains(e.target) && !menuAperto.ancora.contains(e.target)) chiudiMenu();
});
document.addEventListener('keydown', (e) => {
  if (!menuAperto) return;
  if (e.key === 'Escape') { e.preventDefault(); chiudiMenu(true); return; }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  const voci = [...menuAperto.nodo.querySelectorAll('.menu-voce')];
  if (!voci.length) return;
  e.preventDefault();
  const i = voci.indexOf(document.activeElement);
  voci[(i + (e.key === 'ArrowDown' ? 1 : -1) + voci.length) % voci.length].focus();
});
addEventListener('resize', () => chiudiMenu());

const SCELTE = {
  modello: [
    ['opus', 'Opus', 'Montaggio e lavori difficili'],
    ['sonnet', 'Sonnet', 'Lavoro normale, costa la metà'],
    ['haiku', 'Haiku', 'Cose semplici, costa pochissimo'],
  ],
  permessi: [
    ['auto', 'Automatico', 'Claude lavora senza chiedere'],
    ['chiedi', 'Chiedi', 'Ti chiede conferma per comandi e modifiche'],
  ],
};
// Il <select> nascosto resta la fonte del valore: il menu lo legge e lo cambia.
function sincronizzaSelettori() {
  el.menuModello.querySelector('.sel-testo').textContent = SCELTE.modello.find((v) => v[0] === el.modello.value)?.[1] || 'Modello';
  el.menuPermessi.querySelector('.sel-testo').textContent = SCELTE.permessi.find((v) => v[0] === el.permessi.value)?.[1] || 'Permessi';
}
function menuScelta(bottone, select, scelte, su) {
  bottone.addEventListener('click', () => {
    const nodo = document.createElement('div');
    nodo.className = 'popover';
    nodo.setAttribute('role', 'menu');
    for (const [valore, nome, descrizione] of scelte) {
      const v = document.createElement('button');
      v.type = 'button';
      v.className = 'menu-voce';
      v.setAttribute('role', 'menuitemradio');
      v.setAttribute('aria-checked', String(select.value === valore));
      v.innerHTML = `<span class="mv-testo"><strong></strong><small></small></span>${icona('spunta')}`;
      v.querySelector('strong').textContent = nome;
      v.querySelector('small').textContent = descrizione;
      v.addEventListener('click', () => {
        select.value = valore;
        select.dispatchEvent(new Event('change'));
        chiudiMenu(true);
      });
      nodo.append(v);
    }
    apriMenu(bottone, nodo, { su, creato: true });
  });
}
menuScelta(el.menuModello, el.modello, SCELTE.modello, true);
menuScelta(el.menuPermessi, el.permessi, SCELTE.permessi, false);
el.apriStrumenti.addEventListener('click', () => apriMenu(el.apriStrumenti, el.popStrumenti, { su: 'lato' }));

// ---- colonna laterale: richiudibile sul computer, a scomparsa sui schermi stretti ----
const stretto = matchMedia('(max-width: 899px)');
function apriLato(si) {
  if (stretto.matches) {
    document.body.classList.toggle('lato-aperto', si);
    el.velo.hidden = !si;
  } else {
    document.body.classList.toggle('lato-chiuso', !si);
    try { localStorage.setItem('a2p-lato', si ? 'aperto' : 'chiuso'); } catch {}
  }
  chiudiMenu();
}
function chiudiLatoSeStretto() { if (stretto.matches) apriLato(false); }
$('#chiudi-lato').addEventListener('click', () => apriLato(false));
$('#apri-lato').addEventListener('click', () => apriLato(true));
el.velo.addEventListener('click', () => apriLato(false));
stretto.addEventListener('change', () => { el.velo.hidden = true; document.body.classList.remove('lato-aperto'); });
try { if (localStorage.getItem('a2p-lato') === 'chiuso') document.body.classList.add('lato-chiuso'); } catch {}

// ---- schede: le chat aperte in questa finestra (la chat continua a lavorare anche se chiudi la scheda) ----
const MAX_SCHEDE = 8;
const schede = {
  lista: [],
  attiva: null,
  piuProgetti() { return new Set(this.lista.map((s) => s.progetto)).size > 1; },
  lavora(s) {
    if (s === this.attiva && stato.lavoro) return true;
    return !!s.sessione && stato.inCorso.some((x) => x.progetto === s.progetto && x.sessione === s.sessione);
  },
  salva() {
    try {
      localStorage.setItem('a2p-schede', JSON.stringify(this.lista.filter((s) => s.sessione).map(({ progetto, sessione, titolo }) => ({ progetto, sessione, titolo }))));
      const a = this.attiva;
      if (a?.sessione) localStorage.setItem('a2p-scheda-attiva', JSON.stringify({ progetto: a.progetto, sessione: a.sessione }));
      else localStorage.removeItem('a2p-scheda-attiva');
    } catch {}
  },
  ripristina() {
    try {
      const salvate = JSON.parse(localStorage.getItem('a2p-schede') || '[]');
      this.lista = salvate.filter((s) => typeof s?.progetto === 'string' && typeof s?.sessione === 'string')
        .slice(-MAX_SCHEDE).map((s) => ({ id: crypto.randomUUID(), progetto: s.progetto, sessione: s.sessione, chiave: null, titolo: String(s.titolo || 'Chat'), vuota: false, finita: false }));
      const a = JSON.parse(localStorage.getItem('a2p-scheda-attiva') || 'null');
      const s = a && this.lista.find((x) => x.progetto === a.progetto && x.sessione === a.sessione);
      if (s) {
        this.attiva = s;
        localStorage.setItem('a2p-progetto', s.progetto);
        ultimaChat.salva(s.progetto, s.sessione);
      }
    } catch {}
    this.disegna();
  },
  // La finestra è su questa chat: la scheda c'è già oppure si crea.
  attivaChat(progetto, sid, titolo, chiave) {
    let s = this.lista.find((x) => x.progetto === progetto && (sid ? x.sessione === sid : x.chiave === chiave));
    if (!s) {
      if (!sid) this.lista = this.lista.filter((x) => x.progetto !== progetto || x.sessione || !x.vuota || this.lavora(x));  // una sola chat nuova e vuota per progetto
      s = { id: crypto.randomUUID(), progetto, sessione: sid || null, chiave: sid ? null : chiave, titolo: titolo || 'Nuova chat', vuota: !sid, finita: false };
      this.lista.push(s);
    } else if (titolo) s.titolo = titolo;
    this.attiva = s;
    s.finita = false;
    while (this.lista.length > MAX_SCHEDE) {
      const vecchia = this.lista.find((x) => x !== s && !this.lavora(x));
      if (!vecchia) break;
      this.lista.splice(this.lista.indexOf(vecchia), 1);
    }
    this.salva();
    this.disegna();
  },
  assegna(sid) {
    const s = this.attiva;
    if (!s || s.sessione) return;
    s.sessione = sid;
    s.chiave = null;
    this.salva();
    this.disegna();
  },
  scrivi(titolo) {
    if (!this.attiva) return;
    this.attiva.vuota = false;
    this.attiva.titolo = titolo;
    this.disegna();
  },
  // Chat nate in una scheda che non guardavamo: il motore ci dice quale sessione hanno avuto.
  sincronizza(voci) {
    let cambiato = false;
    for (const s of this.lista) {
      if (s.sessione) continue;
      const v = voci.find((x) => x.sessione && x.progetto === s.progetto && x.chiavi?.includes(s.chiave));
      if (v) { s.sessione = v.sessione; s.chiave = null; cambiato = true; }
    }
    if (cambiato) this.salva();
  },
  finita(m) {
    const s = this.lista.find((x) => x.progetto === m.progetto && x.sessione === m.sessione);
    if (s && s !== this.attiva) { s.finita = true; this.disegna(); }
  },
  // Titoli aggiornati dall'elenco; una chat sparita dall'elenco (eliminata) perde la scheda.
  aggiorna(progetto, chat) {
    const prima = this.lista.length;
    let cambiato = false;
    this.lista = this.lista.filter((s) => {
      if (s.progetto !== progetto || !s.sessione) return true;
      const c = chat.find((x) => x.id === s.sessione);
      if (c) { if (c.titolo !== s.titolo) { s.titolo = c.titolo; cambiato = true; } return true; }
      return s === this.attiva || this.lavora(s);
    });
    if (cambiato || this.lista.length !== prima) { this.salva(); this.disegna(); }
  },
  togli(progetto, sid) {
    const s = this.lista.find((x) => x.progetto === progetto && x.sessione === sid);
    if (!s) return;
    this.lista.splice(this.lista.indexOf(s), 1);
    if (s === this.attiva) this.attiva = null;
    this.salva();
    this.disegna();
  },
  chiudi(s) {
    const i = this.lista.indexOf(s);
    if (i < 0) return;
    this.lista.splice(i, 1);
    const eraAttiva = s === this.attiva;
    if (eraAttiva) this.attiva = null;
    this.salva();
    this.disegna();
    if (!eraAttiva) return;
    const v = this.lista[i] || this.lista[i - 1];
    if (v) vaiA(v.progetto, v.sessione, v.titolo, v.chiave);
    else { apriChat(null); caricaChat(); }
  },
  disegna() {
    const fuoco = el.schede.contains(document.activeElement) ? document.activeElement.closest('.scheda')?.dataset.id : null;
    el.schede.hidden = !this.lista.length;
    el.schede.replaceChildren(...this.lista.map((s) => {
      const lavora = this.lavora(s);
      const nodo = document.createElement('div');
      nodo.className = 'scheda' + (s === this.attiva ? ' attiva' : '') + (s.finita ? ' finita' : '');
      nodo.dataset.id = s.id;
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'sc-tab';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', s === this.attiva ? 'true' : 'false');
      tab.tabIndex = s === (this.attiva || this.lista[0]) ? 0 : -1;
      tab.title = `${s.titolo} (${s.progetto})`;
      tab.setAttribute('aria-label', `${s.titolo}, progetto ${s.progetto}${lavora ? ', al lavoro' : ''}${s.finita ? ', ha finito' : ''}`);
      const titolo = document.createElement('span');
      titolo.textContent = s.titolo;
      const progetto = document.createElement('span');
      progetto.className = 'sc-progetto';
      progetto.textContent = s.progetto;
      if (lavora) {
        const punto = document.createElement('span');
        punto.className = 'sc-punto';
        punto.setAttribute('aria-hidden', 'true');
        tab.append(punto);
      }
      tab.append(titolo);
      if (this.piuProgetti()) tab.append(progetto);  // il nome del progetto serve solo se le schede ne mescolano più d'uno
      tab.addEventListener('click', () => { if (s !== this.attiva) vaiA(s.progetto, s.sessione, s.titolo, s.chiave); });
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'sc-chiudi';
      x.innerHTML = icona('x');
      x.title = 'Chiudi la scheda (la chat resta)';
      x.setAttribute('aria-label', `Chiudi la scheda ${s.titolo}`);
      x.addEventListener('click', () => this.chiudi(s));
      nodo.append(tab, x);
      return nodo;
    }));
    if (fuoco) el.schede.querySelector(`[data-id="${fuoco}"] .sc-tab`)?.focus();
    el.schede.querySelector('.attiva')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  },
};
el.schede.addEventListener('keydown', (e) => {
  const passo = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
  if (!passo && e.key !== 'Home' && e.key !== 'End') return;
  const tab = [...el.schede.querySelectorAll('.sc-tab')];
  const i = tab.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const j = e.key === 'Home' ? 0 : e.key === 'End' ? tab.length - 1 : (i + passo + tab.length) % tab.length;
  tab.forEach((t, k) => (t.tabIndex = k === j ? 0 : -1));
  tab[j].focus();
});

// ---- bozze: quello che è scritto e non inviato, per progetto e chat ----
const bozza = {
  chiave: () => `a2p-bozza-${stato.progetto}-${stato.sessione || 'nuova'}`,
  leggi: () => { try { return localStorage.getItem(bozza.chiave()) || ''; } catch { return ''; } },
  salva: (chiave = bozza.chiave()) => {
    try { el.testo.value ? localStorage.setItem(chiave, el.testo.value) : localStorage.removeItem(chiave); } catch {}
  },
  cancella: (chiave = bozza.chiave()) => { try { localStorage.removeItem(chiave); } catch {} },
};

// ---- avvisi a comparsa e titolo della finestra ----
function avvisoFinito(m) {
  document.title = `● ${TITOLO}`;
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'avviso';
  b.textContent = `Ha finito: ${m.titolo} (${m.progetto})`;
  const togli = () => b.remove();
  b.addEventListener('click', () => { togli(); apriDaAvviso(m); });
  el.avvisi.append(b);
  setTimeout(togli, 8000);
}
function apriDaAvviso(m) { vaiA(m.progetto, m.sessione, m.titolo); }

// Porta la finestra su una chat, cambiando progetto se serve. Niente attese: la vista cambia subito,
// l'elenco chat del nuovo progetto e lo storico arrivano in parallelo.
function vaiA(progetto, sessione, titolo, chiave) {
  if (progetto !== stato.progetto) {
    if (![...el.progetto.options].some((o) => o.value === progetto)) return;
    el.progetto.value = progetto;
    stato.progetto = progetto;
    try { localStorage.setItem('a2p-progetto', progetto); } catch {}
    caricaChat();
  }
  apriChat(sessione, titolo, chiave);
}
const titoloNormale = () => { document.title = TITOLO; };
window.addEventListener('focus', titoloNormale);
document.addEventListener('visibilitychange', () => { if (!document.hidden) titoloNormale(); });

// ---- connessione ----
function connetti() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  stato.ws = ws;
  stato.pronto = false;
  ws.onmessage = (e) => ricevi(JSON.parse(e.data));
  ws.onclose = () => { stato.pronto = false; aggiornaCollegamento(); setTimeout(connetti, 1500); };
  // Prima connessione: manda quello che era in coda. Dopo una caduta: riapre la chat in corso.
  ws.onopen = () => {
    const coda = stato.coda.splice(0);
    if (coda.length) coda.forEach((d) => ws.send(JSON.stringify(d)));
    else if (stato.progetto) apriChat(stato.sessione, undefined, stato.chiave);
  };
}
function invia(dati) {
  if (stato.ws?.readyState === 1) stato.ws.send(JSON.stringify(dati));
  else if (dati.tipo === 'apri') stato.coda = [dati];
}

// Dopo «apri» la finestra ignora gli eventi della chat di prima fino a «pronto».
const SEMPRE = ['pronto', 'in_corso', 'chat_finita', 'errore'];
// Questi non toccano i messaggi sullo schermo: non aspettano la cronologia.
const SENZA_ATTESA = [...SEMPRE, 'costo', 'contesto', 'connettori', 'coda'];
function ricevi(m) {
  // «pronto» di un'apertura superata da un'altra: la chat di cui parla non è più quella davanti.
  if (m.tipo === 'pronto' && m.apertura != null && m.apertura !== stato.apertura) return;
  if (!stato.pronto && !SEMPRE.includes(m.tipo)) return;
  if (stato.storicoInCorso && !SENZA_ATTESA.includes(m.tipo)) { stato.buffer.push(m); return; }
  switch (m.tipo) {
    case 'in_corso':
      stato.inCorso = m.chat;
      schede.sincronizza(m.chat);
      segniInCorso();
      break;
    case 'lavora':
      // Appena aperta, la chat dice «ferma» prima di ricevere il messaggio mandato in quel momento: non è vero.
      if (!m.si && stato.mandatoInApertura) { stato.mandatoInApertura = false; break; }
      stato.mandatoInApertura = false;
      inLavoro(m.si);
      break;
    case 'coda':
      disegnaCoda(m.coda);
      break;
    case 'utente':
      stato.bolla = null;
      stato.passi = null;
      aggiungi('msg utente', m.testo);
      indicatore(true);
      break;
    case 'chat_finita':
      schede.sincronizza([m]);
      schede.finita(m);
      if (m.progetto !== stato.progetto || m.sessione !== stato.sessione) avvisoFinito(m);
      break;
    case 'pronto':
      stato.pronto = true;
      aggiornaCollegamento();
      stato.mandatoInApertura = stato.inAttesa.some((d) => d.tipo === 'messaggio');
      for (const d of stato.inAttesa.splice(0)) invia(d);
      break;
    case 'costo':
      mostraCosto(m.costo);
      break;
    case 'contesto': {
      const k = (n) => `${Math.round(n / 1000)}k`;
      const perc = m.massimo ? Math.round((m.usati / m.massimo) * 100) : 0;
      el.contesto.hidden = false;
      el.contesto.querySelector('.anello').style.setProperty('--p', Math.min(perc, 100));
      el.contesto.querySelector('.perc').textContent = `${perc}%`;
      el.contesto.className = 'contesto' + (perc >= 90 ? ' pieno' : perc >= 70 ? ' alto' : '');
      stato.contestoTesto = `Contesto: ${k(m.usati)} su ${k(m.massimo)} (${perc}%). ` + (m.auto
        ? `Quando arriva a ${k(m.massimo)} la chat si riassume da sola. Sopra il 70% conviene aprire una chat nuova: costa meno.`
        : 'La compattazione automatica è spenta.');
      aggiornaTitoloContesto();
      break;
    }
    case 'connettori':
      stato.connettori = m.voci;
      mostraStrumenti();
      break;
    case 'sessione':
      if (m.id && m.id !== stato.sessione) {
        const vecchia = bozza.chiave();
        schede.assegna(m.id);
        stato.sessione = m.id;
        stato.chiave = null;
        if (el.testo.value) { bozza.salva(); bozza.cancella(vecchia); }  // la bozza della chat nuova segue la chat
        ultimaChat.salva(stato.progetto, m.id);
        caricaChat();
      }
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
      aggiungiStrumento(m.testo, m.sotto);
      indicatore(true);
      break;
    case 'passi': {
      indicatore(false);
      const nuovo = !stato.passi;
      stato.passi = disegnaPassi(m.passi, stato.passi);
      if (nuovo) stato.bolla = null;
      scorri();
      indicatore(true);
      break;
    }
    case 'file_anteprima':
      fileAnteprima(m.percorso, true);
      break;
    case 'permesso':
      indicatore(false);
      mostraPermesso(m);
      break;
    case 'fine':
      stato.bolla = null;
      inLavoro(m.lavora);
      if (m.errore) aggiungi('msg claude errore', m.errore);
      if (m.errore?.startsWith('La chiave API')) $('#dlg-impostazioni').showModal();
      mostraCosto(m.costo);
      el.spesaMese.textContent = `Speso questo mese: ${dollari(m.spesa_mese)}`;
      if (m.sessione) { stato.sessione = m.sessione; ultimaChat.salva(stato.progetto, m.sessione); }
      caricaChat().then(() => { stato.titoloProvvisorio = null; });
      break;
    case 'errore':
      aggiungi('msg claude errore', m.testo);
      break;
  }
}
function mostraCosto(costo) {
  stato.costoTesto = `Questa chat: ${dollari(costo)}`;
  el.costo.textContent = dollari(costo);
  aggiornaTitoloContesto();
}
function aggiornaTitoloContesto() {
  const testo = [stato.contestoTesto, stato.costoTesto].filter(Boolean).join('\n');
  el.contesto.title = testo;
  el.contesto.setAttribute('aria-label', testo);
  el.costo.title = stato.costoTesto || 'Spesa di questa chat';
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
  for (const p of elenco) {
    const voce = new Option(p.cartella ? `📁 ${p.nome}` : p.nome, p.nome);
    if (p.cartella) voce.title = p.cartella;
    voce.dataset.base = voce.text;
    el.progetto.append(voce);
  }
  const salvato = scegli || localStorage.getItem('a2p-progetto');
  if (salvato && elenco.some((p) => p.nome === salvato)) el.progetto.value = salvato;
  segniInCorso();
  await cambiaProgetto();
}

// Ricorda l'ultima chat aperta di ogni progetto, così alla riapertura si riparte da lì.
const ultimaChat = {
  leggi: (p) => { try { return localStorage.getItem('a2p-chat-' + p); } catch { return null; } },
  salva: (p, sid) => { try { sid ? localStorage.setItem('a2p-chat-' + p, sid) : localStorage.removeItem('a2p-chat-' + p); } catch {} },
};

// Cambia progetto: la vista cambia subito sull'ultima chat di quel progetto, l'elenco si carica in parallelo.
async function cambiaProgetto() {
  stato.progetto = el.progetto.value;
  try { localStorage.setItem('a2p-progetto', stato.progetto); } catch {}
  const ultima = ultimaChat.leggi(stato.progetto);
  const nota = (stato.elenchi[stato.progetto] || []).find((c) => c.id === ultima) || schede.lista.find((s) => s.progetto === stato.progetto && s.sessione === ultima);
  chiudiLatoSeStretto();
  const apertura = apriChat(ultima || null, nota?.titolo);
  caricaChat();
  await apertura;
}

// Raggruppa per data di modifica, come sulle app di chat: Oggi, Ieri, Ultimi 7 giorni, Più vecchie.
function gruppoData(ms) {
  const oggi = new Date(); oggi.setHours(0, 0, 0, 0);
  const giorno = 86400000;
  if (ms >= oggi.getTime()) return 'Oggi';
  if (ms >= oggi.getTime() - giorno) return 'Ieri';
  if (ms >= oggi.getTime() - 7 * giorno) return 'Ultimi 7 giorni';
  return 'Più vecchie';
}
let sequenzaElenco = 0;
async function caricaChat() {
  if (!stato.progetto) return [];
  const progetto = stato.progetto;
  const mia = ++sequenzaElenco;
  const chat = await api(`/api/chat?${q(progetto)}`);
  stato.elenchi[progetto] = chat;
  if (progetto !== stato.progetto || mia !== sequenzaElenco) return chat;  // nel frattempo si è cambiato progetto: l'elenco non è più questo
  const voci = [];
  // Chat appena iniziata: compare subito in cima, anche prima che sia salvata sul disco.
  const elencoVista = stato.titoloProvvisorio && !chat.some((c) => c.id === stato.sessione)
    ? [{ id: null, titolo: stato.titoloProvvisorio, modificata: Date.now(), provvisoria: true }, ...chat]
    : chat;
  let gruppo = null;
  for (const c of elencoVista) {
    const nome = gruppoData(c.modificata || 0);
    if (nome !== gruppo) {
      gruppo = nome;
      const t = document.createElement('div');
      t.className = 'gruppo-titolo';
      t.textContent = nome;
      voci.push(t);
    }
    const a = document.createElement('a');
    a.href = '#';
    a.title = c.titolo;
    a.innerHTML = `<span></span><i class="punto" aria-hidden="true"></i>`;
    a.querySelector('span').textContent = c.titolo;
    if (c.provvisoria) {
      a.className = stato.lavoro ? 'in-corso' : '';
      a.setAttribute('aria-current', 'true');
      a.dataset.corrente = '1';
      a.addEventListener('click', (e) => e.preventDefault());
      voci.push(a);
      continue;
    }
    a.dataset.sid = c.id;
    const x = document.createElement('button');
    x.type = 'button';
    x.className = 'x';
    x.title = 'Elimina chat';
    x.setAttribute('aria-label', `Elimina la chat ${c.titolo}`);
    x.innerHTML = icona('x');
    a.append(x);
    if (c.id === stato.sessione) { a.setAttribute('aria-current', 'true'); a.dataset.corrente = '1'; el.titolo.textContent = c.titolo; }
    a.addEventListener('click', (e) => {
      e.preventDefault();
      if (e.target.closest('.x')) return eliminaChat(c);
      if (e.target.closest('input')) return;
      chiudiLatoSeStretto();
      if (c.id === stato.sessione) return;  // già qui (anche il secondo clic di un doppio clic)
      apriChat(c.id, c.titolo);
    });
    a.addEventListener('dblclick', (e) => { if (!e.target.closest('.x')) rinominaChat(c, a); });
    a.addEventListener('keydown', (e) => { if (e.key === 'F2') rinominaChat(c, a); });
    voci.push(a);
  }
  if (!elencoVista.length) {
    const v = document.createElement('div');
    v.className = 'chat-vuota';
    v.textContent = 'Nessuna chat in questo progetto.';
    voci.push(v);
  }
  // Mentre si rinomina una chat l'elenco non si ridisegna: il campo di testo sparirebbe sotto le dita.
  if (el.elenco.querySelector('input.rinomina')) stato.elencoRimandato = true;
  else { el.elenco.replaceChildren(...voci); stato.elencoRimandato = false; }
  schede.aggiorna(progetto, chat);
  segniInCorso();
  return chat;
}

// Cronologie già viste: riaprire una chat o una scheda le mostra subito, poi si aggiornano dal disco.
const cacheStorico = new Map();
function disegnaStorico(righe) {
  const locali = [...el.messaggi.querySelectorAll(':scope > .msg.utente.locale')];  // messaggi scritti mentre la chat si apriva
  el.messaggi.replaceChildren();
  stato.bolla = null;
  if (!righe.length && !locali.length) vuoto();
  let passi = null;  // più aggiornamenti della lista tra due messaggi dell'utente restano un riquadro solo
  for (const r of righe) {
    if (r.ruolo === 'user') { passi = null; aggiungi('msg utente', r.testo.replace(/\n\nAllegati \(leggili con Read\):[\s\S]*$/, ' 📎')); }
    else if (r.ruolo === 'assistant') aggiungi('msg claude', markdown(r.testo), true);
    else if (r.ruolo === 'passi') passi = disegnaPassi(r.passi, passi);
    else if (r.ruolo === 'file') fileAnteprima(r.percorso, false);
    else aggiungiStrumento(r.testo);
  }
  el.messaggi.append(...locali);
  if (stato.lavoro) indicatore(true);
  scorri(true);
}
function fineStorico(apertura) {
  if (apertura !== stato.apertura) return;
  stato.storicoInCorso = false;
  for (const m of stato.buffer.splice(0)) ricevi(m);
}

// Apre una chat. Tutto quello che si vede cambia subito (titolo, scheda, casella, bozza); lo storico si scarica
// via HTTP e il motore si collega in parallelo, senza che una cosa aspetti l'altra.
async function apriChat(sid, titolo, chiave) {
  // Messaggi scritti mentre la chat si avviava e non ancora partiti: appartengono a quella chat, non a
  // quella che si apre ora. Tornano bozza dove erano stati scritti.
  const nonPartiti = stato.inAttesa.filter((d) => d.tipo === 'messaggio');
  stato.inAttesa = stato.inAttesa.filter((d) => d.tipo !== 'messaggio');
  if (nonPartiti.length && stato.bozzaInAttesa) {
    try { localStorage.setItem(stato.bozzaInAttesa, nonPartiti.map((d) => d.testo).join('\n\n')); } catch {}
  }
  const apertura = ++stato.apertura;
  if (!titolo && sid && sid === stato.sessione) titolo = el.titolo.textContent;
  stato.sessione = sid;
  stato.chiave = sid ? null : (chiave || crypto.randomUUID());
  schede.attivaChat(stato.progetto, sid, titolo, stato.chiave);
  ultimaChat.salva(stato.progetto, sid);
  stato.bolla = null;
  stato.passi = null;
  stato.pronto = false;
  stato.buffer = [];
  stato.storicoInCorso = !!sid;
  aggiornaCollegamento();
  azzeraAnteprima();
  stato.costoTesto = '';
  stato.contestoTesto = '';
  el.costo.textContent = '';
  el.contesto.hidden = true;
  el.titolo.textContent = titolo || 'Nuova chat';
  el.elenco.querySelectorAll('a').forEach((a) => {
    const corrente = !!sid && a.dataset.sid === sid;
    if (corrente) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current');
    a.dataset.corrente = corrente ? '1' : '';
  });
  inLavoro(false);
  disegnaCoda([]);
  el.testo.value = bozza.leggi();
  aggiornaInvia();
  cresci();
  if (sid) titoloNormale();
  const chiaveCache = `${stato.progetto}\u0000${sid}`;
  const vecchio = sid ? cacheStorico.get(chiaveCache) : null;
  if (!sid) vuoto(); else { el.messaggi.replaceChildren(); if (vecchio) disegnaStorico(JSON.parse(vecchio)); }
  scorri(true);
  // Il motore parte subito, senza aspettare lo storico (e senza che lui aspetti noi).
  invia({ tipo: 'apri', progetto: stato.progetto, sessione: sid, chiave: stato.chiave, modello: el.modello.value, permessi: el.permessi.value, apertura });
  if (!sid) return;
  try {
    const righe = await api(`/api/chat/${sid}?${q(stato.progetto)}`);
    if (apertura !== stato.apertura) return;  // nel frattempo si è aperta un'altra chat: questi risultati non servono più
    const nuovo = JSON.stringify(righe);
    cacheStorico.set(chiaveCache, nuovo);
    if (nuovo !== vecchio) disegnaStorico(righe);
    else if (!righe.length) vuoto();
    caricaChat();
  } catch {
    if (apertura === stato.apertura && !vecchio) vuoto();
  } finally {
    fineStorico(apertura);
  }
}

async function eliminaChat(c) {
  if (!confirm(`Eliminare la chat «${c.titolo}»? Non si può annullare.`)) return;
  await api(`/api/chat/${c.id}?${q(stato.progetto)}`, { method: 'DELETE' });
  cacheStorico.delete(`${stato.progetto}\u0000${c.id}`);
  schede.togli(stato.progetto, c.id);
  if (c.id === stato.sessione) apriChat(null);
  caricaChat();
}

// Rinomina sul posto: doppio clic (o F2), Invio per salvare, Esc per annullare.
function rinominaChat(c, riga) {
  const testo = riga.querySelector('span');
  if (!testo || riga.querySelector('input')) return;
  const campo = document.createElement('input');
  campo.className = 'rinomina';
  campo.value = c.titolo;
  campo.setAttribute('aria-label', 'Nuovo nome della chat');
  let chiuso = false;
  const fine = async (salva) => {
    if (chiuso) return;
    chiuso = true;
    const titolo = campo.value.trim();
    if (salva && titolo && titolo !== c.titolo) {
      try { await api(`/api/chat/${c.id}/rinomina?${q(stato.progetto)}`, { method: 'POST', body: JSON.stringify({ titolo }) }); } catch (err) { alert(err.message); }
    }
    caricaChat();
  };
  campo.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); fine(true); }
    else if (e.key === 'Escape') { e.preventDefault(); fine(false); }
  });
  campo.addEventListener('blur', () => fine(true));
  testo.replaceWith(campo);
  campo.focus();
  campo.select();
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
    s.innerHTML = icona('graffetta');
    const nome = document.createElement('span');
    nome.className = 'nome';
    nome.textContent = a.nome;
    s.append(nome);
    const x = document.createElement('button');
    x.type = 'button'; x.innerHTML = icona('x'); x.setAttribute('aria-label', 'Togli allegato'); x.title = 'Togli allegato';
    x.onclick = () => { stato.allegati.splice(i, 1); mostraAllegati(); };
    s.append(x);
    el.allegati.append(s);
  });
  aggiornaInvia();
}

el.form.addEventListener('submit', (e) => {
  e.preventDefault();
  const testo = el.testo.value.trim();
  if (!testo && !stato.allegati.length) return;
  // Con Claude al lavoro il messaggio va in coda (lo disegna il riquadro «In coda»); altrimenti parte subito.
  const dati = { tipo: 'messaggio', testo: testo || 'Guarda gli allegati.', allegati: stato.allegati.map((a) => a.percorso), locale: !stato.lavoro };
  if (!stato.lavoro) {
    aggiungi('msg utente locale', testo + (stato.allegati.length ? `\n📎 ${stato.allegati.map((a) => a.nome).join(', ')}` : ''));
    scorri(true);
    if (!stato.sessione) {
      stato.titoloProvvisorio = (testo || 'Allegati').slice(0, 70);
      el.titolo.textContent = stato.titoloProvvisorio;
      schede.scrivi(stato.titoloProvvisorio);
    }
    stato.bolla = null;
    stato.passi = null;
    inLavoro(true);
    if (stato.titoloProvvisorio && !stato.sessione) caricaChat();
  }
  el.testo.value = '';
  bozza.cancella();
  stato.allegati = [];
  mostraAllegati();
  cresci();
  if (stato.pronto) invia(dati);
  else { stato.bozzaInAttesa = bozza.chiave(); stato.inAttesa.push(dati); }
});
// Per i browser senza field-sizing: la casella cresce da sola fino a 200px.
function cresci() {
  if (CSS.supports('field-sizing', 'content')) return;
  el.testo.style.height = 'auto';
  el.testo.style.height = `${Math.min(el.testo.scrollHeight, 200)}px`;
}
el.testo.addEventListener('input', () => { bozza.salva(); aggiornaInvia(); cresci(); });
el.testo.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); el.form.requestSubmit(); }
});
el.stop.addEventListener('click', () => invia({ tipo: 'stop' }));
el.modello.addEventListener('change', () => { el.modello.dataset.toccato = '1'; sincronizzaSelettori(); invia({ tipo: 'modello', modello: el.modello.value }); });
el.permessi.addEventListener('change', () => {
  const modo = el.permessi.value;
  sincronizzaSelettori();
  invia({ tipo: 'permessi', modo });
  api('/api/impostazioni', { method: 'POST', body: JSON.stringify({ permessi: modo }) }).catch(() => {});
});
el.progetto.addEventListener('change', cambiaProgetto);
$('#nuova-chat').addEventListener('click', () => {
  chiudiLatoSeStretto();
  if (schede.attiva?.vuota && !schede.attiva.sessione) return;  // già su una chat nuova e vuota
  apriChat(null);
  caricaChat();
  el.testo.focus();
});
el.file.addEventListener('change', () => { caricaFile([...el.file.files]); el.file.value = ''; });
el.testo.addEventListener('paste', (e) => {
  const immagini = [...e.clipboardData.files];
  if (immagini.length) { e.preventDefault(); caricaFile(immagini); }
});
el.form.addEventListener('dragover', (e) => { e.preventDefault(); el.form.classList.add('trascina'); });
el.form.addEventListener('dragleave', () => el.form.classList.remove('trascina'));
el.form.addEventListener('drop', (e) => { e.preventDefault(); el.form.classList.remove('trascina'); caricaFile([...e.dataTransfer.files]); });

// ---- anteprima ----
const anteprima = { file: [], vista: null, autoFatto: false };
function mostraPannello(si) {
  el.anteprima.hidden = !si;
  document.body.classList.toggle('con-anteprima', si);
  $('#apri-anteprima').setAttribute('aria-pressed', String(si));
}
function messaggioAnteprima(testo = '') { el.anteprimaMessaggio.textContent = testo; }
function disegnaElencoFile() {
  const voci = anteprima.file.map((p) => new Option(p, p));
  el.anteprimaFile.replaceChildren(...(voci.length ? voci : [Object.assign(new Option('Nessun file ancora', ''), { disabled: true })]));
  if (anteprima.vista?.file) el.anteprimaFile.value = anteprima.vista.file;
  else el.anteprimaFile.selectedIndex = voci.length ? -1 : 0;
}
function mostraFile(percorso) {
  const indirizzo = percorso.split('/').map(encodeURIComponent).join('/');
  anteprima.vista = { file: percorso };
  el.anteprimaFile.value = percorso;
  messaggioAnteprima();
  el.anteprimaFrame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups');
  el.anteprimaFrame.src = `/anteprima/${encodeURIComponent(stato.progetto)}/${indirizzo}?t=${Date.now()}`;
}
function fileAnteprima(percorso, dalVivo) {
  if (!anteprima.file.includes(percorso)) { anteprima.file.push(percorso); disegnaElencoFile(); }
  if (!dalVivo) return;
  if (!anteprima.autoFatto) { anteprima.autoFatto = true; mostraPannello(true); mostraFile(percorso); }
  else if (anteprima.vista?.file === percorso) mostraFile(percorso);
}
function azzeraAnteprima() {
  Object.assign(anteprima, { file: [], vista: null, autoFatto: false });
  el.anteprimaFrame.src = 'about:blank';
  messaggioAnteprima();
  disegnaElencoFile();
}
function mostraIndirizzo(testo) {
  const m = testo.trim().match(/^http:\/\/(localhost|127\.0\.0\.1):(\d+)(\/.*)?$/);
  if (!m || Number(m[2]) === Number(location.port)) {
    messaggioAnteprima('Scrivi l\'indirizzo di un sito aperto sul tuo computer, per esempio http://localhost:3000 (non quello di questa app).');
    return;
  }
  anteprima.vista = { url: m[0] };
  el.anteprimaFile.selectedIndex = -1;
  messaggioAnteprima();
  el.anteprimaFrame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms allow-popups');
  el.anteprimaFrame.src = m[0];
}
$('#apri-anteprima').addEventListener('click', () => mostraPannello(el.anteprima.hidden));
$('#anteprima-chiudi').addEventListener('click', () => mostraPannello(false));
el.anteprimaFile.addEventListener('change', () => el.anteprimaFile.value && mostraFile(el.anteprimaFile.value));
$('#anteprima-ricarica').addEventListener('click', () => {
  if (anteprima.vista?.file) mostraFile(anteprima.vista.file);
  else if (anteprima.vista?.url) mostraIndirizzo(anteprima.vista.url);
});
$('#anteprima-indirizzo').addEventListener('submit', (e) => { e.preventDefault(); mostraIndirizzo(el.anteprimaUrl.value); });

// ---- finestre ----
$('#form-progetto').addEventListener('submit', async (e) => {
  if (e.submitter?.value !== 'ok') return;
  e.preventDefault();
  const nome = $('#nome-progetto').value.trim();
  const cartella = $('#cartella-progetto').value.trim();
  try {
    const p = await api('/api/progetti', { method: 'POST', body: JSON.stringify({ nome, cartella }) });
    $('#dlg-progetto').close();
    $('#nome-progetto').value = '';
    $('#cartella-progetto').value = '';
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
  $('#imp-chiave-stato').textContent = s.chiave
    ? `Chiave salvata ✓ (finisce con …${s.chiave_fine}). Per cambiarla incolla quella nuova qui sopra e premi Salva.`
    : 'Nessuna chiave salvata: creala su platform.claude.com › API Keys e incollala qui sopra.';
  document.querySelector(`input[name="browser"][value="${s.browser_modo}"]`).checked = true;
  $('#imp-token-stato').textContent = s.estensione_token
    ? 'Codice salvato ✓'
    : 'Senza codice, la prima volta che Claude usa il browser ti chiede di approvare il collegamento in Chrome.';
  if (!el.modello.dataset.toccato) el.modello.value = s.modello;
  el.permessi.value = s.permessi;
  sincronizzaSelettori();
  el.spesaMese.textContent = `Speso questo mese: ${dollari(s.spesa_mese)}`;
  el.versione.textContent = `Versione ${s.versione}`;
  stato.strumenti = s.strumenti;
  mostraStrumenti();
  return s;
}

// Strumenti trovati sul computer + connettori con login (stato dal vivo della chat aperta), nel popover della colonna.
const STATI_CONNETTORE = {
  ok: ['ok', 'Collegato'],
  login: ['login', 'Da collegare: premi Collega e fai il login nel browser'],
  collego: ['collego', 'Login in corso nel browser…'],
  attesa: ['no', 'Si sta collegando…'],
  no: ['no', 'Non disponibile'],
  chiave: ['no', 'Non disponibile con la chiave API'],
};
function rigaStrumento(nome, classe, titolo, nota) {
  // I nomi vengono dalle configurazioni di chi usa l'app: si mettono come testo, non come HTML.
  const r = document.createElement('div');
  r.className = `str-riga ${classe}`;
  r.title = titolo;
  const n = document.createElement('span');
  n.className = 'nome';
  n.textContent = nome;
  r.append(n);
  if (nota) {
    const s = document.createElement('span');
    s.className = 'stato';
    s.textContent = nota;
    r.append(s);
  }
  return r;
}
function mostraStrumenti() {
  const base = (stato.strumenti || []).map(({ nome, ok }) => ({
    ok, nodo: rigaStrumento(nome, ok ? 'ok' : 'no', ok ? 'Collegato' : 'Non disponibile su questo computer', ok ? '' : 'Non disponibile'),
  }));
  const connettori = (stato.connettori || []).map((c) => {
    const [classe, titolo] = STATI_CONNETTORE[c.stato] || STATI_CONNETTORE.no;
    const nodo = rigaStrumento(c.nome, classe, c.motivo && c.stato === 'no' ? `${titolo}: ${c.motivo}` : titolo, '');
    if (c.stato === 'login' || c.stato === 'collego') {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = c.stato === 'collego' ? 'Collego…' : 'Collega';
      b.disabled = c.stato === 'collego';
      b.addEventListener('click', () => invia({ tipo: 'collega', server: c.server }));
      nodo.append(b);
    }
    return { stato: c.stato, nodo };
  });
  const gruppo = (testo) => Object.assign(document.createElement('div'), { className: 'gruppo-str', textContent: testo });
  const collegati = connettori.filter((c) => c.stato === 'ok');
  const daCollegare = connettori.filter((c) => c.stato === 'login' || c.stato === 'collego');
  const altri = connettori.filter((c) => !['ok', 'login', 'collego'].includes(c.stato));
  const voci = [];
  if (base.length) voci.push(gruppo('Su questo computer'), ...base.map((b) => b.nodo));
  if (collegati.length) voci.push(gruppo('Connettori collegati'), ...collegati.map((c) => c.nodo));
  if (daCollegare.length) voci.push(gruppo('Da collegare'), ...daCollegare.map((c) => c.nodo));
  if (altri.length) {
    // I non disponibili stanno in una riga che si apre: la lista resta corta.
    const d = document.createElement('details');
    d.open = !!stato.altriAperti;
    d.addEventListener('toggle', () => (stato.altriAperti = d.open));
    const s = document.createElement('summary');
    s.textContent = `Altri connettori (${altri.length})`;
    d.append(s, ...altri.map((c) => c.nodo));
    voci.push(d);
  }
  if (!voci.length) voci.push(Object.assign(document.createElement('div'), { className: 'chat-vuota', textContent: 'Nessuno strumento trovato.' }));
  el.strumenti.replaceChildren(...voci);
  const collegatiTot = base.filter((b) => b.ok).length + collegati.length;
  el.strumentiConto.textContent = collegatiTot ? String(collegatiTot) : '';
  el.strumentiConto.title = `${collegatiTot} collegati`;
}

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
    apriChat(stato.sessione, stato.sessione ? el.titolo.textContent : undefined);
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
  schede.ripristina();
  await caricaProgetti();
  if (!s.chiave) $('#dlg-impostazioni').showModal();
})();

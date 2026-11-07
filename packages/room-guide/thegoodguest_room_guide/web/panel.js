// The harness's conversation panel: opens the viewer, injects the player into it,
// shows the guide's words and proposals, and plays every move the server sends.
//
// The panel never decides where anything goes. A proposal arrives already solved and
// with its motion checked; "Show me" asks the server to keep it and plays the plan it
// returns; "Put it back" plays the plan back.
//
// Read by: harness.html.
const $ = (id) => document.getElementById(id);
const log = $('log');
let player = null;
let busy = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

function add(kind, html) {
  const el = document.createElement('div');
  el.className = kind;
  el.innerHTML = html;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---------------------------------------------------------------- the viewer and its player
function openViewer() {
  return new Promise((resolve) => {
    const frame = $('viewer');
    frame.src = '/viewer/index.html?scene=/scene.json&intro=0';
    frame.addEventListener('load', () => {
      const win = frame.contentWindow;
      const wait = setInterval(() => {
        if (!win.__diorama) return;
        clearInterval(wait);
        win.addEventListener('guide-player-ready', () => resolve(win.__guidePlayer), { once: true });
        const s = win.document.createElement('script');
        s.type = 'module';
        s.src = '/guide/player.js';
        win.document.body.appendChild(s);
      }, 100);
    }, { once: true });
  });
}

async function play(plan) {
  if (!plan || !player) return;
  player.show({ footprints: plan.footprints || [] });
  await player.play(plan);
}

// ---------------------------------------------------------------- proposals
function proposalCard(p) {
  const el = add('card', `
    <div>${p.words.map(esc).join('; ')}.</div>
    ${p.fixes.length ? `<ul>${p.fixes.map((f) => `<li>${esc(f)}</li>`).join('')}</ul>` : ''}
    ${p.adds.length ? `<div class="meta">Brings: ${p.adds.map(esc).join(' ')}</div>` : ''}
    <div class="meta">${esc(p.effort)}</div>
    <button class="primary">Show me</button>`);
  el.querySelector('button').onclick = async (ev) => {
    if (busy) return;
    busy = true;
    ev.target.disabled = true;
    try {
      const r = await api('/api/show', { id: p.id });
      await play(r.plan);
      render(r.state);
    } finally { busy = false; }
  };
}

// ---------------------------------------------------------------- state
function render(state) {
  $('roomline').textContent = state.room;
  $('undo').disabled = !state.can_undo;
}

function findingsBlock(state) {
  const items = state.findings.filter((f) => f.kind !== 'question')
    .map((f) => `<li class="sev${f.severity}">${esc(f.text)}</li>`).join('');
  add('note', `<details><summary>What the room shows (${state.findings.length})</summary><ul>${items}</ul></details>`);
}

// ---------------------------------------------------------------- the conversation
// A turn streams back as server-sent events: the guide's words as they are written,
// proposal cards it offers, moves to play now, things to light up, notes, and done.
async function turn(path, body) {
  busy = true;
  let words = null;
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let cut;
      while ((cut = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        const kind = (chunk.match(/^event: (.*)$/m) || [])[1];
        const data = JSON.parse((chunk.match(/^data: (.*)$/m) || [, '{}'])[1]);
        if (kind === 'delta') {
          if (!words) words = add('guest', '');
          words.textContent += data.text;
          log.scrollTop = log.scrollHeight;
        } else if (kind === 'card') {
          proposalCard(data); words = null;
        } else if (kind === 'play') {
          await play(data.plan); render(data.state); words = null;
        } else if (kind === 'focus') {
          if (player) player.show(data);
        } else if (kind === 'note') {
          add('note', esc(data.text)); words = null;
        } else if (kind === 'error') {
          add('note', `The guide stopped: ${esc(data.message)}`);
        }
      }
    }
  } finally { busy = false; }
}

async function ask(text) {
  add('person', esc(text));
  await turn('/api/turn', { text });
}

$('ask').onsubmit = (ev) => {
  ev.preventDefault();
  const t = $('text').value.trim();
  if (!t || busy) return;
  $('text').value = '';
  ask(t);
};

$('look').onclick = async () => {
  if (busy) return;
  busy = true;
  const note = add('note', 'Looking at every place each piece could go…');
  try {
    const r = await api('/api/explore', { goal: 'general' });
    note.remove();
    if (!r.proposals.length) add('note', 'Nothing beats the room as it stands, by its own needs.');
    r.proposals.forEach(proposalCard);
  } finally { busy = false; }
};

$('undo').onclick = async () => {
  if (busy) return;
  busy = true;
  try {
    const r = await api('/api/undo', {});
    await play(r.plan);
    render(r.state);
  } finally { busy = false; }
};

(async () => {
  const state = await api('/api/state');
  render(state);
  for (const n of state.notes) add('note', esc(n));
  player = await openViewer();
  if (state.needs_solids) {
    const r = await api('/api/solids', player.solids());
    add('note', `Measured the drawn shapes of ${r.from_builder} pieces.`);
  }
  const fresh = await api('/api/state');
  render(fresh);
  findingsBlock(fresh);
  if (Object.keys(fresh.poses).length) await player.place(fresh.poses);
  await turn('/api/open', {});
})();

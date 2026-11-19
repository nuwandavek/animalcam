const $ = id => document.getElementById(id);
const form = $('filters');
let rows = [], total = 0, appState, generation = 0, lastFinished, pendingRequest = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
  }
  return response.json();
}
function error(message = '') { $('error').textContent = message; $('error').hidden = !message; }
function shortTime(at, zone) {
  return new Date(at).toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZone:zone});
}
function animalTitle(result) {
  if (!result?.animals?.length) return 'A quiet moment';
  return result.animals.map(a => `${a.count} ${a.species}`).join(' · ');
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(svg.namespaceURI, 'path');
  path.setAttribute('d', name === 'star' ? 'm12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z' : 'M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5');
  svg.append(path); return svg;
}
function card(row, featured = false) {
  const button = el('button', featured ? 'observation featured' : 'observation'); button.type = 'button';
  const media = el('div', 'image-wrap');
  if (row.image_url) {
    const img = el('img'); img.src = row.image_url; img.alt = row.result?.scene || `Frame from ${row.cam_name}`;
    img.loading = featured ? 'eager' : 'lazy'; img.width = 1280; img.height = 720;
    img.addEventListener('error', () => { media.replaceChildren(el('div', 'no-image', 'Image unavailable')); });
    media.append(img);
  } else {
    const missing = el('div', 'no-image');
    missing.append(el('span', '', row.status === 'offline' ? '◌' : '◎'), el('small', '', row.status === 'ok' ? 'Image expired' : row.status === 'offline' ? 'Camera offline' : 'Check failed'));
    media.append(missing);
  }
  if (row.interesting) {
    const tag = el('span', 'tag'); tag.append(icon('star'), el('span', '', 'Interesting')); media.append(tag);
  }
  if (featured) media.append(el('span', 'latest-label', 'Latest capture'));
  if (row.image_url) {
    const inspect = el('span', 'inspect'); inspect.setAttribute('aria-hidden', 'true');
    inspect.append(icon('expand')); media.append(inspect);
  }
  const info = el('div', 'card-info');
  const meta = el('div', 'card-meta');
  const time = el('time', '', shortTime(row.checked_at_utc, row.timezone)); time.dateTime = row.checked_at_utc;
  time.title = `${row.checked_at_utc} · ${row.timezone}`;
  meta.append(el('span', 'cam-caption', row.cam_name), time);
  info.append(meta, el('h2', '', row.result ? animalTitle(row.result) : row.status === 'offline' ? 'Camera offline' : 'Check interrupted'));
  info.append(el('p', row.error ? 'card-error' : '', row.error || row.result?.scene || 'No observation available.'));
  button.append(media, info);
  button.addEventListener('click', () => showDetail(row));
  return button;
}
function query(offset = 0) {
  const params = new URLSearchParams(new FormData(form));
  for (const [key, value] of [...params]) if (!value) params.delete(key);
  params.set('offset', offset); return params;
}
async function load(more = false) {
  const requestId = ++generation;
  $('more').disabled = true;
  try {
    const data = await api(`/api/checks?${query(more ? rows.length : 0)}`);
    if (requestId !== generation) return;
    rows = more ? [...rows, ...data.checks] : data.checks; total = data.total;
    if (!more) $('gallery').replaceChildren();
    data.checks.forEach((row, i) => $('gallery').append(card(row, !more && i === 0 && row.image_url && row.status === 'ok')));
    $('gallery').classList.toggle('single', rows.length === 1);
    $('count').textContent = `${total.toLocaleString()} ${total === 1 ? 'check' : 'checks'}`;
    $('empty').hidden = total > 0;
    const filtered = [...new FormData(form)].some(([, v]) => v);
    $('empty').querySelector('h2').textContent = filtered ? 'Nothing in this view. Yet.' : "Let's see who's out there.";
    $('empty').querySelector('.eyebrow').textContent = filtered ? 'Keep looking' : 'Ready when you are';
    $('empty-copy').textContent = filtered ? 'Try another species, camera, or date range.' : 'Capture your first frame. Big cats, little birds, and everything in between.';
    $('empty-run').dataset.action = filtered ? 'clear' : 'run';
    $('empty-run').firstChild.textContent = filtered ? 'Reset filters ' : 'Capture a frame ';
    $('empty-run').disabled = !filtered && $('run').disabled;
    $('more').hidden = rows.length >= total;
    error();
  } catch (e) { if (requestId === generation) error(e.message); }
  finally { if (requestId === generation) $('more').disabled = false; }
}
function options(id, items, label) {
  const select = $(id), selected = select.value;
  const values = items.map(item => typeof item === 'string' ? [item, item] : [item.id, item.name]);
  if (JSON.stringify(values) === select.dataset.options) return;
  select.dataset.options = JSON.stringify(values);
  select.replaceChildren(new Option(label, ''), ...values.map(([value, name]) => new Option(name, value)));
  select.value = selected;
}
function syncViews() {
  const interesting = form.elements.interesting.checked, birds = form.elements.group.checked;
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === 'all' ? !interesting && !birds : button.dataset.view === 'interesting' ? interesting : birds;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  }
  for (const button of document.querySelectorAll('.camera-item')) {
    const selected = button.dataset.cam === $('cam').value;
    button.classList.toggle('selected', selected); button.setAttribute('aria-pressed', String(selected));
  }
  const selectedCam = appState?.cams.find(cam => cam.id === $('cam').value);
  $('run-scope').textContent = selectedCam ? selectedCam.name : 'All cameras';
  const advanced = ['date_from', 'date_to', 'status'].filter(name => form.elements[name].value).length;
  $('filter-badge').hidden = !advanced; $('filter-badge').textContent = advanced;
}
function renderCameras() {
  $('camera-total').textContent = appState.cams.length;
  const signature = JSON.stringify(appState.cams);
  if ($('camera-list').dataset.cameras === signature) return;
  $('camera-list').dataset.cameras = signature;
  $('camera-list').replaceChildren();
  for (const cam of appState.cams) {
    const button = el('button', 'camera-item'); button.type = 'button'; button.dataset.cam = cam.id;
    const initials = cam.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
    const copy = el('span', 'camera-copy');
    copy.append(el('span', 'camera-name', cam.name), el('span', 'camera-zone', cam.timezone.replaceAll('_', ' ')));
    button.append(el('span', 'camera-avatar', initials), copy);
    button.addEventListener('click', () => { $('cam').value = cam.id; syncViews(); load(); });
    $('camera-list').append(button);
  }
}
async function refreshState() {
  appState = await api('/api/state');
  options('cam', appState.cams, 'All cameras'); options('species', appState.species, 'All species');
  const w = appState.worker, busy = w.running || w.queued || pendingRequest;
  $('run').disabled = busy || !appState.configured;
  $('run-label').textContent = busy ? 'Checking…' : 'Check now';
  if ($('empty-run').dataset.action !== 'clear') $('empty-run').disabled = $('run').disabled;
  $('connection').textContent = !appState.configured ? 'Setup needed' : busy ? 'Checking cameras' : w.error ? 'Check needs attention' : w.schedule_enabled ? 'Auto capture on' : 'Manual mode';
  $('connection').classList.toggle('busy', busy);
  $('run-status').classList.toggle('busy', busy);
  const cam = appState.cams.find(c => c.id === w.cam_id);
  $('run-status').textContent = !appState.configured ? 'Add OPENAI_API_KEY to .env, then restart to enable checks.' :
    busy ? `Watching ${cam ? cam.name : 'all cameras'}. Capturing a frame and looking for wildlife…` :
    w.error ? w.error : w.last_finished_at ? `Last check finished ${shortTime(w.last_finished_at)}.` : '';
  $('schedule').textContent = w.schedule_enabled ? `Every ${appState.interval_min} min${w.next_run_at ? ` · next ${new Date(w.next_run_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}` : ''}` : 'Manual checks · schedule paused';
  $('model').textContent = `${appState.cams.length} ${appState.cams.length === 1 ? 'camera' : 'cameras'} · ${appState.model}`;
  renderCameras(); syncViews();
  if (lastFinished !== undefined && lastFinished !== w.last_finished_at) await load();
  lastFinished = w.last_finished_at;
}
function showDetail(row) {
  const content = $('detail-content'); content.replaceChildren();
  content.classList.toggle('no-detail-image', !row.image_url);
  if (row.image_url) {
    const img = el('img', 'detail-image'); img.src = row.image_url; img.alt = row.result?.scene || row.cam_name;
    content.append(img);
  }
  const body = el('div', 'detail-body');
  body.append(el('div', 'detail-meta', `${row.cam_name} · ${shortTime(row.checked_at_utc, row.timezone)} · ${row.timezone}`), el('h2', '', row.result ? animalTitle(row.result) : row.status));
  body.querySelector('h2').id = 'detail-title';
  if (row.error) body.append(el('p', 'error', row.error));
  const result = row.result;
  if (result) {
    body.append(el('p', 'scene', result.scene));
    const reason = el('div', 'reason', result.interesting_reason);
    reason.append(el('small', '', `${result.interesting ? 'Interesting' : 'Routine observation'} · score ${result.interesting_score}/10${row.alerted ? ' · alert sent' : ''}`));
    body.append(reason, el('h3', '', 'Wildlife observed'));
    if (!result.animals.length) body.append(el('p', 'detail-meta', 'No animals confidently identified in this frame.'));
    for (const a of result.animals) {
      const animal = el('div', 'animal-row'), info = el('div');
      info.append(el('strong', '', a.species), el('p', '', [a.group, a.behaviors.join(', '), a.notes].filter(Boolean).join(' · ')));
      const confidence = el('span', 'confidence'), meter = el('meter');
      meter.min = 0; meter.max = 1; meter.value = a.confidence;
      meter.setAttribute('aria-label', `Confidence for ${a.species}`);
      confidence.append(meter, el('span', '', `${Math.round(a.confidence * 100)}% confidence`)); info.append(confidence);
      animal.append(el('span', 'animal-count', a.count), info); body.append(animal);
    }
    if (result.events.length) {
      body.append(el('h3', '', 'Noteworthy events')); const list = el('ul');
      for (const event of result.events) list.append(el('li', '', event)); body.append(list);
    }
    if (result.local_time_from_overlay) body.append(el('p', 'detail-meta', `Camera overlay reads: ${result.local_time_from_overlay}`));
  }
  const links = el('div', 'detail-links');
  const stream = el('a', '', 'Open live camera'); stream.href = row.url; stream.target = '_blank'; stream.rel = 'noopener noreferrer'; links.append(stream);
  if (row.image_url) { const original = el('a', '', 'View full image'); original.href = row.image_url; original.target = '_blank'; original.rel = 'noopener'; links.append(original); }
  body.append(links);
  const raw = el('details'); raw.append(el('summary', '', 'Full saved record'), el('pre', '', JSON.stringify(row, null, 2))); body.append(raw);
  content.append(body); $('detail').showModal();
}
$('close').addEventListener('click', () => $('detail').close());
$('detail').addEventListener('click', e => { if (e.target === $('detail')) { const rect = $('detail').getBoundingClientRect(); if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) $('detail').close(); } });
form.addEventListener('submit', e => e.preventDefault());
form.addEventListener('change', () => { syncViews(); load(); });
function resetFilters() { form.reset(); syncViews(); load(); }
$('clear').addEventListener('click', resetFilters);
$('filter-toggle').addEventListener('click', () => {
  const open = $('advanced-filters').hidden;
  $('advanced-filters').hidden = !open; $('filter-toggle').setAttribute('aria-expanded', String(open));
});
for (const button of document.querySelectorAll('[data-view]')) {
  button.addEventListener('click', () => {
    if (button.dataset.view === 'all') form.reset();
    else {
      form.elements.interesting.checked = button.dataset.view === 'interesting';
      form.elements.group.checked = button.dataset.view === 'birds';
      form.elements.animals.checked = false;
    }
    syncViews(); load();
  });
}
$('empty-run').addEventListener('click', () => $('empty-run').dataset.action === 'clear' ? resetFilters() : $('run').click());
$('camera-guide').addEventListener('click', () => $('camera-help').showModal());
$('mobile-camera-guide').addEventListener('click', () => $('camera-help').showModal());
$('camera-help-close').addEventListener('click', () => $('camera-help').close());
$('copy-config').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('camera-snippet').textContent); $('copy-config').textContent = 'Copied camera config'; }
  catch { $('copy-config').textContent = 'Select and copy the snippet above'; }
});
$('more').addEventListener('click', () => load(true));
$('run').addEventListener('click', async () => {
  pendingRequest = true; $('run').disabled = true;
  try {
    await api('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cam_id:$('cam').value || null})});
    pendingRequest = false; await refreshState();
  } catch (e) { error(e.message); }
  finally { pendingRequest = false; if (appState) $('run').disabled = appState.worker.running || appState.worker.queued || !appState.configured; }
});
async function poll() {
  try { await refreshState(); } catch (e) { error(`Cannot reach animalcam: ${e.message}`); }
  setTimeout(poll, appState?.worker.running || appState?.worker.queued ? 2000 : 10000);
}
load(); poll();

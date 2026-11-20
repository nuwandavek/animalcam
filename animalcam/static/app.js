const $ = id => document.getElementById(id);
const form = $('filters');
let rows = [], total = 0, appState, generation = 0, lastFinished, pendingRequest = false;
let highlightRow = null, highlightLoading = false;
let lastFactsRevision;
let statsPeriod = 'day', statsRequest = 0, statsQuery = '', statsViews = [];

function statsTooltip(_handler, event, _item, value) {
  const tip = $('stats-tooltip');
  tip.hidden = !value;
  if (!value) return;
  tip.textContent = Object.entries(value).map(([key, val]) => `${key}: ${val}`).join('\n');
  tip.style.left = `${Math.max(8, Math.min(event.clientX+12, window.innerWidth-230))}px`;
  tip.style.top = `${Math.max(8, Math.min(event.clientY+12, window.innerHeight-120))}px`;
}
async function drawStats(data) {
  for (const view of statsViews) view.finalize();
  statsViews = [];
  const species = $('species-chart'), activity = $('activity-chart'), top = $('activity-top-chart');
  species.replaceChildren(); activity.replaceChildren(); top.replaceChildren();
  const heatWidth = Math.max(460, $('heatmap-scroll').clientWidth || 460);
  $('species-empty').hidden = data.species.length > 0;
  for (const [node, spec] of [
    [species, AnimalCharts.speciesSpec(data.species, species.clientWidth || 320)],
    [top, AnimalCharts.activityTopSpec(data.activity, heatWidth)],
    [activity, AnimalCharts.activitySpec(data.activity, data.dates, heatWidth, data.bucket_labels)]
  ]) {
    if (node === species && !data.species.length) continue;
    const view = new vega.View(vega.parse(spec, null, {ast:true}), {
      expr:vega.expressionInterpreter, renderer:'svg', container:node, hover:true, tooltip:statsTooltip
    });
    statsViews.push(view);
    await view.runAsync();
  }
}
async function loadStats(force = false) {
  const params = new URLSearchParams({period:statsPeriod});
  if ($('cam').value) params.set('cam', $('cam').value);
  const key = params.toString();
  if (!force && statsQuery === key) return;
  statsQuery = key;
  const requestId = ++statsRequest;
  $('stats-error').hidden = true;
  $('stats').setAttribute('aria-busy', 'true');
  try {
    const data = await api(`/api/stats?${params}`);
    if (requestId !== statsRequest) return;
    const cam = appState?.cams.find(c => c.id === $('cam').value);
    $('stats-scope').textContent = `${cam ? cam.name : 'All cameras'} · all history`;
    $('stats-grain').textContent = `${{day:'Day',week:'Week starting',month:'Month'}[statsPeriod]} × hour`;
    $('stats-diversity').textContent = `${data.species_count} species · frames`;
    $('stats-total').textContent = `${data.wildlife_frames.toLocaleString()} wildlife frames / ${data.total_checks.toLocaleString()} analyzed · confident sightings only`;
    await drawStats(data);
  } catch (e) {
    if (requestId === statsRequest) {
      statsQuery = '';
      $('stats-error').textContent = `Stats unavailable: ${e.message}`; $('stats-error').hidden = false;
    }
  } finally { if (requestId === statsRequest) $('stats').setAttribute('aria-busy', 'false'); }
}

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
function money(value) {
  return new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', minimumFractionDigits:2,
    maximumFractionDigits:value > 0 && value < .01 ? 6 : 4}).format(value);
}
function renderFact(fact) {
  $('highlight-fact').hidden = !fact;
  $('highlight').classList.toggle('has-fact', Boolean(fact));
  if (fact) {
    const changed = $('fact-title').textContent !== fact.title || $('fact-text').textContent !== fact.text;
    $('fact-species').textContent = fact.species || 'Animal spotlight';
    $('fact-title').textContent = fact.title;
    $('fact-text').textContent = fact.text;
    $('fact-source').textContent = fact.source;
    $('fact-source').href = fact.url;
    if (changed && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      $('fact-story').animate([{opacity:0, transform:'translateY(6px)'}, {opacity:1, transform:'translateY(0)'}],
        {duration:340, easing:'cubic-bezier(.2,.7,.2,1)'});
    }
  }
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
function card(row) {
  const button = el('button', 'observation'); button.type = 'button';
  const media = el('div', 'image-wrap');
  if (row.image_url) {
    const img = el('img'); img.src = row.image_url; img.alt = row.result?.scene || `Frame from ${row.cam_name}`;
    img.loading = 'lazy'; img.width = 1280; img.height = 720;
    img.addEventListener('error', () => { media.replaceChildren(el('div', 'no-image', 'Image unavailable')); });
    media.append(img);
  } else {
    const missing = el('div', 'no-image');
    missing.append(el('span', '', row.status === 'offline' ? '◌' : '◎'), el('small', '', row.status === 'ok' ? 'Image expired' : row.status === 'offline' ? 'Camera offline' : 'Check failed'));
    media.append(missing);
  }
  if (row.interesting) {
    const tag = el('span', 'tag'); tag.title = 'New or noteworthy compared with the previous check';
    tag.append(icon('star'), el('span', '', 'New sighting')); media.append(tag);
  }
  if (row.image_url) {
    const inspect = el('span', 'inspect'); inspect.setAttribute('aria-hidden', 'true');
    inspect.append(icon('expand')); media.append(inspect);
  }
  const info = el('div', 'card-info');
  const meta = el('div', 'card-meta');
  const time = el('time', '', shortTime(row.checked_at_utc, row.timezone)); time.dateTime = row.checked_at_utc;
  time.title = `${row.checked_at_utc} · ${row.timezone}`;
  meta.append(el('span', 'cam-caption', row.cam_name), time);
  info.append(el('h2', '', row.result ? animalTitle(row.result) : row.status === 'offline' ? 'Camera offline' : 'Check interrupted'), meta);
  if (row.error) info.append(el('p', 'card-error', row.error));
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
    data.checks.forEach(row => $('gallery').append(card(row)));
    $('count').textContent = `${total.toLocaleString()} ${total === 1 ? 'check' : 'checks'}`;
    $('empty').hidden = total > 0;
    const filtered = [...new FormData(form)].some(([key, v]) => v && key !== 'animals');
    const animalsOnly = form.elements.animals.checked && !filtered;
    $('empty').querySelector('h2').textContent = filtered ? 'Nothing in this view. Yet.' : animalsOnly ? 'No wildlife sightings yet.' : "Let's see who's out there.";
    $('empty').querySelector('.eyebrow').textContent = filtered ? 'Keep looking' : 'Ready when you are';
    $('empty-copy').textContent = filtered ? 'Try another species, camera, or date range.' : animalsOnly ? 'Capture another frame, or turn off Animals or birds to see every check.' : 'Capture your first frame. Big cats, little birds, and everything in between.';
    $('empty-run').dataset.action = filtered ? 'clear' : 'run';
    $('empty-run').firstChild.textContent = filtered ? 'Reset filters ' : 'Capture a frame ';
    $('empty-run').disabled = !filtered && $('run').disabled;
    $('more').hidden = rows.length >= total;
    error();
  } catch (e) { if (requestId === generation) error(e.message); }
  finally { if (requestId === generation) $('more').disabled = false; }
}
async function loadHighlight(shuffle = false) {
  if (highlightLoading) return;
  highlightLoading = true;
  $('highlight-shuffle').disabled = true;
  $('highlight-shuffle-label').textContent = 'Finding a sighting…';
  $('highlight-error').hidden = true;
  $('highlight').setAttribute('aria-busy', 'true');
  try {
    const exclude = shuffle && highlightRow ? `?exclude_id=${highlightRow.id}` : '';
    const data = await api(`/api/highlight${exclude}`);
    highlightRow = data.check;
    $('highlight').hidden = !highlightRow;
    $('overview').classList.toggle('without-highlight', !highlightRow);
    if (!highlightRow) return;
    const row = highlightRow;
    $('highlight-image').src = row.image_url;
    $('highlight-image').alt = row.result.scene;
    const selection = data.selection;
    $('highlight-facts').textContent = `${selection.animal_count} ${selection.animal_count === 1 ? 'animal' : 'animals'}${selection.species_count > 1 ? ` · ${selection.species_count} species` : ''}`;
    $('highlight-title').textContent = animalTitle(row.result);
    $('highlight-meta').textContent = `${row.cam_name} · ${shortTime(row.checked_at_utc, row.timezone)} · ${row.timezone}`;
    $('highlight-reason').textContent = selection.reason;
    renderFact(data.fact);
    $('highlight-open').setAttribute('aria-label', `Open sighting: ${animalTitle(row.result)}`);
    $('highlight-note').textContent = data.has_alternatives ? '' : 'Your first highlight. More will appear as your cameras capture wildlife.';
    $('highlight-note').hidden = data.has_alternatives;
    $('highlight-shuffle').disabled = !data.has_alternatives;
  } catch (e) {
    $('highlight-error').textContent = `Could not load a cool sighting: ${e.message}`;
    $('highlight-error').hidden = false;
    $('highlight-shuffle').disabled = false;
  } finally {
    highlightLoading = false;
    $('highlight-shuffle-label').textContent = 'Random cool sighting';
    $('highlight').setAttribute('aria-busy', 'false');
  }
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
  $('about-cameras').replaceChildren();
  for (const cam of appState.cams) {
    const button = el('button', 'camera-item'); button.type = 'button'; button.dataset.cam = cam.id;
    const initials = cam.name.split(/\s+/).slice(0, 2).map(word => word[0]).join('').toUpperCase();
    const copy = el('span', 'camera-copy');
    copy.append(el('span', 'camera-name', cam.name), el('span', 'camera-zone', cam.timezone.replaceAll('_', ' ')));
    button.append(el('span', 'camera-avatar', initials), copy);
    button.addEventListener('click', () => { $('cam').value = cam.id; syncViews(); load(); loadStats(); });
    $('camera-list').append(button);
    const link = el('a', '', `${cam.name} ↗`);
    link.href = cam.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    $('about-cameras').append(link);
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
  const blockedByYouTube = w.error && w.last_run?.some(run => run.error?.includes('YouTube bot check'));
  const checkError = blockedByYouTube ? 'Live capture blocked by YouTube. Camera access needs attention; saved captures are still available.' : w.error;
  $('run-status').textContent = !appState.configured ? 'Add OPENAI_API_KEY to .env, then restart to enable checks.' :
    busy ? `Watching ${cam ? cam.name : 'all cameras'}. Capturing a frame and looking for wildlife…` :
    checkError ? checkError : w.last_finished_at ? `Last check finished ${shortTime(w.last_finished_at)}.` : '';
  $('schedule').textContent = w.schedule_enabled ? `Every ${appState.interval_min} min${w.next_run_at ? ` · next ${new Date(w.next_run_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}` : ''}` : 'Manual checks · schedule paused';
  $('about-interval').textContent = w.schedule_enabled ? `every ${appState.interval_min} minutes` : 'on demand (automatic checks are paused)';
  $('model').textContent = `${appState.cams.length} ${appState.cams.length === 1 ? 'camera' : 'cameras'} · ${appState.model}`;
  const costs = appState.costs;
  if (costs) {
    $('cost-total').textContent = `${costs.backfilled_calls ? '≈ ' : ''}${money(costs.total_usd)}`;
    $('cost-meta').textContent = `${costs.calls} calls${costs.backfilled_calls ? ` · ${costs.backfilled_calls} backfilled` : ''}${costs.unpriced_calls ? ` · ${costs.unpriced_calls} unpriced` : ''}`;
  }
  renderCameras(); syncViews();
  if (lastFactsRevision !== appState.facts_revision && highlightRow) {
    const currentId = highlightRow.id;
    const detail = await api(`/api/checks/${currentId}`);
    if (highlightRow.id === currentId) renderFact(detail.fact);
  }
  lastFactsRevision = appState.facts_revision;
  if (lastFinished !== undefined && lastFinished !== w.last_finished_at) {
    await load();
    await loadHighlight();
    await loadStats(true);
  }
  lastFinished = w.last_finished_at;
}
async function showDetail(row) {
  try { row = await api(`/api/checks/${row.id}`); } catch { /* Existing gallery data can still be inspected. */ }
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
    reason.append(el('small', '', `${result.interesting ? 'New or noteworthy' : 'Routine observation'} · novelty ${result.interesting_score}/10${row.alerted ? ' · alert sent' : ''}`));
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
  if (row.llm_calls?.length) {
    body.append(el('h3', '', 'Luna usage'));
    for (const call of row.llm_calls) {
      body.append(el('p', 'call-cost', `${call.estimated_cost_usd === null ? 'Cost unavailable' : money(call.estimated_cost_usd)} · ${call.source === 'backfill' ? 'Approximate historical usage' : 'Reported token usage'}`));
      body.append(el('p', 'detail-meta', `${call.input_tokens ?? 'Unknown'} input · ${call.cached_input_tokens ?? 0} cached · ${call.output_tokens ?? 'unknown'} output tokens · ${call.image_width}px image`));
    }
  }
  const raw = el('details'); raw.append(el('summary', '', 'Full saved record'), el('pre', '', JSON.stringify(row, null, 2))); body.append(raw);
  content.append(body); $('detail').showModal();
}
$('close').addEventListener('click', () => $('detail').close());
$('detail').addEventListener('click', e => { if (e.target === $('detail')) { const rect = $('detail').getBoundingClientRect(); if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) $('detail').close(); } });
form.addEventListener('submit', e => e.preventDefault());
form.addEventListener('change', () => { syncViews(); load(); loadStats(); });
function resetFilters() { form.reset(); syncViews(); load(); loadStats(); }
$('clear').addEventListener('click', resetFilters);
$('filter-toggle').addEventListener('click', () => {
  const open = $('advanced-filters').hidden;
  $('advanced-filters').hidden = !open; $('filter-toggle').setAttribute('aria-expanded', String(open));
});
$('about-open').addEventListener('click', () => $('about').showModal());
$('about-close').addEventListener('click', () => $('about').close());
$('about').addEventListener('click', e => {
  if (e.target !== $('about')) return;
  const rect = $('about').getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) $('about').close();
});
$('empty-run').addEventListener('click', () => $('empty-run').dataset.action === 'clear' ? resetFilters() : $('run').click());
$('camera-guide').addEventListener('click', () => $('camera-help').showModal());
$('mobile-camera-guide').addEventListener('click', () => $('camera-help').showModal());
$('camera-help-close').addEventListener('click', () => $('camera-help').close());
$('copy-config').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('camera-snippet').textContent); $('copy-config').textContent = 'Copied camera config'; }
  catch { $('copy-config').textContent = 'Select and copy the snippet above'; }
});
$('more').addEventListener('click', () => load(true));
$('highlight-shuffle').addEventListener('click', () => loadHighlight(true));
for (const id of ['highlight-open', 'highlight-view']) $(id).addEventListener('click', () => { if (highlightRow) showDetail(highlightRow); });
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
for (const button of document.querySelectorAll('[data-period]')) {
  button.addEventListener('click', () => {
    statsPeriod = button.dataset.period;
    for (const item of document.querySelectorAll('[data-period]')) {
      const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active));
    }
    loadStats();
  });
}
let statsResize;
let statsWidth = 0;
new ResizeObserver(entries => {
  const width = Math.round(entries[0].contentRect.width);
  if (width === statsWidth) return;
  statsWidth = width;
  clearTimeout(statsResize);
  statsResize = setTimeout(() => loadStats(true), 180);
}).observe($('stats').parentElement);
load(); loadHighlight(); loadStats(); poll();

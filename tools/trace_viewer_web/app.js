const state = {
  events: [],
  seenSeqs: new Set(),
  selectedSeq: null,
  paused: false,
  visibleCount: null,
  followLive: true,
  streamOpen: false,
  renderQueued: false,
  options: {
    payloadTypes: new Set(),
    threads: new Set(),
    turns: new Set(),
    steps: new Set(),
    categories: new Set(),
    names: new Set(),
    phases: new Set(),
    correlationKeys: new Set(),
  },
};

const elements = {
  connection: document.querySelector('[data-testid="connection-status"]'),
  connectionLabel: document.querySelector('#connection-label'),
  metaTrace: document.querySelector('#meta-trace'),
  metaRollout: document.querySelector('#meta-rollout'),
  metaRoot: document.querySelector('#meta-root'),
  metaStarted: document.querySelector('#meta-started'),
  metaFormat: document.querySelector('#meta-format'),
  search: document.querySelector('#search-filter'),
  payload: document.querySelector('#payload-filter'),
  thread: document.querySelector('#thread-filter'),
  turn: document.querySelector('#turn-filter'),
  step: document.querySelector('#step-filter'),
  category: document.querySelector('#category-filter'),
  name: document.querySelector('#name-filter'),
  phase: document.querySelector('#phase-filter'),
  correlationKey: document.querySelector('#correlation-key-filter'),
  correlationValue: document.querySelector('#correlation-value-filter'),
  harnessOnly: document.querySelector('#harness-only-filter'),
  reset: document.querySelector('#reset-filters'),
  pause: document.querySelector('#pause-stream'),
  follow: document.querySelector('#follow-live'),
  list: document.querySelector('#event-list'),
  empty: document.querySelector('#empty-state'),
  matched: document.querySelector('#matched-count'),
  received: document.querySelector('#received-count'),
  buffered: document.querySelector('#buffered-count'),
  notice: document.querySelector('#stream-notice'),
  detail: document.querySelector('#event-detail'),
  detailEmpty: document.querySelector('#detail-empty'),
};

function text(value, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function setConnection(mode, label) {
  elements.connection.dataset.state = mode;
  elements.connectionLabel.textContent = label;
}

function eventIdentity(event) {
  const harness = event.harness;
  return harness ? `${text(harness.category, 'harness')}.${text(harness.name, '?')}` : event.payload_type;
}

function eventSearchText(event) {
  return JSON.stringify({
    seq: event.seq,
    payload_type: event.payload_type,
    thread_id: event.thread_id,
    codex_turn_id: event.codex_turn_id,
    harness: event.harness,
    payload_metadata: event.payload_metadata,
  }).toLowerCase();
}

function matches(event) {
  if (elements.payload.value && event.payload_type !== elements.payload.value) return false;
  if (elements.thread.value && event.thread_id !== elements.thread.value) return false;
  if (elements.turn.value && event.codex_turn_id !== elements.turn.value) return false;
  if (elements.step.value && event.harness?.step_id !== elements.step.value) return false;
  const category = elements.category.value;
  if (category && event.harness?.category !== category) return false;
  if (elements.name.value && event.harness?.name !== elements.name.value) return false;
  if (elements.phase.value && event.harness?.phase !== elements.phase.value) return false;
  if (elements.harnessOnly.checked && !event.harness) return false;
  const correlationKey = elements.correlationKey.value;
  const correlationValue = elements.correlationValue.value.trim().toLowerCase();
  const correlations = event.harness?.correlations || {};
  if (correlationKey && !(correlationKey in correlations)) return false;
  if (correlationValue) {
    const candidates = correlationKey ? [correlations[correlationKey]] : Object.values(correlations);
    if (!candidates.some((value) => text(value, '').toLowerCase().includes(correlationValue))) return false;
  }
  const query = elements.search.value.trim().toLowerCase();
  return !query || eventSearchText(event).includes(query);
}

function formatStarted(value) {
  if (!Number.isFinite(value)) return '-';
  return new Date(value).toLocaleString();
}

function refreshSelect(select, values, defaultLabel) {
  const selected = select.value;
  const sorted = [...values].sort();
  select.replaceChildren(new Option(defaultLabel, ''));
  for (const value of sorted) select.add(new Option(value, value));
  select.value = sorted.includes(selected) ? selected : '';
}

function refreshOptions() {
  refreshSelect(elements.payload, state.options.payloadTypes, 'All packet types');
  refreshSelect(elements.thread, state.options.threads, 'All threads');
  refreshSelect(elements.turn, state.options.turns, 'All turns');
  refreshSelect(elements.step, state.options.steps, 'All steps');
  refreshSelect(elements.category, state.options.categories, 'All categories');
  refreshSelect(elements.name, state.options.names, 'All event names');
  refreshSelect(elements.phase, state.options.phases, 'All phases');
  refreshSelect(elements.correlationKey, state.options.correlationKeys, 'Any key');
}

function addOptions(event) {
  state.options.payloadTypes.add(event.payload_type);
  if (event.thread_id) state.options.threads.add(event.thread_id);
  if (event.codex_turn_id) state.options.turns.add(event.codex_turn_id);
  if (event.harness?.step_id) state.options.steps.add(event.harness.step_id);
  if (event.harness?.category) state.options.categories.add(event.harness.category);
  if (event.harness?.name) state.options.names.add(event.harness.name);
  if (event.harness?.phase) state.options.phases.add(event.harness.phase);
  for (const key of Object.keys(event.harness?.correlations || {})) {
    state.options.correlationKeys.add(key);
  }
}

function showDetail(event) {
  state.selectedSeq = event.seq;
  elements.detail.textContent = JSON.stringify(event, null, 2);
  elements.detail.hidden = false;
  elements.detailEmpty.hidden = true;
  renderEvents(false);
}

function eventRow(event) {
  const harness = event.harness;
  const item = document.createElement('li');
  item.className = `event-row category-${harness?.category || 'raw'}`;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'event-button';
  button.dataset.testid = `event-${event.seq}`;
  button.setAttribute('aria-current', state.selectedSeq === event.seq ? 'true' : 'false');
  button.addEventListener('click', () => showDetail(event));
  const columns = [
    ['event-seq', `#${event.seq}`],
    ['event-kind', harness?.category || 'raw'],
    ['event-name', eventIdentity(event)],
    ['event-phase', harness?.phase || text(event.payload_metadata?.status, 'packet')],
    ['event-thread', text(event.thread_id, 'no thread')],
  ];
  for (const [className, value] of columns) {
    const span = document.createElement('span');
    span.className = className;
    span.textContent = value;
    button.append(span);
  }
  item.append(button);
  return item;
}

function displayedEvents() {
  return state.paused ? state.events.slice(0, state.visibleCount) : state.events;
}

function updateCounts(filteredCount) {
  const visibleCount = displayedEvents().length;
  const bufferedCount = state.events.length - visibleCount;
  elements.matched.textContent = filteredCount;
  elements.received.textContent = state.events.length;
  elements.buffered.hidden = bufferedCount === 0;
  elements.buffered.textContent = bufferedCount ? `+${bufferedCount} buffered` : '';
}

function renderEvents(follow = state.followLive) {
  const displayed = displayedEvents();
  const filtered = displayed.filter(matches);
  const fragment = document.createDocumentFragment();
  for (const event of filtered) fragment.append(eventRow(event));
  elements.list.replaceChildren(fragment);
  updateCounts(filtered.length);
  elements.empty.hidden = displayed.length > 0;
  if (displayed.length > 0 && filtered.length === 0) {
    elements.empty.hidden = false;
    elements.empty.textContent = 'No events match the current filters.';
  }
  if (follow && filtered.length) elements.list.scrollTop = elements.list.scrollHeight;
}

function scheduleStreamRender() {
  if (state.renderQueued) return;
  state.renderQueued = true;
  window.requestAnimationFrame(() => {
    state.renderQueued = false;
    refreshOptions();
    if (state.paused) updateCounts(displayedEvents().filter(matches).length);
    else renderEvents();
  });
}

function receiveEvent(event) {
  if (state.seenSeqs.has(event.seq)) return;
  state.seenSeqs.add(event.seq);
  state.events.push(event);
  addOptions(event);
  scheduleStreamRender();
}

async function loadHeader() {
  const response = await fetch('/api/header', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Header request failed (${response.status})`);
  const metadata = await response.json();
  elements.metaTrace.textContent = text(metadata.trace_id, metadata.source_name);
  elements.metaTrace.title = elements.metaTrace.textContent;
  elements.metaRollout.textContent = text(metadata.rollout_id);
  elements.metaRollout.title = elements.metaRollout.textContent;
  elements.metaRoot.textContent = text(metadata.root_thread_id);
  elements.metaRoot.title = elements.metaRoot.textContent;
  elements.metaStarted.textContent = formatStarted(metadata.started_at_unix_ms);
  elements.metaFormat.textContent = `raw v${text(metadata.raw_schema_version, metadata.schema_version)} / JSONL`;
  elements.metaFormat.title = `${text(metadata.raw_event_log)}; bundle v${text(metadata.manifest_schema_version, '?')}; ${text(metadata.stream_mode)}`;
}

function connect() {
  setConnection('connecting', 'Connecting');
  const source = new EventSource('/api/stream');
  source.addEventListener('open', () => {
    state.streamOpen = true;
    setConnection(state.paused ? 'paused' : 'live', state.paused ? 'Paused' : 'Live');
  });
  source.addEventListener('trace', (message) => {
    const update = JSON.parse(message.data);
    receiveEvent(update.event);
  });
  source.addEventListener('trace-error', (message) => {
    const update = JSON.parse(message.data);
    elements.notice.textContent = update.message || 'The trace stream reported an error.';
    elements.notice.hidden = false;
    state.streamOpen = false;
    setConnection('error', 'Trace error');
    source.close();
  });
  source.addEventListener('error', () => {
    state.streamOpen = false;
    if (source.readyState !== EventSource.CLOSED) setConnection('connecting', 'Reconnecting');
  });
}

const filterControls = [
  elements.search, elements.payload, elements.thread, elements.turn, elements.step,
  elements.category, elements.name, elements.phase, elements.correlationKey,
  elements.correlationValue, elements.harnessOnly,
];
for (const control of filterControls) {
  control.addEventListener('input', () => renderEvents(false));
  control.addEventListener('change', () => renderEvents(false));
}
elements.reset.addEventListener('click', () => {
  for (const control of filterControls) {
    if (control.type === 'checkbox') control.checked = false;
    else control.value = '';
  }
  elements.harnessOnly.checked = false;
  renderEvents(false);
});
elements.pause.addEventListener('click', () => {
  state.paused = !state.paused;
  state.visibleCount = state.paused ? state.events.length : null;
  elements.pause.textContent = state.paused ? 'Resume' : 'Pause';
  elements.pause.setAttribute('aria-pressed', state.paused ? 'true' : 'false');
  if (state.streamOpen) setConnection(state.paused ? 'paused' : 'live', state.paused ? 'Paused' : 'Live');
  renderEvents(!state.paused && state.followLive);
});
elements.follow.addEventListener('click', () => {
  state.followLive = !state.followLive;
  elements.follow.textContent = `Follow: ${state.followLive ? 'on' : 'off'}`;
  elements.follow.setAttribute('aria-pressed', state.followLive ? 'true' : 'false');
  if (state.followLive) elements.list.scrollTop = elements.list.scrollHeight;
});

loadHeader().then(connect).catch((error) => {
  elements.notice.textContent = error.message;
  elements.notice.hidden = false;
  setConnection('error', 'Unavailable');
});

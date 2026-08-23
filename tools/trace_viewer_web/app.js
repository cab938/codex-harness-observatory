const state = {
  events: [],
  seenSeqs: new Set(),
  selectedSeq: null,
  paused: false,
  visibleCount: null,
  followLive: true,
  streamOpen: false,
  waitingForTrace: false,
  renderQueued: false,
  artifactRequest: 0,
  tools: new Map(),
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
  detailContent: document.querySelector('#detail-content'),
  detailCategory: document.querySelector('#detail-category'),
  detailPhase: document.querySelector('#detail-phase'),
  detailEventTitle: document.querySelector('#detail-event-title'),
  detailDescription: document.querySelector('#detail-description'),
  detailFacts: document.querySelector('#detail-facts'),
  evidenceSection: document.querySelector('#evidence-section'),
  artifactLinks: document.querySelector('#artifact-links'),
  artifactViewer: document.querySelector('#artifact-viewer'),
  artifactTitle: document.querySelector('#artifact-title'),
  artifactMeta: document.querySelector('#artifact-meta'),
  artifactContent: document.querySelector('#artifact-content'),
  patchExplanation: document.querySelector('#patch-explanation'),
  patchFiles: document.querySelector('#patch-files'),
  patchContent: document.querySelector('#patch-content'),
};

function text(value, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function setConnection(mode, label) {
  elements.connection.dataset.state = mode;
  elements.connectionLabel.textContent = label;
}

function humanize(value) {
  return text(value, '?').replaceAll('_', ' ');
}

function mergeDefined(base, update) {
  const merged = { ...base };
  for (const [key, value] of Object.entries(update || {})) {
    if (value !== null && value !== undefined && value !== '') merged[key] = value;
  }
  return merged;
}

function registerTool(event) {
  const tool = event.tool;
  if (!tool?.call_id) return;
  state.tools.set(tool.call_id, mergeDefined(state.tools.get(tool.call_id) || {}, tool));
}

function toolForEvent(event) {
  const tool = event.tool;
  if (!tool?.call_id) return tool || null;
  return mergeDefined(state.tools.get(tool.call_id) || {}, tool);
}

function eventCategory(event) {
  if (event.harness?.category) return event.harness.category;
  if (event.payload_type.startsWith('code_cell_')) return 'code';
  if (event.payload_type.startsWith('inference_')) return 'model';
  if (toolForEvent(event)) return 'tool';
  return 'raw';
}

function toolLifecycle(event) {
  const names = {
    tool_call_started: 'call started',
    tool_call_runtime_started: 'runtime started',
    tool_call_runtime_ended: 'runtime ended',
    tool_call_ended: 'call ended',
    code_cell_started: 'code cell started',
    code_cell_initial_response: 'initial response',
    code_cell_ended: 'code cell ended',
  };
  return names[event.payload_type] || humanize(event.payload_type);
}

function withoutRepeatedPhase(label, event) {
  const suffix = ` ${humanize(eventPhase(event))}`;
  return label.endsWith(suffix) ? label.slice(0, -suffix.length) : label;
}

function eventIdentity(event) {
  const tool = toolForEvent(event);
  if (tool?.name) {
    const action = event.harness ? humanize(event.harness.name) : toolLifecycle(event);
    return withoutRepeatedPhase(`${tool.name} · ${action}`, event);
  }
  if (event.payload_type === 'protocol_event_observed') {
    return humanize(event.payload_metadata?.event_type || event.payload_type);
  }
  if (event.payload_type.startsWith('inference_')) {
    const inferenceLabels = {
      inference_started: 'model request',
      inference_completed: 'model response',
      inference_failed: 'model request failed',
      inference_cancelled: 'model request cancelled',
    };
    return inferenceLabels[event.payload_type] || humanize(event.payload_type);
  }
  const harness = event.harness;
  const label = harness ? humanize(harness.name) : humanize(event.payload_type);
  return withoutRepeatedPhase(label, event);
}

function eventPhase(event) {
  if (event.harness?.phase) return event.harness.phase;
  if (event.payload_metadata?.status) return event.payload_metadata.status;
  if (event.payload_type.endsWith('_started')) return 'started';
  if (event.payload_type.endsWith('_completed')) return 'completed';
  if (event.payload_type.endsWith('_ended')) return 'ended';
  if (event.payload_type.endsWith('_failed')) return 'failed';
  return 'packet';
}

function eventDescription(event) {
  const tool = toolForEvent(event);
  if (tool?.classification_label && event.harness) {
    return `${humanize(event.harness.name)} for ${tool.name || 'this tool'}. ${tool.classification_label}.`;
  }
  if (tool?.classification_label) return tool.classification_label;
  if (event.payload_type === 'inference_started') return 'Core assembled and sent a model request.';
  if (event.payload_type === 'inference_completed') return 'Core received the model output items for this sampling request.';
  if (event.payload_type === 'code_cell_started') return 'The model emitted JavaScript that Codex executes inside code mode.';
  if (event.harness) return `Core harness transition: ${humanize(event.harness.category)} / ${humanize(event.harness.name)}.`;
  return `Raw Core rollout event: ${humanize(event.payload_type)}.`;
}

function eventSearchText(event) {
  return JSON.stringify({
    seq: event.seq,
    payload_type: event.payload_type,
    thread_id: event.thread_id,
    codex_turn_id: event.codex_turn_id,
    harness: event.harness,
    payload_metadata: event.payload_metadata,
    tool: toolForEvent(event),
  }).toLowerCase();
}

function matches(event) {
  if (elements.payload.value && event.payload_type !== elements.payload.value) return false;
  if (elements.thread.value && event.thread_id !== elements.thread.value) return false;
  if (elements.turn.value && event.codex_turn_id !== elements.turn.value) return false;
  if (elements.step.value && event.harness?.step_id !== elements.step.value) return false;
  const category = elements.category.value;
  if (category && eventCategory(event) !== category) return false;
  const selectedName = elements.name.value;
  if (selectedName && ![event.harness?.name, toolForEvent(event)?.name].includes(selectedName)) return false;
  if (elements.phase.value && eventPhase(event) !== elements.phase.value) return false;
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
  state.options.categories.add(eventCategory(event));
  if (event.harness?.name) state.options.names.add(event.harness.name);
  if (toolForEvent(event)?.name) state.options.names.add(toolForEvent(event).name);
  state.options.phases.add(eventPhase(event));
  for (const key of Object.keys(event.harness?.correlations || {})) {
    state.options.correlationKeys.add(key);
  }
}

function appendFact(label, value) {
  if (value === null || value === undefined || value === '') return;
  const wrapper = document.createElement('div');
  const term = document.createElement('dt');
  const detail = document.createElement('dd');
  term.textContent = label;
  detail.textContent = String(value);
  wrapper.append(term, detail);
  elements.detailFacts.append(wrapper);
}

function renderOverview(event) {
  const tool = toolForEvent(event);
  elements.detailCategory.textContent = eventCategory(event);
  elements.detailPhase.textContent = eventPhase(event);
  elements.detailEventTitle.textContent = eventIdentity(event);
  elements.detailDescription.textContent = eventDescription(event);
  elements.detailFacts.replaceChildren();
  appendFact('Sequence', `#${event.seq}`);
  appendFact('Tool', tool?.name);
  appendFact('Tool class', tool?.classification_label);
  appendFact('Requester', tool?.requester ? humanize(tool.requester) : null);
  appendFact('Tool call ID', tool?.call_id);
  appendFact('Thread', event.thread_id);
  appendFact('Turn', event.codex_turn_id);
  appendFact('Agent step', event.harness?.step_id);
}

function referenceKind(reference) {
  const kind = reference?.kind;
  if (typeof kind === 'string') return kind;
  if (kind && typeof kind === 'object') return kind.type || kind.value || 'payload';
  return humanize(reference?.field || 'payload');
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function parseJsonString(value) {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch (_error) {
    return value;
  }
}

function patchDetails(content) {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return null;
  const payload = content.payload && typeof content.payload === 'object' ? content.payload : {};
  const argumentsValue = parseJsonString(payload.arguments);
  let patchText = typeof payload.input === 'string' ? payload.input : null;
  if (!patchText && argumentsValue && typeof argumentsValue === 'object') {
    for (const key of ['patch', 'input', 'patch_text']) {
      if (typeof argumentsValue[key] === 'string') {
        patchText = argumentsValue[key];
        break;
      }
    }
  }
  if (!patchText && typeof payload.arguments === 'string' && payload.arguments.includes('*** Begin Patch')) {
    patchText = payload.arguments;
  }

  const files = [];
  if (content.changes && typeof content.changes === 'object' && !Array.isArray(content.changes)) {
    files.push(...Object.keys(content.changes));
  }
  if (patchText) {
    for (const match of patchText.matchAll(/^\*\*\* (?:Add|Update|Delete) File: (.+)$/gm)) files.push(match[1]);
    for (const match of patchText.matchAll(/^\*\*\* Move to: (.+)$/gm)) files.push(match[1]);
  }
  const isPatch = content.tool_name === 'apply_patch' || Boolean(patchText?.includes('*** Begin Patch')) || files.length > 0;
  if (!isPatch) return null;
  return { patchText, files: [...new Set(files)] };
}

function renderArtifact(reference, artifact) {
  elements.artifactTitle.textContent = `${humanize(referenceKind(reference))} · ${artifact.path}`;
  elements.artifactMeta.textContent = [artifact.media_type, formatBytes(artifact.size_bytes)].filter(Boolean).join(' · ');
  elements.artifactContent.textContent = typeof artifact.content === 'string'
    ? artifact.content
    : JSON.stringify(artifact.content, null, 2);

  const patch = patchDetails(artifact.content);
  elements.patchExplanation.hidden = !patch;
  elements.patchFiles.replaceChildren();
  elements.patchContent.hidden = true;
  elements.patchContent.textContent = '';
  if (patch) {
    for (const path of patch.files) {
      const chip = document.createElement('code');
      chip.textContent = path;
      elements.patchFiles.append(chip);
    }
    if (patch.patchText) {
      elements.patchContent.textContent = patch.patchText;
      elements.patchContent.hidden = false;
    }
  }
}

async function openArtifact(event, reference, button) {
  const request = ++state.artifactRequest;
  for (const candidate of elements.artifactLinks.querySelectorAll('button')) {
    candidate.setAttribute('aria-pressed', candidate === button ? 'true' : 'false');
  }
  elements.artifactViewer.hidden = false;
  elements.artifactTitle.textContent = reference.path;
  elements.artifactMeta.textContent = 'Loading…';
  elements.artifactContent.textContent = 'Loading artifact content…';
  elements.patchExplanation.hidden = true;
  try {
    const response = await fetch(`/api/artifact?path=${encodeURIComponent(reference.path)}`, { cache: 'no-store' });
    const artifact = await response.json();
    if (!response.ok) throw new Error(artifact.error || `Artifact request failed (${response.status})`);
    if (request !== state.artifactRequest || state.selectedSeq !== event.seq) return;
    renderArtifact(reference, artifact);
  } catch (error) {
    if (request !== state.artifactRequest || state.selectedSeq !== event.seq) return;
    elements.artifactMeta.textContent = 'Unavailable';
    elements.artifactContent.textContent = error.message;
  }
}

function renderArtifactLinks(event) {
  state.artifactRequest += 1;
  elements.artifactLinks.replaceChildren();
  elements.artifactViewer.hidden = true;
  elements.patchExplanation.hidden = true;
  const references = event.payload_references || [];
  elements.evidenceSection.hidden = references.length === 0;
  references.forEach((reference, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'artifact-link';
    button.dataset.testid = `artifact-${event.seq}-${index}`;
    button.setAttribute('aria-pressed', 'false');
    const kind = document.createElement('span');
    kind.className = 'artifact-kind';
    kind.textContent = humanize(referenceKind(reference));
    const path = document.createElement('code');
    path.textContent = reference.path;
    const field = document.createElement('span');
    field.className = 'artifact-field';
    field.textContent = humanize(reference.field);
    button.append(kind, path, field);
    button.addEventListener('click', () => openArtifact(event, reference, button));
    elements.artifactLinks.append(button);
  });
}

function showDetail(event) {
  state.selectedSeq = event.seq;
  elements.detail.textContent = JSON.stringify(event, null, 2);
  renderOverview(event);
  renderArtifactLinks(event);
  elements.detailContent.hidden = false;
  elements.detailEmpty.hidden = true;
  renderEvents(false);
}

function eventRow(event) {
  const category = eventCategory(event);
  const item = document.createElement('li');
  item.className = `event-row category-${category}`;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'event-button';
  button.dataset.testid = `event-${event.seq}`;
  button.setAttribute('aria-current', state.selectedSeq === event.seq ? 'true' : 'false');
  button.addEventListener('click', () => showDetail(event));
  const columns = [
    ['event-seq', `#${event.seq}`],
    ['event-kind', category],
    ['event-name', eventIdentity(event)],
    ['event-phase', eventPhase(event)],
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
  registerTool(event);
  state.events.push(event);
  addOptions(event);
  const selected = state.events.find((candidate) => candidate.seq === state.selectedSeq);
  if (selected && event.tool?.call_id && toolForEvent(selected)?.call_id === event.tool.call_id) {
    renderOverview(selected);
  }
  scheduleStreamRender();
}

function displayHeader(metadata) {
  state.waitingForTrace = metadata.stream_mode === 'waiting_for_trace_bundle';
  elements.metaTrace.textContent = text(metadata.trace_id, metadata.source_name);
  elements.metaTrace.title = elements.metaTrace.textContent;
  elements.metaRollout.textContent = text(metadata.rollout_id);
  elements.metaRollout.title = elements.metaRollout.textContent;
  elements.metaRoot.textContent = text(metadata.root_thread_id);
  elements.metaRoot.title = elements.metaRoot.textContent;
  elements.metaStarted.textContent = formatStarted(metadata.started_at_unix_ms);
  const contentMode = metadata.content_mode === 'full' ? 'full content' : 'redacted';
  elements.metaFormat.textContent = `raw v${text(metadata.raw_schema_version, metadata.schema_version)} / ${contentMode}`;
  elements.metaFormat.title = `${text(metadata.raw_event_log)}; bundle v${text(metadata.manifest_schema_version, '?')}; ${text(metadata.stream_mode)}`;
}

async function loadHeader() {
  const response = await fetch('/api/header', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Header request failed (${response.status})`);
  displayHeader(await response.json());
}

function connect() {
  setConnection('connecting', 'Connecting');
  const source = new EventSource('/api/stream');
  source.addEventListener('open', () => {
    state.streamOpen = true;
    if (state.waitingForTrace) setConnection('connecting', 'Waiting for first task');
    else setConnection(state.paused ? 'paused' : 'live', state.paused ? 'Paused' : 'Live');
  });
  source.addEventListener('trace-source', (message) => {
    const update = JSON.parse(message.data);
    displayHeader(update.metadata);
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

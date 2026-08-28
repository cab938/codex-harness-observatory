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
  selectedCategories: new Set(),
  tools: new Map(),
  taskFocus: null,
  tasks: new Map(),
  threads: new Map(),
  header: {},
  concurrency: {},
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
  categorySummary: document.querySelector('#category-filter-summary'),
  categoryOptions: document.querySelector('#category-options'),
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
  countLabel: document.querySelector('#count-label'),
  received: document.querySelector('#received-count'),
  receivedContext: document.querySelector('#received-context'),
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
  identifierDetails: document.querySelector('#identifier-details'),
  detailIdentifiers: document.querySelector('#detail-identifiers'),
  evidenceSection: document.querySelector('#evidence-section'),
  artifactLinks: document.querySelector('#artifact-links'),
  artifactViewer: document.querySelector('#artifact-viewer'),
  artifactTitle: document.querySelector('#artifact-title'),
  artifactMeta: document.querySelector('#artifact-meta'),
  artifactContent: document.querySelector('#artifact-content'),
  patchExplanation: document.querySelector('#patch-explanation'),
  patchFiles: document.querySelector('#patch-files'),
  patchContent: document.querySelector('#patch-content'),
  taskFocusControls: document.querySelector('#task-focus-controls'),
  taskTree: document.querySelector('#task-tree'),
  taskConcurrency: document.querySelector('#task-concurrency-summary'),
};

const SESSION_LANE = '__session_global__';
const TASK_STATUS_PRIORITY = {
  observed: 0,
  waiting: 1,
  active: 2,
  completed: 3,
  failed: 4,
};

function text(value, fallback = '-') {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function setConnection(mode, label) {
  elements.connection.dataset.state = mode;
  elements.connectionLabel.textContent = label;
  elements.connection.hidden = mode === 'live';
}

function humanize(value) {
  return text(value, '?').replaceAll('_', ' ');
}

function sentence(value) {
  if (value === null || value === undefined || value === '') return '';
  const label = humanize(value);
  return label === '?' ? label : label.charAt(0).toUpperCase() + label.slice(1);
}

function categoryLabel(value) {
  const labels = { app_server: 'App Server', mcp: 'MCP' };
  return labels[value] || sentence(value);
}

function record(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function firstValue(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== '') return String(value);
  }
  return '';
}

function taskPayload(event) {
  return record(event.task);
}

function ingestConcurrency(snapshot) {
  const concurrency = record(snapshot);
  if (Object.keys(concurrency).length) state.concurrency = { ...state.concurrency, ...concurrency };
}

function taskCorrelations(event) {
  return record(event.harness?.correlations);
}

function taskRootForEvent(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  const correlations = taskCorrelations(event);
  return firstValue(
    event.task_root_thread_id,
    task.rootThreadId,
    task.root_thread_id,
    task.taskRootThreadId,
    task.task_root_thread_id,
    metadata.task_root_thread_id,
    metadata.root_thread_id,
    correlations.task_root_thread_id,
    correlations.root_thread_id,
  );
}

function threadForEvent(event) {
  const task = taskPayload(event);
  const correlations = taskCorrelations(event);
  return firstValue(
    task.threadId,
    task.thread_id,
    event.thread_id,
    correlations.task_thread_id,
    correlations.child_thread_id,
  );
}

function parentThreadForEvent(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  const correlations = taskCorrelations(event);
  return firstValue(
    task.parentThreadId,
    task.parent_thread_id,
    event.parent_thread_id,
    metadata.parent_thread_id,
    correlations.parent_thread_id,
  );
}

function relatedTaskThreadForEvent(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  const correlations = taskCorrelations(event);
  return firstValue(
    task.taskThreadId,
    task.task_thread_id,
    metadata.task_thread_id,
    correlations.task_thread_id,
  );
}

function taskStatus(value) {
  const normalized = text(value, '').trim().toLowerCase().replaceAll('-', '_').replaceAll(' ', '_');
  if (!normalized) return '';
  if (/(failed|error|cancelled|canceled|interrupted|rejected)/.test(normalized)) return 'failed';
  if (/(complete|success|succeed|done|finished)/.test(normalized)) return 'completed';
  if (/(active|running|started|working|in_progress)/.test(normalized)) return 'active';
  if (/(waiting|queued|paused|pending)/.test(normalized)) return 'waiting';
  return 'observed';
}

function statusForEvent(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  const details = record(event.harness?.details);
  return taskStatus(firstValue(
    event.task_status,
    event.task_lifecycle,
    task.status,
    task.lifecycle,
    task.state,
    metadata.task_status,
    metadata.task_lifecycle,
    details.task_status,
    details.task_lifecycle,
  ));
}

function threadStatusForEvent(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  return taskStatus(firstValue(
    task.threadStatus,
    task.thread_status,
    task.threadLifecycle,
    task.thread_lifecycle,
    metadata.thread_status,
    metadata.thread_lifecycle,
  ));
}

function statusLabel(status) {
  const labels = {
    active: 'Active',
    completed: 'Completed',
    failed: 'Failed',
    waiting: 'Waiting',
    observed: 'Observed',
  };
  return labels[status] || 'Observed';
}

function mergeTaskStatus(current, next) {
  if (!next) return current || 'observed';
  if (!current || TASK_STATUS_PRIORITY[next] >= TASK_STATUS_PRIORITY[current]) return next;
  return current;
}

function shortIdentifier(value, length = 12) {
  const identifier = text(value, '');
  return identifier.length > length ? `${identifier.slice(0, length - 1)}…` : identifier;
}

function pathLabel(value) {
  const path = text(value, '');
  if (!path) return '';
  const segments = path.split('/').filter(Boolean);
  return segments.at(-1) || path;
}

function taskTone(value) {
  let hash = 0;
  for (const character of String(value)) hash = ((hash << 5) - hash) + character.charCodeAt(0);
  return `task-tone-${Math.abs(hash) % 5}`;
}

function updateTask(rootId, updates = {}) {
  if (!rootId) return null;
  const existing = state.tasks.get(rootId) || {
    rootId,
    title: '',
    status: 'observed',
    tone: taskTone(rootId),
  };
  if (updates.title) existing.title = updates.title;
  existing.status = mergeTaskStatus(existing.status, updates.status);
  state.tasks.set(rootId, existing);
  return existing;
}

function updateThread(threadId, rootId, updates = {}) {
  if (!threadId || !rootId) return null;
  const existing = state.threads.get(threadId) || {
    threadId,
    rootId,
    parentThreadId: '',
    title: '',
    status: 'observed',
  };
  existing.rootId = rootId;
  if (updates.parentThreadId && updates.parentThreadId !== threadId) existing.parentThreadId = updates.parentThreadId;
  if (updates.title) existing.title = updates.title;
  existing.status = mergeTaskStatus(existing.status, updates.status);
  state.threads.set(threadId, existing);
  return existing;
}

function eventTaskTitle(event) {
  const task = taskPayload(event);
  const metadata = record(event.payload_metadata);
  return firstValue(
    task.title,
    task.name,
    task.label,
    task.taskTitle,
    task.task_title,
    metadata.task_title,
    metadata.task_name,
  );
}

function eventThreadTitle(event) {
  const task = taskPayload(event);
  const correlations = taskCorrelations(event);
  return pathLabel(firstValue(
    task.agentPath,
    task.agent_path,
    task.threadTitle,
    task.thread_title,
    task.agentName,
    task.agent_name,
    correlations.task_path,
    correlations.agent_path,
  ));
}

function ingestTaskEvent(event) {
  const rootId = taskRootForEvent(event);
  ingestConcurrency(taskPayload(event).concurrency);
  if (!rootId) return;
  const status = statusForEvent(event);
  const threadStatus = threadStatusForEvent(event) || status;
  updateTask(rootId, { title: eventTaskTitle(event), status });
  updateThread(rootId, rootId, { status });

  const threadId = threadForEvent(event);
  const parentThreadId = parentThreadForEvent(event);
  if (threadId) {
    updateThread(threadId, rootId, {
      parentThreadId: threadId === rootId ? '' : (parentThreadId || rootId),
      title: eventThreadTitle(event),
      status: threadStatus,
    });
  }

  const relatedThreadId = relatedTaskThreadForEvent(event);
  if (relatedThreadId && relatedThreadId !== threadId) {
    updateThread(relatedThreadId, rootId, {
      parentThreadId: parentThreadId || rootId,
      title: eventThreadTitle(event),
      status: threadStatus,
    });
  }

  const correlations = taskCorrelations(event);
  const metadata = record(event.payload_metadata);
  const childThreadId = firstValue(
    taskPayload(event).childThreadId,
    taskPayload(event).child_thread_id,
    metadata.child_thread_id,
    correlations.child_thread_id,
  );
  if (childThreadId) {
    updateThread(childThreadId, rootId, {
      parentThreadId: parentThreadId || threadId || rootId,
      title: pathLabel(firstValue(taskPayload(event).childAgentPath, correlations.child_task_path)),
    });
  }
}

function ingestHeaderTasks(metadata) {
  ingestConcurrency(metadata.concurrency);
  const listedTasks = Array.isArray(metadata.tasks)
    ? metadata.tasks
    : Object.entries(record(metadata.tasks)).map(([rootThreadId, task]) => ({ ...record(task), rootThreadId }));
  for (const task of listedTasks) {
    const rootId = firstValue(task.rootThreadId, task.root_thread_id, task.taskRootThreadId, task.id);
    if (!rootId) continue;
    const rootStatus = taskStatus(firstValue(task.status, task.lifecycle, task.state));
    updateTask(rootId, {
      title: firstValue(task.title, task.name, task.label, task.taskTitle, task.task_title),
      status: rootStatus,
    });
    updateThread(rootId, rootId, { status: rootStatus });
    for (const thread of Array.isArray(task.threads) ? task.threads : []) {
      const threadId = firstValue(thread.threadId, thread.thread_id, thread.id);
      if (!threadId) continue;
      updateThread(threadId, rootId, {
        parentThreadId: firstValue(thread.parentThreadId, thread.parent_thread_id),
        title: pathLabel(firstValue(thread.agentPath, thread.agent_path, thread.title, thread.name, thread.label)),
        status: taskStatus(firstValue(thread.status, thread.lifecycle, thread.state)),
      });
    }
  }
}

function laneForEvent(event) {
  const rootId = taskRootForEvent(event);
  if (!rootId) {
    return {
      key: SESSION_LANE,
      label: 'Session / global',
      title: 'Session and global trace events with no task root',
      status: 'observed',
      tone: 'task-tone-session',
    };
  }
  const task = updateTask(rootId);
  const thread = state.threads.get(threadForEvent(event));
  const taskLabel = task.title || `Task ${shortIdentifier(rootId)}`;
  const childLabel = thread && thread.threadId !== rootId
    ? (thread.title || `Agent ${shortIdentifier(thread.threadId)}`)
    : '';
  return {
    key: rootId,
    label: childLabel ? `${taskLabel} / ${childLabel}` : taskLabel,
    title: `${taskLabel} (${rootId})${childLabel ? ` / ${thread.threadId}` : ''}`,
    status: thread?.status || task.status,
    tone: task.tone,
  };
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

const CATEGORY_ORDER = [
  'app_server', 'agent_loop', 'context', 'model', 'tool', 'mcp',
  'decision', 'hooks', 'supervision', 'multi_agent', 'code', 'raw',
];

function compareCategories(left, right) {
  const leftIndex = CATEGORY_ORDER.indexOf(left);
  const rightIndex = CATEGORY_ORDER.indexOf(right);
  if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
  if (leftIndex === -1) return 1;
  if (rightIndex === -1) return -1;
  return leftIndex - rightIndex;
}

function teachingCategory(event) {
  if (event.payload_type === 'app_server_frame_observed') return 'app_server';
  if (event.payload_type === 'mcp_frame_observed') return 'mcp';
  if (event.harness?.name?.startsWith('hook_')) return 'hooks';
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
  const phase = eventPhase(event);
  if (!phase) return label;
  const suffix = ` ${humanize(phase)}`;
  return label.endsWith(suffix) ? label.slice(0, -suffix.length) : label;
}

function eventIdentity(event) {
  const wire = event.payload_metadata || {};
  if (event.payload_type === 'app_server_frame_observed') {
    const boundary = wire.direction === 'client_to_server'
      ? 'Client -> App Server'
      : 'App Server -> Client';
    return `${boundary} · ${wire.method || sentence(wire.frame_kind || 'frame')}`;
  }
  if (event.payload_type === 'mcp_frame_observed') {
    const server = wire.server_name || 'MCP server';
    const boundary = wire.direction === 'client_to_server'
      ? `Codex -> ${server}`
      : `${server} -> Codex`;
    return `${boundary} · ${wire.method || sentence(wire.frame_kind || 'frame')}`;
  }
  const tool = toolForEvent(event);
  if (tool?.name) {
    const action = event.harness ? humanize(event.harness.name) : toolLifecycle(event);
    return withoutRepeatedPhase(`${tool.name} · ${sentence(action)}`, event);
  }
  if (event.payload_type === 'protocol_event_observed') {
    return sentence(event.payload_metadata?.event_type || event.payload_type);
  }
  if (event.payload_type.startsWith('inference_')) {
    const inferenceLabels = {
      inference_started: 'Model request',
      inference_completed: 'Model response',
      inference_failed: 'Model request failed',
      inference_cancelled: 'Model request cancelled',
    };
    return inferenceLabels[event.payload_type] || sentence(event.payload_type);
  }
  const harness = event.harness;
  const label = harness ? humanize(harness.name) : humanize(event.payload_type);
  return sentence(withoutRepeatedPhase(label, event));
}

function eventPhase(event) {
  if (event.harness?.phase) return event.harness.phase;
  if (event.payload_metadata?.frame_kind) return event.payload_metadata.frame_kind;
  if (event.payload_metadata?.status) return event.payload_metadata.status;
  if (event.payload_type.endsWith('_started')) return 'started';
  if (event.payload_type.endsWith('_completed')) return 'completed';
  if (event.payload_type.endsWith('_ended')) return 'ended';
  if (event.payload_type.endsWith('_failed')) return 'failed';
  return '';
}

function eventDescription(event) {
  const tool = toolForEvent(event);
  if (tool?.classification_label) return tool.classification_label;
  if (event.payload_type === 'inference_started') return 'Model input assembled and sent.';
  if (event.payload_type === 'inference_completed') return 'Model output items received.';
  if (event.payload_type === 'code_cell_started') return 'JavaScript entered the built-in code-mode runtime.';
  if (event.payload_type === 'app_server_frame_observed') return 'Exact JSON-RPC frame observed at the App Server transport boundary.';
  if (event.payload_type === 'mcp_frame_observed') return 'Exact JSON-RPC frame observed at the MCP client transport boundary.';
  const descriptions = {
    turn_input_disposition: 'Determines whether input starts, steers, or interrupts a turn.',
    step_context_capture: eventPhase(event) === 'started'
      ? 'Collecting resources for the agent step.'
      : 'Environment, tools, and capability roots available to the agent step.',
    prompt_assembly: 'Model input assembled from conversation and selected context.',
    compaction_decision: 'Determines whether to retain or compact the active context.',
    guardian_review: 'A separate reviewer evaluated an approval request.',
  };
  return descriptions[event.harness?.name] || '';
}

function eventSearchText(event) {
  return JSON.stringify({
    seq: event.seq,
    payload_type: event.payload_type,
    task_root_thread_id: taskRootForEvent(event),
    task: taskPayload(event),
    thread_id: event.thread_id,
    codex_turn_id: event.codex_turn_id,
    harness: event.harness,
    payload_metadata: event.payload_metadata,
    tool: toolForEvent(event),
  }).toLowerCase();
}

function eventCorrelations(event) {
  const correlations = { ...(event.harness?.correlations || {}) };
  const rootId = taskRootForEvent(event);
  if (rootId) correlations.task_root_thread_id = rootId;
  const parentThreadId = parentThreadForEvent(event);
  if (parentThreadId) correlations.parent_thread_id = parentThreadId;
  for (const [key, value] of Object.entries(event.payload_metadata || {})) {
    if (key.endsWith('_id')) correlations[key] = value;
  }
  return correlations;
}

function appServerPairing(event) {
  if (event.payload_type !== 'app_server_frame_observed') return null;
  const metadata = record(event.payload_metadata);
  const connectionId = firstValue(metadata.connection_id);
  const requestId = firstValue(metadata.request_id);
  if (!connectionId || !requestId) return null;
  const direction = firstValue(metadata.direction);
  const frameKind = firstValue(metadata.frame_kind).toLowerCase();
  if (!direction || !frameKind) return null;
  const role = frameKind === 'request'
    ? 'request'
    : (frameKind === 'response' || frameKind === 'error' ? 'response' : 'other');
  return {
    key: `${connectionId}\u001f${requestId}`,
    connectionId,
    requestId,
    direction,
    frameKind,
    role,
  };
}

function appServerPair(event) {
  const pairing = appServerPairing(event);
  if (!pairing || pairing.role === 'other') return pairing;
  const counterpartDirection = pairing.direction === 'client_to_server'
    ? 'server_to_client'
    : (pairing.direction === 'server_to_client' ? 'client_to_server' : '');
  if (!counterpartDirection) return pairing;
  const counterpart = state.events
    .filter((candidate) => candidate.seq !== event.seq)
    .map((candidate) => ({ candidate, pairing: appServerPairing(candidate) }))
    .filter(({ pairing: candidatePairing }) => candidatePairing
      && candidatePairing.key === pairing.key
      && candidatePairing.direction === counterpartDirection
      && candidatePairing.role !== pairing.role)
    .sort((left, right) => Math.abs(left.candidate.seq - event.seq) - Math.abs(right.candidate.seq - event.seq))[0];
  return {
    ...pairing,
    counterpartSeq: counterpart?.candidate.seq || null,
    counterpartRole: counterpart?.pairing.role || null,
  };
}

function identifierLabel(key) {
  return sentence(key).replaceAll(' Id', ' ID');
}

function matches(event) {
  if (state.taskFocus && laneForEvent(event).key !== state.taskFocus) return false;
  if (elements.payload.value && event.payload_type !== elements.payload.value) return false;
  if (elements.thread.value && event.thread_id !== elements.thread.value) return false;
  if (elements.turn.value && event.codex_turn_id !== elements.turn.value) return false;
  if (elements.step.value && event.harness?.step_id !== elements.step.value) return false;
  if (state.selectedCategories.size && !state.selectedCategories.has(teachingCategory(event))) return false;
  const selectedName = elements.name.value;
  if (selectedName && ![
    event.harness?.name,
    toolForEvent(event)?.name,
    event.payload_metadata?.method,
  ].includes(selectedName)) return false;
  if (elements.phase.value && eventPhase(event) !== elements.phase.value) return false;
  if (elements.harnessOnly.checked && !event.harness) return false;
  const correlationKey = elements.correlationKey.value;
  const correlationValue = elements.correlationValue.value.trim().toLowerCase();
  const correlations = eventCorrelations(event);
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

function formatEventTime(value) {
  if (!Number.isFinite(value)) return '-';
  const date = new Date(value);
  const time = date.toLocaleTimeString([], { hour12: false });
  return `${time}.${String(date.getMilliseconds()).padStart(3, '0')}`;
}

function refreshSelect(select, values, defaultLabel) {
  const selected = select.value;
  const sorted = [...values].sort();
  select.replaceChildren(new Option(defaultLabel, ''));
  for (const value of sorted) select.add(new Option(value, value));
  select.value = sorted.includes(selected) ? selected : '';
}

function updateCategorySummary() {
  const selected = [...state.selectedCategories].sort(compareCategories);
  if (selected.length === 0) elements.categorySummary.textContent = 'All categories';
  else if (selected.length <= 2) elements.categorySummary.textContent = selected.map(categoryLabel).join(' + ');
  else elements.categorySummary.textContent = `${selected.length} categories`;
}

function refreshCategoryOptions() {
  const fragment = document.createDocumentFragment();
  for (const category of [...state.options.categories].sort(compareCategories)) {
    const option = document.createElement('label');
    option.className = `category-option category-${category}`;
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = category;
    checkbox.checked = state.selectedCategories.has(category);
    checkbox.dataset.testid = `category-${category}`;
    checkbox.addEventListener('change', () => {
      if (checkbox.checked) state.selectedCategories.add(category);
      else state.selectedCategories.delete(category);
      updateCategorySummary();
      renderEvents(false);
    });
    const label = document.createElement('span');
    label.textContent = categoryLabel(category);
    option.append(checkbox, label);
    fragment.append(option);
  }
  elements.categoryOptions.replaceChildren(fragment);
  updateCategorySummary();
}

function refreshOptions() {
  refreshSelect(elements.payload, state.options.payloadTypes, 'All packet types');
  refreshSelect(elements.thread, state.options.threads, 'All threads');
  refreshSelect(elements.turn, state.options.turns, 'All turns');
  refreshSelect(elements.step, state.options.steps, 'All steps');
  refreshCategoryOptions();
  refreshSelect(elements.name, state.options.names, 'All event names');
  refreshSelect(elements.phase, state.options.phases, 'All phases');
  refreshSelect(elements.correlationKey, state.options.correlationKeys, 'Any key');
}

function addOptions(event) {
  state.options.payloadTypes.add(event.payload_type);
  if (event.thread_id) state.options.threads.add(event.thread_id);
  if (event.codex_turn_id) state.options.turns.add(event.codex_turn_id);
  if (event.harness?.step_id) state.options.steps.add(event.harness.step_id);
  state.options.categories.add(teachingCategory(event));
  if (event.harness?.name) state.options.names.add(event.harness.name);
  if (toolForEvent(event)?.name) state.options.names.add(toolForEvent(event).name);
  if (event.payload_metadata?.method) state.options.names.add(event.payload_metadata.method);
  const phase = eventPhase(event);
  if (phase) state.options.phases.add(phase);
  for (const key of Object.keys(eventCorrelations(event))) {
    state.options.correlationKeys.add(key);
  }
}

function appendFact(target, label, value, seenValues = null) {
  if (value === null || value === undefined || value === '') return;
  const rendered = typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value);
  if (seenValues?.has(rendered)) return;
  seenValues?.add(rendered);
  const wrapper = document.createElement('div');
  const term = document.createElement('dt');
  const detail = document.createElement('dd');
  term.textContent = label;
  detail.textContent = rendered;
  wrapper.append(term, detail);
  target.append(wrapper);
}

function summaryValue(value) {
  if (typeof value === 'boolean' || typeof value === 'number') return value;
  if (typeof value === 'string' && value.length <= 120) return value;
  if (Array.isArray(value) && value.length <= 5 && value.every((item) => ['string', 'number', 'boolean'].includes(typeof item))) {
    return value.join(', ');
  }
  return null;
}

function renderOverview(event) {
  const tool = toolForEvent(event);
  const phase = eventPhase(event);
  const lane = laneForEvent(event);
  elements.detailCategory.textContent = categoryLabel(teachingCategory(event));
  elements.detailPhase.textContent = sentence(phase);
  elements.detailPhase.hidden = !phase;
  elements.detailEventTitle.textContent = eventIdentity(event);
  const description = eventDescription(event);
  elements.detailDescription.textContent = description;
  elements.detailDescription.hidden = !description;
  elements.detailFacts.replaceChildren();
  appendFact(elements.detailFacts, 'Sequence', `#${event.seq}`);
  appendFact(elements.detailFacts, 'Task lane', lane.label);
  if (lane.key !== SESSION_LANE) appendFact(elements.detailFacts, 'Task state', statusLabel(lane.status));
  appendFact(elements.detailFacts, 'Outcome', event.harness?.outcome ? sentence(event.harness.outcome) : null);
  appendFact(elements.detailFacts, 'Reason', event.harness?.reason ? humanize(event.harness.reason) : null);
  appendFact(elements.detailFacts, 'Requester', tool?.requester ? sentence(tool.requester) : null);
  appendFact(elements.detailFacts, 'Method', event.payload_metadata?.method);
  appendFact(elements.detailFacts, 'Direction', event.payload_metadata?.direction ? humanize(event.payload_metadata.direction) : null);
  appendFact(elements.detailFacts, 'Transport', event.payload_metadata?.transport ? humanize(event.payload_metadata.transport) : null);
  appendFact(elements.detailFacts, 'MCP server', event.payload_metadata?.server_name);
  for (const [key, value] of Object.entries(event.harness?.details || {})) {
    if (key.endsWith('_id')) continue;
    appendFact(elements.detailFacts, sentence(key), summaryValue(value));
  }

  elements.detailIdentifiers.replaceChildren();
  const seenIdentifiers = new Set();
  appendFact(elements.detailIdentifiers, 'Task root', taskRootForEvent(event), seenIdentifiers);
  appendFact(elements.detailIdentifiers, 'Parent thread', parentThreadForEvent(event), seenIdentifiers);
  appendFact(elements.detailIdentifiers, 'Tool call', tool?.call_id, seenIdentifiers);
  appendFact(elements.detailIdentifiers, 'Thread', event.thread_id, seenIdentifiers);
  appendFact(elements.detailIdentifiers, 'Turn', event.codex_turn_id, seenIdentifiers);
  appendFact(elements.detailIdentifiers, 'Agent step', event.harness?.step_id, seenIdentifiers);
  for (const [key, value] of Object.entries(event.harness?.correlations || {})) {
    appendFact(elements.detailIdentifiers, identifierLabel(key), summaryValue(value), seenIdentifiers);
  }
  for (const [key, value] of Object.entries(event.payload_metadata || {})) {
    if (!key.endsWith('_id')) continue;
    appendFact(elements.detailIdentifiers, identifierLabel(key), summaryValue(value), seenIdentifiers);
  }
  const pair = appServerPair(event);
  if (pair?.counterpartSeq) {
    appendFact(elements.detailIdentifiers, 'Paired frame', `#${pair.counterpartSeq} (${pair.counterpartRole})`, seenIdentifiers);
  } else if (pair?.role === 'request') {
    appendFact(elements.detailIdentifiers, 'Pairing', pair.direction === 'server_to_client' ? 'Server-initiated request' : 'Request', seenIdentifiers);
  }
  elements.identifierDetails.hidden = elements.detailIdentifiers.childElementCount === 0;
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
  elements.artifactTitle.textContent = artifact.path;
  elements.artifactMeta.textContent = [sentence(referenceKind(reference)), artifact.media_type, formatBytes(artifact.size_bytes)].filter(Boolean).join(' · ');
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
  elements.artifactMeta.textContent = 'Loading';
  elements.artifactContent.textContent = '';
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
    button.append(kind, path);
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
  const category = teachingCategory(event);
  const lane = laneForEvent(event);
  const pair = appServerPair(event);
  const selectedPair = state.selectedSeq === null
    ? null
    : appServerPair(state.events.find((candidate) => candidate.seq === state.selectedSeq) || {});
  const item = document.createElement('li');
  item.className = `event-row category-${category} ${lane.tone}`;
  item.dataset.taskRoot = lane.key;
  if (selectedPair?.counterpartSeq === event.seq) item.classList.add('event-row-related');
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'event-button';
  button.dataset.testid = `event-${event.seq}`;
  button.setAttribute('aria-current', state.selectedSeq === event.seq ? 'true' : 'false');
  button.addEventListener('click', () => showDetail(event));
  const columns = [
    ['event-seq', `#${event.seq}`],
    ['event-time', formatEventTime(event.wall_time_unix_ms)],
    ['event-name', eventIdentity(event)],
    ['event-lane', lane.label],
    ['event-kind', categoryLabel(category)],
    ['event-phase', sentence(eventPhase(event))],
  ];
  for (const [className, value] of columns) {
    const span = document.createElement('span');
    span.className = className;
    if (className === 'event-name' && pair?.counterpartSeq) {
      span.append(document.createTextNode(value));
      const badge = document.createElement('small');
      badge.className = 'event-pair';
      badge.textContent = `paired #${pair.counterpartSeq}`;
      span.append(badge);
    } else {
      span.textContent = value;
    }
    if (className === 'event-lane') span.title = lane.title;
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
  elements.countLabel.textContent = filteredCount === visibleCount ? ` event${visibleCount === 1 ? '' : 's'}` : '';
  elements.receivedContext.hidden = filteredCount === visibleCount;
  elements.received.textContent = `${visibleCount} event${visibleCount === 1 ? '' : 's'}`;
  elements.buffered.hidden = bufferedCount === 0;
  elements.buffered.textContent = bufferedCount ? `+${bufferedCount} buffered` : '';
}

function laneCounts() {
  const counts = new Map([[SESSION_LANE, 0]]);
  for (const event of displayedEvents()) {
    const lane = laneForEvent(event);
    counts.set(lane.key, (counts.get(lane.key) || 0) + 1);
  }
  return counts;
}

function concurrencySummary() {
  const activeCount = Number(state.concurrency.activeTaskCount);
  const maxActiveCount = Number(state.concurrency.maxActiveTaskCount);
  const labels = ['Raw sequence'];
  if (Number.isFinite(activeCount)) labels.push(`${activeCount} active`);
  if (Number.isFinite(maxActiveCount) && maxActiveCount > activeCount) labels.push(`peak ${maxActiveCount}`);
  return labels.join(' · ');
}

function taskLabel(task) {
  return task.title || `Task ${shortIdentifier(task.rootId)}`;
}

function threadLabel(thread) {
  return thread.title || `Agent ${shortIdentifier(thread.threadId)}`;
}

function taskStatusChip(status, fallback = '') {
  const chip = document.createElement('span');
  const normalized = status || 'observed';
  chip.className = `task-status task-status-${normalized}`;
  chip.textContent = fallback || statusLabel(normalized);
  return chip;
}

function taskCountChip(count) {
  const chip = document.createElement('span');
  chip.className = 'task-event-count';
  chip.textContent = `${count} event${count === 1 ? '' : 's'}`;
  return chip;
}

function focusTask(key) {
  state.taskFocus = key || null;
  renderEvents(false);
}

function taskFocusButton({ key, label, title, status, count, tone, testId }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `task-focus-button ${tone}`;
  button.dataset.taskRoot = key;
  button.dataset.testid = testId;
  button.setAttribute('aria-pressed', state.taskFocus === key ? 'true' : 'false');
  button.title = title || label;
  button.addEventListener('click', () => focusTask(key));
  const name = document.createElement('span');
  name.className = 'task-focus-name';
  name.textContent = label;
  button.append(name);
  if (status) button.append(taskStatusChip(status));
  button.append(taskCountChip(count));
  return button;
}

function appendThreadBranch(target, thread, threadsByParent, depth, visited) {
  if (visited.has(thread.threadId)) return;
  visited.add(thread.threadId);
  const item = document.createElement('li');
  item.className = 'task-thread-node';
  item.style.setProperty('--tree-depth', depth);
  item.title = thread.threadId;
  const connector = document.createElement('span');
  connector.className = 'task-thread-connector';
  connector.setAttribute('aria-hidden', 'true');
  connector.textContent = '└';
  const name = document.createElement('span');
  name.className = 'task-thread-name';
  name.textContent = threadLabel(thread);
  item.append(connector, name, taskStatusChip(thread.status));
  target.append(item);
  const children = threadsByParent.get(thread.threadId) || [];
  for (const child of children) appendThreadBranch(target, child, threadsByParent, depth + 1, visited);
}

function appendTaskTree(task, count, index) {
  const node = document.createElement('div');
  node.className = `task-tree-node ${task.tone}`;
  node.append(taskFocusButton({
    key: task.rootId,
    label: taskLabel(task),
    title: `${taskLabel(task)} (${task.rootId})`,
    status: task.status,
    count,
    tone: task.tone,
    testId: `task-focus-${index}`,
  }));

  const threads = [...state.threads.values()]
    .filter((thread) => thread.rootId === task.rootId && thread.threadId !== task.rootId)
    .sort((left, right) => threadLabel(left).localeCompare(threadLabel(right)));
  if (threads.length) {
    const branches = new Map();
    for (const thread of threads) {
      const parent = thread.parentThreadId && thread.parentThreadId !== thread.threadId
        ? thread.parentThreadId
        : task.rootId;
      if (!branches.has(parent)) branches.set(parent, []);
      branches.get(parent).push(thread);
    }
    const list = document.createElement('ul');
    list.className = 'task-thread-tree';
    const visited = new Set();
    for (const thread of branches.get(task.rootId) || []) {
      appendThreadBranch(list, thread, branches, 0, visited);
    }
    for (const thread of threads) appendThreadBranch(list, thread, branches, 0, visited);
    node.append(list);
  }
  elements.taskTree.append(node);
}

function renderTaskLanes() {
  const counts = laneCounts();
  elements.taskConcurrency.textContent = concurrencySummary();
  const allButton = document.createElement('button');
  allButton.type = 'button';
  allButton.className = 'task-focus-button task-focus-all';
  allButton.dataset.testid = 'task-focus-all';
  allButton.setAttribute('aria-pressed', state.taskFocus === null ? 'true' : 'false');
  allButton.addEventListener('click', () => focusTask(null));
  const allLabel = document.createElement('span');
  allLabel.className = 'task-focus-name';
  allLabel.textContent = 'All tasks';
  allButton.append(allLabel, taskCountChip(displayedEvents().length));
  elements.taskFocusControls.replaceChildren(allButton);

  elements.taskTree.replaceChildren();
  elements.taskTree.append(taskFocusButton({
    key: SESSION_LANE,
    label: 'Session / global',
    title: 'Session and global trace events with no task root',
    status: '',
    count: counts.get(SESSION_LANE) || 0,
    tone: 'task-tone-session',
    testId: 'task-focus-global',
  }));
  let index = 0;
  for (const task of state.tasks.values()) {
    appendTaskTree(task, counts.get(task.rootId) || 0, index);
    index += 1;
  }
}

function renderEvents(follow = state.followLive) {
  const displayed = displayedEvents();
  const filtered = displayed.filter(matches);
  const fragment = document.createDocumentFragment();
  for (const event of filtered) fragment.append(eventRow(event));
  elements.list.replaceChildren(fragment);
  renderTaskLanes();
  updateCounts(filtered.length);
  elements.reset.disabled = state.taskFocus === null && state.selectedCategories.size === 0 && !filterControls.some((control) => (
    control.type === 'checkbox' ? control.checked : Boolean(control.value)
  ));
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
  ingestTaskEvent(event);
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
  state.header = { ...state.header, ...metadata };
  ingestHeaderTasks(metadata);
  state.waitingForTrace = metadata.stream_mode === 'waiting_for_trace_bundle';
  elements.metaTrace.textContent = text(metadata.trace_id, metadata.source_name);
  elements.metaTrace.title = elements.metaTrace.textContent;
  elements.metaRollout.textContent = text(metadata.rollout_id);
  elements.metaRollout.title = elements.metaRollout.textContent;
  elements.metaRoot.textContent = text(metadata.root_thread_id);
  elements.metaRoot.title = elements.metaRoot.textContent;
  elements.metaStarted.textContent = formatStarted(metadata.started_at_unix_ms);
  elements.metaFormat.textContent = `raw v${text(metadata.raw_schema_version, metadata.schema_version)} / full teaching evidence`;
  elements.metaFormat.title = `Private trace with complete event and payload evidence; ${text(metadata.raw_event_log)}; bundle v${text(metadata.manifest_schema_version, '?')}; ${text(metadata.stream_mode)}`;
  renderEvents(false);
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
  elements.name, elements.phase, elements.correlationKey,
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
  state.selectedCategories.clear();
  state.taskFocus = null;
  elements.category.open = false;
  refreshCategoryOptions();
  elements.harnessOnly.checked = false;
  renderEvents(false);
});
document.addEventListener('click', (event) => {
  if (elements.category.open && !elements.category.contains(event.target)) elements.category.open = false;
});
elements.category.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    elements.category.open = false;
    elements.categorySummary.focus();
  }
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
  elements.follow.setAttribute('aria-pressed', state.followLive ? 'true' : 'false');
  if (state.followLive) elements.list.scrollTop = elements.list.scrollHeight;
});

loadHeader().then(connect).catch((error) => {
  elements.notice.textContent = error.message;
  elements.notice.hidden = false;
  setConnection('error', 'Unavailable');
});

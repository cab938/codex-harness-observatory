(() => {
  const ui = { view: 'events', data: null, request: 'live', item: null, row: null, tab: 'Summary', query: '', folded: false, baseline: 'request', root: '', thread: '', descendants: true, expanded: new Set(), generation: 0, timer: null, itemData: null, knownThreads: new Map() };
  const root = document.querySelector('#teaching-root');
  const thread = document.querySelector('#teaching-thread');
  const descendants = document.querySelector('#teaching-descendants');
  const trajectory = document.querySelector('#trajectory-view');
  const context = document.querySelector('#context-view');
  const colors = { base_instructions: '#665cf4', tool_definitions: '#ee9a22', human_messages: '#18ad66', injected_context: '#a640e7', skill_instructions: '#eb6b22', assistant_messages: '#3687e9', tool_results: '#10aa9e', unknown: '#9ba5ae' };
  const el = (tag, cls, value) => { const n = document.createElement(tag); if (cls) n.className = cls; if (value !== undefined && value !== null) n.textContent = String(value); return n; };
  const num = (v) => v === null || v === undefined ? 'Unknown' : Number(v).toLocaleString();
  const duration = (v) => v === null || v === undefined ? 'Unknown' : v < 1000 ? `${num(v)} ms` : `${(v / 1000).toFixed(2)} s`;
  const value = (v, fallback = 'Unknown') => v === null || v === undefined || v === '' ? fallback : String(v);
  const title = (v) => value(v).replaceAll('_', ' ');
  const pretty = (v) => typeof v === 'string' ? v : JSON.stringify(v, null, 2);
  const textButton = (label, action, cls = 'small-button') => { const b = el('button', cls, label); b.type = 'button'; b.addEventListener('click', action); return b; };
  const add = (parent, ...children) => { parent.append(...children.filter(Boolean)); return parent; };
  const opts = (select, options, selected) => { select.replaceChildren(); for (const [v, label] of options) { const o = el('option', '', label); o.value = v; select.append(o); } select.value = selected; };
  const heading = (label) => { const h = el('div', 'section-heading'); h.append(el('h2', '', label)); return h; };
  const section = (label, cls = '') => { const s = el('section', `teaching-section ${cls}`); s.append(heading(label)); return s; };
  function requestUrl(request = ui.request, item = null) {
    const p = new URLSearchParams();
    if (ui.root) p.set('root', ui.root);
    if (ui.thread) p.set('thread', ui.thread);
    if (ui.descendants) p.set('descendants', '1');
    const bridge = window.ObservatoryBridge.state();
    if (bridge.until !== null) p.set('until', String(bridge.until));
    if (request) p.set('request', request);
    if (item) p.set('item', item);
    return `/api/teaching?${p}`;
  }
  async function get(request = ui.request, item = null, url = requestUrl(request, item)) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`Teaching projection unavailable (${response.status})`);
    const data = await response.json();
    if (data.version !== 1) throw new Error(`Unsupported teaching projection version: ${value(data.version)}`);
    return data;
  }
  function schedule() {
    if (ui.view === 'events' && window.ObservatoryBridge.state().selectedSeq === null) return;
    clearTimeout(ui.timer);
    ui.timer = setTimeout(refresh, 250);
  }
  async function refresh() {
    const generation = ++ui.generation;
    const url = requestUrl();
    try {
      const data = await get(ui.request, null, url);
      if (generation !== ui.generation || url !== requestUrl()) return;
      ui.data = data;
      for (const t of data.threads || []) ui.knownThreads.set(t.id, t);
      updateScopes();
      updateRelated();
      render();
    } catch (error) {
      if (generation !== ui.generation || url !== requestUrl()) return;
      const target = ui.view === 'trajectory' ? trajectory : context;
      target.replaceChildren(el('p', 'teaching-notice teaching-error', error.message));
    }
  }
  function updateScopes() {
    const threads = [...ui.knownThreads.values()];
    const roots = [...new Set(threads.map(t => t.root_thread_id || (!t.parent_thread_id ? t.id : '')).filter(Boolean))];
    if (ui.root && !roots.includes(ui.root)) roots.push(ui.root);
    opts(root, [['', 'All tasks'], ...roots.map(id => [id, `Task ${id}`])], ui.root);
    const visible = threads.filter(t => !ui.root || (t.root_thread_id || t.id) === ui.root);
    const ids = visible.map(t => t.id);
    if (ui.thread && !ids.includes(ui.thread)) visible.push({ id: ui.thread });
    opts(thread, [['', 'All agents'], ...visible.map(t => [t.id, `${t.agent_path || (t.parent_thread_id ? 'Agent' : 'Root')} · ${t.id}`])], ui.thread);
    descendants.checked = ui.descendants;
  }
  function scopeChange() {
    ui.root = root.value; ui.thread = thread.value; ui.descendants = descendants.checked;
    ui.request = 'live'; ui.item = null; ui.row = null; ui.itemData = null;
    window.ObservatoryBridge.setScope(ui.root, ui.thread, ui.descendants);
    if (ui.view === 'context') context.replaceChildren(el('p', 'teaching-notice', 'Loading context…'));
    refresh();
  }
  root.addEventListener('change', () => { thread.value = ''; scopeChange(); });
  thread.addEventListener('change', scopeChange);
  descendants.addEventListener('change', scopeChange);
  for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => {
    ui.view = button.dataset.view;
    for (const tab of document.querySelectorAll('[data-view]')) tab.setAttribute('aria-selected', String(tab === button));
    for (const name of ['events', 'trajectory', 'context']) document.querySelector(`#${name}-view`).hidden = name !== ui.view;
    if (ui.view === 'context') context.replaceChildren(el('p', 'teaching-notice', 'Loading context…'));
    if (ui.view !== 'events') refresh();
  });
  window.addEventListener('observatory-change', () => {
    const bridge = window.ObservatoryBridge.state();
    if (ui.root !== bridge.root || ui.thread !== bridge.thread) { ui.root = bridge.root; ui.thread = bridge.thread; ui.request = 'live'; ui.row = null; ui.item = null; }
    updateRelated();
    schedule();
  });
  function updateRelated() {
    const box = document.querySelector('#related-teaching');
    if (!box) return;
    box.replaceChildren();
    const seq = window.ObservatoryBridge.state().selectedSeq;
    const row = (ui.data?.trajectory || []).find(r => (r.seqs || []).includes(seq));
    const request = (ui.data?.requests || []).find(r => r.seq === seq || r.end_seq === seq) || (row?.request_id && (ui.data?.requests || []).find(r => r.id === row.request_id));
    if (row) box.append(textButton('Related trajectory', () => navigateTrajectory(row)));
    if (request) box.append(textButton('Related context', () => { ui.request = request.id; document.querySelector('[data-view=context]').click(); }));
  }
  function evidence(seqs, refs = []) {
    const box = el('div', 'evidence-links');
    for (const seq of [...new Set((seqs || []).filter(v => v !== null && v !== undefined))]) box.append(textButton(`Event #${seq}`, () => {
      if (!window.ObservatoryBridge.selectEvent(seq)) box.append(el('span', 'muted', 'Event is outside the loaded prefix.'));
    }));
    for (const ref of refs || []) {
      const path = typeof ref === 'string' ? ref : ref.path;
      if (!path) continue;
      box.append(textButton(`Artifact: ${typeof ref === 'object' ? (ref.field || path) : path}`, async () => {
        try { const res = await fetch(`/api/artifact?path=${encodeURIComponent(path)}`); if (!res.ok) throw new Error(`Artifact unavailable (${res.status})`); const body = await res.json(); box.append(el('pre', 'teaching-pre', body.raw_text ?? pretty(body.content ?? body))); }
        catch (error) { box.append(el('span', 'teaching-error', error.message)); }
      }));
    }
    return box;
  }
  function fields(obj) {
    const dl = el('dl', 'detail-fields');
    for (const [key, val] of Object.entries(obj)) { dl.append(el('dt', '', key), el('dd', '', value(val))); }
    return dl;
  }
  function requestSelect() {
    const select = el('select'); select.setAttribute('aria-label', 'Context request');
    const requests = ui.data?.requests || [];
    opts(select, [['live', 'Live history preview'], ...requests.map((r, i) => [r.id, `Request ${i + 1} · ${value(r.model, 'model unknown')} · #${r.seq}`])], ui.request);
    if (!select.value) { const o = el('option', '', 'Selected request unavailable'); o.value = ui.request; select.append(o); select.value = ui.request; }
    select.addEventListener('change', () => selectRequest(select.value));
    return select;
  }
  function selectRequest(request) {
    ui.request = request; ui.item = null; ui.itemData = null;
    context.replaceChildren(el('p', 'teaching-notice', 'Loading context…'));
    refresh();
  }
  function render() { if (ui.view === 'trajectory') renderTrajectory(); else if (ui.view === 'context') renderContext(); }
  function selectRow(row, reveal = false) {
    ui.row = row.id;
    if (row.request_id) ui.request = row.request_id;
    if (reveal) {
      if (row.parent_id) ui.folded = false;
      if (ui.query && !pretty([row.kind, row.title, row.summary, row.status]).toLowerCase().includes(ui.query.toLowerCase())) ui.query = '';
      ui.revealRow = true;
    }
    renderTrajectory();
  }
  function navigateTrajectory(row) {
    ui.row = row.id;
    if (row.request_id) ui.request = row.request_id;
    if (row.parent_id) ui.folded = false;
    if (ui.query && !pretty([row.kind, row.title, row.summary, row.status]).toLowerCase().includes(ui.query.toLowerCase())) ui.query = '';
    ui.revealRow = true;
    document.querySelector('[data-view="trajectory"]').click();
  }
  function lane(kind) { const k = String(kind || '').toLowerCase(); return /tool|command|code/.test(k) ? 'tool' : /model|assistant|request/.test(k) ? 'model' : 'input'; }
  function renderTrajectory() {
    const data = ui.data; const rows = data.trajectory || [];
    const ledgerScroll = trajectory.querySelector('.trajectory-ledger')?.scrollTop || 0;
    const detailScroll = trajectory.querySelector('.teaching-detail')?.scrollTop || 0;
    const toolbar = el('div', 'teaching-toolbar');
    const search = el('input'); search.type = 'search'; search.placeholder = 'Search visible summaries'; search.value = ui.query;
    search.setAttribute('aria-label', 'Search trajectory summaries'); search.addEventListener('input', () => { ui.query = search.value; renderTrajectory(); const n = trajectory.querySelector('input[type=search]'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); });
    const fold = textButton(ui.folded ? 'Expand hierarchy' : 'Fold hierarchy', () => { ui.folded = !ui.folded; renderTrajectory(); });
    add(toolbar, el('h2', '', 'Trajectory'), fold, el('span', 'muted', `${rows.length} records · search covers summaries`), el('span', 'spacer'), search);
    const overview = el('div', 'teaching-overview');
    for (const kind of ['input', 'model', 'tool']) {
      const line = el('div', 'overview-lane'); line.append(el('span', '', kind === 'input' ? 'Input' : kind === 'model' ? 'Model' : 'Tools'));
      for (const row of rows) { const marker = el('button'); marker.type = 'button'; marker.dataset.kind = lane(row.kind) === kind ? kind : 'empty'; marker.title = `${title(row.kind)} · ${value(row.title, row.summary)} · #${row.seq}`; marker.setAttribute('aria-label', marker.title); marker.setAttribute('aria-current', String(row.id === ui.row)); marker.addEventListener('click', () => selectRow(row, true)); line.append(marker); }
      overview.append(line);
    }
    const body = el('div', 'trajectory-body'); const ledger = el('div', 'trajectory-ledger');
    const query = ui.query.toLowerCase();
    const visible = rows.filter(row => (!ui.folded || !row.parent_id) && (!query || pretty([row.kind, row.title, row.summary, row.status]).toLowerCase().includes(query)));
    for (const row of visible) {
      const b = el('button', 'trajectory-row'); b.type = 'button'; b.setAttribute('aria-current', String(row.id === ui.row));
      const parent = rows.find(candidate => candidate.id === row.parent_id);
      const isSubtool = row.kind === 'tool' && ['code_cell', 'tool'].includes(parent?.kind);
      b.append(el('span', `kind-label kind-${isSubtool ? 'subtool' : String(row.kind).replace(/[^a-z_]/g, '')}`, title(isSubtool ? 'subtool' : row.kind)), el('span', 'row-title', `${row.parent_id ? '↳ ' : ''}${value(row.title, value(row.summary, 'Untitled observation'))}${row.title && row.summary ? ` · ${row.summary}` : ''}`), el('span', 'row-meta', `${row.status || ''} ${row.duration_ms == null ? '' : duration(row.duration_ms)}`));
      b.addEventListener('click', () => selectRow(row)); ledger.append(b);
    }
    if (!visible.length) ledger.append(el('p', 'teaching-notice', rows.length ? 'No trajectory summaries match.' : 'No trajectory records are available in this scope.'));
    const detail = el('aside', 'teaching-detail'); const selected = rows.find(r => r.id === ui.row);
    if (!selected) detail.append(el('p', 'teaching-notice', 'Select a trajectory record.'));
    else renderRowDetail(detail, selected);
    add(body, ledger, detail); trajectory.replaceChildren(toolbar, overview, body);
    ledger.scrollTop = ledgerScroll; detail.scrollTop = detailScroll;
    if (ui.revealRow) { ledger.querySelector('.trajectory-row[aria-current="true"]')?.scrollIntoView({ block: 'nearest' }); ui.revealRow = false; }
  }
  function renderRowDetail(target, row) {
    target.append(el('h2', '', `${title(row.kind)} · ${value(row.title, 'Observation')}`));
    const tabs = el('div', 'teaching-tabs');
    for (const name of ['Summary', 'Payload', 'Result', 'Schema', 'Timing']) { const b = textButton(name, () => { ui.tab = name; renderTrajectory(); }, ''); b.setAttribute('aria-selected', String(ui.tab === name)); tabs.append(b); }
    target.append(tabs);
    if (ui.tab === 'Summary') {
      target.append(fields({ Status: row.status, Thread: row.thread_id, Turn: row.turn_id, Step: row.step_id, Request: row.request_id, Parent: row.parent_id }), el('p', '', value(row.summary, 'No summary was recorded.')));
      if (row.request_id) target.append(textButton('Open request in Context', () => { ui.request = row.request_id; document.querySelector('[data-view="context"]').click(); }));
      if (row.parent_id) target.append(textButton('Select parent', () => { const parent = ui.data.trajectory.find(r => r.id === row.parent_id); if (parent) selectRow(parent, true); }));
      target.append(evidence(row.seqs || [row.seq], row.payload_refs));
    } else if (ui.tab === 'Timing') target.append(fields({ Started: row.time_ms == null ? null : new Date(row.time_ms).toLocaleString(), 'Observed duration': duration(row.duration_ms), Usage: row.usage ? pretty(row.usage) : null }), el('p', 'muted', 'Observed intervals may overlap; they are not decode phases.'));
    else {
      const names = ui.tab === 'Payload' ? /invocation|request|payload|source|frame/i : ui.tab === 'Result' ? /result|response|output/i : /schema|tool_definition/i;
      const refs = (row.payload_refs || []).filter(ref => names.test(typeof ref === 'string' ? ref : `${ref.field || ''} ${ref.path || ''}`));
      target.append(el('p', 'muted', refs.length ? 'Recorded artifacts:' : `${ui.tab} is unavailable in this record.`), evidence([], refs));
      if (ui.tab === 'Schema' && row.request_id) target.append(textButton('Inspect request context and tool definitions', () => { ui.request = row.request_id; document.querySelector('[data-view="context"]').click(); }));
    }
  }
  function bar(composition) {
    const b = el('div', 'composition-bar');
    const known = (composition || []).filter(c => Number.isFinite(c.tokens) && c.tokens > 0);
    for (const c of known) { const part = el('span'); part.style.flex = String(c.tokens); part.style.backgroundColor = colors[c.key] || colors.unknown; part.title = `${c.label}: approximately ${num(c.tokens)} tokens`; b.append(part); }
    return b;
  }
  function legend(composition) {
    const result = el('div', 'category-legend');
    for (const c of composition || []) { const x = el('span'); const dot = el('i', 'category-dot'); dot.style.backgroundColor = colors[c.key] || colors.unknown; add(x, dot, document.createTextNode(`${value(c.label, title(c.key))} ≈${num(c.tokens)} (${num(c.count)} items)`)); result.append(x); }
    return result;
  }
  function stat(label, val) { const s = el('div', 'stat'); add(s, el('strong', '', val), el('span', '', label)); return s; }
  function renderContext() {
    const d = ui.data; const snap = d.snapshot; const summary = d.summary || {}; const usage = summary.usage || {}; const page = el('div', 'context-page');
    if (d.scope?.truncated) page.append(el('p', 'teaching-notice teaching-error full', `Recording prefix is incomplete: ${value(d.scope.diagnostic, 'read stopped before the end')}`));
    const stats = section('Context stats', 'full'); const grid = el('div', 'stats-grid');
    for (const [label, val] of [['Turns', summary.turns], ['Steps', summary.steps], ['Model requests', summary.requests], ['Tool calls', summary.tool_calls], ['Threads', summary.threads]]) grid.append(stat(label, num(val)));
    stats.append(grid); page.append(stats);
    const tokens = section('Reported token usage');
    const cache = usage.input_tokens > 0 && usage.cached_input_tokens != null ? `${(100 * usage.cached_input_tokens / usage.input_tokens).toFixed(1)}%` : 'Unknown';
    tokens.append(fields({ 'Input': num(usage.input_tokens), 'Cached input': num(usage.cached_input_tokens), 'Output': num(usage.output_tokens), 'Reasoning within output': num(usage.reasoning_output_tokens), 'Total processed': num(usage.total_tokens), 'Cache share': cache, 'Usage coverage': `${num(usage.reported_requests)} of ${num(usage.total_requests)} requests` }), el('p', 'muted', 'Processed totals count repeated context across requests. Cached input is included in input; reasoning is included in output.'));
    page.append(tokens);
    const timing = section('Observed timing'); const t = d.timing || {};
    const waits = (t.intervals || []).filter(i => i.kind === 'observable_wait' && i.duration_ms != null);
    timing.append(fields({ 'Observed span': duration(t.observed_span_ms), 'Union of active intervals': duration(t.active_union_ms), 'Sum of wait-like intervals (may overlap)': waits.length ? duration(waits.reduce((sum, i) => sum + i.duration_ms, 0)) : 'Unknown', 'Uncovered time': duration(t.uncovered_ms) }), el('p', 'muted', 'Request and tool intervals can overlap. Uncovered time is not attributed to a specific cause.'));
    timing.append(renderTimingStrip(t, d.trajectory || []));
    page.append(timing);
    const current = section('Selected context');
    if (!snap) current.append(el('p', 'muted', 'No context snapshot is available in this scope.'));
    else {
      current.append(fields({ Stage: snap.stage, Source: snap.source, Model: snap.model, 'Estimated visible tokens': `≈${num(snap.estimated_tokens)}`, 'Provider input tokens': num(snap.reported_input_tokens), 'Context window': num(snap.context_window) }), bar(snap.composition), legend(snap.composition), el('p', 'muted', `${snap.coverage?.description || 'Opaque content and media may be unknown.'} ${snap.coverage?.estimate_method || ''}`));
      if (ui.request === 'live') current.append(el('p', 'muted', 'Live is an observed history preview; it does not guarantee the next request payload.'));
      const allItems = [...(snap.items || []), ...(snap.tools || [])];
      const unknownSources = snap.coverage?.unknown_source_items ?? allItems.filter(item => !item.source || item.source === 'unknown').length;
      current.append(fields({ 'Unknown-source items': num(unknownSources), 'Media or opaque parts excluded from estimates': num(snap.coverage?.media_items) }));
      const prefixes = snap.coverage?.prefix || {};
      for (const [key, prefix] of Object.entries(prefixes)) {
        const label = key === 'base_instructions' ? 'Base instructions' : key === 'tool_definitions' ? 'Tool definitions' : title(key);
        const line = el('div', 'activity-row');
        line.append(el('span', '', `${label}: last observed at event #${value(prefix.seq)} · ${title(prefix.source)} · ${title(prefix.stage)}`), evidence([prefix.seq]));
        current.append(line);
      }
      const active = snap.budget?.active_context_tokens; const limit = snap.budget?.full_context_window_limit;
      if (Number.isFinite(active) && Number.isFinite(limit) && limit > 0) current.append(el('p', '', `Core estimate at last budget observation: ${num(active)} / ${num(limit)} tokens (${(100 * active / limit).toFixed(1)}%).`));
      if (snap.budget && Object.keys(snap.budget).length) {
        current.append(el('p', '', 'Recorded budget'), fields(Object.fromEntries(Object.entries(snap.budget).map(([key, v]) => [title(key), v && typeof v === 'object' ? pretty(v) : v]))));
      }
    }
    page.append(current);
    const browser = section('Context browser'); const head = browser.firstChild; head.append(el('span', 'spacer'));
    const prevRequest = textButton('Previous request', () => { ui.baseline = 'request'; renderContext(); }); prevRequest.setAttribute('aria-pressed', String(ui.baseline === 'request'));
    const prevTurn = textButton('Previous turn', () => { ui.baseline = 'turn'; renderContext(); }); prevTurn.setAttribute('aria-pressed', String(ui.baseline === 'turn'));
    add(head, prevRequest, prevTurn, requestSelect());
    if (snap) renderBrowser(browser, snap, requestUrl()); else browser.append(el('p', 'muted', 'No recorded context to browse.'));
    page.append(browser);
    page.append(renderTrend(d));
    page.append(activity('Context events', d.context_events, row => `${title(row.name)} · ${value(row.phase, '')} ${value(row.outcome, '')}`));
    page.append(activity('File activity', d.files, row => `${row.evidence_basis === 'patch_invocation' ? 'Patch attempt' : 'File observation'} · ${value(row.operation, 'operation unknown')} · ${value(row.path)} · Tool ${value(row.status, 'status unknown')}`));
    page.append(activity('Command executions', d.commands, row => `${value(row.command)} · Tool ${value(row.status, 'status unknown')} · ${row.exit_code == null ? 'process exit unknown' : `process exit ${row.exit_code}`} · ${duration(row.duration_ms)}`, 'full'));
    context.replaceChildren(page);
    loadBaseline();
  }
  function renderBrowser(target, snap, snapshotUrl) {
    target.append(el('p', 'muted', `Snapshot #${value(snap.seq)} · ${title(snap.source)} · category sizes are estimated`), bar(snap.composition));
    const compare = el('p', 'muted', 'Loading comparison…'); compare.id = 'context-comparison'; target.append(compare);
    const itemSnapshotUrl = new URL(snapshotUrl, window.location.origin);
    if (!itemSnapshotUrl.searchParams.has('until') && ui.data.last_seq != null) itemSnapshotUrl.searchParams.set('until', String(ui.data.last_seq));
    const groups = snap.composition || []; const all = [...(snap.items || []), ...(snap.tools || []).filter(tool => !(snap.items || []).some(item => item.id === tool.id))];
    for (const group of groups) {
      const details = el('details', 'browser-category'); details.open = ui.expanded.has(`group:${group.key}`);
      const sum = el('summary');
      sum.addEventListener('click', event => {
        event.preventDefault();
        details.open = !details.open;
        if (details.open) ui.expanded.add(`group:${group.key}`);
        else ui.expanded.delete(`group:${group.key}`);
      }); const dot = el('i', 'category-dot'); dot.style.backgroundColor = colors[group.key] || colors.unknown;
      add(sum, dot, document.createTextNode(`${value(group.label, title(group.key))} · ${num(group.count)} items · ≈${num(group.tokens)} tokens`)); details.append(sum);
      const items = all.filter(item => item.category === group.key);
      for (const item of items) {
        const itemNode = el('details', 'browser-item'); itemNode.open = ui.expanded.has(`item:${item.id}`);
        const itemSummary = el('summary', '', `${value(item.role, title(item.category))} · ${value(item.source)} · ≈${num(item.tokens)} · ${value(item.preview, 'No preview')}`);
        const body = el('div', 'browser-item-body context-detail'); itemNode.append(itemSummary, body);
        const itemUrl = new URL(itemSnapshotUrl); itemUrl.searchParams.set('item', item.id);
        itemSummary.addEventListener('click', event => {
          event.preventDefault();
          itemNode.open = !itemNode.open;
          if (itemNode.open) { ui.expanded.add(`item:${item.id}`); loadItem(item, body, itemUrl.href); }
          else ui.expanded.delete(`item:${item.id}`);
        });
        details.append(itemNode); if (itemNode.open) loadItem(item, body, itemUrl.href);
      }
      if (!items.length) details.append(el('p', 'teaching-notice', 'No item details available.'));
      target.append(details);
    }
    if (!groups.length) target.append(el('p', 'muted', 'No composition details were recorded.'));
  }
  async function loadItem(item, target, itemUrl) {
    target.replaceChildren(el('span', 'muted', 'Loading item…'));
    try {
      const data = await get(null, null, itemUrl); const selected = data.selected_item;
      if (!target.isConnected) return;
      target.replaceChildren();
      if (!selected) { target.append(el('p', 'muted', 'Item content is unavailable.')); return; }
      target.append(fields({ Source: selected.source, 'Source kind': selected.source_kind, Stage: selected.stage, Role: selected.role, 'Recorded events': (selected.seqs || []).map(seq => `#${seq}`).join(', ') || null, 'JSON pointer': selected.json_pointer }), el('pre', 'teaching-pre', selected.content == null ? 'Content not recorded.' : pretty(selected.content)), evidence(selected.seqs, selected.payload_ref ? [selected.payload_ref] : []));
      if (selected.media) target.append(el('pre', 'teaching-pre', pretty(selected.media)));
      const findImages = (v) => {
        if (typeof v === 'string' && /^data:image\/(png|jpeg|gif|webp);base64,/i.test(v)) return [v];
        if (Array.isArray(v)) return v.flatMap(findImages);
        if (v && typeof v === 'object') return Object.values(v).flatMap(findImages);
        return [];
      };
      for (const src of findImages(selected.content)) { const image = el('img'); image.src = src; image.alt = 'Recorded image'; target.append(image); }
      const related = (ui.data.trajectory || []).find(row => row.request_id === snapRequest() && (row.seqs || []).some(seq => (selected.seqs || []).includes(seq)));
      if (related) target.append(textButton('Open related trajectory', () => navigateTrajectory(related)));
    } catch (error) { if (target.isConnected) target.replaceChildren(el('span', 'teaching-error', error.message)); }
  }
  function snapRequest() { return ui.data?.snapshot?.request_id; }
  async function loadBaseline() {
    const d = ui.data; const requests = d.requests || []; const selected = requests.find(r => r.id === (d.selected_request || d.snapshot?.request_id)); let index = requests.findIndex(r => r.id === selected?.id);
    if (ui.request === 'live' && index < 0) index = requests.length;
    let prior = null;
    for (let i = index - 1; i >= 0; i--) { if (requests[i].thread_id === (selected?.thread_id || d.snapshot?.thread_id) && (ui.baseline === 'request' || requests[i].turn_id !== selected?.turn_id)) { prior = requests[i]; break; } }
    const node = context.querySelector('#context-comparison'); if (!node) return;
    if (!prior) { node.textContent = `Previous ${ui.baseline} baseline unavailable; change is unknown.`; return; }
    const requestAtStart = ui.request; const baselineAtStart = ui.baseline;
    try {
      const baseline = await get(prior.id); if (!node.isConnected || requestAtStart !== ui.request || baselineAtStart !== ui.baseline) return;
      const current = d.snapshot?.composition || []; const old = baseline.snapshot?.composition || [];
      const changes = current.map(c => { const previous = old.find(o => o.key === c.key); if (c.tokens == null || previous?.tokens == null) return `${c.label}: unknown`; const delta = c.tokens - previous.tokens; return `${c.label}: ${delta >= 0 ? '+' : ''}${num(delta)}`; });
      node.textContent = `Estimated change from previous ${ui.baseline} (#${prior.seq}): ${changes.join(' · ') || 'unavailable'}. Membership changes do not establish a removal cause.`;
    } catch (error) { if (node.isConnected) node.textContent = `Comparison unavailable: ${error.message}`; }
  }
  function renderTimingStrip(timing, rows) {
    const container = el('div', 'timing-strip');
    const intervals = timing.intervals || [];
    const known = intervals.filter(i => Number.isFinite(i.start_ms) && Number.isFinite(i.end_ms) && i.end_ms >= i.start_ms && i.duration_ms != null);
    const incomplete = timing.incomplete_intervals ?? intervals.filter(i => i.kind !== 'uncovered' && !known.includes(i)).length;
    if (!known.length) {
      container.append(el('p', 'muted', `No complete observed intervals are available. ${num(incomplete)} incomplete interval(s) excluded.`));
      return container;
    }
    const start = Math.min(...known.map(i => i.start_ms));
    const end = Math.max(...known.map(i => i.end_ms));
    const span = Math.max(1, end - start);
    const categories = [
      ['Model', ['request']], ['Tools', ['tool', 'code_cell']],
      ['Wait', ['observable_wait']], ['Unknown cause', ['uncovered']],
    ];
    for (const [label, kinds] of categories) {
      const selected = known.filter(i => kinds.includes(i.kind)).sort((a, b) => a.start_ms - b.start_ms || a.end_ms - b.end_ms);
      const layers = [];
      for (const interval of selected) {
        let layer = layers.find(group => group.end <= interval.start_ms);
        if (!layer) { layer = { end: -Infinity, intervals: [] }; layers.push(layer); }
        layer.intervals.push(interval); layer.end = interval.end_ms;
      }
      const track = el('div', 'timing-track'); track.append(el('span', 'timing-label', label));
      const rail = el('div', 'timing-rail'); rail.style.height = `${Math.max(1, layers.length) * 13}px`;
      layers.forEach((layer, index) => layer.intervals.forEach(interval => {
        const row = rows.find(r => r.id === interval.id);
        const item = row ? el('button', `timing-segment timing-${interval.kind}`) : el('span', `timing-segment timing-${interval.kind}`);
        if (row) { item.type = 'button'; item.addEventListener('click', () => navigateTrajectory(row)); }
        item.style.left = `${100 * (interval.start_ms - start) / span}%`;
        item.style.width = `${100 * (interval.end_ms - interval.start_ms) / span}%`;
        item.style.top = `${index * 13}px`;
        item.title = `${label}: ${duration(interval.duration_ms)} · ${new Date(interval.start_ms).toLocaleTimeString()} to ${new Date(interval.end_ms).toLocaleTimeString()}`;
        if (row) item.setAttribute('aria-label', `${item.title} · open trajectory`);
        rail.append(item);
      }));
      track.append(rail); container.append(track);
    }
    container.append(el('p', 'muted', `Observed time from ${new Date(start).toLocaleTimeString()} to ${new Date(end).toLocaleTimeString()}. Concurrent intervals appear on separate lines. ${num(incomplete)} incomplete interval(s) excluded.`));
    const selectable = known.filter(interval => rows.some(row => row.id === interval.id));
    if (selectable.length) {
      const list = el('details', 'timing-intervals');
      list.append(el('summary', '', `Select an observed interval (${selectable.length})`));
      const options = el('div', 'timing-interval-list');
      for (const interval of selectable.sort((a, b) => a.start_ms - b.start_ms)) {
        const row = rows.find(candidate => candidate.id === interval.id);
        const label = interval.kind === 'request' ? 'Model' : interval.kind === 'observable_wait' ? 'Wait' : 'Tool';
        options.append(textButton(`${label} · ${new Date(interval.start_ms).toLocaleTimeString()} · ${duration(interval.duration_ms)} · #${row.seq} · ${value(row.title, 'Observation')}`, () => navigateTrajectory(row)));
      }
      list.append(options); container.append(list);
    }
    return container;
  }
  function renderTrend(d) {
    const s = section('Context trend'); const requests = d.requests || []; const max = Math.max(1, ...requests.map(r => r.estimated_tokens || 0)); const chart = el('div', 'trend');
    for (const [i, r] of requests.entries()) {
      const b = el('button'); b.type = 'button'; b.title = `Request ${i + 1} · #${r.seq} · estimated ${num(r.estimated_tokens)} tokens`; b.setAttribute('aria-label', b.title); b.setAttribute('aria-current', String(ui.request === r.id));
      const comp = r.composition || []; if (r.estimated_tokens == null) { const unknown = el('span'); unknown.style.height = '3px'; unknown.style.backgroundColor = colors.unknown; b.append(unknown); } for (const c of comp) { if (!(c.tokens > 0)) continue; const segment = el('span'); segment.style.height = `${100 * c.tokens / max}%`; segment.style.backgroundColor = colors[c.key] || colors.unknown; b.append(segment); }
      b.addEventListener('click', () => selectRequest(r.id)); chart.append(b);
    }
    s.append(el('p', 'muted', 'Each bar is one observed request. Heights and category sizes are estimates; select a bar to inspect it.'), chart);
    if (!requests.length) s.append(el('p', 'muted', 'No observed requests.'));
    return s;
  }
  function activity(label, rows, describe, cls = '') {
    const s = section(label, cls); const list = el('div', 'activity-list');
    for (const row of [...(rows || [])].reverse()) { const line = el('div', 'activity-row'); line.append(textButton(`#${row.seq}`, () => window.ObservatoryBridge.selectEvent(row.seq)), el('span', '', describe(row))); if (row.exit_code_seq != null && row.exit_code_seq !== row.seq) line.append(evidence([row.exit_code_seq])); if (row.payload_refs?.length) line.append(evidence([], row.payload_refs)); list.append(line); }
    if (!rows?.length) list.append(el('p', 'muted', 'No observations available.')); s.append(list); return s;
  }
  refresh();
})();

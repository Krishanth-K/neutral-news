/**
 * Media Lens — Client-side Application Controller
 * Handles routing, feed interactions, deep analysis rendering, and debug pipeline controls.
 */

// State Management
const state = {
  currentView: 'feed',
  currentEventId: null,
  feed: {
    page: 1,
    pageSize: 15,
    search: '',
    source: 'all',
    multiOnly: false,
    totalPages: 1,
    isLoading: false,
  },
  debug: {
    activeTable: 'articles',
    articleSearch: '',
    articleSource: 'all',
    articleStatus: 'all',
    activeTaskId: null,
    pollInterval: null,
  },
};

// Source colors and CSS class mapping
const SOURCE_CLASS_MAP = {
  'the hindu': 'hindu',
  'indian express': 'express',
  'times of india': 'toi',
};

const ROLE_COLOR_MAP = {
  government: '#4A7BA7',
  opposition: '#C27642',
  expert: '#7B68A8',
  police: '#7A7A72',
  citizen: '#4D804C',
  other: '#9E9E93',
};

// =============================================================================
// Initialization & Hash Router
// =============================================================================

document.addEventListener('DOMContentLoaded', () => {
  initIcons();
  setupEventListeners();
  handleRoute();

  // Listen for hash changes
  window.addEventListener('hashchange', handleRoute);
});

function initIcons() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function handleRoute() {
  const hash = window.location.hash || '#feed';
  
  if (hash.startsWith('#event/')) {
    const eventId = hash.replace('#event/', '').trim();
    if (eventId) {
      showView('event');
      loadEventDetail(eventId);
      return;
    }
  }

  if (hash === '#debug') {
    showView('debug');
    loadDebugStats();
    loadMakeTargets();
    loadDebugTable(state.debug.activeTable);
    return;
  }

  // Default: feed
  showView('feed');
  loadEventsFeed();
}

function showView(viewName) {
  state.currentView = viewName;

  document.querySelectorAll('.app-view').forEach((el) => el.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach((el) => el.classList.remove('active'));

  const targetView = document.getElementById(`view-${viewName}`);
  if (targetView) targetView.classList.add('active');

  const activeTab = document.getElementById(`tab-${viewName === 'event' ? 'feed' : viewName}`);
  if (activeTab) activeTab.classList.add('active');

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// =============================================================================
// Event Listeners Setup
// =============================================================================

function setupEventListeners() {
  // Feed search input with debounce
  const searchInput = document.getElementById('feed-search-input');
  const clearBtn = document.getElementById('feed-search-clear');
  let searchTimeout = null;

  searchInput.addEventListener('input', (e) => {
    const val = e.target.value;
    clearBtn.classList.toggle('hidden', !val);

    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      state.feed.search = val;
      state.feed.page = 1;
      loadEventsFeed();
    }, 300);
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    clearBtn.classList.add('hidden');
    state.feed.search = '';
    state.feed.page = 1;
    loadEventsFeed();
  });

  // Source filter pills
  document.getElementById('source-filters').addEventListener('click', (e) => {
    if (e.target.classList.contains('pill')) {
      document.querySelectorAll('#source-filters .pill').forEach((p) => p.classList.remove('active'));
      e.target.classList.add('active');
      state.feed.source = e.target.dataset.source;
      state.feed.page = 1;
      loadEventsFeed();
    }
  });

  // Multi-source comparison toggle
  document.getElementById('multi-source-toggle').addEventListener('change', (e) => {
    state.feed.multiOnly = e.target.checked;
    state.feed.page = 1;
    loadEventsFeed();
  });

  // Pagination buttons
  document.getElementById('btn-prev-page').addEventListener('click', () => {
    if (state.feed.page > 1) {
      state.feed.page--;
      loadEventsFeed();
    }
  });

  document.getElementById('btn-next-page').addEventListener('click', () => {
    if (state.feed.page < state.feed.totalPages) {
      state.feed.page++;
      loadEventsFeed();
    }
  });

  // Debug Refresh button
  document.getElementById('btn-refresh-debug').addEventListener('click', () => {
    loadDebugStats();
    loadMakeTargets();
    loadDebugTable(state.debug.activeTable);
  });

  // Clear Terminal button
  document.getElementById('btn-clear-terminal').addEventListener('click', () => {
    document.getElementById('terminal-log').textContent = 'Console cleared.';
  });

  // Debug Table Tabs
  document.getElementById('table-switcher-tabs').addEventListener('click', (e) => {
    if (e.target.classList.contains('table-tab')) {
      document.querySelectorAll('.table-tab').forEach((t) => t.classList.remove('active'));
      e.target.classList.add('active');
      const table = e.target.dataset.table;
      state.debug.activeTable = table;
      loadDebugTable(table);
    }
  });

  // Debug Articles Table Filter
  document.getElementById('btn-filter-debug-table').addEventListener('click', () => {
    state.debug.articleSearch = document.getElementById('debug-article-search').value;
    state.debug.articleSource = document.getElementById('debug-source-filter').value;
    state.debug.articleStatus = document.getElementById('debug-status-filter').value;
    loadDebugTable('articles');
  });
}

// =============================================================================
// Feed View Functions
// =============================================================================

async function loadEventsFeed() {
  const container = document.getElementById('events-container');
  container.innerHTML = `
    <div class="loading-state">
      <div class="spinner"></div>
      <p>Loading news events...</p>
    </div>
  `;

  try {
    const params = new URLSearchParams({
      page: state.feed.page,
      page_size: state.feed.pageSize,
      multi_only: state.feed.multiOnly,
    });

    if (state.feed.search) params.append('search', state.feed.search);
    if (state.feed.source && state.feed.source !== 'all') params.append('source', state.feed.source);

    const res = await fetch(`/api/events?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderEventsFeed(data);
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <p>Failed to load events: ${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderEventsFeed(data) {
  const container = document.getElementById('events-container');
  const events = data.events || [];
  const pagination = data.pagination || {};

  state.feed.totalPages = pagination.total_pages || 1;

  if (events.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No events found matching your criteria.</p>
      </div>
    `;
    updatePaginationControls(pagination);
    return;
  }

  const html = events.map((ev) => {
    const sourceBadges = (ev.sources || [])
      .map((s) => {
        const cls = SOURCE_CLASS_MAP[s.toLowerCase()] || 'other';
        return `<span class="source-badge ${cls}">${escapeHtml(s)}</span>`;
      })
      .join('');

    const isMulti = (ev.sources || []).length > 1;
    const timeFormatted = formatDate(ev.latest_pub || ev.created_at);

    return `
      <div class="event-card" onclick="window.location.hash='#event/${ev.id}'">
        <div class="event-card-header">
          <div class="source-badges">${sourceBadges}</div>
          ${isMulti ? `<span class="multi-source-tag"><i data-lucide="split"></i> Multi-source</span>` : ''}
        </div>
        <h2 class="event-card-title">${escapeHtml(ev.title)}</h2>
        <div class="event-card-meta">
          <div class="meta-stats">
            <span class="meta-stat-item"><i data-lucide="layers"></i> ${ev.article_count} article${ev.article_count !== 1 ? 's' : ''}</span>
            <span class="meta-stat-item"><i data-lucide="quote"></i> ${ev.quote_count} quotes</span>
            <span class="meta-stat-item"><i data-lucide="tag"></i> ${ev.entity_count} entities</span>
          </div>
          <span>${timeFormatted}</span>
        </div>
      </div>
    `;
  }).join('');

  container.innerHTML = html;
  updatePaginationControls(pagination);
  initIcons();
}

function updatePaginationControls(pagination) {
  const bar = document.getElementById('feed-pagination');
  if (!pagination.total_items || pagination.total_items <= state.feed.pageSize) {
    bar.classList.add('hidden');
    return;
  }

  bar.classList.remove('hidden');
  document.getElementById('btn-prev-page').disabled = !pagination.has_prev;
  document.getElementById('btn-next-page').disabled = !pagination.has_next;
  document.getElementById('page-indicator').textContent = `Page ${pagination.page} of ${pagination.total_pages} (${pagination.total_items} events)`;
}

// =============================================================================
// Event Deep Dive & Analysis View
// =============================================================================

async function loadEventDetail(eventId) {
  state.currentEventId = eventId;
  const titleEl = document.getElementById('event-detail-title');
  titleEl.textContent = 'Loading event analysis...';

  try {
    const res = await fetch(`/api/events/${eventId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    renderEventDetail(data);
  } catch (err) {
    titleEl.textContent = 'Error loading event';
    alert(`Could not load event: ${err.message}`);
  }
}

function renderEventDetail(data) {
  const event = data.event;
  const articles = data.articles || [];
  const quotes = data.quotes || [];
  const entities = data.entities || [];
  const analysis = data.analysis || {};
  const explanation = data.explanation || null;
  const relatedEvents = data.related_events || [];

  // 1. Header Information
  document.getElementById('event-detail-title').textContent = event.title;
  document.getElementById('event-detail-timestamp').textContent = `Clustered: ${formatDate(event.created_at)} • ID: ${event.id}`;

  const sourcesList = [...new Set(articles.map((a) => a.source_name))];
  const sourceBadgesHtml = sourcesList
    .map((s) => {
      const cls = SOURCE_CLASS_MAP[s.toLowerCase()] || 'other';
      return `<span class="source-badge ${cls}">${escapeHtml(s)}</span>`;
    })
    .join('');
  document.getElementById('event-sources-badge-row').innerHTML = sourceBadgesHtml;

  // 2. Section 01: Sources Grid
  const articlesGrid = document.getElementById('event-articles-grid');
  if (articles.length === 0) {
    articlesGrid.innerHTML = `<p class="empty-state">No articles linked to this event.</p>`;
  } else {
    articlesGrid.innerHTML = articles
      .map((a) => {
        const cls = SOURCE_CLASS_MAP[a.source_name.toLowerCase()] || 'other';
        return `
          <div class="article-source-card">
            <div>
              <div class="article-source-header">
                <span class="source-badge ${cls}">${escapeHtml(a.source_name)}</span>
                <span style="font-size: 12px; color: var(--text-muted);">${formatDate(a.published_at)}</span>
              </div>
              <h3 class="article-source-title">${escapeHtml(a.headline)}</h3>
              <p class="article-source-snippet">${escapeHtml(a.snippet || 'No text available.')}</p>
            </div>
            <div class="article-source-footer">
              <span style="color: var(--text-muted);">Status: ${a.scrape_status}</span>
              <a href="${escapeHtml(a.article_url)}" target="_blank" rel="noopener noreferrer" class="link-original">
                Read original <i data-lucide="external-link"></i>
              </a>
            </div>
          </div>
        `;
      })
      .join('');
  }

  // 3. Section 02: Quote Distribution
  renderQuoteAnalysis(analysis.quote_distribution, quotes);

  // 4. Section 03: Missing Context Matrix
  renderMissingContextMatrix(analysis.missing_context, entities, sourcesList);

  // 5. Section 04: AI Summary
  renderAISummary(explanation, sourcesList);

  // 6. Section 05: Related Events
  const relatedGrid = document.getElementById('related-events-grid');
  if (relatedEvents.length === 0) {
    relatedGrid.innerHTML = `<p style="color: var(--text-muted); font-size: 14px;">No related cluster stories found.</p>`;
  } else {
    relatedGrid.innerHTML = relatedEvents
      .map((re) => {
        return `
          <div class="related-event-card" onclick="window.location.hash='#event/${re.id}'">
            <h4 class="related-event-title">${escapeHtml(re.title)}</h4>
            <div style="font-size: 12px; color: var(--text-muted); display: flex; justify-content: space-between;">
              <span>${re.article_count} article${re.article_count !== 1 ? 's' : ''}</span>
              <span>${formatDate(re.latest_pub)}</span>
            </div>
          </div>
        `;
      })
      .join('');
  }

  initIcons();
}

function renderAISummary(explanation, sourcesList) {
  const container = document.getElementById('ai-summary-container');
  if (!container) return;

  if (explanation) {
    container.innerHTML = `
      <div class="ai-summary-card">
        <div class="ai-summary-header">
          <i data-lucide="sparkles" class="ai-summary-icon"></i>
          <span class="ai-summary-label">Gemini 2.5 Flash · Evidence-only summary</span>
        </div>
        <p class="ai-summary-text">${escapeHtml(explanation)}</p>
        <div class="ai-summary-footer">
          <i data-lucide="shield-check" style="width:14px;height:14px;"></i>
          This summary narrates pre-computed evidence. The model does not independently assess or score coverage.
        </div>
      </div>
    `;
  } else {
    const sourcesNote = sourcesList.length >= 2
      ? `This event has ${sourcesList.length} sources — eligible for explanation.`
      : `Explanations require ≥2 sources. This event has only 1 source.`;
    container.innerHTML = `
      <div class="ai-summary-empty">
        <i data-lucide="message-square" style="width:32px;height:32px;opacity:0.3;margin-bottom:12px;"></i>
        <p>No explanation generated yet.</p>
        <p style="font-size:13px;color:var(--text-muted);margin-top:4px;">${escapeHtml(sourcesNote)}</p>
        <code style="font-size:12px;color:var(--accent-primary);margin-top:8px;display:block;">make explain</code>
      </div>
    `;
  }
}

function renderQuoteAnalysis(quoteDist, allQuotes) {
  const container = document.getElementById('quote-analysis-container');
  if (!quoteDist || !quoteDist.by_source || Object.keys(quoteDist.by_source).length === 0) {
    container.innerHTML = `<p style="color: var(--text-muted);">No quote analysis available for this event. Run <code>make extract-quotes</code> and <code>make analyse</code> to populate.</p>`;
    return;
  }

  // Legend
  const legendHtml = `
    <div class="role-legend">
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-government);"></span> Government</span>
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-opposition);"></span> Opposition</span>
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-expert);"></span> Expert</span>
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-police);"></span> Police</span>
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-citizen);"></span> Citizen</span>
      <span class="legend-item"><span class="legend-dot" style="background: var(--role-other);"></span> Other</span>
    </div>
  `;

  let rowsHtml = '';
  for (const [source, data] of Object.entries(quoteDist.by_source)) {
    const total = data.total_quotes || 0;
    const counts = data.counts || {};
    const proportions = data.proportions || {};

    let segmentsHtml = '';
    if (total > 0) {
      for (const [role, count] of Object.entries(counts)) {
        if (count > 0) {
          const pct = ((count / total) * 100).toFixed(1);
          const color = ROLE_COLOR_MAP[role] || '#9E9E93';
          segmentsHtml += `<div class="stacked-segment" style="width: ${pct}%; background-color: ${color};" title="${role}: ${count} quotes (${pct}%)"></div>`;
        }
      }
    } else {
      segmentsHtml = `<div class="stacked-segment" style="width: 100%; background-color: var(--border-subtle);" title="No quotes extracted"></div>`;
    }

    // Individual quotes for this source
    const sourceQuotes = data.quotes || [];
    const quotesCardsHtml = sourceQuotes.length > 0
      ? `
        <div class="quotes-list-accordion">
          ${sourceQuotes.map((q) => `
            <div class="quote-card">
              <p class="quote-text">"${escapeHtml(q.quote_text)}"</p>
              <div class="quote-attribution">
                <span class="role-pill ${escapeHtml(q.role)}">${escapeHtml(q.role)}</span>
                <strong>${escapeHtml(q.speaker || 'Unidentified')}</strong>
              </div>
            </div>
          `).join('')}
        </div>
      `
      : `<p style="font-size: 13px; color: var(--text-muted); margin-top: 8px;">No extracted direct quotes for this outlet.</p>`;

    rowsHtml += `
      <div class="quote-source-row">
        <div class="quote-source-head">
          <span class="quote-source-name">${escapeHtml(source)}</span>
          <span class="quote-source-meta">Total Quotes: <strong>${total}</strong> ${data.dominant_role ? `• Dominant: <strong>${data.dominant_role}</strong>` : ''}</span>
        </div>
        <div class="stacked-bar-container">
          ${segmentsHtml}
        </div>
        ${quotesCardsHtml}
      </div>
    `;
  }

  container.innerHTML = legendHtml + rowsHtml;
}

function renderMissingContextMatrix(missingContext, entities, sourcesList) {
  const container = document.getElementById('missing-context-container');
  if (!missingContext || !missingContext.missing_by_source || Object.keys(missingContext.missing_by_source).length === 0) {
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">No missing context data available. Run <code>make extract</code> and <code>make analyse</code> to generate entity comparisons.</p>`;
    return;
  }

  const sources = missingContext.sources_analyzed || sourcesList || [];
  if (sources.length === 0) {
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">No sources to compare.</p>`;
    return;
  }

  // Create map of entities: name -> { label, presentIn: Set, missingIn: Set }
  const entityMap = new Map();

  for (const [source, sData] of Object.entries(missingContext.missing_by_source)) {
    (sData.present_entities || []).forEach((ent) => {
      if (!entityMap.has(ent)) {
        entityMap.set(ent, { name: ent, presentIn: new Set(), missingIn: new Set() });
      }
      entityMap.get(ent).presentIn.add(source);
    });

    (sData.missing_entities || []).forEach((ent) => {
      if (!entityMap.has(ent)) {
        entityMap.set(ent, { name: ent, presentIn: new Set(), missingIn: new Set() });
      }
      entityMap.get(ent).missingIn.add(source);
    });
  }

  // Find entity labels from the entities list
  const labelMap = new Map();
  entities.forEach((e) => labelMap.set(e.text, e.label));

  const allEntities = Array.from(entityMap.values());
  if (allEntities.length === 0) {
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">No extracted named entities found for this event.</p>`;
    return;
  }

  // Sort entities: those with omissions first (highest missing count), then alphabetically
  allEntities.sort((a, b) => {
    if (b.missingIn.size !== a.missingIn.size) {
      return b.missingIn.size - a.missingIn.size;
    }
    return a.name.localeCompare(b.name);
  });

  const theadHtml = `
    <thead>
      <tr>
        <th>Entity / Concept</th>
        ${sources.map((s) => `<th class="matrix-cell-status">${escapeHtml(s)}</th>`).join('')}
      </tr>
    </thead>
  `;

  const tbodyHtml = allEntities
    .map((item) => {
      const label = labelMap.get(item.name) || '';
      const cellsHtml = sources
        .map((s) => {
          const isPresent = item.presentIn.has(s);
          return isPresent
            ? `<td class="matrix-cell-status cell-present" title="Mentioned in ${escapeHtml(s)}">✓ Mentioned</td>`
            : `<td class="matrix-cell-status cell-missing" title="Omitted by ${escapeHtml(s)}">✗ Omitted</td>`;
        })
        .join('');

      return `
        <tr>
          <td>
            <strong>${escapeHtml(item.name)}</strong>
            ${label ? `<span class="entity-type-badge">${escapeHtml(label)}</span>` : ''}
          </td>
          ${cellsHtml}
        </tr>
      `;
    })
    .join('');

  container.innerHTML = `
    <div style="padding: 12px 18px; background: var(--bg-surface-subtle); border-bottom: 1px solid var(--border-subtle); font-size: 13px; color: var(--text-secondary);">
      Universal unique entities: <strong>${missingContext.universal_entity_count || allEntities.length}</strong> • Omissions are highlighted in red.
    </div>
    <table class="matrix-table">
      ${theadHtml}
      <tbody>${tbodyHtml}</tbody>
    </table>
  `;
}

// =============================================================================
// Debug & Pipeline Controls View
// =============================================================================

async function loadDebugStats() {
  try {
    const res = await fetch('/api/debug/stats');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const counts = data.counts || {};
    document.getElementById('stat-articles').textContent = (counts.articles || 0).toLocaleString();
    document.getElementById('stat-articles-sub').textContent = `${data.scrape_statuses?.completed || 0} scraped • ${data.scrape_statuses?.failed || 0} failed`;

    document.getElementById('stat-events').textContent = (counts.events || 0).toLocaleString();
    document.getElementById('stat-events-sub').textContent = `${data.multi_source_events_count || 0} cross-source comparisons`;

    document.getElementById('stat-quotes').textContent = (counts.quotes || 0).toLocaleString();
    document.getElementById('stat-quotes-sub').textContent = `From ${data.quote_statuses?.completed || 0} articles`;

    document.getElementById('stat-entities').textContent = (counts.entities || 0).toLocaleString();
    document.getElementById('stat-entities-sub').textContent = `DB Disk: ${data.db_size || 'N/A'}`;
  } catch (err) {
    console.error('Failed to load debug stats:', err);
  }
}

async function loadMakeTargets() {
  const grid = document.getElementById('make-targets-grid');
  try {
    const res = await fetch('/api/debug/targets');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const targets = await res.json();

    grid.innerHTML = targets
      .map((t) => {
        const isRunning = t.latest_status === 'running';
        return `
          <button class="btn-make-target ${isRunning ? 'running' : ''}" data-target="${escapeHtml(t.target)}" onclick="runMakeCommand('${escapeHtml(t.target)}')">
            <div class="target-btn-top">
              <span class="target-btn-name">
                <i data-lucide="${t.icon || 'play'}"></i>
                make ${escapeHtml(t.target)}
              </span>
              <span class="target-status-dot ${t.latest_status || 'idle'}" id="dot-${t.target}"></span>
            </div>
            <div class="target-btn-desc">${escapeHtml(t.description)}</div>
          </button>
        `;
      })
      .join('');

    initIcons();
  } catch (err) {
    grid.innerHTML = `<p>Failed to load make options: ${escapeHtml(err.message)}</p>`;
  }
}

async function runMakeCommand(target) {
  const terminal = document.getElementById('terminal-log');
  const taskLabel = document.getElementById('active-task-label');
  const taskStatus = document.getElementById('active-task-status');

  taskLabel.textContent = `make ${target}`;
  taskStatus.className = 'task-status-tag running';
  taskStatus.textContent = 'RUNNING';
  terminal.textContent = `[INIT] Triggering make ${target}...\n`;

  // Update button visual state
  const dot = document.getElementById(`dot-${target}`);
  if (dot) dot.className = 'target-status-dot running';

  try {
    const res = await fetch(`/api/debug/run/${target}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    state.debug.activeTaskId = data.task_id;
    startTaskLogPolling(data.task_id, target);
  } catch (err) {
    taskStatus.className = 'task-status-tag failed';
    taskStatus.textContent = 'FAILED';
    terminal.textContent += `\n[ERROR] Failed to start task: ${err.message}\n`;
    if (dot) dot.className = 'target-status-dot failed';
  }
}

function startTaskLogPolling(taskId, target) {
  if (state.debug.pollInterval) {
    clearInterval(state.debug.pollInterval);
  }

  const terminal = document.getElementById('terminal-log');
  const taskStatus = document.getElementById('active-task-status');
  const dot = document.getElementById(`dot-${target}`);

  state.debug.pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/debug/tasks/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();

      // Render logs
      const logs = data.logs || [];
      if (logs.length > 0) {
        terminal.textContent = logs.join('\n');
        terminal.scrollTop = terminal.scrollHeight;
      }

      // Check completion
      if (data.status === 'completed' || data.status === 'failed') {
        clearInterval(state.debug.pollInterval);
        state.debug.pollInterval = null;

        taskStatus.className = `task-status-tag ${data.status}`;
        taskStatus.textContent = data.status.toUpperCase();
        if (dot) dot.className = `target-status-dot ${data.status}`;

        // Auto refresh stats after task completes
        loadDebugStats();
        loadDebugTable(state.debug.activeTable);
      }
    } catch (err) {
      console.error('Error polling task logs:', err);
    }
  }, 1000);
}

async function loadDebugTable(tableName) {
  const container = document.getElementById('debug-table-container');
  const filterBar = document.getElementById('articles-filter-bar');

  // Toggle filter bar visibility for articles table
  filterBar.style.display = tableName === 'articles' ? 'flex' : 'none';

  container.innerHTML = `
    <div style="padding: 30px; text-align: center; color: var(--text-muted);">
      <div class="spinner"></div>
      <p>Loading table ${escapeHtml(tableName)}...</p>
    </div>
  `;

  try {
    if (tableName === 'articles') {
      const params = new URLSearchParams({
        limit: 50,
        offset: 0,
      });
      if (state.debug.articleSearch) params.append('search', state.debug.articleSearch);
      if (state.debug.articleSource && state.debug.articleSource !== 'all') params.append('source', state.debug.articleSource);
      if (state.debug.articleStatus && state.debug.articleStatus !== 'all') params.append('status', state.debug.articleStatus);

      const res = await fetch(`/api/debug/articles?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderDebugArticlesTable(data);
    } else {
      const res = await fetch(`/api/debug/tables/${tableName}?limit=30`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      renderRawDebugTable(data);
    }
  } catch (err) {
    container.innerHTML = `<p style="padding: 20px; color: var(--accent-red);">Failed to load table: ${escapeHtml(err.message)}</p>`;
  }
}

function renderDebugArticlesTable(data) {
  const container = document.getElementById('debug-table-container');
  const articles = data.articles || [];

  if (articles.length === 0) {
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">No articles match current filter.</p>`;
    return;
  }

  const thead = `
    <thead>
      <tr>
        <th>Source</th>
        <th>Headline</th>
        <th>Scrape Status</th>
        <th>Embed Status</th>
        <th>Quotes Status</th>
        <th>Entities Status</th>
        <th>Published At</th>
      </tr>
    </thead>
  `;

  const tbody = articles
    .map((a) => {
      return `
        <tr>
          <td><strong>${escapeHtml(a.source_name)}</strong></td>
          <td>
            <a href="${escapeHtml(a.article_url)}" target="_blank" rel="noopener noreferrer" style="text-decoration: underline;" title="${escapeHtml(a.headline)}">
              ${escapeHtml(a.headline.length > 70 ? a.headline.substring(0, 70) + '...' : a.headline)}
            </a>
          </td>
          <td><span class="status-badge ${a.scrape_status}">${a.scrape_status}</span></td>
          <td><span class="status-badge ${a.embedding_status || 'pending'}">${a.embedding_status || 'pending'}</span></td>
          <td><span class="status-badge ${a.quote_status}">${a.quote_status}</span></td>
          <td><span class="status-badge ${a.entity_status}">${a.entity_status}</span></td>
          <td style="font-family: var(--font-mono); font-size: 11px;">${formatDate(a.published_at)}</td>
        </tr>
      `;
    })
    .join('');

  container.innerHTML = `
    <table class="debug-data-table">
      ${thead}
      <tbody>${tbody}</tbody>
    </table>
  `;
}

function renderRawDebugTable(data) {
  const container = document.getElementById('debug-table-container');
  const columns = data.columns || [];
  const rows = data.rows || [];

  if (rows.length === 0) {
    container.innerHTML = `<p style="padding: 20px; color: var(--text-muted);">Table ${escapeHtml(data.table_name)} is currently empty.</p>`;
    return;
  }

  const thead = `
    <thead>
      <tr>
        ${columns.map((c) => `<th>${escapeHtml(c.name)}</th>`).join('')}
      </tr>
    </thead>
  `;

  const tbody = rows
    .map((row) => {
      const tds = columns
        .map((c) => {
          let val = row[c.name];
          if (val === null || val === undefined) val = '<span style="color: var(--text-muted);">NULL</span>';
          else if (typeof val === 'string' && val.length > 60) val = escapeHtml(val.substring(0, 60)) + '...';
          else val = escapeHtml(String(val));
          return `<td>${val}</td>`;
        })
        .join('');
      return `<tr>${tds}</tr>`;
    })
    .join('');

  container.innerHTML = `
    <table class="debug-data-table">
      ${thead}
      <tbody>${tbody}</tbody>
    </table>
  `;
}

// =============================================================================
// Helper Functions
// =============================================================================

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatDate(isoString) {
  if (!isoString) return 'N/A';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoString;
  }
}

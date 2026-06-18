<script lang="ts">
  import { appState } from './lib/stores.svelte.ts';
  import { getProjects, getActions, getDashboard, getProject } from './lib/api.ts';
  import { wsManager } from './lib/websocket.ts';
  import type { WSEvent } from './lib/websocket.ts';

  import Sidebar from './components/Sidebar.svelte';
  import ProjectDetail from './components/ProjectDetail.svelte';
  import LiveFeed from './components/LiveFeed.svelte';
  import NewProject from './components/NewProject.svelte';
  import ActionItem from './components/ActionItem.svelte';

  let autopilot: boolean = $state(true);

  // Initial data load
  async function loadData() {
    appState.loading = true;
    try {
      const [projects, actions] = await Promise.all([
        getProjects().catch(() => []),
        getActions().catch(() => []),
      ]);
      appState.projects = projects;
      appState.actions = actions;

      // Try loading dashboard data too
      getDashboard()
        .then((d) => { appState.dashboardData = d; })
        .catch(() => {});
    } catch (err) {
      appState.error = `Failed to load data: ${err}`;
    } finally {
      appState.loading = false;
    }
  }

  // Load project messages when selected project changes
  $effect(() => {
    const id = appState.selectedProjectId;
    if (id) {
      getProject(id)
        .then((p) => {
          appState.updateProject(p);
          if (p.messages) {
            appState.messages = p.messages;
          }
        })
        .catch(() => {});
    }
  });

  // WebSocket event handling
  function handleWSEvent(event: WSEvent) {
    switch (event.type) {
      case 'connected':
        appState.wsConnected = true;
        break;
      case 'message':
        if (event.data) {
          appState.addMessage(event.data);
        }
        break;
      case 'project_created':
      case 'project_updated':
        if (event.data) {
          appState.updateProject(event.data);
        }
        break;
      case 'milestone_completed':
      case 'milestone_started':
        // Refresh the project
        if (event.data?.project_id) {
          getProject(event.data.project_id)
            .then((p) => {
              appState.updateProject(p);
              if (p.messages && p.id === appState.selectedProjectId) {
                appState.messages = p.messages;
              }
            })
            .catch(() => {});
        }
        break;
      case 'action_created':
        if (event.data) {
          const existing = appState.actions.find((a) => a.id === event.data.id);
          if (!existing) {
            appState.actions = [...appState.actions, event.data];
          }
        }
        break;
      case 'action_resolved':
        if (event.data?.id) {
          appState.resolveActionById(event.data.id);
        }
        break;
      case 'error':
        appState.error = event.data?.message ?? 'WebSocket error';
        break;
    }
  }

  // Connect WebSocket and load initial data
  const unsubscribe = wsManager.subscribe(handleWSEvent);
  wsManager.connect();
  loadData();

  function dismissError() {
    appState.error = null;
  }

  function formatCurrency(n: number): string {
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
</script>

<div class="app-layout">
  <Sidebar />

  <div class="main-area">
    <!-- Top Bar -->
    <header class="top-bar">
      <div class="top-left">
        <h1 class="top-title">MeshCorp HQ</h1>
      </div>
      <div class="top-right">
        <button
          class="autopilot-toggle"
          class:on={autopilot}
          onclick={() => autopilot = !autopilot}
        >
          <span class="toggle-dot"></span>
          <span class="toggle-label">Autopilot {autopilot ? 'ON' : 'OFF'}</span>
        </button>

        <span class="top-stat">
          <span class="stat-label">Budget</span>
          <span class="stat-value">{formatCurrency(appState.totalBudget)}</span>
        </span>

        {#if appState.pendingActions.length > 0}
          <button class="alert-badge" onclick={() => appState.currentView = 'inbox'}>
            <span class="alert-icon">!</span>
            <span class="alert-count">{appState.pendingActions.length}</span>
          </button>
        {/if}

        <span class="ws-indicator" class:connected={appState.wsConnected} title={appState.wsConnected ? 'Connected' : 'Disconnected'}>
          &#9679;
        </span>
      </div>
    </header>

    <!-- Error Toast -->
    {#if appState.error}
      <div class="error-toast">
        <span class="error-text">{appState.error}</span>
        <button class="error-dismiss" onclick={dismissError}>&#10005;</button>
      </div>
    {/if}

    <!-- Content Area -->
    <div class="content-layout">
      <div class="content-main">
        {#if appState.currentView === 'new'}
          <NewProject />
        {:else if appState.currentView === 'inbox'}
          <div class="inbox-view">
            <h2 class="view-title">Action Items</h2>
            {#if appState.pendingActions.length === 0}
              <div class="empty-view">
                <span class="empty-icon">&#9745;</span>
                <p>No pending actions. All clear.</p>
              </div>
            {:else}
              <div class="action-list">
                {#each appState.pendingActions as action (action.id)}
                  <ActionItem {action} />
                {/each}
              </div>
            {/if}
          </div>
        {:else if appState.currentView === 'project' && appState.selectedProject}
          <ProjectDetail />
        {:else}
          <!-- Dashboard view -->
          <div class="dashboard-view">
            <h2 class="view-title">Dashboard</h2>
            <div class="dash-stats">
              <div class="dash-stat-card">
                <span class="dsc-value">{appState.activeProjects.length}</span>
                <span class="dsc-label">Active Projects</span>
              </div>
              <div class="dash-stat-card">
                <span class="dsc-value">{appState.projects.length}</span>
                <span class="dsc-label">Total Projects</span>
              </div>
              <div class="dash-stat-card">
                <span class="dsc-value">{formatCurrency(appState.totalBudget)}</span>
                <span class="dsc-label">Total Budget</span>
              </div>
              <div class="dash-stat-card">
                <span class="dsc-value">{formatCurrency(appState.totalSpent)}</span>
                <span class="dsc-label">Total Spent</span>
              </div>
              <div class="dash-stat-card">
                <span class="dsc-value">{appState.pendingActions.length}</span>
                <span class="dsc-label">Pending Actions</span>
              </div>
            </div>

            {#if appState.projects.length === 0 && !appState.loading}
              <div class="empty-view">
                <span class="empty-icon">&#9670;</span>
                <p>No projects yet. Create one to get started.</p>
                <button class="btn-cta" onclick={() => appState.currentView = 'new'}>
                  + New Project
                </button>
              </div>
            {/if}

            {#if appState.loading}
              <div class="loading-indicator">Loading...</div>
            {/if}
          </div>
        {/if}
      </div>

      <!-- Live Feed (bottom panel) -->
      <div class="content-feed">
        <LiveFeed />
      </div>
    </div>
  </div>
</div>

<style>
  .app-layout {
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  .main-area {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    overflow: hidden;
  }

  /* Top Bar */
  .top-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    height: 52px;
    min-height: 52px;
    border-bottom: 1px solid var(--border);
    background: var(--card-bg);
  }

  .top-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .top-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 700;
    color: var(--text-h);
    letter-spacing: -0.02em;
  }

  .top-right {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .autopilot-toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
    font-family: var(--sans);
    font-size: 0.76rem;
    color: var(--text);
    transition: all 0.15s;
  }

  .autopilot-toggle.on {
    background: rgba(34, 197, 94, 0.1);
    border-color: rgba(34, 197, 94, 0.3);
    color: #22c55e;
  }

  .toggle-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: currentColor;
  }

  .top-stat {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }

  .stat-label {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text);
    opacity: 0.5;
  }

  .stat-value {
    font-size: 0.82rem;
    font-family: var(--mono);
    color: var(--text-h);
    font-weight: 600;
  }

  .alert-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 10px;
    background: rgba(239, 68, 68, 0.12);
    border: 1px solid rgba(239, 68, 68, 0.25);
    border-radius: 6px;
    cursor: pointer;
    font-family: var(--mono);
    font-size: 0.76rem;
    color: #ef4444;
    font-weight: 600;
  }

  .alert-badge:hover {
    background: rgba(239, 68, 68, 0.2);
  }

  .alert-icon {
    font-weight: 800;
  }

  .ws-indicator {
    font-size: 0.6rem;
    color: #ef4444;
    transition: color 0.3s;
  }

  .ws-indicator.connected {
    color: #22c55e;
  }

  /* Error Toast */
  .error-toast {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: rgba(239, 68, 68, 0.1);
    border-bottom: 1px solid rgba(239, 68, 68, 0.2);
    color: #ef4444;
    font-size: 0.82rem;
    flex-shrink: 0;
  }

  .error-text {
    flex: 1;
  }

  .error-dismiss {
    background: none;
    border: none;
    color: #ef4444;
    cursor: pointer;
    padding: 2px 6px;
    font-size: 0.9rem;
    opacity: 0.7;
  }

  .error-dismiss:hover {
    opacity: 1;
  }

  /* Content Layout */
  .content-layout {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .content-main {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }

  .content-feed {
    height: 280px;
    min-height: 200px;
    flex-shrink: 0;
    border-top: 1px solid var(--border);
  }

  /* Dashboard View */
  .dashboard-view {
    padding: 24px;
  }

  .view-title {
    margin: 0 0 20px;
    font-size: 1.2rem;
    font-weight: 700;
  }

  .dash-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 10px;
    margin-bottom: 24px;
  }

  .dash-stat-card {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 16px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .dsc-value {
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--text-h);
    font-family: var(--mono);
  }

  .dsc-label {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text);
    opacity: 0.5;
  }

  .empty-view {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 48px 0;
    color: var(--text);
    opacity: 0.5;
  }

  .empty-icon {
    font-size: 2.5rem;
    color: var(--accent);
    opacity: 0.3;
  }

  .empty-view p {
    margin: 0;
    font-size: 0.9rem;
  }

  .btn-cta {
    padding: 8px 20px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 500;
    font-family: var(--sans);
    transition: opacity 0.15s;
  }

  .btn-cta:hover {
    opacity: 0.9;
  }

  .loading-indicator {
    text-align: center;
    color: var(--text);
    opacity: 0.4;
    padding: 24px;
    font-size: 0.88rem;
  }

  /* Inbox View */
  .inbox-view {
    padding: 24px;
  }

  .action-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
</style>

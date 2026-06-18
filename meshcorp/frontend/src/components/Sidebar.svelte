<script lang="ts">
  import { appState } from '../lib/stores.svelte.ts';

  function selectProject(id: string) {
    appState.selectProject(id);
  }

  function showNewProject() {
    appState.currentView = 'new';
    appState.clearSelection();
  }

  function showInbox() {
    appState.currentView = 'inbox';
    appState.clearSelection();
  }

  function showDashboard() {
    appState.currentView = 'dashboard';
    appState.clearSelection();
  }

  function statusIcon(status: string): string {
    switch (status) {
      case 'active': return '●';
      case 'planning': return '◐';
      case 'proposal': return '○';
      case 'completed': return '✓';
      case 'killed': return '✕';
      default: return '·';
    }
  }

  function milestoneProgress(project: any): string {
    if (!project.milestones || project.milestones.length === 0) return '';
    const done = project.milestones.filter((m: any) => m.status === 'completed').length;
    return `${done}/${project.milestones.length}`;
  }
</script>

<aside class="sidebar">
  <div class="sidebar-header">
    <button class="logo-btn" onclick={showDashboard}>
      <span class="logo-icon">&#9670;</span>
      <span class="logo-text">MeshCorp</span>
    </button>
  </div>

  <div class="sidebar-actions">
    <button class="btn-new" onclick={showNewProject}>
      <span class="plus">+</span> New Project
    </button>
  </div>

  <nav class="sidebar-nav">
    <button
      class="nav-item"
      class:active={appState.currentView === 'dashboard'}
      onclick={showDashboard}
    >
      <span class="nav-icon">&#9632;</span>
      Dashboard
    </button>
    <button
      class="nav-item"
      class:active={appState.currentView === 'inbox'}
      onclick={showInbox}
    >
      <span class="nav-icon">&#9993;</span>
      Inbox
      {#if appState.pendingActions.length > 0}
        <span class="badge">{appState.pendingActions.length}</span>
      {/if}
    </button>
  </nav>

  <div class="project-groups">
    {#if appState.activeProjects.length > 0}
      <div class="group">
        <div class="group-label">Active</div>
        {#each appState.activeProjects as project (project.id)}
          <button
            class="project-item"
            class:selected={appState.selectedProjectId === project.id}
            onclick={() => selectProject(project.id)}
          >
            <span class="status-dot active">{statusIcon('active')}</span>
            <span class="project-name">{project.template_name ?? project.template_id}</span>
            <span class="milestone-count">{milestoneProgress(project)}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if appState.planningProjects.length > 0}
      <div class="group">
        <div class="group-label">Planning</div>
        {#each appState.planningProjects as project (project.id)}
          <button
            class="project-item"
            class:selected={appState.selectedProjectId === project.id}
            onclick={() => selectProject(project.id)}
          >
            <span class="status-dot planning">{statusIcon('planning')}</span>
            <span class="project-name">{project.template_name ?? project.template_id}</span>
            <span class="milestone-count">{milestoneProgress(project)}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if appState.proposalProjects.length > 0}
      <div class="group">
        <div class="group-label">Proposals</div>
        {#each appState.proposalProjects as project (project.id)}
          <button
            class="project-item"
            class:selected={appState.selectedProjectId === project.id}
            onclick={() => selectProject(project.id)}
          >
            <span class="status-dot proposal">{statusIcon('proposal')}</span>
            <span class="project-name">{project.template_name ?? project.template_id}</span>
          </button>
        {/each}
      </div>
    {/if}

    {#if appState.completedProjects.length > 0}
      <div class="group">
        <div class="group-label">Completed</div>
        {#each appState.completedProjects as project (project.id)}
          <button
            class="project-item"
            class:selected={appState.selectedProjectId === project.id}
            onclick={() => selectProject(project.id)}
          >
            <span class="status-dot completed">{statusIcon(project.status)}</span>
            <span class="project-name">{project.template_name ?? project.template_id}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>
</aside>

<style>
  .sidebar {
    width: 260px;
    min-width: 260px;
    height: 100vh;
    background: var(--card-bg);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .sidebar-header {
    padding: 16px 16px 8px;
    border-bottom: 1px solid var(--border);
  }

  .logo-btn {
    background: none;
    border: none;
    color: var(--text-h);
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    font-size: 1rem;
    font-weight: 600;
    font-family: var(--sans);
  }

  .logo-icon {
    color: var(--accent);
    font-size: 1.2rem;
  }

  .sidebar-actions {
    padding: 12px 16px;
  }

  .btn-new {
    width: 100%;
    padding: 8px 12px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.85rem;
    font-weight: 500;
    font-family: var(--sans);
    display: flex;
    align-items: center;
    gap: 6px;
    justify-content: center;
    transition: opacity 0.15s;
  }

  .btn-new:hover {
    opacity: 0.9;
  }

  .plus {
    font-size: 1.1rem;
    line-height: 1;
  }

  .sidebar-nav {
    padding: 4px 8px;
    border-bottom: 1px solid var(--border);
  }

  .nav-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px;
    background: none;
    border: none;
    border-radius: 6px;
    color: var(--text);
    cursor: pointer;
    font-size: 0.85rem;
    font-family: var(--sans);
    text-align: left;
    transition: background 0.12s;
  }

  .nav-item:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .nav-item.active {
    background: rgba(59, 130, 246, 0.12);
    color: var(--accent);
  }

  .nav-icon {
    font-size: 0.9rem;
    width: 18px;
    text-align: center;
  }

  .badge {
    margin-left: auto;
    background: #ef4444;
    color: #fff;
    font-size: 0.7rem;
    padding: 1px 6px;
    border-radius: 8px;
    font-weight: 600;
    font-family: var(--mono);
  }

  .project-groups {
    flex: 1;
    overflow-y: auto;
    padding: 8px;
  }

  .group {
    margin-bottom: 12px;
  }

  .group-label {
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text);
    padding: 4px 8px;
    opacity: 0.6;
  }

  .project-item {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    background: none;
    border: none;
    border-radius: 6px;
    color: var(--text-h);
    cursor: pointer;
    font-size: 0.82rem;
    font-family: var(--sans);
    text-align: left;
    transition: background 0.12s;
  }

  .project-item:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .project-item.selected {
    background: rgba(59, 130, 246, 0.12);
  }

  .status-dot {
    font-size: 0.7rem;
    width: 14px;
    text-align: center;
    flex-shrink: 0;
  }

  .status-dot.active { color: #22c55e; }
  .status-dot.planning { color: #f59e0b; }
  .status-dot.proposal { color: var(--text); }
  .status-dot.completed { color: var(--text); opacity: 0.5; }

  .project-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .milestone-count {
    font-size: 0.7rem;
    color: var(--text);
    font-family: var(--mono);
    opacity: 0.7;
  }
</style>

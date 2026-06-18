<script lang="ts">
  import { appState } from '../lib/stores.svelte.ts';
  import { advanceProject, fundProject, killProject, getProject } from '../lib/api.ts';

  let advancing: boolean = $state(false);
  let funding: boolean = $state(false);
  let killing: boolean = $state(false);
  let showFundInput: boolean = $state(false);
  let fundAmount: string = $state('10000');

  let project = $derived(appState.selectedProject);

  function statusBadgeClass(status: string): string {
    switch (status) {
      case 'active': return 'badge-active';
      case 'planning': return 'badge-planning';
      case 'proposal': return 'badge-proposal';
      case 'completed': return 'badge-completed';
      case 'killed': return 'badge-killed';
      default: return '';
    }
  }

  function milestoneIcon(status: string): string {
    switch (status) {
      case 'completed': return '✓';
      case 'active': return '◉';
      case 'failed': return '✕';
      default: return '○';
    }
  }

  function milestoneClass(status: string): string {
    switch (status) {
      case 'completed': return 'ms-completed';
      case 'active': return 'ms-active';
      case 'failed': return 'ms-failed';
      default: return 'ms-pending';
    }
  }

  async function handleAdvance() {
    if (!project || advancing) return;
    advancing = true;
    try {
      const updated = await advanceProject(project.id);
      appState.updateProject(updated);
      // Refresh full project data (messages, etc.)
      const full = await getProject(project.id);
      appState.updateProject(full);
      if (full.messages) {
        for (const msg of full.messages) {
          appState.addMessage(msg);
        }
      }
    } catch (err) {
      appState.error = `Advance failed: ${err}`;
    } finally {
      advancing = false;
    }
  }

  async function handleFund() {
    if (!project || funding) return;
    const amount = parseFloat(fundAmount);
    if (isNaN(amount) || amount <= 0) return;
    funding = true;
    try {
      const updated = await fundProject(project.id, amount);
      appState.updateProject(updated);
      showFundInput = false;
    } catch (err) {
      appState.error = `Funding failed: ${err}`;
    } finally {
      funding = false;
    }
  }

  async function handleKill() {
    if (!project || killing) return;
    if (!confirm('Kill this project? This cannot be undone.')) return;
    killing = true;
    try {
      const updated = await killProject(project.id);
      appState.updateProject(updated);
    } catch (err) {
      appState.error = `Kill failed: ${err}`;
    } finally {
      killing = false;
    }
  }

  function formatCurrency(n: number): string {
    return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
</script>

{#if project}
  <div class="project-detail">
    <div class="detail-header">
      <div class="header-top">
        <h2 class="project-title">{project.template_name ?? project.template_id}</h2>
        <span class="status-badge {statusBadgeClass(project.status)}">{project.status}</span>
      </div>

      {#if project.description}
        <p class="project-desc">{project.description}</p>
      {/if}

      <div class="meta-row">
        <span class="meta-item">
          <span class="meta-label">Model</span>
          <span class="meta-value mono">{project.model}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">Budget</span>
          <span class="meta-value mono">{formatCurrency(project.budget)}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">Spent</span>
          <span class="meta-value mono">{formatCurrency(project.spent)}</span>
        </span>
        <span class="meta-item">
          <span class="meta-label">Milestone</span>
          <span class="meta-value mono">{project.current_milestone + 1}/{project.milestones?.length ?? '?'}</span>
        </span>
      </div>
    </div>

    <div class="milestones-section">
      <h3 class="section-title">Milestones</h3>
      <div class="milestone-list">
        {#if project.milestones && project.milestones.length > 0}
          {#each project.milestones as ms, i}
            <div class="milestone-item {milestoneClass(ms.status)}">
              <div class="ms-indicator">
                <span class="ms-icon">{milestoneIcon(ms.status)}</span>
                {#if i < project.milestones.length - 1}
                  <div class="ms-line"></div>
                {/if}
              </div>
              <div class="ms-content">
                <div class="ms-header">
                  <span class="ms-name">{ms.name}</span>
                  <span class="ms-status-label">{ms.status}</span>
                </div>
                <p class="ms-desc">{ms.description}</p>
                {#if ms.participants && ms.participants.length > 0}
                  <div class="ms-participants">
                    {#each ms.participants as p}
                      <span class="participant-tag">{p}</span>
                    {/each}
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        {:else}
          <p class="no-milestones">No milestones defined yet.</p>
        {/if}
      </div>
    </div>

    <div class="actions-bar">
      {#if project.status !== 'completed' && project.status !== 'killed'}
        <button class="btn btn-primary" onclick={handleAdvance} disabled={advancing}>
          {advancing ? 'Advancing...' : 'Advance'}
        </button>

        {#if showFundInput}
          <div class="fund-inline">
            <span class="fund-dollar">$</span>
            <input
              type="number"
              class="fund-input"
              bind:value={fundAmount}
              min="1"
              step="1000"
            />
            <button class="btn btn-success btn-sm" onclick={handleFund} disabled={funding}>
              {funding ? '...' : 'Add'}
            </button>
            <button class="btn btn-ghost btn-sm" onclick={() => showFundInput = false}>
              Cancel
            </button>
          </div>
        {:else}
          <button class="btn btn-secondary" onclick={() => showFundInput = true}>
            Fund
          </button>
        {/if}

        <button class="btn btn-danger" onclick={handleKill} disabled={killing}>
          {killing ? 'Killing...' : 'Kill'}
        </button>
      {/if}
    </div>
  </div>
{:else}
  <div class="no-project">
    <span class="no-project-icon">&#9670;</span>
    <p>Select a project from the sidebar</p>
  </div>
{/if}

<style>
  .project-detail {
    padding: 20px 24px;
    overflow-y: auto;
  }

  .detail-header {
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }

  .header-top {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .project-title {
    margin: 0;
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--text-h);
  }

  .status-badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 2px 10px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-family: var(--mono);
  }

  .badge-active { background: rgba(34, 197, 94, 0.15); color: #22c55e; }
  .badge-planning { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
  .badge-proposal { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
  .badge-completed { background: rgba(34, 197, 94, 0.1); color: #22c55e; opacity: 0.7; }
  .badge-killed { background: rgba(239, 68, 68, 0.15); color: #ef4444; }

  .project-desc {
    margin: 0 0 12px;
    color: var(--text);
    font-size: 0.88rem;
    line-height: 1.5;
  }

  .meta-row {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
  }

  .meta-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .meta-label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text);
    opacity: 0.5;
  }

  .meta-value {
    font-size: 0.88rem;
    color: var(--text-h);
  }

  .mono {
    font-family: var(--mono);
  }

  .milestones-section {
    margin-bottom: 20px;
  }

  .section-title {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text);
    margin: 0 0 12px;
  }

  .milestone-list {
    display: flex;
    flex-direction: column;
  }

  .milestone-item {
    display: flex;
    gap: 12px;
    position: relative;
  }

  .ms-indicator {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 20px;
    flex-shrink: 0;
  }

  .ms-icon {
    font-size: 0.85rem;
    line-height: 1;
    z-index: 1;
  }

  .ms-line {
    width: 1px;
    flex: 1;
    background: var(--border);
    margin: 4px 0;
  }

  .ms-completed .ms-icon { color: #22c55e; }
  .ms-active .ms-icon { color: var(--accent); }
  .ms-failed .ms-icon { color: #ef4444; }
  .ms-pending .ms-icon { color: var(--text); opacity: 0.3; }

  .ms-content {
    flex: 1;
    padding-bottom: 16px;
  }

  .ms-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }

  .ms-name {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-h);
  }

  .ms-status-label {
    font-size: 0.62rem;
    font-family: var(--mono);
    color: var(--text);
    opacity: 0.5;
    text-transform: uppercase;
  }

  .ms-desc {
    margin: 0;
    font-size: 0.82rem;
    color: var(--text);
    line-height: 1.4;
  }

  .ms-participants {
    display: flex;
    gap: 4px;
    margin-top: 6px;
    flex-wrap: wrap;
  }

  .participant-tag {
    font-size: 0.65rem;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text);
    font-family: var(--mono);
  }

  .no-milestones {
    color: var(--text);
    opacity: 0.4;
    font-size: 0.85rem;
  }

  .actions-bar {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    padding-top: 12px;
    border-top: 1px solid var(--border);
  }

  .btn {
    padding: 7px 16px;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.82rem;
    font-weight: 500;
    font-family: var(--sans);
    transition: opacity 0.15s;
  }

  .btn:hover:not(:disabled) { opacity: 0.9; }
  .btn:disabled { opacity: 0.4; cursor: not-allowed; }

  .btn-sm { padding: 5px 12px; font-size: 0.78rem; }

  .btn-primary { background: var(--accent); color: #fff; }
  .btn-secondary { background: rgba(255, 255, 255, 0.08); color: var(--text-h); }
  .btn-success { background: #22c55e; color: #fff; }
  .btn-danger { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
  .btn-ghost { background: none; color: var(--text); }

  .fund-inline {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .fund-dollar {
    color: var(--text);
    font-size: 0.85rem;
    font-family: var(--mono);
  }

  .fund-input {
    width: 100px;
    padding: 5px 8px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text-h);
    font-size: 0.82rem;
    font-family: var(--mono);
    outline: none;
  }

  .fund-input:focus {
    border-color: var(--accent);
  }

  .no-project {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text);
    opacity: 0.3;
    gap: 12px;
  }

  .no-project-icon {
    font-size: 3rem;
    color: var(--accent);
    opacity: 0.3;
  }
</style>

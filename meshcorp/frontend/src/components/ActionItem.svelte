<script lang="ts">
  import type { Action } from '../lib/api.ts';
  import { resolveAction } from '../lib/api.ts';
  import { appState } from '../lib/stores.svelte.ts';

  let { action }: { action: Action } = $props();

  let resolving: boolean = $state(false);

  function urgencyClass(urgency: string): string {
    switch (urgency) {
      case 'critical': return 'urgency-critical';
      case 'high': return 'urgency-high';
      case 'medium': return 'urgency-medium';
      default: return 'urgency-low';
    }
  }

  function formatDate(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
             d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }

  async function handleResolve() {
    if (resolving) return;
    resolving = true;
    try {
      await resolveAction(action.id);
      appState.resolveActionById(action.id);
    } catch (err) {
      appState.error = `Failed to resolve action: ${err}`;
    } finally {
      resolving = false;
    }
  }
</script>

<div class="action-card" class:resolved={action.resolved}>
  <div class="action-header">
    <span class="action-title">{action.title}</span>
    <span class="urgency-badge {urgencyClass(action.urgency)}">{action.urgency}</span>
  </div>

  {#if action.description}
    <p class="action-desc">{action.description}</p>
  {/if}

  <div class="action-footer">
    <div class="action-meta">
      {#if action.blocking}
        <span class="blocking-tag">BLOCKING</span>
      {/if}
      <span class="action-time">{formatDate(action.created_at)}</span>
    </div>

    {#if !action.resolved}
      <button class="btn-resolve" onclick={handleResolve} disabled={resolving}>
        {resolving ? 'Resolving...' : 'Mark Complete'}
      </button>
    {:else}
      <span class="resolved-label">Resolved</span>
    {/if}
  </div>
</div>

<style>
  .action-card {
    padding: 14px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border);
    border-radius: 6px;
    transition: border-color 0.15s;
  }

  .action-card:hover {
    border-color: rgba(255, 255, 255, 0.1);
  }

  .action-card.resolved {
    opacity: 0.5;
  }

  .action-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }

  .action-title {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-h);
    flex: 1;
  }

  .urgency-badge {
    font-size: 0.62rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-family: var(--mono);
    flex-shrink: 0;
  }

  .urgency-critical { background: rgba(239, 68, 68, 0.2); color: #ef4444; }
  .urgency-high { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
  .urgency-medium { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
  .urgency-low { background: rgba(255, 255, 255, 0.06); color: var(--text); }

  .action-desc {
    margin: 0 0 10px;
    font-size: 0.82rem;
    color: var(--text);
    line-height: 1.4;
  }

  .action-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .action-meta {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .blocking-tag {
    font-size: 0.6rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 3px;
    background: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    font-family: var(--mono);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .action-time {
    font-size: 0.68rem;
    color: var(--text);
    opacity: 0.4;
    font-family: var(--mono);
  }

  .btn-resolve {
    padding: 5px 14px;
    background: rgba(34, 197, 94, 0.12);
    color: #22c55e;
    border: 1px solid rgba(34, 197, 94, 0.2);
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.78rem;
    font-weight: 500;
    font-family: var(--sans);
    transition: background 0.15s;
  }

  .btn-resolve:hover:not(:disabled) {
    background: rgba(34, 197, 94, 0.2);
  }

  .btn-resolve:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .resolved-label {
    font-size: 0.72rem;
    color: #22c55e;
    opacity: 0.6;
    font-family: var(--mono);
  }
</style>

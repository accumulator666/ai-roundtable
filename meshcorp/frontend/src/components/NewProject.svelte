<script lang="ts">
  import { appState } from '../lib/stores.svelte.ts';
  import { createProject, getTemplates } from '../lib/api.ts';

  let description: string = $state('');
  let selectedTemplateId: string | null = $state(null);
  let creating: boolean = $state(false);
  let loadingTemplates: boolean = $state(false);

  const TEMPLATE_ICONS: Record<string, string> = {
    'saas': '&#9729;',      // cloud
    'ecommerce': '&#9733;', // star
    'mobile': '&#9742;',    // phone
    'api': '&#9881;',       // gear
    'content': '&#9998;',   // pencil
    'research': '&#9782;',  // beaker-like
    'consulting': '&#9670;', // diamond
  };

  function getIcon(template: any): string {
    if (template.icon) return template.icon;
    const id = (template.id || template.name || '').toLowerCase();
    for (const [key, icon] of Object.entries(TEMPLATE_ICONS)) {
      if (id.includes(key)) return icon;
    }
    return '&#9670;';
  }

  async function loadTemplates() {
    if (appState.templates.length > 0) return;
    loadingTemplates = true;
    try {
      appState.templates = await getTemplates();
    } catch (err) {
      appState.error = `Failed to load templates: ${err}`;
    } finally {
      loadingTemplates = false;
    }
  }

  async function handleCreate() {
    if (!selectedTemplateId || creating) return;
    creating = true;
    try {
      const project = await createProject({
        template_id: selectedTemplateId,
        description: description.trim() || undefined,
      });
      appState.updateProject(project);
      appState.selectProject(project.id);
    } catch (err) {
      appState.error = `Failed to create project: ${err}`;
    } finally {
      creating = false;
    }
  }

  // Load templates when component mounts
  loadTemplates();
</script>

<div class="new-project">
  <div class="np-header">
    <h2>New Project</h2>
    <p class="np-subtitle">Select an organization template and describe your vision.</p>
  </div>

  {#if loadingTemplates}
    <div class="loading-state">
      <span class="spinner">&#8987;</span>
      Loading templates...
    </div>
  {:else if appState.templates.length === 0}
    <div class="empty-state">
      No templates available. Start the backend to load templates.
    </div>
  {:else}
    <div class="template-grid">
      {#each appState.templates as template (template.id)}
        <button
          class="template-card"
          class:selected={selectedTemplateId === template.id}
          onclick={() => selectedTemplateId = template.id}
        >
          <div class="tc-icon">{@html getIcon(template)}</div>
          <div class="tc-info">
            <span class="tc-name">{template.name}</span>
            <span class="tc-desc">{template.description}</span>
            <span class="tc-meta">{template.roles?.length ?? 0} roles &middot; {template.milestones?.length ?? 0} milestones</span>
          </div>
        </button>
      {/each}
    </div>

    <div class="np-form">
      <label class="form-label" for="np-desc">Project Description</label>
      <textarea
        id="np-desc"
        class="np-textarea"
        bind:value={description}
        placeholder="Describe your idea or leave blank for auto-generate..."
        rows="3"
      ></textarea>

      <button
        class="btn-launch"
        onclick={handleCreate}
        disabled={!selectedTemplateId || creating}
      >
        {#if creating}
          <span class="spinner-inline">&#8987;</span> Creating...
        {:else}
          Launch Project
        {/if}
      </button>
    </div>
  {/if}
</div>

<style>
  .new-project {
    padding: 24px;
    overflow-y: auto;
    max-width: 800px;
  }

  .np-header {
    margin-bottom: 24px;
  }

  .np-header h2 {
    margin: 0 0 6px;
    font-size: 1.3rem;
    font-weight: 700;
  }

  .np-subtitle {
    margin: 0;
    color: var(--text);
    font-size: 0.88rem;
  }

  .loading-state,
  .empty-state {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    opacity: 0.5;
    font-size: 0.88rem;
    padding: 32px 0;
  }

  .spinner {
    animation: pulse 1s infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  .template-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    margin-bottom: 24px;
  }

  .template-card {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 14px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border);
    border-radius: 8px;
    cursor: pointer;
    text-align: left;
    font-family: var(--sans);
    transition: border-color 0.15s, background 0.15s;
    color: var(--text);
  }

  .template-card:hover {
    border-color: rgba(59, 130, 246, 0.3);
    background: rgba(255, 255, 255, 0.04);
  }

  .template-card.selected {
    border-color: var(--accent);
    background: rgba(59, 130, 246, 0.08);
  }

  .tc-icon {
    font-size: 1.6rem;
    line-height: 1;
    flex-shrink: 0;
    width: 32px;
    text-align: center;
    color: var(--accent);
  }

  .tc-info {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .tc-name {
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--text-h);
  }

  .tc-desc {
    font-size: 0.78rem;
    color: var(--text);
    line-height: 1.3;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .tc-meta {
    font-size: 0.68rem;
    color: var(--text);
    opacity: 0.5;
    font-family: var(--mono);
  }

  .np-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .form-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .np-textarea {
    width: 100%;
    padding: 10px 12px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-h);
    font-size: 0.88rem;
    font-family: var(--sans);
    resize: vertical;
    outline: none;
    transition: border-color 0.15s;
  }

  .np-textarea:focus {
    border-color: var(--accent);
  }

  .np-textarea::placeholder {
    color: var(--text);
    opacity: 0.4;
  }

  .btn-launch {
    align-self: flex-start;
    padding: 10px 24px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.88rem;
    font-weight: 600;
    font-family: var(--sans);
    display: flex;
    align-items: center;
    gap: 6px;
    transition: opacity 0.15s;
  }

  .btn-launch:hover:not(:disabled) {
    opacity: 0.9;
  }

  .btn-launch:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .spinner-inline {
    animation: pulse 1s infinite;
  }
</style>

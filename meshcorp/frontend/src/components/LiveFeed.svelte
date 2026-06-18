<script lang="ts">
  import { appState } from '../lib/stores.svelte.ts';
  import { chatProject } from '../lib/api.ts';

  let feedEl: HTMLDivElement | undefined = $state(undefined);
  let inputText: string = $state('');
  let sending: boolean = $state(false);

  // Participant color map for consistent coloring
  const COLORS = [
    '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#a855f7',
    '#ec4899', '#14b8a6', '#f97316', '#6366f1', '#84cc16',
    '#06b6d4', '#e879f9', '#fb923c', '#4ade80', '#fbbf24',
  ];

  function participantColor(name: string): string {
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    return COLORS[Math.abs(hash) % COLORS.length];
  }

  function isCEO(participant: string): boolean {
    return participant.toLowerCase() === 'ceo' || participant.toLowerCase() === 'you';
  }

  function formatTime(ts: string): string {
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return '';
    }
  }

  async function sendMessage() {
    if (!inputText.trim() || !appState.selectedProjectId || sending) return;
    const content = inputText.trim();
    inputText = '';
    sending = true;
    try {
      await chatProject(appState.selectedProjectId, content);
    } catch (err) {
      appState.error = `Failed to send message: ${err}`;
    } finally {
      sending = false;
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  // Auto-scroll to bottom when messages change
  $effect(() => {
    const _len = appState.messages.length;
    if (feedEl) {
      // Use microtask to let DOM update
      queueMicrotask(() => {
        if (feedEl) {
          feedEl.scrollTop = feedEl.scrollHeight;
        }
      });
    }
  });
</script>

<div class="live-feed">
  <div class="feed-header">
    <span class="feed-title">Live Feed</span>
    <span class="msg-count">{appState.messages.length} messages</span>
  </div>

  <div class="feed-messages" bind:this={feedEl}>
    {#if appState.messages.length === 0}
      <div class="empty-feed">
        <span class="empty-icon">&#9672;</span>
        <span>No messages yet. Start a conversation or advance the project.</span>
      </div>
    {:else}
      {#each appState.messages as msg (msg.id)}
        <div class="message" class:ceo-message={isCEO(msg.participant)}>
          <div class="msg-header">
            <span class="participant-name" style="color: {participantColor(msg.participant)}">
              {msg.participant}
            </span>
            {#if msg.role}
              <span class="msg-role">{msg.role}</span>
            {/if}
            {#if msg.skills && msg.skills.length > 0}
              {#each msg.skills as skill}
                <span class="skill-badge">{skill}</span>
              {/each}
            {/if}
            <span class="msg-time">{formatTime(msg.timestamp)}</span>
          </div>
          <div class="msg-content">{msg.content}</div>
        </div>
      {/each}
    {/if}
  </div>

  {#if appState.selectedProjectId}
    <div class="input-bar">
      <textarea
        class="msg-input"
        placeholder="Message as CEO..."
        bind:value={inputText}
        onkeydown={handleKeydown}
        rows="1"
        disabled={sending}
      ></textarea>
      <button class="send-btn" onclick={sendMessage} disabled={sending || !inputText.trim()}>
        {sending ? '...' : '&#9654;'}
      </button>
    </div>
  {/if}
</div>

<style>
  .live-feed {
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--border);
    height: 100%;
    min-height: 0;
  }

  .feed-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
  }

  .feed-title {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text);
  }

  .msg-count {
    font-size: 0.72rem;
    color: var(--text);
    opacity: 0.5;
    font-family: var(--mono);
  }

  .feed-messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .empty-feed {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    height: 100%;
    color: var(--text);
    opacity: 0.4;
    font-size: 0.85rem;
  }

  .empty-icon {
    font-size: 1.2rem;
  }

  .message {
    padding: 8px 10px;
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid transparent;
    transition: background 0.1s;
  }

  .message:hover {
    background: rgba(255, 255, 255, 0.04);
  }

  .message.ceo-message {
    background: rgba(59, 130, 246, 0.06);
    border-color: rgba(59, 130, 246, 0.15);
    margin-left: 32px;
  }

  .msg-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 3px;
    flex-wrap: wrap;
  }

  .participant-name {
    font-size: 0.8rem;
    font-weight: 600;
  }

  .msg-role {
    font-size: 0.68rem;
    color: var(--text);
    opacity: 0.5;
    font-family: var(--mono);
  }

  .skill-badge {
    font-size: 0.62rem;
    padding: 1px 5px;
    border-radius: 4px;
    background: rgba(99, 102, 241, 0.15);
    color: #818cf8;
    font-family: var(--mono);
    font-weight: 500;
  }

  .msg-time {
    margin-left: auto;
    font-size: 0.68rem;
    color: var(--text);
    opacity: 0.4;
    font-family: var(--mono);
  }

  .msg-content {
    font-size: 0.85rem;
    color: var(--text-h);
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .input-bar {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    padding: 10px 16px;
    border-top: 1px solid var(--border);
    background: var(--card-bg);
    flex-shrink: 0;
  }

  .msg-input {
    flex: 1;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    color: var(--text-h);
    font-size: 0.85rem;
    font-family: var(--sans);
    resize: none;
    min-height: 36px;
    max-height: 120px;
    outline: none;
    transition: border-color 0.15s;
  }

  .msg-input:focus {
    border-color: var(--accent);
  }

  .msg-input::placeholder {
    color: var(--text);
    opacity: 0.4;
  }

  .send-btn {
    padding: 8px 14px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.9rem;
    font-family: var(--sans);
    transition: opacity 0.15s;
    flex-shrink: 0;
    height: 36px;
  }

  .send-btn:hover:not(:disabled) {
    opacity: 0.9;
  }

  .send-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>

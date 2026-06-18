// Svelte 5 rune-based global state for MeshCorp HQ
// NOTE: This module exports factory functions, not raw runes.
// Svelte 5 runes ($state, $derived) can only be used at the top level
// of .svelte files or in .svelte.ts files. For plain .ts we use
// a class-based reactive pattern.

import type { Project, Template, Message, Action, DashboardData } from './api.ts';

class AppState {
  projects: Project[] = $state([]);
  templates: Template[] = $state([]);
  actions: Action[] = $state([]);
  selectedProjectId: string | null = $state(null);
  messages: Message[] = $state([]);
  dashboardData: DashboardData | null = $state(null);
  wsConnected: boolean = $state(false);
  currentView: 'dashboard' | 'project' | 'new' | 'inbox' = $state('dashboard');
  loading: boolean = $state(false);
  error: string | null = $state(null);

  get selectedProject(): Project | null {
    if (!this.selectedProjectId) return null;
    return this.projects.find((p) => p.id === this.selectedProjectId) ?? null;
  }

  get activeProjects(): Project[] {
    return this.projects.filter((p) => p.status === 'active');
  }

  get planningProjects(): Project[] {
    return this.projects.filter((p) => p.status === 'planning');
  }

  get proposalProjects(): Project[] {
    return this.projects.filter((p) => p.status === 'proposal');
  }

  get completedProjects(): Project[] {
    return this.projects.filter((p) => p.status === 'completed' || p.status === 'killed');
  }

  get pendingActions(): Action[] {
    return this.actions.filter((a) => !a.resolved);
  }

  get totalBudget(): number {
    return this.projects.reduce((sum, p) => sum + (p.budget ?? 0), 0);
  }

  get totalSpent(): number {
    return this.projects.reduce((sum, p) => sum + (p.spent ?? 0), 0);
  }

  selectProject(id: string): void {
    this.selectedProjectId = id;
    this.currentView = 'project';
  }

  clearSelection(): void {
    this.selectedProjectId = null;
    this.messages = [];
  }

  addMessage(msg: Message): void {
    // Avoid duplicates
    if (!this.messages.find((m) => m.id === msg.id)) {
      this.messages = [...this.messages, msg];
    }
  }

  updateProject(project: Project): void {
    const idx = this.projects.findIndex((p) => p.id === project.id);
    if (idx >= 0) {
      this.projects[idx] = project;
      // Trigger reactivity
      this.projects = [...this.projects];
    } else {
      this.projects = [...this.projects, project];
    }
  }

  removeAction(id: string): void {
    this.actions = this.actions.filter((a) => a.id !== id);
  }

  resolveActionById(id: string): void {
    const idx = this.actions.findIndex((a) => a.id === id);
    if (idx >= 0) {
      this.actions[idx] = { ...this.actions[idx], resolved: true };
      this.actions = [...this.actions];
    }
  }
}

export const appState = new AppState();

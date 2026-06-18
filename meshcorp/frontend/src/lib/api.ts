// API client for MeshCorp HQ backend

export interface Template {
  id: string;
  name: string;
  description: string;
  icon: string;
  roles: { title: string; model: string; persona: string }[];
  milestones: { name: string; description: string; participants: string[] }[];
}

export interface Milestone {
  index: number;
  name: string;
  description: string;
  participants: string[];
  status: string; // "pending" | "active" | "completed" | "failed"
  started_at?: string;
  completed_at?: string;
  result?: string;
}

export interface Message {
  id: string;
  project_id: string;
  participant: string;
  role: string;
  content: string;
  milestone_index?: number;
  skills?: string[];
  timestamp: string;
}

export interface Action {
  id: string;
  project_id: string;
  title: string;
  description: string;
  urgency: string; // "low" | "medium" | "high" | "critical"
  blocking: boolean;
  resolved: boolean;
  created_at: string;
  resolved_at?: string;
}

export interface Project {
  id: string;
  template_id: string;
  template_name?: string;
  description: string;
  status: string; // "proposal" | "planning" | "active" | "completed" | "killed"
  model: string;
  budget: number;
  spent: number;
  current_milestone: number;
  milestones: Milestone[];
  messages?: Message[];
  actions?: Action[];
  created_at: string;
  updated_at: string;
}

export interface DashboardData {
  projects: Project[];
  active_count: number;
  total_budget: number;
  total_spent: number;
  pending_actions: number;
  recent_messages: Message[];
}

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new ApiError(res.status, `${res.status}: ${text}`);
  }
  return res.json();
}

export function getTemplates(): Promise<Template[]> {
  return request('/api/templates');
}

export function getProjects(): Promise<Project[]> {
  return request('/api/projects');
}

export function getProject(id: string): Promise<Project> {
  return request(`/api/projects/${id}`);
}

export function createProject(data: {
  template_id: string;
  description?: string;
  model?: string;
}): Promise<Project> {
  return request('/api/projects', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function advanceProject(id: string): Promise<Project> {
  return request(`/api/projects/${id}/advance`, { method: 'POST' });
}

export function chatProject(id: string, content: string): Promise<Message> {
  return request(`/api/projects/${id}/chat`, {
    method: 'POST',
    body: JSON.stringify({ content }),
  });
}

export function fundProject(id: string, amount: number): Promise<Project> {
  return request(`/api/projects/${id}/fund`, {
    method: 'POST',
    body: JSON.stringify({ amount }),
  });
}

export function killProject(id: string): Promise<Project> {
  return request(`/api/projects/${id}/kill`, { method: 'POST' });
}

export function getActions(): Promise<Action[]> {
  return request('/api/actions');
}

export function resolveAction(id: string): Promise<Action> {
  return request(`/api/actions/${id}/resolve`, { method: 'POST' });
}

export function getDashboard(): Promise<DashboardData> {
  return request('/api/dashboard');
}

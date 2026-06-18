// Auto-reconnecting WebSocket manager for MeshCorp HQ

export type WSEventType =
  | 'message'
  | 'project_created'
  | 'milestone_completed'
  | 'milestone_started'
  | 'project_updated'
  | 'action_created'
  | 'action_resolved'
  | 'error'
  | 'pong'
  | 'connected';

export interface WSEvent {
  type: WSEventType;
  data: any;
}

type WSCallback = (event: WSEvent) => void;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private callbacks: Set<WSCallback> = new Set();
  private pingInterval: ReturnType<typeof setInterval> | null = null;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private _connected = false;
  private intentionalClose = false;

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.intentionalClose = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/api/ws`;

    try {
      this.ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this._connected = true;
      this.reconnectDelay = 1000;
      this.startPing();
      this.dispatch({ type: 'connected', data: null });
    };

    this.ws.onmessage = (event) => {
      try {
        const parsed: WSEvent = JSON.parse(event.data);
        this.dispatch(parsed);
      } catch {
        // Ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this._connected = false;
      this.stopPing();
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror
    };
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.stopPing();
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this._connected = false;
  }

  subscribe(callback: WSCallback): () => void {
    this.callbacks.add(callback);
    return () => this.callbacks.delete(callback);
  }

  send(data: any): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private dispatch(event: WSEvent): void {
    for (const cb of this.callbacks) {
      try {
        cb(event);
      } catch {
        // Don't let one bad callback break others
      }
    }
  }

  private startPing(): void {
    this.stopPing();
    this.pingInterval = setInterval(() => {
      this.send({ type: 'ping' });
    }, 30000);
  }

  private stopPing(): void {
    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) return;
    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();

import { EventEnvelope } from "./events";
import { WS_BASE_URL } from "./env";

type Handler = (event: EventEnvelope<unknown>) => void;

export class AstraWsClient {
  private socket: WebSocket | null = null;
  private readonly handlers = new Set<Handler>();

  connect(sessionId: string) {
    this.close();
    this.socket = new WebSocket(`${WS_BASE_URL}/ws/session/${sessionId}`);
    this.socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as EventEnvelope<unknown>;
        this.handlers.forEach((handler) => handler(event));
      } catch {
        this.handlers.forEach((handler) =>
          handler({
            id: "evt_parse_error",
            type: "error",
            session_id: sessionId,
            ts: Date.now(),
            payload: { code: "invalid_server_message" },
          }),
        );
      }
    };
    return this.socket;
  }

  onEvent(handler: Handler) {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  send(event: EventEnvelope<unknown>) {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(event));
      return true;
    }
    return false;
  }

  close() {
    this.socket?.close();
    this.socket = null;
  }
}

export const wsClient = new AstraWsClient();

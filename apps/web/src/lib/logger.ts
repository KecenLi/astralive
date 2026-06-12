export function logDebug(message: string, extra?: unknown) {
  if (import.meta.env.DEV) {
    console.debug(`[AstraLive] ${message}`, extra ?? "");
  }
}


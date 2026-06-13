function resolveApiBaseUrl() {
  const fromQuery = new URLSearchParams(window.location.search).get("apiBaseUrl");
  return fromQuery ?? import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
}

function resolveLive2DModelUrl() {
  const fromEnv = import.meta.env.VITE_LIVE2D_MODEL_URL;
  const modelUrl = fromEnv || "./live2d/haru/haru/runtime/haru.model3.json";
  if (modelUrl.startsWith("/live2d/")) return `.${modelUrl}`;
  return modelUrl;
}

export const API_BASE_URL = resolveApiBaseUrl();
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");
export const LIVE2D_MODEL_URL = resolveLive2DModelUrl();
export const APP_MODE = new URLSearchParams(window.location.search).get("mode") ?? "main";

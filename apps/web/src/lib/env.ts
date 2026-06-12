export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");
export const LIVE2D_MODEL_URL = import.meta.env.VITE_LIVE2D_MODEL_URL ?? "";

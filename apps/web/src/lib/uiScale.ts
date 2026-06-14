// Global UI zoom: Ctrl + mouse wheel scales every component that sizes itself
// from the --ui-scale custom property (see global.css). Kept self-contained and
// wired from main.tsx so it does not depend on the React tree or App.tsx.

const STORAGE_KEY = "modvii.uiScale";
export const MIN_SCALE = 0.7;
export const MAX_SCALE = 1.8;
export const SCALE_STEP = 0.06;

export function clampScale(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

function readStoredScale(): number {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw == null) return 1;
    return clampScale(parseFloat(raw));
  } catch {
    return 1;
  }
}

function applyScale(scale: number): void {
  const clamped = clampScale(scale);
  document.documentElement.style.setProperty("--ui-scale", clamped.toFixed(3));
  try {
    window.localStorage.setItem(STORAGE_KEY, clamped.toFixed(3));
  } catch {
    // Persistence is best-effort; ignore storage failures.
  }
}

export function initUiScale(): void {
  let scale = readStoredScale();
  applyScale(scale);

  const onWheel = (event: WheelEvent) => {
    // Only hijack the wheel while Ctrl (or Cmd) is held, so normal scrolling and
    // any list scroll behaviour stay untouched.
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const direction = event.deltaY < 0 ? 1 : -1;
    scale = clampScale(scale + direction * SCALE_STEP);
    applyScale(scale);
  };

  const onKeyDown = (event: KeyboardEvent) => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key === "0") {
      event.preventDefault();
      scale = 1;
      applyScale(scale);
    } else if (event.key === "=" || event.key === "+") {
      event.preventDefault();
      scale = clampScale(scale + SCALE_STEP);
      applyScale(scale);
    } else if (event.key === "-") {
      event.preventDefault();
      scale = clampScale(scale - SCALE_STEP);
      applyScale(scale);
    }
  };

  // passive:false is required because we call preventDefault to stop the browser
  // page-zoom default on Ctrl+wheel.
  window.addEventListener("wheel", onWheel, { passive: false });
  window.addEventListener("keydown", onKeyDown);
}

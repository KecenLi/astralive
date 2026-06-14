// Shared visual-capture coordinator.
//
// Camera and screen capture run as independent timer loops. They should be able
// to progress in parallel, but each individual source still needs its own guard
// so a slow capture cannot pile up stale frames. The legacy runExclusiveCapture
// API is kept for tests and older callers; panels use runVisualSourceCapture.

const MIN_GAP_MS = 180;
// If a single capture somehow never resolves, release the lock anyway after
// this long so the pipeline can never permanently wedge.
const MAX_HOLD_MS = 8000;

let busy = false;
let lastRunAt = 0;
let lockedAt = 0;

const SOURCE_MIN_GAP_MS = 160;
const SOURCE_MAX_HOLD_MS = 8000;
const MAX_PARALLEL_SOURCES = 2;

const sourceBusy = new Map<string, number>();
const sourceLastRunAt = new Map<string, number>();

function now(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function lockIsStale(): boolean {
  return busy && now() - lockedAt > MAX_HOLD_MS;
}

/**
 * Try to acquire the shared capture slot. Returns false immediately if another
 * source holds it or if we are still within the minimum gap — the caller should
 * simply skip this tick rather than queue (visual frames are time-sensitive; a
 * stale queued frame is worthless).
 */
export function tryAcquireCaptureSlot(): boolean {
  const t = now();
  if (busy && !lockIsStale()) return false;
  if (t - lastRunAt < MIN_GAP_MS) return false;
  busy = true;
  lockedAt = t;
  return true;
}

/** Release the shared capture slot. Safe to call more than once. */
export function releaseCaptureSlot(): void {
  busy = false;
  lastRunAt = now();
}

/**
 * Run an async capture under the shared slot. Returns null without invoking
 * `fn` if the slot was unavailable. Always releases, even on error.
 */
export async function runExclusiveCapture<T>(fn: () => Promise<T>): Promise<T | null> {
  if (!tryAcquireCaptureSlot()) return null;
  try {
    return await fn();
  } finally {
    releaseCaptureSlot();
  }
}

function cleanupStaleSourceLocks(t: number): void {
  for (const [source, startedAt] of sourceBusy) {
    if (t - startedAt > SOURCE_MAX_HOLD_MS) {
      sourceBusy.delete(source);
      sourceLastRunAt.set(source, t);
    }
  }
}

/**
 * Run one capture for a named source. Camera and screen may run at the same
 * time, while repeated captures from the same source are skipped until the
 * previous one finishes. This gives us real camera/screen parallelism without
 * allowing a single stream to backlog.
 */
export async function runVisualSourceCapture<T>(
  source: "camera" | "screen",
  fn: () => Promise<T>,
): Promise<T | null> {
  const t = now();
  cleanupStaleSourceLocks(t);
  if (sourceBusy.has(source)) return null;
  if (sourceBusy.size >= MAX_PARALLEL_SOURCES) return null;
  if (t - (sourceLastRunAt.get(source) ?? 0) < SOURCE_MIN_GAP_MS) return null;
  sourceBusy.set(source, t);
  try {
    return await fn();
  } finally {
    sourceBusy.delete(source);
    sourceLastRunAt.set(source, now());
  }
}

// Test-only reset so unit tests start from a clean slot.
export function __resetCaptureCoordinator(): void {
  busy = false;
  lastRunAt = 0;
  lockedAt = 0;
  sourceBusy.clear();
  sourceLastRunAt.clear();
}

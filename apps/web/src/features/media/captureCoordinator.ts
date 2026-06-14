// Shared visual-capture coordinator.
//
// Camera and screen capture run as independent timer loops. Without a shared
// gate they can fire frames at the same instant, and together with a voice turn
// starting they overwhelm the server's single-concurrency vision path, which
// then defers / drops / cools-down in a cascade — observed as a race when the
// avatar, camera and screen are all active at once.
//
// This module is a tiny, dependency-free coordinator that every visual source
// funnels through. It guarantees:
//   1. Only one capture+upload runs at a time across ALL sources (mutex).
//   2. A minimum spacing between any two uploads, regardless of source, so two
//      loops cannot burst-submit back to back.
//   3. A hard staleness guard so a hung capture can never wedge the mutex.
//
// It is intentionally redundant on top of each panel's own in-flight guard:
// defense in depth against the cross-source race.

const MIN_GAP_MS = 180;
// If a single capture somehow never resolves, release the lock anyway after
// this long so the pipeline can never permanently wedge.
const MAX_HOLD_MS = 8000;

let busy = false;
let lastRunAt = 0;
let lockedAt = 0;

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

// Test-only reset so unit tests start from a clean slot.
export function __resetCaptureCoordinator(): void {
  busy = false;
  lastRunAt = 0;
  lockedAt = 0;
}

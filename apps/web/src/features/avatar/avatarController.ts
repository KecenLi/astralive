import { AvatarExpression, AvatarMode } from "../../lib/events";

export interface AvatarController {
  setState: (state: {
    mode: AvatarMode;
    expression: AvatarExpression;
    subtitle: string;
    lipSync: boolean;
    lipSyncLevel?: number;
  }) => void;
  dispose: () => void;
}

export class FallbackAvatarController implements AvatarController {
  private callback: AvatarController["setState"];

  constructor(callback: AvatarController["setState"]) {
    this.callback = callback;
  }

  setState(state: Parameters<AvatarController["setState"]>[0]) {
    this.callback(state);
  }

  dispose() {
    return;
  }
}

export class Live2DAvatarController implements AvatarController {
  private app: unknown = null;
  private model: unknown = null;
  private lastExpression = "";
  private lastMotion = "";
  private lipSync = false;
  private targetMouthOpen = 0;
  private mouthOpen = 0;

  private static cubism4CoreLoaded = false;

  async mount(canvas: HTMLCanvasElement, modelUrl: string) {
    const PIXI = await import("pixi.js");
    (window as unknown as { PIXI?: unknown }).PIXI = PIXI;
    patchPixiUrlResolve(PIXI);
    const live2d = await this.loadLive2DDisplay(modelUrl);
    const Application = (PIXI as unknown as { Application: new (options: unknown) => unknown }).Application;
    const Live2DModel = (live2d as unknown as { Live2DModel: { from: (url: string) => Promise<unknown> } })
      .Live2DModel;

    this.app = new Application({
      view: canvas,
      resizeTo: canvas.parentElement ?? canvas,
      backgroundAlpha: 0,
      autoStart: true,
    });
    this.model = await Live2DModel.from(modelUrl);
    this.fitModel(canvas);
    const stage = (this.app as { stage?: { addChild: (model: unknown) => void } }).stage;
    stage?.addChild(this.model);
    this.addLipSyncTicker();
  }

  setState(state: Parameters<AvatarController["setState"]>[0]) {
    this.lipSync = state.lipSync;
    this.targetMouthOpen = state.lipSync ? Math.min(1, Math.max(0, state.lipSyncLevel ?? 0.18)) : 0;
    this.applyExpression(state.expression);
    this.applyMotion(state.mode);
  }

  dispose() {
    const destroy = (this.app as { destroy?: (removeView: boolean) => void } | null)?.destroy;
    destroy?.call(this.app, false);
    this.app = null;
    this.model = null;
  }

  private async loadLive2DDisplay(modelUrl: string) {
    if (modelUrl.endsWith(".model3.json")) {
      if (!Live2DAvatarController.cubism4CoreLoaded) {
        await loadScript("./vendor/live2dcubismcore.min.js");
        await waitForCubismCoreReady();
        Live2DAvatarController.cubism4CoreLoaded = true;
      }
      const live2d = await import("pixi-live2d-display/cubism4");
      patchCubism4WebGLContext(live2d);
      return live2d;
    }
    return import("pixi-live2d-display/cubism2");
  }

  private fitModel(canvas: HTMLCanvasElement) {
    const model = this.model as {
      width?: number;
      height?: number;
      scale?: { set: (value: number) => void };
      anchor?: { set: (x: number, y?: number) => void };
      x?: number;
      y?: number;
    } | null;
    if (!model?.width || !model.height) return;
    const parent = canvas.parentElement ?? canvas;
    const scale = Math.min((parent.clientWidth * 0.62) / model.width, (parent.clientHeight * 0.9) / model.height);
    model.scale?.set(scale);
    model.anchor?.set(0.5, 0.5);
    model.x = parent.clientWidth / 2;
    model.y = parent.clientHeight * 0.56;
  }

  private addLipSyncTicker() {
    const app = this.app as {
      ticker?: { add: (callback: () => void) => void };
    } | null;
    app?.ticker?.add(() => {
      const fallback = this.lipSync ? 0.12 + Math.abs(Math.sin(performance.now() / 120)) * 0.18 : 0;
      const target = this.lipSync ? Math.max(this.targetMouthOpen, fallback) : 0;
      this.mouthOpen += (target - this.mouthOpen) * 0.35;
      this.setParameter("ParamMouthOpenY", this.mouthOpen);
    });
  }

  private applyExpression(expression: AvatarExpression) {
    const mapped = expressionName(expression);
    if (mapped === this.lastExpression) return;
    this.lastExpression = mapped;
    const model = this.model as { expression?: (nameOrIndex: string | number) => void } | null;
    try {
      model?.expression?.(mapped);
    } catch {
      return;
    }
  }

  private applyMotion(mode: AvatarMode) {
    const mapped = motionName(mode);
    if (mapped === this.lastMotion) return;
    this.lastMotion = mapped;
    const model = this.model as { motion?: (group: string, index?: number) => void } | null;
    try {
      model?.motion?.(mapped, 0);
    } catch {
      try {
        model?.motion?.("Idle", 0);
      } catch {
        return;
      }
    }
  }

  private setParameter(id: string, value: number) {
    const coreModel = (
      this.model as {
        internalModel?: { coreModel?: { setParameterValueById?: (id: string, value: number) => void } };
      } | null
    )?.internalModel?.coreModel;
    coreModel?.setParameterValueById?.(id, value);
  }
}

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-modvii-src="${src}"]`);
    if (existing) {
      if (existing.dataset.modviiLoaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`Failed to load Live2D runtime: ${src}`)), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.modviiSrc = src;
    script.onload = () => {
      script.dataset.modviiLoaded = "true";
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load Live2D runtime: ${src}`));
    document.head.appendChild(script);
  });
}

async function waitForCubismCoreReady(timeoutMs = 5000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    const core = (window as unknown as {
      Live2DCubismCore?: {
        Memory?: { initializeAmountOfMemory?: (memorySize?: number) => void };
        Version?: { csmGetVersion?: () => number };
      };
    }).Live2DCubismCore;
    try {
      if (
        core?.Version?.csmGetVersion &&
        core.Version.csmGetVersion() > 0 &&
        typeof core.Memory?.initializeAmountOfMemory === "function"
      ) {
        return;
      }
    } catch {
      // The Emscripten runtime is loaded but not initialized yet.
    }
    await new Promise((resolve) => window.setTimeout(resolve, 50));
  }
  throw new Error("Live2D Cubism core did not become ready.");
}

export function describeLive2DError(error: unknown) {
  if (!(error instanceof Error)) return String(error);
  const candidate = error as Error & { cause?: unknown };
  const cause = candidate.cause instanceof Error ? ` cause=${candidate.cause.stack || candidate.cause.message}` : "";
  return `${error.stack || error.message}${cause}`;
}

function patchCubism4WebGLContext(live2d: unknown) {
  const cubism4 = live2d as {
    Cubism4InternalModel?: { prototype?: Record<string, unknown> };
    CubismShader_WebGL?: { getInstance?: () => { _shaderSets?: unknown[] } };
  };
  const prototype = cubism4.Cubism4InternalModel?.prototype;
  if (!prototype || prototype.__modviiWebGLContextPatch) return;

  prototype.updateWebGLContext = function updateWebGLContext(gl: WebGLRenderingContext, glContextID: number) {
    const internal = this as {
      renderer?: {
        _bufferData?: { index: null; uv: null; vertex: null };
        _clippingManager?: { _currentFrameNo?: number; _maskTexture?: unknown };
        firstDraw?: boolean;
        startUp?: (context: WebGLRenderingContext) => void;
      };
    };
    if (!internal.renderer) return;
    internal.renderer.firstDraw = true;
    internal.renderer._bufferData = { vertex: null, uv: null, index: null };
    internal.renderer.startUp?.(gl);
    if (internal.renderer._clippingManager) {
      internal.renderer._clippingManager._currentFrameNo = glContextID;
      internal.renderer._clippingManager._maskTexture = undefined;
    }
    const shaders = cubism4.CubismShader_WebGL?.getInstance?.();
    if (shaders) shaders._shaderSets = [];
  };
  prototype.__modviiWebGLContextPatch = true;
}

function patchPixiUrlResolve(PIXI: unknown) {
  const pixi = PIXI as {
    utils?: { url?: { resolve?: (base: string, path: string) => string }; __modviiUrlResolvePatch?: boolean };
  };
  if (!pixi.utils?.url || pixi.utils.__modviiUrlResolvePatch) return;
  const resolve = (base: string, resourcePath: string) =>
    new URL(resourcePath, new URL(base, window.location.href)).toString();
  try {
    Object.defineProperty(pixi.utils.url, "resolve", {
      configurable: true,
      value: resolve,
    });
    pixi.utils.__modviiUrlResolvePatch = true;
  } catch {
    // Some Pixi builds expose url.resolve as a read-only accessor. The original resolver still works.
  }
}

function expressionName(expression: AvatarExpression) {
  const map: Record<AvatarExpression, string> = {
    neutral: "Normal",
    happy: "Smile",
    curious: "f01",
    surprised: "Surprised",
    confused: "f02",
    concerned: "Sad",
    thinking: "Blushing",
    sleepy: "Normal",
  };
  return map[expression];
}

function motionName(mode: AvatarMode) {
  const map: Partial<Record<AvatarMode, string>> = {
    sleeping: "Idle",
    idle: "Idle",
    listening: "TapBody",
    thinking: "TapBody",
    speaking: "TapBody",
    interrupted: "TapBody",
    error: "TapBody",
  };
  return map[mode] ?? "Idle";
}

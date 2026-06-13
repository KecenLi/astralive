import { AvatarExpression, AvatarMode } from "../../lib/events";

export interface AvatarController {
  setState: (state: {
    mode: AvatarMode;
    expression: AvatarExpression;
    motion?: string;
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
      premultipliedAlpha: false,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(window.devicePixelRatio || 1, 2),
      autoStart: true,
    });
    this.model = await Live2DModel.from(modelUrl);
    this.initializePartVisibility();
    this.fitModel(canvas);
    const stage = (this.app as { stage?: { addChild: (model: unknown) => void } }).stage;
    stage?.addChild(this.model);
    this.addLipSyncTicker();
  }

  setState(state: Parameters<AvatarController["setState"]>[0]) {
    this.lipSync = state.lipSync;
    this.targetMouthOpen = state.lipSync ? Math.min(1, Math.max(0, state.lipSyncLevel ?? 0.18)) : 0;
    this.applyExpression(state.expression);
    this.applyMotion(state.mode, state.motion, state.subtitle);
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
      alpha?: number;
      x?: number;
      y?: number;
    } | null;
    if (!model?.width || !model.height) return;
    const parent = canvas.parentElement ?? canvas;
    const scale = Math.min((parent.clientWidth * 0.62) / model.width, (parent.clientHeight * 0.9) / model.height);
    model.scale?.set(scale);
    model.anchor?.set(0.5, 0.5);
    model.alpha = 1;
    model.x = parent.clientWidth / 2;
    model.y = parent.clientHeight * 0.56;
  }

  private initializePartVisibility() {
    const coreModel = (
      this.model as {
        internalModel?: { coreModel?: { setPartOpacityById?: (id: string, value: number) => void } };
      } | null
    )?.internalModel?.coreModel;
    if (!coreModel?.setPartOpacityById) return;

    const visibleParts = [
      "HairFrontPart",
      "ExpressionsPart",
      "EyeLPart",
      "EyeRPart",
      "FacePart",
      "HairSideL3SkinningPart",
      "HairSideL4SkinningPart",
      "HairSideR4SkinningPart",
      "NeckScarfPart",
      "ArmLPart",
      "LowerArmLPart",
      "BodyPart",
      "DressPart",
      "ArmRPart",
      "LegRPart",
      "LegLPart",
      "DressBackPart",
      "HairRibbonPart",
      "HairBackPart",
      "ScissorLPart",
      "ScissorRPart",
      "HairBackSkinningPart",
    ];
    for (const id of visibleParts) {
      coreModel.setPartOpacityById(id, 1);
    }
    const hiddenParts = [
      "GlowTracingPart",
      "SpecialEffectsPart",
      "ScissorLAnimationPart",
      "ScissorRAnimationPart",
      "GuideImagePart",
      "BodySilhouettePart",
      "FaceBackupPart",
    ];
    for (const id of hiddenParts) {
      coreModel.setPartOpacityById(id, 0);
    }
  }

  private addLipSyncTicker() {
    const app = this.app as {
      ticker?: { add: (callback: () => void) => void };
    } | null;
    app?.ticker?.add(() => {
      this.initializePartVisibility();
      const fallback = this.lipSync ? 0.12 + Math.abs(Math.sin(performance.now() / 120)) * 0.18 : 0;
      const target = this.lipSync ? Math.max(this.targetMouthOpen, fallback) : 0;
      this.mouthOpen += (target - this.mouthOpen) * 0.35;
      this.setMouthOpen(this.mouthOpen);
    });
  }

  private applyExpression(expression: AvatarExpression) {
    const mapped = expressionNames(expression);
    const key = mapped.join("|");
    if (key === this.lastExpression) return;
    this.lastExpression = key;
    const model = this.model as { expression?: (nameOrIndex: string | number) => void } | null;
    for (const name of mapped) {
      try {
        model?.expression?.(name);
        return;
      } catch {
        // Try the next model-specific expression alias.
      }
    }
  }

  private applyMotion(mode: AvatarMode, requestedMotion = "", subtitle = "") {
    const mapped = motionSpec(requestedMotion, mode);
    const key = `${mapped.groups.join("|")}:${mapped.index ?? "auto"}:${
      mode === "speaking" ? subtitle.slice(0, 32) : ""
    }`;
    if (key === this.lastMotion) return;
    this.lastMotion = key;
    const model = this.model as { motion?: (group: string, index?: number) => void } | null;
    for (const group of mapped.groups) {
      try {
        if (typeof mapped.index === "number") {
          model?.motion?.(group, mapped.index);
        } else {
          model?.motion?.(group);
        }
        return;
      } catch {
        // Try the next common group alias for models with different naming.
      }
    }
    try {
      model?.motion?.("Idle");
    } catch {
      return;
    }
  }

  private setMouthOpen(value: number) {
    for (const id of ["ParamMouthOpenY", "PARAM_MOUTH_OPEN_Y", "ParamMouthOpen", "PARAM_MOUTH_OPEN"]) {
      this.setParameter(id, value);
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

function expressionNames(expression: AvatarExpression) {
  const map: Record<AvatarExpression, string[]> = {
    neutral: ["Normal"],
    happy: ["Smile", "shy"],
    curious: ["f01", "sans_eye_glow", "shy"],
    surprised: ["Surprised", "frenzy"],
    confused: ["f02", "frenzy"],
    concerned: ["Sad", "sad", "tear"],
    thinking: ["Blushing", "shy"],
    sleepy: ["Normal", "shy"],
  };
  return map[expression];
}

interface MotionSpec {
  groups: string[];
  index?: number;
}

function motionSpec(motion: string | undefined, mode: AvatarMode): MotionSpec {
  const normalized = (motion || "").trim();
  if (normalized) {
    const parsed = parseExplicitMotion(normalized);
    if (parsed) return parsed;
  }

  const map: Record<string, MotionSpec> = {
    idle: { groups: ["Idle", "Breathing", "HandFiddle", "ShyIdle"] },
    sleep: { groups: ["Idle", "Breathing", "ShyIdle"] },
    sleeping: { groups: ["Idle", "Breathing", "ShyIdle"] },
    listen: { groups: ["Tap", "Tap@Body", "Flick", "Greeting", "HandFiddle"] },
    listening: { groups: ["Tap", "Tap@Body", "Flick", "Greeting", "HandFiddle"] },
    think: { groups: ["Flick", "FlickDown", "Tap", "Tap@Body", "HandFiddle", "ShyIdle"] },
    thinking: { groups: ["Flick", "FlickDown", "Tap", "Tap@Body", "HandFiddle", "ShyIdle"] },
    talk: { groups: ["Tap", "Tap@Body", "Flick", "Greeting", "Happy"] },
    speaking: { groups: ["Tap", "Tap@Body", "Flick", "Greeting", "Happy"] },
    happy: { groups: ["Flick3", "Flick", "Tap", "Happy", "Greeting", "ShyIdle"] },
    curious: { groups: ["FlickRight", "Flick", "Tap", "Greeting", "HandFiddle"] },
    surprised: { groups: ["FlickLeft", "FlickDown", "Flick", "Jump", "Frenzy"] },
    concerned: { groups: ["Shake", "FlickDown", "Tap", "Sad", "SadIdle", "ShyIdle"] },
    confused: { groups: ["Shake", "FlickDown", "Tap", "Frenzy", "HandFiddle"] },
    nod: { groups: ["Tap", "Tap@Body", "Greeting"] },
    reject: { groups: ["Shake", "FlickDown", "Sad"] },
    interrupted: { groups: ["Shake", "FlickLeft", "Tap", "Jump"] },
    error: { groups: ["Shake", "FlickDown", "Tap", "Sad"] },
  };
  return map[normalized] ?? map[mode] ?? { groups: ["Idle"] };
}

function parseExplicitMotion(motion: string): MotionSpec | null {
  const parts = motion.split(":");
  if (!parts[0]) return null;
  const group = parts[0].trim();
  if (!group) return null;
  if (parts.length === 1 || !parts[1]) return { groups: [group] };
  const index = Number(parts[1]);
  return Number.isInteger(index) && index >= 0 ? { groups: [group], index } : { groups: [group] };
}

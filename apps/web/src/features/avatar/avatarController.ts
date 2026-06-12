import { AvatarExpression, AvatarMode } from "../../lib/events";

export interface AvatarController {
  setState: (state: {
    mode: AvatarMode;
    expression: AvatarExpression;
    subtitle: string;
    lipSync: boolean;
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

  async mount(canvas: HTMLCanvasElement, modelUrl: string) {
    const PIXI = await import("pixi.js");
    const live2d = await import("pixi-live2d-display");
    (window as unknown as { PIXI?: unknown }).PIXI = PIXI;
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
    const stage = (this.app as { stage?: { addChild: (model: unknown) => void } }).stage;
    stage?.addChild(this.model);
  }

  setState(state: Parameters<AvatarController["setState"]>[0]) {
    void state;
    return;
  }

  dispose() {
    const destroy = (this.app as { destroy?: (removeView: boolean) => void } | null)?.destroy;
    destroy?.call(this.app, false);
    this.app = null;
    this.model = null;
  }
}

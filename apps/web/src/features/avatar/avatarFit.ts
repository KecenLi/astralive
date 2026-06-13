import { AvatarLayoutSettings, normalizeAvatarLayout } from "../../lib/desktopSettings";

export interface AvatarFitInput {
  mode: "main" | "pet";
  parentWidth: number;
  parentHeight: number;
  modelWidth: number;
  modelHeight: number;
  layout?: Partial<AvatarLayoutSettings>;
}

export interface AvatarFitResult {
  scale: number;
  x: number;
  y: number;
}

export function computeAvatarFit(input: AvatarFitInput): AvatarFitResult {
  const parentWidth = Math.max(1, input.parentWidth);
  const parentHeight = Math.max(1, input.parentHeight);
  const modelWidth = Math.max(1, input.modelWidth);
  const modelHeight = Math.max(1, input.modelHeight);
  const layout = normalizeAvatarLayout(input.layout, input.mode);

  const widthScale = (parentWidth * layout.widthFill) / modelWidth;
  const heightScale = (parentHeight * layout.heightFill) / modelHeight;
  const maxHeightScale = layout.maxHeightPx / modelHeight;
  const scale = Math.max(0.01, Math.min(widthScale, heightScale) * layout.scale);
  const cappedScale = Math.min(scale, maxHeightScale);

  return {
    scale: cappedScale,
    x: parentWidth / 2 + layout.offsetX,
    y: parentHeight * layout.yRatio + layout.offsetY,
  };
}

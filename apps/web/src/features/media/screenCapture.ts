import { isDesktopRuntime } from "../../lib/desktopBridge";

export interface ScreenCaptureResult {
  stream: MediaStream;
  sourceName: string;
}

type ChromiumDesktopConstraints = MediaTrackConstraints & {
  mandatory?: {
    chromeMediaSource: "desktop";
    chromeMediaSourceId: string;
    maxWidth: number;
    maxHeight: number;
    maxFrameRate: number;
  };
};

export async function requestScreenCapture(): Promise<ScreenCaptureResult> {
  if (isDesktopRuntime() && window.modvii) {
    const source = await window.modvii.screen.getPrimarySource();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: "desktop",
          chromeMediaSourceId: source.id,
          maxWidth: 1920,
          maxHeight: 1080,
          maxFrameRate: 30,
        },
      } as ChromiumDesktopConstraints,
    });
    return { stream, sourceName: source.name };
  }

  if (!navigator.mediaDevices.getDisplayMedia) {
    throw new Error("当前环境不支持屏幕捕捉");
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
  return { stream, sourceName: "浏览器选择的屏幕" };
}

export function stopMediaStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

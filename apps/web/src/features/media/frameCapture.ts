import { FramePayload } from "../../lib/events";
import { computeAverageHash } from "./sceneHash";

async function canvasToJpegBase64(canvas: HTMLCanvasElement, quality: number): Promise<string> {
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (result) => {
        if (result) {
          resolve(result);
        } else {
          reject(new Error("Canvas JPEG encoding failed."));
        }
      },
      "image/jpeg",
      quality,
    );
  });
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return btoa(binary);
}

export async function captureVideoFrame(
  video: HTMLVideoElement,
  reason: FramePayload["capture_reason"],
  prompt: string,
  options: { quality: number; maxWidth: number; maxHeight: number },
): Promise<FramePayload> {
  const ratio = Math.min(
    1,
    options.maxWidth / video.videoWidth,
    options.maxHeight / video.videoHeight,
  );
  const width = Math.max(1, Math.round(video.videoWidth * ratio));
  const height = Math.max(1, Math.round(video.videoHeight * ratio));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not available.");
  ctx.drawImage(video, 0, 0, width, height);
  const sceneHash = computeAverageHash(canvas);
  const dataBase64 = await canvasToJpegBase64(canvas, options.quality);
  return {
    frame_id: `frame_${Date.now()}`,
    mime: "image/jpeg",
    width,
    height,
    quality: options.quality,
    capture_reason: reason,
    scene_hash: sceneHash,
    data_base64: dataBase64,
    prompt,
  };
}

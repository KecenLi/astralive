export function hammingDistance(a: string, b: string) {
  const length = Math.min(a.length, b.length);
  let distance = Math.abs(a.length - b.length);
  for (let index = 0; index < length; index += 1) {
    if (a[index] !== b[index]) distance += 1;
  }
  return distance;
}

export function normalizedHashDistance(a: string, b: string) {
  if (!a || !b) return 1;
  return hammingDistance(a, b) / Math.max(a.length, b.length);
}

export function computeAverageHash(source: HTMLVideoElement | HTMLCanvasElement, size = 16) {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return "";
  ctx.drawImage(source, 0, 0, size, size);
  const data = ctx.getImageData(0, 0, size, size).data;
  const grays: number[] = [];
  for (let index = 0; index < data.length; index += 4) {
    grays.push(data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114);
  }
  const average = grays.reduce((sum, value) => sum + value, 0) / grays.length;
  return grays.map((value) => (value >= average ? "1" : "0")).join("");
}


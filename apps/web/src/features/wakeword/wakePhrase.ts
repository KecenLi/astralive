export interface WakePhraseMatch {
  matched: boolean;
  requestText: string;
}

const XIAOQI_ALIASES = [
  "小七",
  "小7",
  "小柒",
  "小琪",
  "小奇",
  "小期",
  "晓七",
  "晓琪",
  "晓柒",
];

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function wakePatterns(wakeWord: string) {
  const aliases = new Set([wakeWord, ...XIAOQI_ALIASES]);
  return [...aliases]
    .filter(Boolean)
    .map((alias) => alias.split("").map(escapeRegExp).join("\\s*"))
    .map((pattern) => new RegExp(pattern, "i"));
}

function stripLeadingNoise(value: string) {
  return value.trim().replace(/^[，,。.!！?？、：:；;\s]+/, "");
}

export function extractWakeRequest(transcript: string, wakeWord: string): WakePhraseMatch {
  const normalized = transcript.trim();
  for (const pattern of wakePatterns(wakeWord)) {
    const match = pattern.exec(normalized);
    if (!match || match.index < 0) continue;
    const afterWake = normalized.slice(match.index + match[0].length);
    return { matched: true, requestText: stripLeadingNoise(afterWake) };
  }
  return { matched: false, requestText: "" };
}

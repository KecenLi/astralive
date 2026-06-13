export interface WakePhraseMatch {
  matched: boolean;
  requestText: string;
}

export function extractWakeRequest(transcript: string, wakeWord: string): WakePhraseMatch {
  const normalized = transcript.trim();
  const index = normalized.indexOf(wakeWord);
  if (index < 0) return { matched: false, requestText: "" };
  return {
    matched: true,
    requestText: normalized.slice(index + wakeWord.length).trim().replace(/^[，,。.\s]+/, ""),
  };
}

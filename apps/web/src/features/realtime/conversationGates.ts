export type SpeechInputTransition =
  | { type: "speech_start" }
  | { type: "audio_chunk"; isFinal: boolean; hasAudio: boolean }
  | { type: "audio_final" }
  | { type: "stop" }
  | { type: "cancel" }
  | { type: "error" };

export interface VisualAutoUploadGateState {
  realSpeechInputActive: boolean;
  conversationMode: boolean;
  liveAudioActive: boolean;
  voiceResponsePending: boolean;
  status: string;
}

export function nextRealSpeechInputActive(current: boolean, transition: SpeechInputTransition) {
  if (transition.type === "speech_start") return true;
  if (transition.type === "audio_chunk") {
    if (transition.isFinal) return false;
    return transition.hasAudio ? true : current;
  }
  return false;
}

export function shouldSuspendVisualAutoUpload(state: VisualAutoUploadGateState) {
  return state.realSpeechInputActive;
}

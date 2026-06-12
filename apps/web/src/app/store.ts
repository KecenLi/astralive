import { create } from "zustand";

import { AudioCapabilities, AvatarStatePayload, CostMeter, createId } from "../lib/events";

export interface ConversationMessage {
  id: string;
  speaker: "user" | "assistant" | "system";
  text: string;
}

export interface AppState {
  sessionId: string;
  connection: "idle" | "connecting" | "connected" | "error";
  status: string;
  wakeWord: string;
  wakeSerial: number;
  currentUserDraft: string;
  currentAssistantDraft: string;
  messages: ConversationMessage[];
  visualSummary: string;
  lastFrameInfo: string;
  avatar: AvatarStatePayload;
  cost: CostMeter;
  audioCapabilities: AudioCapabilities | null;
  setSession: (sessionId: string, wakeWord: string) => void;
  setConnection: (connection: AppState["connection"]) => void;
  setStatus: (status: string) => void;
  setAudioCapabilities: (audioCapabilities: AudioCapabilities) => void;
  markWake: () => void;
  setVisualSummary: (summary: string) => void;
  setLastFrameInfo: (info: string) => void;
  setAvatar: (payload: AvatarStatePayload) => void;
  setCost: (cost: CostMeter) => void;
  addMessage: (speaker: ConversationMessage["speaker"], text: string) => void;
  setUserSpeechDraft: (text: string) => void;
  finalizeUserSpeech: (text: string) => void;
  appendAssistantDelta: (delta: string) => void;
  finalizeAssistant: (text: string) => void;
}

const initialCost: CostMeter = {
  frames_uploaded: 0,
  bytes_uploaded: 0,
  vision_calls: 0,
  llm_calls: 0,
  asr_calls: 0,
  tts_calls: 0,
  estimated_input_tokens: 0,
  estimated_output_tokens: 0,
  estimated_cost_usd: 0,
  mode: "sleep",
  last_latency_ms: null,
};

export const useAppStore = create<AppState>((set) => ({
  sessionId: "",
  connection: "idle",
  status: "sleeping",
  wakeWord: "阿斯塔",
  wakeSerial: 0,
  currentUserDraft: "",
  currentAssistantDraft: "",
  messages: [],
  visualSummary: "",
  lastFrameInfo: "尚未上传",
  avatar: {
    mode: "sleeping",
    expression: "sleepy",
    motion: "idle",
    subtitle: "等待唤醒",
    lip_sync: false,
  },
  cost: initialCost,
  audioCapabilities: null,
  setSession: (sessionId, wakeWord) => set({ sessionId, wakeWord }),
  setConnection: (connection) => set({ connection }),
  setStatus: (status) => set({ status }),
  setAudioCapabilities: (audioCapabilities) => set({ audioCapabilities }),
  markWake: () => set((state) => ({ wakeSerial: state.wakeSerial + 1, status: "listening" })),
  setVisualSummary: (visualSummary) => set({ visualSummary }),
  setLastFrameInfo: (lastFrameInfo) => set({ lastFrameInfo }),
  setAvatar: (avatar) => set({ avatar, status: avatar.mode }),
  setCost: (cost) => set({ cost }),
  addMessage: (speaker, text) =>
    set((state) => ({
      messages: [...state.messages, { id: createId("msg"), speaker, text }],
    })),
  setUserSpeechDraft: (currentUserDraft) => set({ currentUserDraft }),
  finalizeUserSpeech: (text) =>
    set((state) => ({
      currentUserDraft: "",
      messages: text
        ? [...state.messages, { id: createId("msg"), speaker: "user", text }]
        : state.messages,
    })),
  appendAssistantDelta: (delta) =>
    set((state) => ({ currentAssistantDraft: state.currentAssistantDraft + delta })),
  finalizeAssistant: (text) =>
    set((state) => ({
      currentAssistantDraft: "",
      messages: [...state.messages, { id: createId("msg"), speaker: "assistant", text }],
    })),
}));

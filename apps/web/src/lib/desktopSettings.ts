export type AvatarLayoutMode = "main" | "pet";
export type VadProvider = "ten" | "silero" | "rms";
export type VoiceSendMode = "streaming_chunks" | "buffered_turn";
export type VoiceRoute = "asr_first" | "live_first";

export interface AvatarLayoutSettings {
  scale: number;
  offsetX: number;
  offsetY: number;
  maxHeightPx: number;
  widthFill: number;
  heightFill: number;
  yRatio: number;
}

export interface VoiceSettings {
  vadProvider: VadProvider;
  sendMode: VoiceSendMode;
  route: VoiceRoute;
  inputGain: number;
  tenThreshold: number;
  tenRmsFloor: number;
  tenDebounceOn: number;
  tenDebounceOff: number;
  sileroPositiveThreshold: number;
  sileroNegativeThreshold: number;
  silenceAfterSpeechMs: number;
  minSpeechMs: number;
  preRollMs: number;
  initialSilenceMs: number;
  maxTurnMs: number;
  echoCancellation: boolean;
  noiseSuppression: boolean;
  autoGainControl: boolean;
}

export interface ProactiveChatSettings {
  enabled: boolean;
  minIntervalMinutes: number;
  maxIntervalMinutes: number;
  petBubbleFirst: boolean;
}

export interface DesktopSettings {
  firstRunComplete?: boolean;
  autostartAsked?: boolean;
  autostartEnabled?: boolean;
  captureMode?: "low_fps" | "continuous";
  petEnabled?: boolean;
  avatarLayout: {
    main: AvatarLayoutSettings;
    pet: AvatarLayoutSettings;
  };
  voice: VoiceSettings;
  proactiveChat: ProactiveChatSettings;
}

export type DesktopSettingsPatch = Partial<
  Omit<DesktopSettings, "avatarLayout" | "voice" | "proactiveChat">
> & {
  avatarLayout?: {
    main?: Partial<AvatarLayoutSettings>;
    pet?: Partial<AvatarLayoutSettings>;
  };
  voice?: Partial<VoiceSettings>;
  proactiveChat?: Partial<ProactiveChatSettings>;
};

export const DEFAULT_AVATAR_LAYOUTS: Record<AvatarLayoutMode, AvatarLayoutSettings> = {
  main: {
    scale: 0.86,
    offsetX: 0,
    offsetY: 24,
    maxHeightPx: 760,
    widthFill: 0.7,
    heightFill: 0.88,
    yRatio: 0.54,
  },
  pet: {
    scale: 0.96,
    offsetX: 0,
    offsetY: 6,
    maxHeightPx: 470,
    widthFill: 0.92,
    heightFill: 0.98,
    yRatio: 0.54,
  },
};

export const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  vadProvider: "ten",
  sendMode: "streaming_chunks",
  route: "asr_first",
  inputGain: 1.15,
  tenThreshold: 0.58,
  tenRmsFloor: 0.0045,
  tenDebounceOn: 3,
  tenDebounceOff: 34,
  sileroPositiveThreshold: 0.32,
  sileroNegativeThreshold: 0.2,
  silenceAfterSpeechMs: 950,
  minSpeechMs: 280,
  preRollMs: 520,
  initialSilenceMs: 10000,
  maxTurnMs: 24000,
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

export const DEFAULT_PROACTIVE_CHAT: ProactiveChatSettings = {
  enabled: true,
  minIntervalMinutes: 6,
  maxIntervalMinutes: 15,
  petBubbleFirst: true,
};

export const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  firstRunComplete: false,
  autostartAsked: false,
  autostartEnabled: false,
  captureMode: "low_fps",
  petEnabled: true,
  avatarLayout: {
    main: DEFAULT_AVATAR_LAYOUTS.main,
    pet: DEFAULT_AVATAR_LAYOUTS.pet,
  },
  voice: DEFAULT_VOICE_SETTINGS,
  proactiveChat: DEFAULT_PROACTIVE_CHAT,
};

function numberValue(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function booleanValue(value: unknown, fallback: boolean) {
  return typeof value === "boolean" ? value : fallback;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function normalizeAvatarLayout(
  value: Partial<AvatarLayoutSettings> | undefined,
  mode: AvatarLayoutMode,
): AvatarLayoutSettings {
  const defaults = DEFAULT_AVATAR_LAYOUTS[mode];
  return {
    scale: clamp(numberValue(value?.scale, defaults.scale), 0.15, 2.25),
    offsetX: clamp(numberValue(value?.offsetX, defaults.offsetX), -900, 900),
    offsetY: clamp(numberValue(value?.offsetY, defaults.offsetY), -900, 900),
    maxHeightPx: clamp(numberValue(value?.maxHeightPx, defaults.maxHeightPx), 180, 1600),
    widthFill: clamp(numberValue(value?.widthFill, defaults.widthFill), 0.2, 1.25),
    heightFill: clamp(numberValue(value?.heightFill, defaults.heightFill), 0.2, 1.25),
    yRatio: clamp(numberValue(value?.yRatio, defaults.yRatio), 0.05, 0.95),
  };
}

export function normalizeVoiceSettings(value?: Partial<VoiceSettings>): VoiceSettings {
  const provider = value?.vadProvider;
  const sendMode = value?.sendMode;
  const route = value?.route;
  return {
    vadProvider: provider === "silero" || provider === "rms" || provider === "ten" ? provider : DEFAULT_VOICE_SETTINGS.vadProvider,
    sendMode: sendMode === "buffered_turn" || sendMode === "streaming_chunks" ? sendMode : DEFAULT_VOICE_SETTINGS.sendMode,
    route: route === "live_first" || route === "asr_first" ? route : DEFAULT_VOICE_SETTINGS.route,
    inputGain: clamp(numberValue(value?.inputGain, DEFAULT_VOICE_SETTINGS.inputGain), 0.2, 4),
    tenThreshold: clamp(numberValue(value?.tenThreshold, DEFAULT_VOICE_SETTINGS.tenThreshold), 0.05, 0.95),
    tenRmsFloor: clamp(numberValue(value?.tenRmsFloor, DEFAULT_VOICE_SETTINGS.tenRmsFloor), 0.0005, 0.05),
    tenDebounceOn: Math.round(clamp(numberValue(value?.tenDebounceOn, DEFAULT_VOICE_SETTINGS.tenDebounceOn), 1, 12)),
    tenDebounceOff: Math.round(clamp(numberValue(value?.tenDebounceOff, DEFAULT_VOICE_SETTINGS.tenDebounceOff), 8, 120)),
    sileroPositiveThreshold: clamp(
      numberValue(value?.sileroPositiveThreshold, DEFAULT_VOICE_SETTINGS.sileroPositiveThreshold),
      0.05,
      0.95,
    ),
    sileroNegativeThreshold: clamp(
      numberValue(value?.sileroNegativeThreshold, DEFAULT_VOICE_SETTINGS.sileroNegativeThreshold),
      0.01,
      0.9,
    ),
    silenceAfterSpeechMs: Math.round(clamp(numberValue(value?.silenceAfterSpeechMs, DEFAULT_VOICE_SETTINGS.silenceAfterSpeechMs), 250, 3000)),
    minSpeechMs: Math.round(clamp(numberValue(value?.minSpeechMs, DEFAULT_VOICE_SETTINGS.minSpeechMs), 120, 2000)),
    preRollMs: Math.round(clamp(numberValue(value?.preRollMs, DEFAULT_VOICE_SETTINGS.preRollMs), 0, 1600)),
    initialSilenceMs: Math.round(clamp(numberValue(value?.initialSilenceMs, DEFAULT_VOICE_SETTINGS.initialSilenceMs), 1500, 30000)),
    maxTurnMs: Math.round(clamp(numberValue(value?.maxTurnMs, DEFAULT_VOICE_SETTINGS.maxTurnMs), 5000, 60000)),
    echoCancellation: booleanValue(value?.echoCancellation, DEFAULT_VOICE_SETTINGS.echoCancellation),
    noiseSuppression: booleanValue(value?.noiseSuppression, DEFAULT_VOICE_SETTINGS.noiseSuppression),
    autoGainControl: booleanValue(value?.autoGainControl, DEFAULT_VOICE_SETTINGS.autoGainControl),
  };
}

export function normalizeProactiveChatSettings(
  value?: Partial<ProactiveChatSettings>,
): ProactiveChatSettings {
  const minIntervalMinutes = clamp(
    numberValue(value?.minIntervalMinutes, DEFAULT_PROACTIVE_CHAT.minIntervalMinutes),
    0.05,
    240,
  );
  const maxIntervalMinutes = clamp(
    numberValue(value?.maxIntervalMinutes, DEFAULT_PROACTIVE_CHAT.maxIntervalMinutes),
    minIntervalMinutes,
    480,
  );
  return {
    enabled: booleanValue(value?.enabled, DEFAULT_PROACTIVE_CHAT.enabled),
    minIntervalMinutes,
    maxIntervalMinutes,
    petBubbleFirst: booleanValue(value?.petBubbleFirst, DEFAULT_PROACTIVE_CHAT.petBubbleFirst),
  };
}

export function normalizeDesktopSettings(value?: DesktopSettingsPatch | null): DesktopSettings {
  return {
    ...DEFAULT_DESKTOP_SETTINGS,
    ...value,
    captureMode: value?.captureMode === "continuous" ? "continuous" : "low_fps",
    avatarLayout: {
      main: normalizeAvatarLayout(value?.avatarLayout?.main, "main"),
      pet: normalizeAvatarLayout(value?.avatarLayout?.pet, "pet"),
    },
    voice: normalizeVoiceSettings(value?.voice),
    proactiveChat: normalizeProactiveChatSettings(value?.proactiveChat),
  };
}

export function mergeDesktopSettings(
  current: Partial<DesktopSettings> | undefined,
  patch: DesktopSettingsPatch,
) {
  const base = normalizeDesktopSettings(current ?? {});
  return normalizeDesktopSettings({
    ...base,
    ...patch,
    avatarLayout: {
      main: { ...base.avatarLayout.main, ...patch.avatarLayout?.main },
      pet: { ...base.avatarLayout.pet, ...patch.avatarLayout?.pet },
    },
    voice: { ...base.voice, ...patch.voice },
    proactiveChat: { ...base.proactiveChat, ...patch.proactiveChat },
  });
}

import { Bot, MessageCircle, Mic, Monitor, SlidersHorizontal, X } from "lucide-react";

import { DesktopSettings, DesktopSettingsPatch, VoiceSettings } from "../../lib/desktopSettings";

interface SettingsPanelProps {
  open: boolean;
  settings: DesktopSettings;
  onClose: () => void;
  onPatch: (patch: DesktopSettingsPatch) => void;
}

function numberInput(
  value: number,
  onChange: (value: number) => void,
  options: { min: number; max: number; step: number },
) {
  return (
    <input
      type="number"
      min={options.min}
      max={options.max}
      step={options.step}
      value={Number(value.toFixed(options.step < 1 ? 2 : 0))}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}

function voicePatch<K extends keyof VoiceSettings>(key: K, value: VoiceSettings[K]) {
  return { voice: { [key]: value } } as DesktopSettingsPatch;
}

export function SettingsPanel({ open, settings, onClose, onPatch }: SettingsPanelProps) {
  if (!open) return null;

  const main = settings.avatarLayout.main;
  const pet = settings.avatarLayout.pet;
  const voice = settings.voice;
  const proactive = settings.proactiveChat;

  return (
    <div className="settings-overlay" role="dialog" aria-modal="true" aria-label="MODVII Settings">
      <section className="settings-window">
        <header className="settings-title">
          <span>
            <SlidersHorizontal size={18} />
            Settings
          </span>
          <button className="icon-button" type="button" title="关闭设置" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="settings-grid">
          <fieldset className="settings-group">
            <legend>
              <Monitor size={16} />
              Avatar
            </legend>
            <label>
              Scale
              {numberInput(main.scale, (scale) => onPatch({ avatarLayout: { main: { scale } } }), {
                min: 0.15,
                max: 2.25,
                step: 0.05,
              })}
            </label>
            <label>
              Offset X
              {numberInput(main.offsetX, (offsetX) => onPatch({ avatarLayout: { main: { offsetX } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              Offset Y
              {numberInput(main.offsetY, (offsetY) => onPatch({ avatarLayout: { main: { offsetY } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              Max H
              {numberInput(
                main.maxHeightPx,
                (maxHeightPx) => onPatch({ avatarLayout: { main: { maxHeightPx } } }),
                { min: 180, max: 1600, step: 10 },
              )}
            </label>
          </fieldset>

          <fieldset className="settings-group">
            <legend>
              <Bot size={16} />
              Pet
            </legend>
            <label>
              Scale
              {numberInput(pet.scale, (scale) => onPatch({ avatarLayout: { pet: { scale } } }), {
                min: 0.15,
                max: 2.25,
                step: 0.05,
              })}
            </label>
            <label>
              Offset X
              {numberInput(pet.offsetX, (offsetX) => onPatch({ avatarLayout: { pet: { offsetX } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              Offset Y
              {numberInput(pet.offsetY, (offsetY) => onPatch({ avatarLayout: { pet: { offsetY } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              Max H
              {numberInput(
                pet.maxHeightPx,
                (maxHeightPx) => onPatch({ avatarLayout: { pet: { maxHeightPx } } }),
                { min: 180, max: 1600, step: 10 },
              )}
            </label>
          </fieldset>

          <fieldset className="settings-group">
            <legend>
              <Mic size={16} />
              Voice
            </legend>
            <label>
              VAD
              <select
                value={voice.vadProvider}
                onChange={(event) => onPatch(voicePatch("vadProvider", event.target.value as VoiceSettings["vadProvider"]))}
              >
                <option value="ten">TEN</option>
                <option value="silero">Silero</option>
                <option value="rms">RMS</option>
              </select>
            </label>
            <label>
              Send
              <select
                value={voice.sendMode}
                onChange={(event) => onPatch(voicePatch("sendMode", event.target.value as VoiceSettings["sendMode"]))}
              >
                <option value="streaming_chunks">streaming</option>
                <option value="buffered_turn">buffered</option>
              </select>
            </label>
            <label>
              Route
              <select
                value={voice.route}
                onChange={(event) => onPatch(voicePatch("route", event.target.value as VoiceSettings["route"]))}
              >
                <option value="asr_first">ASR first</option>
                <option value="live_first">Live first</option>
              </select>
            </label>
            <label>
              Gain
              {numberInput(voice.inputGain, (inputGain) => onPatch(voicePatch("inputGain", inputGain)), {
                min: 0.2,
                max: 4,
                step: 0.05,
              })}
            </label>
            <label>
              Tail ms
              {numberInput(
                voice.silenceAfterSpeechMs,
                (silenceAfterSpeechMs) => onPatch(voicePatch("silenceAfterSpeechMs", silenceAfterSpeechMs)),
                { min: 250, max: 3000, step: 50 },
              )}
            </label>
            <label>
              Max ms
              {numberInput(voice.maxTurnMs, (maxTurnMs) => onPatch(voicePatch("maxTurnMs", maxTurnMs)), {
                min: 5000,
                max: 60000,
                step: 500,
              })}
            </label>
          </fieldset>

          <fieldset className="settings-group">
            <legend>
              <MessageCircle size={16} />
              Proactive
            </legend>
            <label className="check-row">
              <input
                type="checkbox"
                checked={proactive.enabled}
                onChange={(event) => onPatch({ proactiveChat: { enabled: event.target.checked } })}
              />
              Enabled
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={proactive.petBubbleFirst}
                onChange={(event) => onPatch({ proactiveChat: { petBubbleFirst: event.target.checked } })}
              />
              Pet first
            </label>
            <label>
              Min m
              {numberInput(
                proactive.minIntervalMinutes,
                (minIntervalMinutes) => onPatch({ proactiveChat: { minIntervalMinutes } }),
                { min: 0.05, max: 240, step: 0.5 },
              )}
            </label>
            <label>
              Max m
              {numberInput(
                proactive.maxIntervalMinutes,
                (maxIntervalMinutes) => onPatch({ proactiveChat: { maxIntervalMinutes } }),
                { min: 0.05, max: 480, step: 0.5 },
              )}
            </label>
          </fieldset>
        </div>
      </section>
    </div>
  );
}

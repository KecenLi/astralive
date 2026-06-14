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
    <div className="settings-overlay" role="dialog" aria-modal="true" aria-label="MODVII 设置">
      <section className="settings-window">
        <header className="settings-title">
          <span>
            <SlidersHorizontal size={18} />
            设置
          </span>
          <button className="icon-button" type="button" title="关闭设置" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="settings-grid">
          <fieldset className="settings-group">
            <legend>
              <Monitor size={16} />
              主界面立绘
            </legend>
            <label>
              缩放
              {numberInput(main.scale, (scale) => onPatch({ avatarLayout: { main: { scale } } }), {
                min: 0.15,
                max: 2.25,
                step: 0.05,
              })}
            </label>
            <label>
              横向偏移
              {numberInput(main.offsetX, (offsetX) => onPatch({ avatarLayout: { main: { offsetX } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              纵向偏移
              {numberInput(main.offsetY, (offsetY) => onPatch({ avatarLayout: { main: { offsetY } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              最大高度
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
              桌宠
            </legend>
            <label>
              缩放
              {numberInput(pet.scale, (scale) => onPatch({ avatarLayout: { pet: { scale } } }), {
                min: 0.15,
                max: 2.25,
                step: 0.05,
              })}
            </label>
            <label>
              横向偏移
              {numberInput(pet.offsetX, (offsetX) => onPatch({ avatarLayout: { pet: { offsetX } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              纵向偏移
              {numberInput(pet.offsetY, (offsetY) => onPatch({ avatarLayout: { pet: { offsetY } } }), {
                min: -900,
                max: 900,
                step: 5,
              })}
            </label>
            <label>
              最大高度
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
              语音
            </legend>
            <label>
              端点检测
              <select
                value={voice.vadProvider}
                onChange={(event) => onPatch(voicePatch("vadProvider", event.target.value as VoiceSettings["vadProvider"]))}
              >
                <option value="ten">TEN 神经端点</option>
                <option value="silero">Silero 备用端点</option>
                <option value="rms">RMS 音量门限</option>
              </select>
            </label>
            <label>
              发送模式
              <select
                value={voice.sendMode}
                onChange={(event) => onPatch(voicePatch("sendMode", event.target.value as VoiceSettings["sendMode"]))}
              >
                <option value="streaming_chunks">分块流式</option>
                <option value="buffered_turn">整句缓存</option>
              </select>
            </label>
            <label>
              路线
              <select
                value={voice.route}
                onChange={(event) => onPatch(voicePatch("route", event.target.value as VoiceSettings["route"]))}
              >
                <option value="asr_first">先本地识别</option>
                <option value="live_first">先实时通道</option>
              </select>
            </label>
            <label>
              输入增益
              {numberInput(voice.inputGain, (inputGain) => onPatch(voicePatch("inputGain", inputGain)), {
                min: 0.2,
                max: 4,
                step: 0.05,
              })}
            </label>
            <label>
              尾部静音（毫秒）
              {numberInput(
                voice.silenceAfterSpeechMs,
                (silenceAfterSpeechMs) => onPatch(voicePatch("silenceAfterSpeechMs", silenceAfterSpeechMs)),
                { min: 250, max: 3000, step: 50 },
              )}
            </label>
            <label>
              单轮最长（毫秒）
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
              主动聊天
            </legend>
            <label className="check-row">
              <input
                type="checkbox"
                checked={proactive.enabled}
                onChange={(event) => onPatch({ proactiveChat: { enabled: event.target.checked } })}
              />
              启用
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={proactive.petBubbleFirst}
                onChange={(event) => onPatch({ proactiveChat: { petBubbleFirst: event.target.checked } })}
              />
              先弹桌宠气泡
            </label>
            <label>
              最短间隔 分钟
              {numberInput(
                proactive.minIntervalMinutes,
                (minIntervalMinutes) => onPatch({ proactiveChat: { minIntervalMinutes } }),
                { min: 0.05, max: 240, step: 0.5 },
              )}
            </label>
            <label>
              最长间隔 分钟
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

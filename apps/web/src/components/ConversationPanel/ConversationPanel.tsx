import { MessageSquareText } from "lucide-react";

import { useAppStore } from "../../app/store";

const speakerLabel: Record<string, string> = {
  user: "你",
  assistant: "小七",
  system: "系统",
};

export function ConversationPanel() {
  const messages = useAppStore((state) => state.messages);
  const userDraft = useAppStore((state) => state.currentUserDraft);
  const draft = useAppStore((state) => state.currentAssistantDraft);
  const visualSummary = useAppStore((state) => state.visualSummary);
  const lastFrameInfo = useAppStore((state) => state.lastFrameInfo);
  const memoryTurns = useAppStore((state) => state.memoryTurns);
  const visualSelfCheckNotice = useAppStore((state) => state.visualSelfCheckNotice);
  const latestFocusMessage = useAppStore(
    (state) =>
      [...state.messages]
        .reverse()
        .find(
          (message) =>
            message.speaker === "system" &&
            (message.text.includes("更清晰") || message.text.toLowerCase().includes("focus")),
        )?.text ?? "",
  );
  const selfCheckNotice = visualSelfCheckNotice || latestFocusMessage || "视觉自检正常";

  return (
    <section className="conversation-panel" aria-label="对话">
      <div className="panel-title">
        <MessageSquareText size={18} />
        <span>对话</span>
        <small className="memory-badge">记忆 {memoryTurns} 轮</small>
      </div>
      <div className="conversation-observability" aria-label="对话状态">
        <span>
          <strong>记忆</strong> {memoryTurns} 轮
        </span>
        <span>
          <strong>自检</strong> {selfCheckNotice}
        </span>
        <span>
          <strong>画面</strong> {lastFrameInfo}
        </span>
      </div>
      <div className="visual-summary">
        <strong>视觉摘要</strong>
        <span>{visualSummary || "尚未看画面"}</span>
      </div>
      <div className="message-list">
        {messages.map((message) => (
          <article key={message.id} className={`message message-${message.speaker}`}>
            <span>{speakerLabel[message.speaker] ?? message.speaker}</span>
            <p>{message.text}</p>
          </article>
        ))}
        {userDraft && (
          <article className="message message-user">
            <span>你</span>
            <p>{userDraft}</p>
          </article>
        )}
        {draft && (
          <article className="message message-assistant">
            <span>小七</span>
            <p>{draft}</p>
          </article>
        )}
      </div>
    </section>
  );
}

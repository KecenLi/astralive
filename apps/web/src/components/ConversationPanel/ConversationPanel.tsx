import { MessageSquareText } from "lucide-react";

import { useAppStore } from "../../app/store";

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
    <section className="conversation-panel" aria-label="Conversation">
      <div className="panel-title">
        <MessageSquareText size={18} />
        <span>Conversation</span>
        <small className="memory-badge">memory {memoryTurns} turns</small>
      </div>
      <div className="conversation-observability" aria-label="Conversation observability">
        <span>
          <strong>Memory</strong> {memoryTurns} turns
        </span>
        <span>
          <strong>Self-check</strong> {selfCheckNotice}
        </span>
        <span>
          <strong>Frame</strong> {lastFrameInfo}
        </span>
      </div>
      <div className="visual-summary">
        <strong>视觉摘要</strong>
        <span>{visualSummary || "尚未看画面"}</span>
      </div>
      <div className="message-list">
        {messages.map((message) => (
          <article key={message.id} className={`message message-${message.speaker}`}>
            <span>{message.speaker}</span>
            <p>{message.text}</p>
          </article>
        ))}
        {userDraft && (
          <article className="message message-user">
            <span>user</span>
            <p>{userDraft}</p>
          </article>
        )}
        {draft && (
          <article className="message message-assistant">
            <span>assistant</span>
            <p>{draft}</p>
          </article>
        )}
      </div>
    </section>
  );
}

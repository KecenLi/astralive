import { MessageSquareText } from "lucide-react";

import { useAppStore } from "../../app/store";

export function ConversationPanel() {
  const messages = useAppStore((state) => state.messages);
  const userDraft = useAppStore((state) => state.currentUserDraft);
  const draft = useAppStore((state) => state.currentAssistantDraft);
  const visualSummary = useAppStore((state) => state.visualSummary);

  return (
    <section className="conversation-panel" aria-label="Conversation">
      <div className="panel-title">
        <MessageSquareText size={18} />
        <span>Conversation</span>
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

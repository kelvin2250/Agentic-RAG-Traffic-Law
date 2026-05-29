import React, { useEffect, useRef, useState } from 'react';
import MessageBubble from './MessageBubble';
import { ArrowDown } from 'lucide-react';
import styles from './ChatMessages.module.css';

const SUGGESTED_PROMPTS = [
  'Mức phạt nồng độ cồn xe máy là bao nhiêu?',
  'Lỗi vượt đèn đỏ phạt bao nhiêu tiền?',
  'Đi ngược chiều đường cao tốc bị phạt thế nào?',
  'Thủ tục sang tên đổi chủ xe máy gồm những gì?'
];

export default function ChatMessages({ messages, isStreaming, streamingText, streamingDocs, activeNode, thinkingSeconds, isLoading, onSuggestedPrompt }) {
  const containerRef = useRef(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const checkScrollPosition = () => {
    const el = containerRef.current;
    if (!el) return;
    const isAtBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 150;
    setShowScrollBtn(!isAtBottom);
  };

  const scrollToBottom = () => {
    const el = containerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  };

  // Tự động cuộn xuống khi có tin nhắn mới hoặc có chunk mới
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Luôn auto-scroll khi đang stream (người dùng có thể cuộn lên nhưng sẽ bị kéo xuống)
    if (isStreaming) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      return;
    }

    // Khi không stream, chỉ scroll nếu đang ở gần cuối
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 200;
    if (isNearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, streamingText, isStreaming]);

  return (
    <div className={styles.wrapper}>
      <div
        className={styles.container}
        ref={containerRef}
        onScroll={checkScrollPosition}
      >
        {isLoading && messages.length === 0 ? (
          <div className={styles.loadingContainer}>
            <div className={styles.skeletonBubble} />
            <div className={styles.skeletonBubble} />
            <div className={styles.skeletonBubbleShort} />
          </div>
        ) : messages.length === 0 && !isStreaming ? (
          <div className={styles.welcome}>
            <div className={styles.logo}>⚖️</div>
            <h1 className={styles.title}>Tôi có thể giúp gì cho bạn hôm nay?</h1>
            <p className={styles.subtitle}>
              Hỏi tôi về Luật giao thông Việt Nam, các nghị định xử phạt hoặc thủ tục hành chính.
            </p>

            <div className={styles.grid}>
              {SUGGESTED_PROMPTS.map((prompt, idx) => (
                <div key={idx} className={styles.card} onClick={() => onSuggestedPrompt?.(prompt)}>
                  <p className={styles.cardText}>{prompt}</p>
                  <span className={styles.cardIcon}>➔</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className={styles.messageList}>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}

            {isStreaming && (
              <MessageBubble
                message={{
                  role: 'assistant',
                  content: streamingText,
                  metadata_json: { retrieved_docs: streamingDocs }
                }}
                isStreaming={true}
                activeNode={activeNode}
                thinkingSeconds={thinkingSeconds}
              />
            )}
          </div>
        )}
      </div>

      {showScrollBtn && isStreaming && (
        <button className={styles.scrollBtn} onClick={scrollToBottom}>
          <ArrowDown size={14} /> AI đang trả lời...
        </button>
      )}
    </div>
  );
}

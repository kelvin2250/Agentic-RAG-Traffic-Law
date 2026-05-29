import React, { useState, useRef, useEffect } from 'react';
import { ArrowUp, Square } from 'lucide-react';
import styles from './ChatInput.module.css';

export default function ChatInput({ onSend, onStop, isStreaming }) {
  const [text, setText] = useState('');
  const textareaRef = useRef(null);

  // Auto resize textarea height
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [text]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (isStreaming) {
      onStop();
      return;
    }
    if (!text.trim()) return;
    onSend(text.trim());
    setText('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.inputWrapper}>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Hỏi về luật giao thông đường bộ..."
          rows={1}
          className={styles.textarea}
        />
        <button
          type="submit"
          className={`${styles.button} ${isStreaming ? styles.stopBtn : styles.sendBtn}`}
          disabled={!text.trim() && !isStreaming}
          title={isStreaming ? "Dừng trả lời" : "Gửi tin nhắn"}
        >
          {isStreaming ? (
            <Square size={16} fill="var(--text-primary)" stroke="var(--text-primary)" />
          ) : (
            <ArrowUp size={16} />
          )}
        </button>
      </div>
      <p className={styles.disclaimer}>
        Trợ lý ảo có thể đưa ra câu trả lời không chính xác, vui lòng đối chiếu lại với văn bản pháp luật chính thống.
      </p>
    </form>
  );
}

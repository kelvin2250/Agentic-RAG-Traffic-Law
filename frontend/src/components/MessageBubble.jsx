import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { BookOpen, ChevronDown, ChevronUp } from 'lucide-react';
import styles from './MessageBubble.module.css';

const NODE_LABELS = {
  orchestrator: 'Phân loại ý định & Phân rã câu hỏi',
  knowledge: 'Truy vấn cơ sở dữ liệu luật giao thông',
  analyst: 'Phân tích hành vi vi phạm',
  sanction: 'Trích xuất khung hình phạt & Mức phạt',
  validator: 'Kiểm định căn cứ pháp lý & Trích dẫn',
  synthesizer: 'Tổng hợp câu trả lời cuối cùng'
};

export default function MessageBubble({ message, isStreaming, activeNode, thinkingSeconds }) {
  const isUser = message.role === 'user';
  const docs = message.metadata_json?.retrieved_docs || [];
  const thinkingTime = message.metadata_json?.thinking_time;
  const [showSources, setShowSources] = useState(false);

  return (
    <div className={`${styles.bubbleWrapper} ${isUser ? styles.userAlign : styles.aiAlign}`}>
      <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.aiBubble}`}>
        {isUser ? (
          <p className={styles.text}>{message.content}</p>
        ) : (
          <div className={styles.markdownContent}>
            {/* Thinking Status Indicator during initial processing */}
            {isStreaming && !message.content && (
              <div className={styles.thinkingContainer}>
                <div className={styles.pulseDot}></div>
                <span className={styles.thinkingText}>
                  Đang suy nghĩ: <strong className={styles.nodeHighlight}>{NODE_LABELS[activeNode] || 'Đang xử lý'}</strong>... ({thinkingSeconds}s)
                </span>
              </div>
            )}

            {/* Render Final response or streaming response */}
            {message.content && (
              <>
                {isStreaming && (
                  <div className={styles.thinkingTimeBadge}>
                    ⏱️ Đang trả lời ({thinkingSeconds}s)
                  </div>
                )}
                {!isStreaming && thinkingTime && (
                  <div className={styles.thinkingTimeBadgeDone}>
                    ⏱️ Đã suy nghĩ trong {thinkingTime} giây
                  </div>
                )}
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </>
            )}

            {isStreaming && message.content && <span className={styles.cursor}>█</span>}
          </div>
        )}
      </div>

      {!isUser && docs.length > 0 && (
        <div className={styles.sourcesContainer}>
          <button 
            className={styles.sourcesToggle} 
            onClick={() => setShowSources(!showSources)}
          >
            <BookOpen size={14} />
            <span>Nguồn tham khảo ({docs.length})</span>
            {showSources ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          
          {showSources && (
            <div className={styles.sourcesList}>
              {docs.map((doc, idx) => {
                const title = doc.metadata?.title || doc.title || `Văn bản pháp luật #${idx + 1}`;
                const chunk = doc.page_content || doc.text || '';
                const score = doc.score ? `(Độ khớp: ${(doc.score * 100).toFixed(0)}%)` : '';
                
                return (
                  <div key={idx} className={styles.sourceCard}>
                    <div className={styles.sourceHeader}>
                      <span className={styles.sourceTitle}>📄 {title}</span>
                      {score && <span className={styles.scoreText}>{score}</span>}
                    </div>
                    {chunk && <p className={styles.sourceContent}>{chunk.slice(0, 300)}{chunk.length > 300 ? '...' : ''}</p>}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

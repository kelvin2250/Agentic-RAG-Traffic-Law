import React, { useState, useEffect, useRef, useCallback } from 'react';
import Sidebar from '../components/Sidebar';
import ChatMessages from '../components/ChatMessages';
import ChatInput from '../components/ChatInput';
import { chatService } from '../services/chat';
import { useToast } from '../components/Toast';
import styles from './ChatPage.module.css';

// Thời gian timeout streaming: 90 giây
const STREAM_TIMEOUT_MS = 90000;

export default function ChatPage() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [streamingDocs, setStreamingDocs] = useState([]);
  const [thinkingSeconds, setThinkingSeconds] = useState(0);
  const [activeNode, setActiveNode] = useState('');
  const [isLoadingSessions, setIsLoadingSessions] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);

  const abortControllerRef = useRef(null);
  const prevSessionIdRef = useRef(null);
  const thinkingTimerRef = useRef(null);
  const streamTimeoutRef = useRef(null);
  const toast = useToast();

  // Cleanup khi unmount
  useEffect(() => {
    return () => {
      if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
      if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);
    };
  }, []);

  // Load danh sách hội thoại
  useEffect(() => {
    loadSessions();
  }, []);

  // Load tin nhắn của session đang active
  useEffect(() => {
    if (activeSessionId) {
      const isSwitchingSessions = prevSessionIdRef.current && prevSessionIdRef.current !== activeSessionId;
      prevSessionIdRef.current = activeSessionId;

      if (isSwitchingSessions && abortControllerRef.current) {
        abortControllerRef.current.abort();
        setIsStreaming(false);
        if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
        if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);
      }
      loadMessages(activeSessionId);
    } else {
      prevSessionIdRef.current = null;
      setMessages([]);
    }
  }, [activeSessionId]);

  const loadSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const data = await chatService.getSessions();
      // Deduplicate sessions by ID
      const seen = new Set();
      const deduped = (Array.isArray(data) ? data : []).filter(s => {
        if (seen.has(s.id)) return false;
        seen.add(s.id);
        return true;
      });
      setSessions(deduped);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setIsLoadingSessions(false);
    }
  };

  const loadMessages = async (id) => {
    setIsLoadingMessages(true);
    try {
      const data = await chatService.getSessionDetail(id);
      setMessages(data.messages || []);
    } catch (err) {
      console.error('Failed to load messages:', err);
      toast.error('Không thể tải tin nhắn');
    } finally {
      setIsLoadingMessages(false);
    }
  };

  const handleSelectSession = (id) => {
    setActiveSessionId(id);
  };

  const handleCreateSession = async () => {
    try {
      const newSession = await chatService.createSession();
      setSessions(prev => {
        const seen = new Set(prev.map(s => s.id));
        if (seen.has(newSession.id)) return prev;
        return [newSession, ...prev];
      });
      setActiveSessionId(newSession.id);
    } catch (err) {
      console.error('Failed to create session:', err);
      toast.error('Không thể tạo cuộc trò chuyện mới');
    }
  };

  const handleDeleteSession = async (id, e) => {
    e.stopPropagation();
    try {
      await chatService.deleteSession(id);
      setSessions(prev => prev.filter(s => s.id !== id));
      if (activeSessionId === id) {
        setActiveSessionId(null);
      }
      toast.success('Đã xóa cuộc trò chuyện');
    } catch (err) {
      console.error('Failed to delete session:', err);
      toast.error('Không thể xóa cuộc trò chuyện');
    }
  };

  const handleSendMessage = useCallback(async (query) => {
    let currentSessionId = activeSessionId;

    if (!currentSessionId) {
      try {
        const newSession = await chatService.createSession(query.slice(0, 30));
        setSessions(prev => {
          const seen = new Set(prev.map(s => s.id));
          if (seen.has(newSession.id)) return prev;
          return [newSession, ...prev];
        });
        setActiveSessionId(newSession.id);
        currentSessionId = newSession.id;
      } catch (err) {
        toast.error('Không thể khởi tạo phiên chat');
        return;
      }
    }

    const userMsg = { id: Date.now().toString(), role: 'user', content: query };
    setMessages(prev => [...prev, userMsg]);

    // Reset stream state
    setIsStreaming(true);
    setStreamingText('');
    setStreamingDocs([]);
    setThinkingSeconds(0);
    setActiveNode('orchestrator');

    const startTimestamp = Date.now();
    if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
    thinkingTimerRef.current = setInterval(() => {
      setThinkingSeconds(((Date.now() - startTimestamp) / 1000).toFixed(1));
    }, 100);

    // Timeout safety: nếu stream kéo dài quá 90s, tự động hủy
    if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);
    streamTimeoutRef.current = setTimeout(() => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        toast.error('Yêu cầu quá thời gian chờ, vui lòng thử lại');
      }
    }, STREAM_TIMEOUT_MS + 10000); // +10s buffer so với backend timeout

    abortControllerRef.current = new AbortController();

    await chatService.sendMessage(query, currentSessionId, {
      onNodeUpdate: (nodeName) => {
        setActiveNode(nodeName);
      },
      onChunk: (chunkText, docs) => {
        if (chunkText) setStreamingText(chunkText);
        if (docs && docs.length > 0) setStreamingDocs(docs);
      },
      onDone: (finalData) => {
        setIsStreaming(false);
        if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
        if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);

        const finalDuration = ((Date.now() - startTimestamp) / 1000).toFixed(1);

        const aiMsg = {
          id: finalData.id || Date.now().toString(),
          role: 'assistant',
          content: finalData.final_response,
          metadata_json: {
            retrieved_docs: finalData.retrieved_docs,
            thinking_time: finalDuration
          }
        };
        setMessages(prev => [...prev, aiMsg]);
        setStreamingText('');
        setStreamingDocs([]);
        loadSessions();
      },
      onError: (err) => {
        setIsStreaming(false);
        if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
        if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);
        toast.error('Lỗi kết nối: ' + (err.message || 'Không thể kết nối đến máy chủ'));
      },
      onTimeout: (partialText) => {
        setIsStreaming(false);
        if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
        if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);
        if (partialText) {
          const partialMsg = {
            id: 'timeout-' + Date.now(),
            role: 'assistant',
            content: partialText + '\n\n*(Trả lời bị gián đoạn do quá thời gian chờ)*',
            metadata_json: { retrieved_docs: streamingDocs, thinking_time: thinkingSeconds }
          };
          setMessages(prev => [...prev, partialMsg]);
        }
        toast.error('Phản hồi quá thời gian chờ, vui lòng thử câu hỏi ngắn hơn');
        setStreamingText('');
        setStreamingDocs([]);
      },
      signal: abortControllerRef.current.signal
    });
  }, [activeSessionId, streamingDocs, thinkingSeconds, toast]);

  const handleStopStreaming = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      setIsStreaming(false);
      if (thinkingTimerRef.current) clearInterval(thinkingTimerRef.current);
      if (streamTimeoutRef.current) clearTimeout(streamTimeoutRef.current);

      if (streamingText) {
        const partialMsg = {
          id: 'partial-' + Date.now(),
          role: 'assistant',
          content: streamingText + '\n\n*(Đã dừng bởi người dùng)*',
          metadata_json: { retrieved_docs: streamingDocs, thinking_time: thinkingSeconds }
        };
        setMessages(prev => [...prev, partialMsg]);
      }
      setStreamingText('');
      setStreamingDocs([]);
    }
  }, [streamingText, streamingDocs, thinkingSeconds]);

  const handleSuggestedPrompt = useCallback((prompt) => {
    handleSendMessage(prompt);
  }, [handleSendMessage]);

  return (
    <div className={styles.container}>
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onCreateSession={handleCreateSession}
        onDeleteSession={handleDeleteSession}
        isLoading={isLoadingSessions}
      />
      <div className={styles.chatArea}>
        <ChatMessages
          messages={messages}
          isStreaming={isStreaming}
          streamingText={streamingText}
          streamingDocs={streamingDocs}
          activeNode={activeNode}
          thinkingSeconds={thinkingSeconds}
          isLoading={isLoadingMessages}
          onSuggestedPrompt={handleSuggestedPrompt}
        />
        <ChatInput
          onSend={handleSendMessage}
          onStop={handleStopStreaming}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  );
}

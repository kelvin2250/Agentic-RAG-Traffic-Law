import { apiFetch } from './api';

export const chatService = {
  async getSessions() {
    const res = await apiFetch('/api/v1/chat/sessions');
    return res.json();
  },

  async createSession(title = '') {
    const res = await apiFetch('/api/v1/chat/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    return res.json();
  },

  async getSessionDetail(sessionId) {
    const res = await apiFetch(`/api/v1/chat/sessions/${sessionId}`);
    return res.json();
  },

  async deleteSession(sessionId) {
    const res = await apiFetch(`/api/v1/chat/sessions/${sessionId}`, {
      method: 'DELETE',
    });
    return res.json();
  },

  async sendMessage(query, sessionId, { onNodeUpdate, onChunk, onDone, onError, signal, onTimeout }) {
    try {
      const res = await apiFetch('/api/v1/chat/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          session_id: sessionId,
          stream: true
        }),
        signal
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || 'Gửi yêu cầu thất bại');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let lastEventTime = Date.now();
      let partialText = '';

      // Kiểm tra timeout mỗi 5 giây, nếu 90s không có data → timeout
      const TIMEOUT_MS = 90000;
      const timeoutCheck = setInterval(() => {
        if (Date.now() - lastEventTime > TIMEOUT_MS) {
          reader.cancel();
          if (onTimeout) onTimeout(partialText);
        }
      }, 5000);

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          lastEventTime = Date.now();
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            if (trimmed.startsWith('event:')) {
              const eventType = trimmed.slice(6).trim();
              if (eventType === 'error') {
                // SSE error event from backend
                throw new Error('AI service error');
              }
              continue;
            }

            if (trimmed.startsWith('data:')) {
              const rawData = trimmed.slice(5).trim();
              try {
                const parsed = JSON.parse(rawData);

                // ═══ TOKEN STREAMING: từng token từ answer_generate ═══
                if (parsed.token) {
                  partialText += parsed.token;
                  onChunk(partialText, []);
                  continue;
                }

                if (parsed.final_response) {
                  clearInterval(timeoutCheck);
                  onDone(parsed);
                  return;
                }

                const keys = Object.keys(parsed);
                if (keys.length > 0) {
                  const nodeName = keys[0];
                  onNodeUpdate?.(nodeName);

                  const nodeData = parsed[nodeName];
                  if (nodeName === 'synthesizer' && nodeData.final_response) {
                    partialText = nodeData.final_response;
                    onChunk(nodeData.final_response, nodeData.retrieved_docs || []);
                  } else if (nodeData.retrieved_docs) {
                    onChunk('', nodeData.retrieved_docs);
                  }
                }
              } catch (e) {
                // Bỏ qua lỗi parse JSON dòng không hoàn chỉnh
              }
            }
          }
        }
      } finally {
        clearInterval(timeoutCheck);
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      onError(err);
    }
  }
};

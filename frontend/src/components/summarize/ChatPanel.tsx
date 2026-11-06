import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { MessageSquare, Send, Square, Trash2 } from 'lucide-react';
import * as api from '../../api/client';
import type { ChatMessage } from '../../types';

interface ChatPanelProps {
  /** Full source text the conversation is about. */
  sourceContent: string;
  /** Extra notices to show above the conversation (e.g. from extraction). */
  notices?: string[];
}

/** Collapsible "Chat about this" panel. Owns its own conversation state. */
export default function ChatPanel({ sourceContent, notices = [] }: ChatPanelProps) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [chatNotices, setChatNotices] = useState<string[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages]);

  // New source → new conversation; stop anything in flight on unmount.
  useEffect(() => {
    setMessages([]);
    setChatNotices([]);
    return () => abortRef.current?.abort();
  }, [sourceContent]);

  const setLastAssistant = (content: string) =>
    setMessages(prev => {
      const updated = [...prev];
      updated[updated.length - 1] = { role: 'assistant', content };
      return updated;
    });

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming || !sourceContent) return;

    const history: ChatMessage[] = [...messages, { role: 'user', content: trimmed }];
    setMessages([...history, { role: 'assistant', content: '' }]);
    setInput('');
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;
    let acc = '';
    await api.chat(sourceContent, history, {
      onChunk: chunk => { acc += chunk; setLastAssistant(acc); },
      onNotice: notice => setChatNotices(prev => (prev.includes(notice) ? prev : [...prev, notice])),
      onError: err => { setLastAssistant(`Error: ${err}`); setStreaming(false); },
      onDone: () => setStreaming(false),
    }, controller.signal);
    if (controller.signal.aborted) setStreaming(false);
  };

  const stop = () => abortRef.current?.abort();
  const allNotices = [...notices, ...chatNotices];

  return (
    <div className="summarize-chat-section">
      <button
        className={`summarize-chat-toggle${open ? ' active' : ''}`}
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <MessageSquare size={14} aria-hidden="true" />
        {open ? 'Hide chat' : 'Chat about this'}
      </button>

      {open && (
        <div className="summarize-chat-panel">
          {allNotices.length > 0 && (
            <div className="summarize-chat-notices">
              {allNotices.map((n, i) => <div key={i} className="summarize-chat-notice">{n}</div>)}
            </div>
          )}

          <div className="summarize-chat-messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="summarize-chat-empty">Ask a question about the content…</div>
            )}
            {messages.map((msg, i) => {
              const isLast = i === messages.length - 1;
              return (
                <div key={i} className={`summarize-chat-msg summarize-chat-msg--${msg.role}`}>
                  <div className="summarize-chat-msg-role">{msg.role === 'user' ? 'You' : 'AI'}</div>
                  <div className="summarize-chat-msg-content">
                    {!msg.content ? (
                      <span className="summarize-thinking-dot-row">
                        <span className="summarize-thinking-dot" />
                        <span className="summarize-thinking-dot" />
                        <span className="summarize-thinking-dot" />
                      </span>
                    ) : msg.role === 'assistant' && !(isLast && streaming) ? (
                      <div className="markdown"><ReactMarkdown>{msg.content}</ReactMarkdown></div>
                    ) : (
                      msg.content
                    )}
                    {isLast && msg.role === 'assistant' && streaming && msg.content && (
                      <span className="summarize-cursor" aria-hidden="true" />
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={endRef} />
          </div>

          <div className="summarize-chat-input-row">
            <textarea
              className="summarize-chat-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey && !streaming) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask a question… (Enter to send, Shift+Enter for newline)"
              rows={2}
              disabled={streaming}
              aria-label="Chat input"
            />
            {streaming ? (
              <button className="summarize-chat-send" onClick={stop} aria-label="Stop response">
                <Square size={14} aria-hidden="true" />
              </button>
            ) : (
              <button
                className="summarize-chat-send"
                onClick={send}
                disabled={!input.trim()}
                aria-label="Send message"
              >
                <Send size={15} aria-hidden="true" />
              </button>
            )}
          </div>

          {messages.length > 0 && (
            <button
              className="summarize-chat-clear"
              onClick={() => { setMessages([]); setChatNotices([]); }}
              disabled={streaming}
            >
              <Trash2 size={12} aria-hidden="true" />
              Clear history
            </button>
          )}
        </div>
      )}
    </div>
  );
}

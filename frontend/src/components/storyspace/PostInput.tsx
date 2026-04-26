import { useState, useRef } from 'react';

interface Props {
  onSend: (content: string) => Promise<void>;
  disabled?: boolean;
  channelType?: string;
}

export default function PostInput({ onSend, disabled = false, channelType }: Props) {
  const [content, setContent] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const placeholder =
    channelType === 'chat'
      ? 'Say something…'
      : channelType === 'planning'
      ? 'Add a note or idea…'
      : 'Write the next beat…';

  async function handleSend() {
    const trimmed = content.trim();
    if (!trimmed || sending || disabled) return;
    setSending(true);
    setError('');
    try {
      await onSend(trimmed);
      setContent('');
      textareaRef.current?.focus();
    } catch (err) {
      setError((err as Error).message || 'Could not send. Please try again.');
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  const canSend = content.trim().length > 0 && !sending && !disabled;

  return (
    <div className="px-3 py-3">
      {error && (
        <p className="text-xs text-red-400 mb-2 px-1">{error}</p>
      )}
      <div className="flex items-end gap-2 bg-gray-900 border border-gray-800 rounded-xl px-3 py-2 focus-within:border-gray-700 transition-colors">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => {
            setContent(e.target.value);
            // Auto-resize: reset then grow to content
            e.target.style.height = 'auto';
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
          }}
          onKeyDown={handleKeyDown}
          disabled={disabled || sending}
          placeholder={placeholder}
          rows={1}
          className="flex-1 bg-transparent text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none leading-relaxed min-h-[1.5rem] max-h-40 disabled:opacity-50"
          style={{ height: '1.5rem' }}
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={!canSend}
          aria-label="Send"
          className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center transition-colors disabled:opacity-30 disabled:cursor-not-allowed bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 2L11 13" />
            <path d="M22 2L15 22 11 13 2 9l20-7z" />
          </svg>
        </button>
      </div>
      <p className="text-[10px] text-gray-700 mt-1 px-1">
        Enter to send · Shift+Enter for new line
      </p>
    </div>
  );
}

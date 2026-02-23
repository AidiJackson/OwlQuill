import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';

const TITLE_KEY      = 'ficshon.workspace.title';
const BODY_KEY       = 'ficshon.workspace.body';
const PASTE_HINT_KEY = 'ficshon.workspace_paste_hint';

const MOCK_CHARACTERS = [
  { id: 0, name: 'No character' },
  { id: 1, name: 'Arleth Vane' },
  { id: 2, name: 'Seren Dusk' },
];

async function copyToClipboard(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // fall through to execCommand fallback
    }
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export default function Workspace() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [body, setBody]   = useState('');
  const [characterId, setCharacterId] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [saveTick, setSaveTick] = useState(0);
  const [mode, setMode] = useState<'write' | 'preview'>('write');
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [realms, setRealms] = useState<Realm[]>([]);
  const [selectedRealmId, setSelectedRealmId] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load saved draft on mount
  useEffect(() => {
    const savedTitle = localStorage.getItem(TITLE_KEY);
    const savedBody  = localStorage.getItem(BODY_KEY);
    if (savedTitle) setTitle(savedTitle);
    if (savedBody)  setBody(savedBody);
  }, []);

  // Debounced autosave
  useEffect(() => {
    setIsSaving(true);
    const t = setTimeout(() => {
      localStorage.setItem(TITLE_KEY, title);
      localStorage.setItem(BODY_KEY, body);
      setIsSaving(false);
      setLastSavedAt(Date.now());
    }, 500);
    return () => clearTimeout(t);
  }, [title, body]);

  useEffect(() => {
    if (!lastSavedAt) return;
    const i = setInterval(() => {
      setSaveTick((t) => t + 1);
    }, 10000);
    return () => clearInterval(i);
  }, [lastSavedAt]);

  // Load non-commons realms for the destination selector
  useEffect(() => {
    apiClient.getRealms()
      .then((all) => setRealms(all.filter((r) => !r.is_commons)))
      .catch(() => { /* non-fatal: selector stays empty */ });
  }, []);

  const handlePublishToCommons = async () => {
    if (!body.trim()) return;
    setPublishing(true);
    setPublishError('');
    try {
      let realmId: number;

      if (selectedRealmId !== null) {
        realmId = selectedRealmId;
      } else {
        const all = await apiClient.getRealms();
        const commons = all.find((r) => r.is_commons);
        if (!commons) {
          setPublishError('Post failed. Try again.');
          return;
        }
        realmId = commons.id;
      }

      // Capture destination before any state mutations
      const destination = selectedRealmId !== null
        ? `/realms/${selectedRealmId}`
        : '/';

      await apiClient.createPost(realmId, {
        content: body.trim(),
        content_type: 'ic',
        ...(title.trim() ? { title: title.trim() } : {}),
      });

      setTitle('');
      setBody('');
      localStorage.removeItem(TITLE_KEY);
      localStorage.removeItem(BODY_KEY);
      navigate(destination);
    } catch {
      setPublishError('Post failed. Try again.');
    } finally {
      setPublishing(false);
    }
  };

  // Wrap selection with before/after markers (Bold, Italic)
  function insertAroundSelection(before: string, after = before) {
    const el = textareaRef.current;
    if (!el) return;

    const start = el.selectionStart;
    const end   = el.selectionEnd;

    const newText =
      body.slice(0, start) +
      before +
      body.slice(start, end) +
      after +
      body.slice(end);

    setBody(newText);

    setTimeout(() => {
      el.focus();
      el.setSelectionRange(start + before.length, end + before.length);
    }, 0);
  }

  // Prefix each selected line (or current line) with "## "
  function insertHeaderPrefix() {
    const el = textareaRef.current;
    if (!el) return;

    const start  = el.selectionStart;
    const end    = el.selectionEnd;
    const prefix = '## ';

    if (start === end) {
      // No selection: prefix the line the cursor is on
      const lineStart = body.lastIndexOf('\n', start - 1) + 1;
      const newText   = body.slice(0, lineStart) + prefix + body.slice(lineStart);
      setBody(newText);
      setTimeout(() => {
        el.focus();
        el.setSelectionRange(start + prefix.length, start + prefix.length);
      }, 0);
    } else {
      // Selection: prefix every line in the selected range
      const selected  = body.slice(start, end);
      const prefixed  = selected.split('\n').map((line) => prefix + line).join('\n');
      const newText   = body.slice(0, start) + prefixed + body.slice(end);
      setBody(newText);
      setTimeout(() => {
        el.focus();
        el.setSelectionRange(start, start + prefixed.length);
      }, 0);
    }
  }

  function renderPreview(text: string) {
    if (!text.trim()) {
      return (
        <p className="text-gray-500 text-sm">Nothing to preview yet.</p>
      );
    }

    // Escape HTML first for safety
    let html = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Scene breaks
    html = html.replace(/^---$/gm, '<hr class="border-gray-700 my-6" />');

    // Headers
    html = html.replace(/^## (.*)$/gm, '<h2 class="text-xl font-semibold mt-6 mb-2">$1</h2>');

    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Split into paragraphs on blank lines
    const paragraphs = html
      .split(/\n{2,}/)
      .map((p) => p.trim())
      .filter(Boolean);

    if (!paragraphs.length) {
      return <span className="text-gray-500">Nothing to preview yet.</span>;
    }

    // Single newlines within a paragraph become <br/>; wrap each block in <p>
    html = paragraphs
      .map((p) => `<p>${p.replace(/\n/g, '<br/>')}</p>`)
      .join('');

    return (
      <div
        className="prose prose-invert max-w-none leading-relaxed"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  function getSaveLabel() {
    void saveTick;
    if (isSaving) return 'Saving\u2026';
    if (!lastSavedAt) return 'Draft saved locally';
    const diff = Math.floor((Date.now() - lastSavedAt) / 1000);
    if (diff < 5) return 'Saved just now';
    if (diff < 60) return `Saved ${diff}s ago`;
    const mins = Math.floor(diff / 60);
    return `Saved ${mins}m ago`;
  }

  const selectedRealmName = selectedRealmId !== null
    ? realms.find((r) => r.id === selectedRealmId)?.name
    : null;

  return (
    <div className="w-full h-[calc(100vh-24px)] p-6 flex flex-col">
      {/* A) Header bar */}
      <div className="flex items-center gap-4 mb-4 flex-shrink-0">
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Untitled story"
          className="flex-1 bg-transparent text-lg font-bold text-gray-100 placeholder-gray-600 focus:outline-none"
        />
        <select
          value={characterId}
          onChange={(e) => setCharacterId(Number(e.target.value))}
          className="input text-sm"
        >
          {MOCK_CHARACTERS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={selectedRealmId ?? ''}
          onChange={(e) =>
            setSelectedRealmId(e.target.value ? Number(e.target.value) : null)
          }
          className="input text-sm"
        >
          <option value="">Publish to Commons</option>
          {realms.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <p className="text-xs text-gray-500">
          {getSaveLabel()}
        </p>
      </div>

      {/* B) Editor + C) Sidebar */}
      <div className="flex gap-6 flex-1 min-h-0">
        {/* B) Editor column: toolbar + textarea */}
        <div className="flex-1 min-w-0 flex flex-col">
          {/* Write / Preview toggle */}
          <div className="flex items-center gap-2 mb-2 flex-shrink-0">
            <button
              type="button"
              onClick={() => setMode('write')}
              className={`px-3 py-1 rounded-md text-sm ${
                mode === 'write'
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Write
            </button>
            <button
              type="button"
              onClick={() => setMode('preview')}
              className={`px-3 py-1 rounded-md text-sm ${
                mode === 'preview'
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Preview
            </button>
          </div>

          {/* Formatting toolbar */}
          <div className="flex flex-wrap gap-2 mb-2 flex-shrink-0">
            <button
              type="button"
              onClick={() => insertAroundSelection('**')}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Bold
            </button>
            <button
              type="button"
              onClick={() => insertAroundSelection('*', '*')}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Italic
            </button>
            <button
              type="button"
              onClick={insertHeaderPrefix}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Header
            </button>
            <button
              type="button"
              onClick={() => setBody((prev) => prev + '\n\n---\n\n')}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Scene break
            </button>
          </div>
          <p className="text-xs text-gray-500 mb-3 flex-shrink-0">Formatting inserts Markdown.</p>

          {mode === 'write' ? (
            <textarea
              ref={textareaRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Start writing..."
              className="flex-1 min-h-0 bg-gray-900 border border-gray-800 rounded-xl p-4 leading-relaxed resize-none outline-none text-gray-200 placeholder-gray-600 focus:border-gray-700"
            />
          ) : (
            <div className="flex-1 min-h-0 bg-gray-900 border border-gray-800 rounded-xl p-4 overflow-y-auto text-gray-200">
              <div className="text-gray-300 text-base leading-relaxed space-y-3">
                {renderPreview(body)}
              </div>
            </div>
          )}
        </div>

        {/* C) Right sidebar */}
        <aside className="w-[340px] shrink-0 space-y-3 overflow-y-auto">
          {/* Publish context */}
          <div className="text-xs text-gray-500 space-y-1 border-b border-gray-800 pb-3">
            <div>
              <span>Posting to: </span>
              <span className="text-gray-300">
                {selectedRealmName ?? 'Commons'}
              </span>
            </div>
            <div>
              <span>Posting as: </span>
              <span className="text-gray-300">
                {characterId !== 0
                  ? MOCK_CHARACTERS.find((c) => c.id === characterId)?.name
                  : 'No character selected'}
              </span>
            </div>
          </div>

          <button
            onClick={handlePublishToCommons}
            disabled={publishing || !body.trim()}
            className="btn btn-primary w-full"
          >
            {publishing
              ? 'Publishing\u2026'
              : selectedRealmId === null
                ? 'Publish to Commons'
                : 'Publish to Realm'}
          </button>
          {publishError && (
            <p className="text-xs text-red-400">{publishError}</p>
          )}
          <button className="btn btn-secondary w-full">
            Download text
          </button>

          <div className="border-t border-gray-800 pt-3 space-y-2">
            <button
              type="button"
              onClick={async () => {
                if (!body.trim()) {
                  setCopyStatus('failed');
                  return;
                }
                const ok = await copyToClipboard(body);
                setCopyStatus(ok ? 'copied' : 'failed');
              }}
              className="btn btn-secondary w-full"
            >
              Copy for posting
            </button>
            <button
              type="button"
              onClick={() => {
                localStorage.setItem(PASTE_HINT_KEY, 'true');
                navigate('/');
              }}
              className="btn btn-secondary w-full"
            >
              Go to Home &amp; paste
            </button>
            {copyStatus === 'copied' && (
              <p className="text-xs text-gray-400">Copied.</p>
            )}
            {copyStatus === 'failed' && (
              <p className="text-xs text-gray-500">
                {body.trim()
                  ? 'Copy failed \u2014 select text and copy manually.'
                  : 'Nothing to copy yet.'}
              </p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

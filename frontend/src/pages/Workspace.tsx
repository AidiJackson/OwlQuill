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
  // execCommand fallback for older browsers / non-https contexts
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

  // Debounced autosave — marks saving on change, clears flag after write
  useEffect(() => {
    setIsSaving(true);
    const t = setTimeout(() => {
      localStorage.setItem(TITLE_KEY, title);
      localStorage.setItem(BODY_KEY, body);
      setIsSaving(false);
    }, 500);
    return () => clearTimeout(t);
  }, [title, body]);

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

      // Clear draft on success
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

    // Restore cursor/selection after React commits the new value
    setTimeout(() => {
      el.focus();
      el.setSelectionRange(
        start + before.length,
        end   + before.length,
      );
    }, 0);
  }

  const selectedRealmName = selectedRealmId !== null
    ? realms.find((r) => r.id === selectedRealmId)?.name
    : null;

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* A) Header bar */}
      <div className="flex items-center gap-4 mb-6">
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
        <span className="text-xs text-gray-500 whitespace-nowrap flex-shrink-0">
          {isSaving ? 'Saving\u2026' : 'Draft saved locally'}
        </span>
      </div>

      {/* B) Editor + C) Sidebar */}
      <div className="flex gap-6 items-start">
        {/* B) Editor column: toolbar + textarea */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Formatting toolbar */}
          <div className="flex flex-wrap gap-2 mb-3">
            <button
              type="button"
              onClick={() => insertAroundSelection('**')}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Bold
            </button>
            <button
              type="button"
              onClick={() => insertAroundSelection('*')}
              className="px-3 py-1 text-sm rounded-md border border-gray-700 hover:bg-gray-800"
            >
              Italic
            </button>
            <button
              type="button"
              onClick={() => insertAroundSelection('## ')}
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

          <textarea
            ref={textareaRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Start writing your story..."
            className="w-full bg-gray-900 border border-gray-800 rounded-xl px-4 py-4 text-base leading-relaxed resize-none min-h-[400px] text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-700"
          />
        </div>

        {/* C) Right sidebar panel */}
        <div className="w-[280px] flex-shrink-0 space-y-3">
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
        </div>
      </div>
    </div>
  );
}

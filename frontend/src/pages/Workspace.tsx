import { useState, useEffect, useRef } from 'react';

const TITLE_KEY = 'ficshon.workspace.title';
const BODY_KEY  = 'ficshon.workspace.body';

const MOCK_CHARACTERS = [
  { id: 0, name: 'No character' },
  { id: 1, name: 'Arleth Vane' },
  { id: 2, name: 'Seren Dusk' },
];

export default function Workspace() {
  const [title, setTitle] = useState('');
  const [body, setBody]   = useState('');
  const [characterId, setCharacterId] = useState(0);
  const [isSaving, setIsSaving] = useState(false);
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
          <button className="btn btn-primary w-full">
            Publish to Commons
          </button>
          <button className="btn btn-secondary w-full">
            Publish to Realm
          </button>
          <button className="btn btn-secondary w-full">
            Download text
          </button>
        </div>
      </div>
    </div>
  );
}

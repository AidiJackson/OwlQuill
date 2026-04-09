import { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';

const TITLE_KEY      = 'ficshon.workspace.title';
const BODY_KEY       = 'ficshon.workspace.body';
const PASTE_HINT_KEY = 'ficshon.workspace_paste_hint';
const MODE_KEY       = 'ficshon.writespace.mode';
const REALM_KEY      = 'ficshon.writespace.selected_realm_id';
const CHARACTER_KEY  = 'ficshon.writespace.selected_character_id';
const SURFACE_KEY    = 'fic_surface_mode';

const EDITOR_TEXT    = 'text-[16px] md:text-[17px] lg:text-[18px]';
const EDITOR_LEADING = 'leading-[1.75]';
const EDITOR_FONT    = 'font-normal';
const EDITOR_TRACKING = 'tracking-[0.01em]';
const PAPER        = 'bg-gray-900/60 border border-gray-800/70 ring-1 ring-black/10 shadow-[0_8px_30px_rgba(0,0,0,0.25)]';
const PAPER_LIGHT  = 'bg-[#F5F0E8] border border-[#A09382]/30 shadow-[0_4px_16px_rgba(0,0,0,0.06)]';
const TOOLBTN      = 'h-9 px-3 text-sm rounded-lg bg-gray-900/30 border border-gray-800/70 text-gray-200 hover:bg-gray-800/40 hover:border-gray-700 transition';

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

// ── Local analysis helpers (pure, no React) ──────────────────────────────────

function normalizeText(text: string): string {
  return text.replace(/\r\n/g, '\n').replace(/ +$/gm, '');
}

function getParagraphs(text: string): string[] {
  return text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
}

function getSentences(text: string): string[] {
  const flat = text.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
  return flat
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 2);
}

function countWords(text: string): number {
  return text.match(/[A-Za-z0-9\u2019']+/g)?.length ?? 0;
}

function estimateSyllables(word: string): number {
  const w = word.toLowerCase().replace(/[^a-z]/g, '');
  const groups = w.match(/[aeiouy]+/g);
  let count = groups?.length ?? 0;
  if (w.endsWith('e') && count > 1) count -= 1;
  return Math.max(1, count);
}

function fleschReadingEase(text: string): number | null {
  const words = text.match(/[A-Za-z0-9\u2019']+/g) ?? [];
  const sentences = getSentences(text);
  if (words.length < 20 || sentences.length < 1) return null;
  const syllables = words.reduce((sum, w) => sum + estimateSyllables(w), 0);
  return 206.835 - 1.015 * (words.length / sentences.length) - 84.6 * (syllables / words.length);
}

function detectPassiveSentences(sentences: string[]): number {
  return sentences.filter((s) =>
    /\b(am|is|are|was|were|be|been|being)\b\s+\w+(ed|en)\b/i.test(s)
  ).length;
}

function splitLongSentence(text: string, sentence: string): string {
  const idx = text.indexOf(sentence);
  if (idx === -1) return text;
  const mid = Math.floor(sentence.length / 2);
  const breakpoints = ['. ', '; ', ', and ', ', but ', ' \u2014 ', ' - '];
  for (const bp of breakpoints) {
    let bestPos = -1, bestDist = Infinity, search = 0;
    while (search < sentence.length) {
      const found = sentence.indexOf(bp, search);
      if (found === -1) break;
      const splitAt = found + bp.length;
      const dist = Math.abs(splitAt - mid);
      if (dist < bestDist) { bestDist = dist; bestPos = splitAt; }
      search = found + 1;
    }
    if (bestPos !== -1) {
      const before = sentence.slice(0, bestPos).trimEnd();
      const after  = sentence.slice(bestPos).trimStart();
      return text.slice(0, idx) + before + '\n\n' + after + text.slice(idx + sentence.length);
    }
  }
  return text;
}

function breakUpParagraph(text: string, paragraph: string): string {
  const idx = text.indexOf(paragraph);
  if (idx === -1) return text;
  const sentences = getSentences(paragraph);
  if (sentences.length < 2) return text;
  const chunks: string[] = [];
  let current = '';
  for (const s of sentences) {
    const candidate = current ? current + ' ' + s : s;
    if (current && candidate.length > 400) { chunks.push(current); current = s; }
    else { current = candidate; }
  }
  if (current) chunks.push(current);
  if (chunks.length < 2) return text;
  return text.slice(0, idx) + chunks.join('\n\n') + text.slice(idx + paragraph.length);
}

function buildActiveSuggestion(sentence: string): string {
  const snippet = sentence.length > 100 ? sentence.slice(0, 100) + '\u2026' : sentence;
  return `Suggestion: Try rewriting in active voice. Example pattern: [Actor] [verb] [object].\n\nOriginal: "${snippet}"`;
}

function normKey(s: string): string {
  return (s || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[""]/g, '"')
    .replace(/['']/g, "'")
    .trim();
}

// Grammar Engine v1 — deterministic, client-side, zero dependencies

/** Safe HTML escaper — always escape raw text before inserting into dangerouslySetInnerHTML. */
function escHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/** Stop words excluded from high-frequency repeat detection. */
const STOP_WORDS = new Set([
  'the','a','an','and','or','but','in','on','at','to','for','of','with','by','from',
  'is','was','are','were','be','been','being','have','has','had','do','does','did',
  'will','would','could','should','may','might','shall','can','it','its','this','that',
  'these','those','i','he','she','we','they','you','me','him','her','us','them',
  'my','his','our','their','your','what','which','who','how','when','where','why',
  'as','if','so','not','no','up','out','into','then','than','there','here','some',
  'any','all','each','every','more','most','one','two','three','also','even','still',
  'now','after','before','about','over','both','few','many','much','such','other',
]);

/** Adjacent repeated word detection: finds "the the", "a a" etc. within sentences. */
function detectAdjacentRepeats(sentences: string[]): { word: string; sentence: string }[] {
  const results: { word: string; sentence: string }[] = [];
  for (const s of sentences) {
    const tokens = s.match(/\b\w+\b/g) ?? [];
    for (let i = 0; i < tokens.length - 1; i++) {
      if (tokens[i].length >= 2 && tokens[i].toLowerCase() === tokens[i + 1].toLowerCase()) {
        results.push({ word: tokens[i].toLowerCase(), sentence: s });
        break; // one hit per sentence
      }
    }
  }
  return results;
}

/** High-frequency repeated word: same significant word 3+ times in one sentence. */
function detectHighFreqRepeats(sentences: string[]): { word: string; sentence: string }[] {
  const results: { word: string; sentence: string }[] = [];
  for (const s of sentences) {
    const tokens = s.toLowerCase().match(/\b[a-z]{4,}\b/g) ?? [];
    const freq: Record<string, number> = {};
    for (const w of tokens) { if (!STOP_WORDS.has(w)) freq[w] = (freq[w] ?? 0) + 1; }
    const hit = Object.entries(freq).find(([, n]) => n >= 3);
    if (hit) results.push({ word: hit[0], sentence: s });
  }
  return results;
}

/** Human-readable category label for a suggestion id. */
function suggestionLabel(id: string): string {
  if (id === 'long-sent' || id === 'very-long-sent') return 'Long sentence';
  if (id === 'passive') return 'Passive voice';
  if (id === 'long-para' || id === 'one-para') return 'Long paragraph';
  if (id === 'repeat-adj') return 'Duplicate word';
  if (id === 'repeat-word') return 'Repeated word';
  if (id === 'filler') return 'Weak phrase';
  if (id === 'dense') return 'Readability';
  if (id === 'easy') return 'Readability';
  return '';
}

/** Weak/filler phrase detection across all sentences. Returns first hit + total count. */
const FILLER_MULTI = [
  'started to', 'began to', 'seemed to', 'appeared to',
  'was able to', 'were able to', 'kind of', 'sort of',
  'in order to', 'the fact that', 'due to the fact that',
];
const FILLER_SINGLE = ['very', 'really', 'basically', 'literally', 'actually', 'quite'];

function detectFillerPhrases(
  sentences: string[]
): { phrase: string; sentence: string; count: number } | null {
  let total = 0;
  let first: { phrase: string; sentence: string } | null = null;
  for (const s of sentences) {
    for (const phrase of FILLER_MULTI) {
      const re = new RegExp(`\\b${phrase.replace(/\s+/g, '\\s+')}\\b`, 'i');
      if (re.test(s)) { total++; if (!first) first = { phrase, sentence: s }; }
    }
    for (const word of FILLER_SINGLE) {
      const re = new RegExp(`\\b${word}\\b`, 'i');
      if (re.test(s)) { total++; if (!first) first = { phrase: word, sentence: s }; }
    }
  }
  return first && total >= 2 ? { ...first, count: total } : null;
}

/**
 * Apply inline Write-mode marks to a raw sentence string.
 * Returns an HTML string with zero or more <span class="ws-repeat|ws-filler"> wrappers.
 * Marks are non-overlapping; first match wins on conflict.
 * baseOffset — character position of `raw` within the full body string (used for quick-fix offsets).
 */
function markInlineSentence(raw: string, baseOffset = 0): string {
  type Mark = { start: number; end: number; cls: string; count?: number };
  const marks: Mark[] = [];
  let m: RegExpExecArray | null;

  // Adjacent duplicate words — "the the", "had had", etc.
  const adjRe = /\b(\w{2,})\s+\1\b/gi;
  while ((m = adjRe.exec(raw)) !== null) {
    marks.push({ start: m.index, end: m.index + m[0].length, cls: 'ws-repeat' });
  }

  // Multi-word filler phrases
  for (const phrase of FILLER_MULTI) {
    const re = new RegExp(`\\b${phrase.replace(/\s+/g, '\\s+')}\\b`, 'gi');
    while ((m = re.exec(raw)) !== null) {
      marks.push({ start: m.index, end: m.index + m[0].length, cls: 'ws-filler' });
    }
  }

  // Single-word fillers (mark all in Write mode — instant feedback even for one instance)
  for (const word of FILLER_SINGLE) {
    const re = new RegExp(`\\b${word}\\b`, 'gi');
    while ((m = re.exec(raw)) !== null) {
      marks.push({ start: m.index, end: m.index + m[0].length, cls: 'ws-filler' });
    }
  }

  // High-frequency word overuse: same significant word appears 3+ times in sentence
  {
    const tokens = raw.toLowerCase().match(/\b[a-z]{4,}\b/g) ?? [];
    const freq: Record<string, number> = {};
    for (const w of tokens) { if (!STOP_WORDS.has(w)) freq[w] = (freq[w] ?? 0) + 1; }
    for (const [word, count] of Object.entries(freq)) {
      if (count < 3) continue;
      const wordRe = new RegExp(`\\b${word}\\b`, 'gi');
      while ((m = wordRe.exec(raw)) !== null) {
        marks.push({ start: m.index, end: m.index + m[0].length, cls: 'ws-overuse', count });
      }
    }
  }

  if (marks.length === 0) return escHtml(raw);

  // Sort by start; resolve overlaps (first/adjacent wins)
  marks.sort((a, b) => a.start - b.start);
  const resolved: Mark[] = [];
  let cursor = 0;
  for (const mark of marks) {
    if (mark.start >= cursor) { resolved.push(mark); cursor = mark.end; }
  }

  // Interleave plain escaped text with marked spans
  const parts: string[] = [];
  let pos = 0;
  for (const mark of resolved) {
    if (mark.start > pos) parts.push(escHtml(raw.slice(pos, mark.start)));
    const matchedText = raw.slice(mark.start, mark.end);
    const bodyOffset   = baseOffset + mark.start;
    const markLength   = mark.end - mark.start;

    // Determine label, hint, and whether this mark is auto-fixable
    let label: string, hint: string, fixType: string | null = null;
    if (mark.cls === 'ws-repeat') {
      label   = 'Duplicate word';
      hint    = 'This word appears twice in a row — likely a typo. Click to fix.';
      fixType = 'remove-dup';
    } else if (mark.cls === 'ws-overuse') {
      label   = 'Word overuse';
      hint    = `"${matchedText}" appears ${mark.count ?? 'several'} times in this sentence — consider varying your word choice.`;
      fixType = null; // explanation only; no safe auto-removal
    } else {
      // ws-filler: single words are safely removable; multi-word phrases are not
      const isSingleWord = FILLER_SINGLE.some(
        (w) => w.toLowerCase() === matchedText.trim().toLowerCase()
      );
      label   = 'Weak phrase';
      if (isSingleWord) {
        hint    = 'This word may weaken the sentence. Click to remove it.';
        fixType = 'remove-word';
      } else {
        hint    = 'This phrase may weaken the sentence. Consider rewriting.';
        fixType = null; // multi-word phrases need manual rewrite
      }
    }

    const fixAttrs = fixType
      ? ` data-ws-fix-type="${fixType}" data-ws-offset="${bodyOffset}" data-ws-length="${markLength}"`
      : '';

    parts.push(
      `<span class="${mark.cls}" data-ws-label="${escHtml(label)}" data-ws-hint="${escHtml(hint)}"${fixAttrs}>${escHtml(matchedText)}</span>`
    );
    pos = mark.end;
  }
  if (pos < raw.length) parts.push(escHtml(raw.slice(pos)));
  return parts.join('');
}

function makeKey(s: string, n = 80): string {
  const t = normKey(s);
  return t.length > n ? t.slice(0, n) : t;
}

// ─────────────────────────────────────────────────────────────────────────────

type ReviewSuggestion = {
  id: string;
  text: string;
  kind: 'sentence' | 'paragraph' | 'info';
  matchText: string;
  matchKey?: string;
  fix?: { label: string; applyMode: 'apply' | 'suggest' };
};

type GrammarMatch = {
  offset: number;
  length: number;
  message: string;
  shortMessage?: string | null;
  rule: {
    id: string;
    description?: string | null;
    issueType?: string | null;
    category?: string | null;
  };
  replacements: { value: string }[];
};

type GrammarState = {
  status: 'idle' | 'loading' | 'ok' | 'error';
  matches: GrammarMatch[];
  error?: string;
};

export default function Workspace() {
  const navigate = useNavigate();
  const [title, setTitle] = useState(() => localStorage.getItem(TITLE_KEY) ?? '');
  const [body, setBody]   = useState(() => localStorage.getItem(BODY_KEY)  ?? '');
  const [characterId, setCharacterId] = useState<number>(() => {
    const v = localStorage.getItem(CHARACTER_KEY);
    if (!v) return 0;
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  });
  const [isSaving, setIsSaving] = useState(false);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [saveTick, setSaveTick] = useState(0);
  const [surfaceMode, setSurfaceMode] = useState<'night' | 'paper'>(
    () => (localStorage.getItem(SURFACE_KEY) as 'night' | 'paper') ?? 'night'
  );
  const [mode, setMode] = useState<'write' | 'preview' | 'review'>(() => {
    const v = localStorage.getItem(MODE_KEY);
    return v === 'preview' || v === 'review' || v === 'write' ? v : 'write';
  });
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [publishSuccess, setPublishSuccess] = useState(false);
  const [publishDestination, setPublishDestination] = useState('');
  const [realms, setRealms] = useState<Realm[]>([]);
  const [selectedRealmId, setSelectedRealmId] = useState<number | null>(() => {
    const v = localStorage.getItem(REALM_KEY);
    if (!v) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  });
  const [showPanel, setShowPanel] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [wsTip, setWsTip] = useState<{ show: boolean; x: number; y: number; label: string; hint: string }>(
    { show: false, x: 0, y: 0, label: '', hint: '' }
  );
  const [highlightId, setHighlightId] = useState<string>('');
  const [fixStatus, setFixStatus] = useState<{ id: string; msg: string } | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fixTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [formatFlash, setFormatFlash] = useState<string>('');
  const formatFlashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [grammar, setGrammar] = useState<GrammarState>({ status: 'idle', matches: [] });
  const [ignoredKeys, setIgnoredKeys] = useState<Set<string>>(new Set<string>());
  const grammarTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const grammarAbortRef = useRef<AbortController | null>(null);
  const pendingCaretRef = useRef<number | null>(null);


  // Debounced autosave — persists draft content + UI context
  useEffect(() => {
    setIsSaving(true);
    const t = setTimeout(() => {
      localStorage.setItem(TITLE_KEY, title);
      localStorage.setItem(BODY_KEY, body);
      localStorage.setItem(MODE_KEY, mode);
      localStorage.setItem(REALM_KEY, selectedRealmId === null ? '' : String(selectedRealmId));
      localStorage.setItem(CHARACTER_KEY, String(characterId));
      setIsSaving(false);
      setLastSavedAt(Date.now());
    }, 500);
    return () => clearTimeout(t);
  }, [title, body, mode, selectedRealmId, characterId]);

  useEffect(() => {
    if (!lastSavedAt) return;
    const i = setInterval(() => {
      setSaveTick((t) => t + 1);
    }, 10000);
    return () => clearInterval(i);
  }, [lastSavedAt]);

  // Persist UI preferences immediately (no typing debounce needed for these)
  useEffect(() => { localStorage.setItem(MODE_KEY, mode); }, [mode]);
  useEffect(() => { localStorage.setItem(REALM_KEY, selectedRealmId === null ? '' : String(selectedRealmId)); }, [selectedRealmId]);
  useEffect(() => { localStorage.setItem(CHARACTER_KEY, String(characterId)); }, [characterId]);
  useEffect(() => { localStorage.setItem(SURFACE_KEY, surfaceMode); }, [surfaceMode]);

  // Load non-commons realms for the destination selector
  useEffect(() => {
    apiClient.getRealms()
      .then((all) => setRealms(all.filter((r) => !r.is_commons)))
      .catch(() => { /* non-fatal: selector stays empty */ });
  }, []);

  // Scroll to highlighted element whenever preview becomes active with a highlight
  useEffect(() => {
    if (mode === 'preview' && highlightId) {
      requestAnimationFrame(() => {
        document.getElementById(`ws-hl-${highlightId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
  }, [mode, highlightId]);

  // Cleanup timers on unmount
  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
      if (fixTimerRef.current) clearTimeout(fixTimerRef.current);
      if (formatFlashTimerRef.current) clearTimeout(formatFlashTimerRef.current);
      if (grammarTimerRef.current) clearTimeout(grammarTimerRef.current);
      if (grammarAbortRef.current) grammarAbortRef.current.abort();
    };
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
      setPublishDestination(destination);
      setPublishSuccess(true);
    } catch {
      setPublishError('Post failed. Try again.');
    } finally {
      setPublishing(false);
    }
  };

  function downloadDraft() {
    if (!body.trim()) return;
    const blob = new Blob([body], { type: 'text/plain' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = (title.trim() || 'draft') + '.txt';
    a.click();
    URL.revokeObjectURL(url);
  }

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

  function revealFormatting() {
    setMode('preview');
    setShowPanel(false);
  }

  function flash(msg: string) {
    if (formatFlashTimerRef.current) clearTimeout(formatFlashTimerRef.current);
    setFormatFlash(msg);
    formatFlashTimerRef.current = setTimeout(() => setFormatFlash(''), 1500);
  }

  function wrapOrInsertPlaceholder(before: string, after: string, placeholder: string, flashMsg: string) {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart ?? 0;
    const end   = el.selectionEnd ?? 0;
    if (start !== end) {
      insertAroundSelection(before, after);
      flash(flashMsg);
      revealFormatting();
      return;
    }
    const newText = body.slice(0, start) + before + placeholder + after + body.slice(start);
    setBody(newText);
    setTimeout(() => {
      el.setSelectionRange(start + before.length, start + before.length + placeholder.length);
      el.focus();
    }, 0);
    flash(flashMsg);
    revealFormatting();
  }

  function insertHeaderSmart() {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart ?? 0;
    const end   = el.selectionEnd ?? 0;
    if (start !== end) {
      insertHeaderPrefix();
      flash('Heading inserted');
      revealFormatting();
      return;
    }
    const lineStart  = body.lastIndexOf('\n', start - 1) + 1;
    const lineEndIdx = body.indexOf('\n', start);
    const lineContent = body.slice(lineStart, lineEndIdx === -1 ? body.length : lineEndIdx);
    const placeholder = 'Heading';
    const prefix = '## ';
    if (lineContent.trim() === '') {
      const newText = body.slice(0, lineStart) + prefix + placeholder + body.slice(lineStart);
      setBody(newText);
      setTimeout(() => {
        el.setSelectionRange(lineStart + prefix.length, lineStart + prefix.length + placeholder.length);
        el.focus();
      }, 0);
    } else {
      const newText = body.slice(0, lineStart) + prefix + body.slice(lineStart);
      setBody(newText);
      setTimeout(() => {
        el.setSelectionRange(start + prefix.length, start + prefix.length);
        el.focus();
      }, 0);
    }
    flash('Heading inserted');
    revealFormatting();
  }

  function clearDraft() {
    setTitle('');
    setBody('');
    localStorage.removeItem(TITLE_KEY);
    localStorage.removeItem(BODY_KEY);
    localStorage.removeItem(PASTE_HINT_KEY);
    setLastSavedAt(null);
  }

  function handleSuggestionClick(id: string, kind: ReviewSuggestion['kind'], matchText: string, destinationMode: 'preview' | 'review' = 'preview') {
    setMode(destinationMode);
    setShowPanel(false);
    if (kind !== 'info' && matchText) {
      if (highlightTimerRef.current) clearTimeout(highlightTimerRef.current);
      setHighlightId(id);
      highlightTimerRef.current = setTimeout(() => setHighlightId(''), 2000);
    }
  }

  async function applySuggestionFix(s: ReviewSuggestion) {
    if (!s.fix || !s.matchText) return;
    if (s.fix.applyMode === 'apply') {
      if (s.kind === 'sentence')  setBody(splitLongSentence(body, s.matchText));
      if (s.kind === 'paragraph') setBody(breakUpParagraph(body, s.matchText));
      setFixStatus({ id: s.id, msg: 'Applied \u2713' });
    } else {
      const hint = buildActiveSuggestion(s.matchText);
      try { await navigator.clipboard.writeText(hint); } catch { /* no-op */ }
      setFixStatus({ id: s.id, msg: 'Suggestion copied' });
    }
    setShowPanel(false);
    if (fixTimerRef.current) clearTimeout(fixTimerRef.current);
    fixTimerRef.current = setTimeout(() => setFixStatus(null), 2000);
  }

  function grammarIgnoreKey(m: GrammarMatch): string {
    return `${m.rule.id}:${m.offset}:${m.length}:${m.message}`;
  }

  function jumpToRange(offset: number, length: number) {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(offset, offset + length);
    const linesBefore = el.value.slice(0, offset).split('\n').length;
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 28;
    el.scrollTop = Math.max(0, (linesBefore - 3) * lineHeight);
  }

  function applyGrammarFix(m: GrammarMatch, replacement: string) {
    const newBody = body.slice(0, m.offset) + replacement + body.slice(m.offset + m.length);
    setBody(newBody);
    setGrammar((prev) => ({ ...prev, matches: prev.matches.filter((x) => x !== m) }));
  }

  /**
   * Quick Fix v1 — apply a simple, deterministic edit to the body.
   * Only called for high-confidence cases: duplicate word removal and single filler-word removal.
   */
  function applyQuickFix(fixType: string, offset: number, length: number) {
    if (offset < 0 || length <= 0 || offset + length > body.length) return;
    const matchText = body.slice(offset, offset + length);
    let newBody: string;
    let caretPos: number;

    if (fixType === 'remove-dup') {
      // "the the" → "the"  (keep first copy, preserve original casing)
      const firstWord = matchText.match(/^(\S+)/)?.[1] ?? matchText;
      newBody   = body.slice(0, offset) + firstWord + body.slice(offset + length);
      caretPos  = offset + firstWord.length;
    } else if (fixType === 'remove-word') {
      // "very" → ""  — absorb one adjacent space to avoid double-spacing
      let start = offset;
      let end   = offset + length;
      if (start > 0 && body[start - 1] === ' ') {
        start--; // remove the space before the word
      } else if (end < body.length && body[end] === ' ') {
        end++;   // remove the space after the word
      }
      newBody  = body.slice(0, start) + body.slice(end);
      caretPos = start;
    } else {
      return; // unknown type — do nothing
    }

    setBody(newBody);
    // Restore caret near the edit location after React re-renders
    pendingCaretRef.current = caretPos;
    requestAnimationFrame(() => {
      const el = textareaRef.current;
      if (!el || pendingCaretRef.current === null) return;
      el.focus();
      el.setSelectionRange(pendingCaretRef.current, pendingCaretRef.current);
      pendingCaretRef.current = null;
    });
  }

  function ignoreGrammarMatch(m: GrammarMatch) {
    setIgnoredKeys((prev) => {
      const next = new Set(prev);
      next.add(grammarIgnoreKey(m));
      return next;
    });
  }

  async function runGrammarCheck() {
    if (grammarAbortRef.current) grammarAbortRef.current.abort();
    const controller = new AbortController();
    grammarAbortRef.current = controller;
    setGrammar({ status: 'loading', matches: [] });
    try {
      const resp = await fetch('/api/grammar/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: body, language: 'en-US' }),
        signal: controller.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as { language: string; matches: GrammarMatch[] };
      setGrammar({ status: 'ok', matches: data.matches });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setGrammar({ status: 'error', matches: [], error: 'Grammar check failed.' });
    }
  }

  // Debounced grammar check — fires 800 ms after body/mode changes in review mode
  useEffect(() => {
    if (mode !== 'review') {
      setGrammar({ status: 'idle', matches: [] });
      setIgnoredKeys(new Set<string>());
      if (grammarAbortRef.current) { grammarAbortRef.current.abort(); grammarAbortRef.current = null; }
      return;
    }
    if (!body.trim()) {
      setGrammar({ status: 'idle', matches: [] });
      return;
    }
    if (grammarTimerRef.current) clearTimeout(grammarTimerRef.current);
    grammarTimerRef.current = setTimeout(() => void runGrammarCheck(), 800);
    return () => {
      if (grammarTimerRef.current) clearTimeout(grammarTimerRef.current);
    };
  // body / mode are the only values that should retrigger this effect
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, mode]);

  function renderLiveChecks() {
    const checks = review.suggestions.filter((s) => s.kind !== 'info').slice(0, 6);

    function labelFor(id: string) { return suggestionLabel(id) || 'Issue'; }

    return (
      <div className="shrink-0 mt-3 border border-gray-800 rounded-xl bg-gray-900/40">
        <div className="px-3 py-2 border-b border-gray-800 flex items-center justify-between">
          <span className="text-xs font-semibold text-gray-300">Live Checks</span>
          {checks.length > 0 && (
            <span className="text-xs text-gray-500">
              {checks.length} {checks.length === 1 ? 'issue' : 'issues'}
            </span>
          )}
        </div>
        {checks.length === 0 ? (
          <div className="px-3 py-2 text-xs text-emerald-300">\u2705 No issues detected</div>
        ) : (
          <ul className="divide-y divide-gray-800">
            {checks.map((s) => {
              const maxLen = s.kind === 'paragraph' ? 140 : 120;
              const snippet = s.matchText.length > maxLen
                ? s.matchText.slice(0, maxLen) + '\u2026'
                : s.matchText;
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => handleSuggestionClick(s.id, s.kind, s.matchText, 'review')}
                    className="w-full text-left px-3 py-2 text-xs text-gray-300 hover:bg-gray-800/60 transition-colors"
                  >
                    <div>{snippet}</div>
                    <div className="mt-1 text-[11px] text-gray-500">{labelFor(s.id)}</div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  function renderWriteOverlay(text: string) {
    if (!text) return null;

    // Split on sentence-ending punctuation, keeping delimiters
    const parts = text.split(/([.!?]+)/);
    const rebuilt: string[] = [];
    let bodyPos = 0; // cumulative char offset into the original text

    for (let i = 0; i < parts.length; i += 2) {
      const sentence = (parts[i] ?? '') + (parts[i + 1] ?? '');
      if (!sentence) continue;
      const words = sentence.trim().split(/\s+/).filter(Boolean).length;
      // Apply repeat + filler inline marks, with exact body offsets for quick-fix
      const markedHtml = markInlineSentence(sentence, bodyPos);
      if (words > 28) {
        // Long sentence: wrap everything in ws-long; inner marks remain visible
        const longHint = `${words}-word sentence — click to split in place.`;
        rebuilt.push(`<span class="ws-long" data-ws-long="1" data-ws-words="${words}" data-ws-key="${escHtml(makeKey(sentence))}" data-ws-sentence="${escHtml(sentence)}" data-ws-label="Long sentence" data-ws-hint="${escHtml(longHint)}">${markedHtml}</span>`);
      } else {
        rebuilt.push(markedHtml);
      }
      bodyPos += sentence.length;
    }

    return (
      <div
        ref={overlayRef}
        className="ws-write-overlay"
        aria-hidden="true"
        dangerouslySetInnerHTML={{ __html: rebuilt.join('') }}
      />
    );
  }

  function renderPreview(text: string) {
    if (!text.trim()) {
      return <p className="text-gray-500 text-sm">Nothing to preview yet.</p>;
    }

    // Escape HTML first for safety
    let escaped = text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Scene breaks
    escaped = escaped.replace(/^---$/gm, `<hr class="${surfaceMode === 'paper' ? 'border-stone-400' : 'border-gray-700'} my-6" />`);

    // Headers
    escaped = escaped.replace(/^## (.*)$/gm, '<h2 class="text-xl font-semibold mt-6 mb-2">$1</h2>');

    // Bold
    escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Italic
    escaped = escaped.replace(/\*(.*?)\*/g, '<em>$1</em>');

    // Split in parallel: raw for matching, escaped for rendering
    const rawParas  = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
    const htmlParas = escaped.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);

    if (!htmlParas.length) {
      return <span className="text-gray-500">Nothing to preview yet.</span>;
    }

    // All actionable suggestions drive underlines + active highlight
    const actionable = review.suggestions.filter((s) => s.matchText && s.kind !== 'info');

    // Pre-compute where each rawPara starts in the original text (for grammar offset mapping)
    const paraStartOffsets: number[] = [];
    {
      let search = 0;
      for (const rp of rawParas) {
        const idx = text.indexOf(rp, search);
        paraStartOffsets.push(idx >= 0 ? idx : 0);
        if (idx >= 0) search = idx + rp.length;
      }
    }

    const finalHtml = htmlParas.map((paraHtml, i) => {
      const rawPara = rawParas[i] ?? '';
      let content = paraHtml.replace(/\n/g, '<br/>');
      let paraIdAttr = '';
      let paraOpenExtra = '';

      // Sentence underlines
      for (const s of actionable.filter((s) => s.kind === 'sentence')) {
        const rawFlat = rawPara.replace(/\n/g, ' ').replace(/\s+/g, ' ').trim();
        if (!rawFlat.includes(s.matchText)) continue;

        const isActive = s.id === highlightId;
        if (isActive) paraIdAttr = ` id="ws-hl-${s.id}"`;

        const escapedSentence = s.matchText
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>');
        if (!content.includes(escapedSentence)) continue;

        const base = s.id === 'passive' ? 'ws-ul-passive' : 'ws-ul-sentence';
        const cls  = isActive ? `${base} ws-hl` : base;
        const title = s.id === 'passive'
          ? 'Passive voice \u2014 click to review'
          : 'Long sentence \u2014 click to review';
        content = content.replace(
          escapedSentence,
          `<span class="${cls}" data-ws-id="${s.id}" title="${title}" style="cursor:pointer">${escapedSentence}</span>`,
        );
      }

      // Paragraph underlines (add class + handler to the <p> element)
      for (const s of actionable.filter((s) => s.kind === 'paragraph')) {
        if (rawPara.trim() !== s.matchText.trim()) continue;
        const isActive = s.id === highlightId;
        if (isActive) paraIdAttr = ` id="ws-hl-${s.id}"`;
        const cls = isActive ? 'ws-ul-para ws-hl' : 'ws-ul-para';
        paraOpenExtra = ` class="${cls}" data-ws-id="${s.id}" title="Dense paragraph \u2014 click to review" style="cursor:pointer"`;
        break;
      }

      // Grammar underlines — char-offset based, wavy red
      const paraStart = paraStartOffsets[i] ?? 0;
      for (const gm of visibleGrammarMatches) {
        if (gm.offset < paraStart || gm.offset >= paraStart + rawPara.length) continue;
        const matchText = text.slice(gm.offset, gm.offset + gm.length);
        if (!matchText.trim()) continue;
        const escapedMatch = matchText
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          .replace(/\*(.*?)\*/g, '<em>$1</em>');
        if (!content.includes(escapedMatch)) continue;
        const titleAttr = (gm.shortMessage || gm.message).replace(/"/g, '&quot;');
        content = content.replace(
          escapedMatch,
          `<span class="ws-ul-grammar" data-ws-grammar-offset="${gm.offset}" data-ws-grammar-length="${gm.length}" title="${titleAttr}" style="cursor:pointer">${escapedMatch}</span>`,
        );
      }

      return `<p${paraIdAttr}${paraOpenExtra}>${content}</p>`;
    }).join('');

    return (
      <div
        className={`${surfaceMode === 'paper' ? 'prose' : 'prose prose-invert'} max-w-none leading-relaxed`}
        dangerouslySetInnerHTML={{ __html: finalHtml }}
      />
    );
  }

  function renderSidebarContent(variant: 'desktop' | 'drawer') {
    const drawerSelectors = variant === 'drawer' ? (
      <div className="space-y-3 border-b border-gray-800 pb-4 mb-1">
        <div className="space-y-1">
          <p className="text-xs text-gray-500">Character</p>
          <select
            value={characterId}
            onChange={(e) => setCharacterId(Number(e.target.value))}
            className="input text-sm"
          >
            {MOCK_CHARACTERS.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <p className="text-xs text-gray-500">Posting to</p>
          <select
            value={selectedRealmId ?? ''}
            onChange={(e) => setSelectedRealmId(e.target.value ? Number(e.target.value) : null)}
            className="input text-sm"
          >
            <option value="">Commons</option>
            {realms.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </div>
      </div>
    ) : null;

    if (mode === 'review') {
      return (
        <>
          {drawerSelectors}
          <div className="space-y-4">
          {/* Stats card */}
          <div className="border border-gray-800 rounded-xl p-4 space-y-2">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Writing stats</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <span className="text-gray-500">Words</span>
              <span className="text-gray-200">{review.words}</span>
              <span className="text-gray-500">Sentences</span>
              <span className="text-gray-200">{review.sentences}</span>
              <span className="text-gray-500">Paragraphs</span>
              <span className="text-gray-200">{review.paragraphs}</span>
              <span className="text-gray-500">Avg sentence</span>
              <span className="text-gray-200">{Math.round(review.avgSentenceWords)} words</span>
              <span className="text-gray-500">Readability</span>
              <span className="text-gray-200">
                {review.readabilityLabel}
                {review.readabilityScore !== null && (
                  <span className="text-gray-500"> ({Math.round(review.readabilityScore)})</span>
                )}
              </span>
            </div>
          </div>

          {/* Suggestions card */}
          <div className="border border-gray-800 rounded-xl p-4 space-y-2">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Suggestions</p>
            {review.suggestions.length === 0 ? (
              <p className="text-sm text-gray-500">No suggestions right now.</p>
            ) : (
              <ul className="space-y-1">
                {review.suggestions.map((s) => (
                  <li
                    key={s.id}
                    onClick={() => handleSuggestionClick(s.id, s.kind, s.matchText)}
                    className={`flex items-start justify-between gap-2 text-sm text-gray-300 py-2 px-2 rounded-lg transition-colors ${
                      s.kind !== 'info' && s.matchText
                        ? 'cursor-pointer hover:bg-gray-800'
                        : ''
                    }`}
                  >
                    <div className="flex gap-2 min-w-0">
                      <span className="text-gray-600 select-none mt-0.5 shrink-0">&bull;</span>
                      <span className="flex flex-col gap-0.5">
                        <span>{s.text}</span>
                        {suggestionLabel(s.id) && (
                          <span className="text-[11px] text-gray-500">{suggestionLabel(s.id)}</span>
                        )}
                      </span>
                    </div>
                    {s.fix && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); void applySuggestionFix(s); }}
                        className="btn btn-secondary text-xs shrink-0"
                      >
                        {s.fix.label}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {fixStatus && (
              <p className="text-xs text-gray-400 pt-1">{fixStatus.msg}</p>
            )}
          </div>

          {/* Grammar & Spelling card */}
          <div className="border border-gray-800 rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Grammar & Spelling</p>
              {grammar.status === 'loading' && (
                <span className="text-xs text-gray-500">Checking…</span>
              )}
              {grammar.status === 'ok' && visibleGrammarMatches.length > 0 && (
                <span className="text-xs text-gray-500">
                  {visibleGrammarMatches.length} {visibleGrammarMatches.length === 1 ? 'issue' : 'issues'}
                </span>
              )}
            </div>
            {grammar.status === 'loading' && (
              <p className="text-sm text-gray-500">Analyzing your writing…</p>
            )}
            {grammar.status === 'error' && (
              <p className="text-sm text-red-400">{grammar.error}</p>
            )}
            {grammar.status === 'ok' && visibleGrammarMatches.length === 0 && (
              <p className="text-sm text-emerald-300">&#10003; No grammar issues found.</p>
            )}
            {grammar.status === 'ok' && visibleGrammarMatches.length > 0 && (
              <ul className="space-y-2">
                {visibleGrammarMatches.map((m, i) => (
                  <li key={i} className="text-sm border border-gray-800 rounded-lg p-2 space-y-1">
                    <button
                      type="button"
                      onClick={() => jumpToRange(m.offset, m.length)}
                      className="text-left text-gray-200 hover:text-emerald-300 transition-colors w-full"
                    >
                      {m.shortMessage || m.message}
                    </button>
                    {m.rule.category && (
                      <p className="text-xs text-gray-500">{m.rule.category}</p>
                    )}
                    <div className="flex flex-wrap gap-1 pt-1">
                      {m.replacements.slice(0, 3).map((r, ri) => (
                        <button
                          key={ri}
                          type="button"
                          onClick={() => applyGrammarFix(m, r.value)}
                          className="text-xs px-2 py-0.5 rounded-md bg-emerald-900/40 border border-emerald-800/60 text-emerald-300 hover:bg-emerald-800/40 transition"
                        >
                          {r.value}
                        </button>
                      ))}
                      <button
                        type="button"
                        onClick={() => ignoreGrammarMatch(m)}
                        className="text-xs px-2 py-0.5 rounded-md bg-gray-800/60 border border-gray-700 text-gray-400 hover:text-gray-200 transition"
                      >
                        Ignore
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        </>
      );
    }

    return (
      <>
      {drawerSelectors}
      <div className="space-y-3">

        {publishSuccess ? (
          /* ── Post success panel ─────────────────────────────────── */
          <div className="rounded-xl border border-emerald-800/50 bg-emerald-950/20 p-4 space-y-3">
            <div className="space-y-1">
              <p className="text-sm font-semibold text-emerald-300">Published</p>
              <p className="text-xs text-gray-400 leading-relaxed">
                Your post is live on{' '}
                <span className="text-gray-300">
                  {publishDestination === '/' ? 'Commons' : selectedRealmName ?? 'the realm'}
                </span>.
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => navigate(publishDestination)}
                className="w-full py-2 px-3 rounded-lg bg-emerald-700/80 hover:bg-emerald-600 active:bg-emerald-700 text-white text-xs font-semibold transition"
              >
                View post
              </button>
              <button
                type="button"
                onClick={() => setPublishSuccess(false)}
                className="w-full py-1.5 px-3 rounded-lg text-gray-500 hover:text-gray-300 text-xs transition"
              >
                Write another
              </button>
            </div>
          </div>
        ) : (
          /* ── Publish controls ───────────────────────────────────── */
          <>
            {/* Identity summary */}
            <div className="rounded-lg bg-gray-900/40 border border-gray-800/60 px-3 py-2.5 space-y-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[10px] font-medium text-gray-600 uppercase tracking-wider">To</span>
                <span className="text-xs text-gray-300 text-right">{selectedRealmName ?? 'Commons'}</span>
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[10px] font-medium text-gray-600 uppercase tracking-wider">As</span>
                <span className="text-xs text-right">
                  {characterId !== 0 ? (
                    <>
                      <span className="text-gray-300">
                        {MOCK_CHARACTERS.find((c) => c.id === characterId)?.name ?? 'Character'}
                      </span>
                      <span className="text-gray-600"> · IC</span>
                    </>
                  ) : (
                    <span className="text-gray-500">You · OOC</span>
                  )}
                </span>
              </div>
              {hasText && (
                <div className="flex items-baseline justify-between gap-2 pt-0.5 border-t border-gray-800/50">
                  <span className="text-[10px] font-medium text-gray-600 uppercase tracking-wider">Words</span>
                  <span className="text-[11px] text-gray-500">
                    {body.trim().split(/\s+/).filter(Boolean).length}
                  </span>
                </div>
              )}
            </div>

            {/* Publish button */}
            <button
              type="button"
              onClick={handlePublishToCommons}
              disabled={publishing || !body.trim()}
              className="w-full py-2.5 px-4 rounded-xl bg-emerald-700/90 hover:bg-emerald-600 active:bg-emerald-700 text-white font-semibold text-sm tracking-wide transition disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {publishing
                ? 'Publishing\u2026'
                : selectedRealmId === null
                  ? 'Publish to Commons'
                  : `Publish to ${selectedRealmName ?? 'Realm'}`}
            </button>

            {/* Error state */}
            {publishError && (
              <div className="flex items-start gap-2 rounded-lg border border-red-800/40 bg-red-950/20 px-3 py-2">
                <p className="text-xs text-red-400 flex-1 leading-relaxed">{publishError}</p>
                <button
                  type="button"
                  onClick={handlePublishToCommons}
                  className="shrink-0 text-[11px] text-red-500 hover:text-red-300 transition font-medium"
                >
                  Retry
                </button>
              </div>
            )}

            <button
              type="button"
              onClick={downloadDraft}
              disabled={!body.trim()}
              className="btn btn-secondary w-full disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Download text
            </button>
          </>
        )}

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

        <div className="border-t border-gray-800 pt-3">
          <button
            type="button"
            onClick={clearDraft}
            className="w-full text-left px-2 py-1.5 text-xs text-gray-600 hover:text-red-400 hover:bg-red-950/20 rounded-lg transition-colors"
          >
            Clear draft
          </button>
        </div>

        {/* StoryLab CTA */}
        <div className="border border-gray-800 rounded-xl p-4 space-y-3 bg-gray-900/30">
          <div className="space-y-0.5">
            <p className="text-xs font-semibold text-gray-300">Collaborate with StoryLab</p>
            <p className="text-xs text-gray-500">Co-create scenes with the engine in a dedicated space.</p>
          </div>
          <button
            type="button"
            onClick={() => navigate('/storylab')}
            className="w-full py-1.5 px-4 rounded-lg border border-emerald-800/60 bg-emerald-900/20 hover:bg-emerald-900/40 text-emerald-400 hover:text-emerald-300 text-xs font-medium transition"
          >
            Open StoryLab
          </button>
        </div>
      </div>
      </>
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

  const hasText = body.trim().length > 0;

  const visibleGrammarMatches = useMemo(
    () => grammar.matches.filter(
      (m) => !ignoredKeys.has(`${m.rule.id}:${m.offset}:${m.length}:${m.message}`)
    ),
    [grammar.matches, ignoredKeys]
  );

  const review = useMemo(() => {
    const norm = normalizeText(body);
    const words = countWords(norm);
    const sentenceList = getSentences(norm);
    const paragraphList = getParagraphs(norm);
    const sentences = sentenceList.length;
    const paragraphs = paragraphList.length;
    const avgSentenceWords = sentences > 0 ? words / sentences : 0;
    const sentenceWordCounts = sentenceList.map((s) => countWords(s));
    const longestSentenceWords = sentenceWordCounts.length > 0 ? Math.max(...sentenceWordCounts) : 0;
    const longSentenceCount = sentenceWordCounts.filter((c) => c > 30).length;
    const longParagraphCount = paragraphList.filter((p) => countWords(p) > 120).length;
    const passiveCount = detectPassiveSentences(sentenceList);
    const readabilityScore = fleschReadingEase(norm);
    const readabilityLabel: 'Easy' | 'Medium' | 'Dense' | 'N/A' =
      readabilityScore === null ? 'N/A'
      : readabilityScore >= 60  ? 'Easy'
      : readabilityScore >= 45  ? 'Medium'
      : 'Dense';

    // Grammar Engine v1 — client-side checks
    const adjacentRepeats = detectAdjacentRepeats(sentenceList);
    const highFreqRepeats = detectHighFreqRepeats(sentenceList);
    const fillerHit = detectFillerPhrases(sentenceList);

    const suggestions: ReviewSuggestion[] = [];
    if (words === 0) {
      suggestions.push({ id: 'empty', text: 'Start writing to see suggestions.', kind: 'info', matchText: '' });
    } else {
      const firstLongSentIdx = sentenceWordCounts.findIndex((c) => c > 30);
      if (longSentenceCount > 0)
        suggestions.push({ id: 'long-sent', text: `Consider breaking up ${longSentenceCount} long sentence(s) (30+ words).`, kind: 'sentence', matchText: firstLongSentIdx >= 0 ? sentenceList[firstLongSentIdx] : '', matchKey: makeKey(firstLongSentIdx >= 0 ? sentenceList[firstLongSentIdx] : ''), fix: { label: 'Split sentence', applyMode: 'apply' } });

      const longestSentIdx = sentenceWordCounts.indexOf(longestSentenceWords);
      if (longestSentenceWords >= 45)
        suggestions.push({ id: 'very-long-sent', text: `One sentence is very long (\u2248${longestSentenceWords} words). Split it for clarity.`, kind: 'sentence', matchText: longestSentIdx >= 0 ? sentenceList[longestSentIdx] : '', matchKey: makeKey(longestSentIdx >= 0 ? sentenceList[longestSentIdx] : ''), fix: { label: 'Split sentence', applyMode: 'apply' } });

      const firstLongParaIdx = paragraphList.findIndex((p) => countWords(p) > 120);
      if (longParagraphCount > 0)
        suggestions.push({ id: 'long-para', text: `Consider splitting ${longParagraphCount} long paragraph(s) (120+ words).`, kind: 'paragraph', matchText: firstLongParaIdx >= 0 ? paragraphList[firstLongParaIdx] : '', fix: { label: 'Add breaks', applyMode: 'apply' } });

      const firstPassiveIdx = sentenceList.findIndex((s) => /\b(am|is|are|was|were|be|been|being)\b\s+\w+(ed|en)\b/i.test(s));
      if (passiveCount > 0)
        suggestions.push({ id: 'passive', text: `Passive phrasing detected in ${passiveCount} sentence(s). Consider active voice for punch.`, kind: 'sentence', matchText: firstPassiveIdx >= 0 ? sentenceList[firstPassiveIdx] : '', fix: { label: 'Show suggestion', applyMode: 'suggest' } });

      // Repeated word checks
      if (adjacentRepeats.length > 0) {
        const hit = adjacentRepeats[0];
        suggestions.push({
          id: 'repeat-adj',
          text: `Duplicate word "${hit.word} ${hit.word}" — likely a typo (${adjacentRepeats.length} instance${adjacentRepeats.length > 1 ? 's' : ''}).`,
          kind: 'sentence',
          matchText: hit.sentence,
          matchKey: makeKey(hit.sentence),
        });
      } else if (highFreqRepeats.length > 0) {
        const hit = highFreqRepeats[0];
        suggestions.push({
          id: 'repeat-word',
          text: `"${hit.word}" repeats 3+ times in a sentence. Vary your word choice.`,
          kind: 'sentence',
          matchText: hit.sentence,
          matchKey: makeKey(hit.sentence),
        });
      }

      // Filler / weak phrase check
      if (fillerHit) {
        suggestions.push({
          id: 'filler',
          text: `Weak phrase "${fillerHit.phrase}" found (${fillerHit.count} filler instance${fillerHit.count > 1 ? 's' : ''}). Cut or replace for stronger prose.`,
          kind: 'sentence',
          matchText: fillerHit.sentence,
          matchKey: makeKey(fillerHit.sentence),
        });
      }

      if (paragraphs === 1 && words > 120)
        suggestions.push({ id: 'one-para', text: 'Try adding paragraph breaks for readability.', kind: 'paragraph', matchText: paragraphList[0] ?? '', fix: { label: 'Add breaks', applyMode: 'apply' } });

      if (readabilityScore !== null && readabilityScore < 45)
        suggestions.push({ id: 'dense', text: 'Readability is dense. Shorten sentences and simplify phrasing.', kind: 'info', matchText: '' });

      if (readabilityScore !== null && readabilityScore >= 60)
        suggestions.push({ id: 'easy', text: 'Readability is strong. Nice flow.', kind: 'info', matchText: '' });
    }

    return {
      words, sentences, paragraphs, avgSentenceWords, longestSentenceWords,
      longSentenceCount, longParagraphCount, passiveCount,
      readabilityScore, readabilityLabel,
      suggestions: suggestions.slice(0, 8),
    };
  }, [body]);


  return (
    <div className={
      "w-full h-[calc(100vh-24px)] flex flex-col transition-colors " +
      (focusMode ? "bg-black" : "bg-gray-950")
    }>
      <style>{`
        .ws-hl{background:rgba(52,211,153,.15);border-radius:3px;padding:0 2px;outline:1px solid rgba(52,211,153,.4)}
        .ws-ul-sentence{text-decoration:underline;text-decoration-color:rgba(251,191,36,.6);text-decoration-thickness:2px}
        .ws-ul-passive{text-decoration:underline dotted;text-decoration-color:rgba(96,165,250,.7)}
        .ws-ul-grammar{text-decoration-line:underline;text-decoration-style:wavy;text-decoration-color:rgba(248,113,113,.8);text-underline-offset:3px}
        .ws-ul-para{background:rgba(251,191,36,.06);border-radius:4px}
        .ws-write-overlay{position:absolute;inset:0;padding:1rem;border-radius:1rem;white-space:pre-wrap;word-break:break-word;color:transparent;pointer-events:none;font:inherit;line-height:inherit;overflow:hidden}
        @media(min-width:768px){.ws-write-overlay{padding:1.25rem}}
        .ws-write-overlay span.ws-long{color:transparent;text-decoration:underline;text-decoration-color:rgba(251,191,36,.45);text-decoration-thickness:2px;text-underline-offset:3px;pointer-events:auto;cursor:pointer}
        .ws-write-overlay span.ws-repeat{color:transparent;text-decoration-line:underline;text-decoration-style:wavy;text-decoration-color:rgba(251,113,133,.8);text-decoration-thickness:2px;text-underline-offset:3px;pointer-events:auto;cursor:pointer}
        .ws-write-overlay span.ws-filler{color:transparent;text-decoration-line:underline;text-decoration-style:dotted;text-decoration-color:rgba(167,139,250,.7);text-decoration-thickness:2px;text-underline-offset:3px;pointer-events:auto;cursor:pointer}
        .ws-write-overlay span.ws-overuse{color:transparent;text-decoration-line:underline;text-decoration-style:dashed;text-decoration-color:rgba(251,146,60,.7);text-decoration-thickness:2px;text-underline-offset:3px;pointer-events:auto;cursor:default}
        .ws-tip{position:fixed;pointer-events:none;transform:translate(12px,12px);background:#111827;border:1px solid #374151;color:#e5e7eb;font-size:.75rem;line-height:1.4;border-radius:.5rem;padding:.375rem .625rem;box-shadow:0 4px 16px rgba(0,0,0,.5);max-width:260px;z-index:9999}
        ::selection{background:rgba(52,211,153,.25)}
        .ws-paper-surface::placeholder{color:#9D8E7D}
      `}</style>
      {/* A) Header bar */}
      <div className="px-4 md:px-6 pt-4 pb-3 border-b border-gray-800 flex-shrink-0">
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Untitled story"
            className="flex-1 bg-transparent text-lg font-bold text-gray-100 placeholder-gray-600 focus:outline-none"
          />
          {/* Selectors: desktop only — drawer carries them on mobile */}
          <div className="hidden lg:flex items-center gap-3">
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
          </div>
          <p className="text-xs text-gray-500">
            {getSaveLabel()}
          </p>
          {formatFlash && <span className="text-xs text-emerald-400">{formatFlash}</span>}
          {/* Surface mode toggle — Night / Paper */}
          <div className="flex items-center rounded-md border border-gray-700 overflow-hidden text-xs">
            <button
              type="button"
              onClick={() => setSurfaceMode('night')}
              className={`px-2 py-1 transition ${surfaceMode === 'night' ? 'bg-gray-700 text-white' : 'text-gray-500 hover:text-gray-300'}`}
            >Night</button>
            <button
              type="button"
              onClick={() => setSurfaceMode('paper')}
              className={`px-2 py-1 transition ${surfaceMode === 'paper' ? 'bg-[#E8E0D0] text-[#1C1917]' : 'text-gray-500 hover:text-gray-300'}`}
            >Paper</button>
          </div>
          <button
            type="button"
            onClick={() => setFocusMode((v) => !v)}
            className="text-xs px-2 py-1 rounded-md border border-gray-700 hover:bg-gray-800"
          >
            {focusMode ? 'Exit focus' : 'Focus'}
          </button>
          <button
            type="button"
            onClick={clearDraft}
            className="text-xs px-2 py-1 rounded-md border border-gray-700 text-gray-500 hover:text-red-400 hover:border-red-800 hover:bg-red-950/30 transition-colors"
          >
            Clear draft
          </button>
          <button
            className="lg:hidden btn btn-secondary text-xs"
            onClick={() => setShowPanel(true)}
          >
            Options
          </button>
        </div>
      </div>

      {/* B) Main content */}
      <div className="flex flex-1 min-h-0 relative">
        {/* B) Editor column: toolbar + textarea */}
        <div className="flex-1 flex flex-col min-w-0 px-4 md:px-6 py-4">
        <div className={`flex flex-col gap-3 flex-1 min-h-0 w-full ${focusMode ? 'max-w-[760px] mx-auto' : 'max-w-none'}`}>
          {/* Write / Preview / Review toggle */}
          <div className="flex items-center gap-2 flex-shrink-0">
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
            <button
              type="button"
              onClick={() => setMode('review')}
              className={`px-3 py-1 rounded-md text-sm ${
                mode === 'review'
                  ? 'bg-gray-800 text-white'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              Review
            </button>
          </div>

          {/* Ambient status row — write mode, fades in once body has content */}
          {mode === 'write' && (
            <div className={`flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500 flex-shrink-0 ${hasText ? 'opacity-100 transition-opacity duration-200' : 'opacity-0 pointer-events-none h-0 overflow-hidden'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <span>{review.words} words</span>
                <span>·</span>
                <span>{review.sentences} sentences</span>
                <span>·</span>
                <span>Readability: {review.readabilityLabel === 'N/A' ? '\u2014' : review.readabilityLabel}</span>
              </div>
              {!body.trim() ? (
                <span className="px-2 py-1 rounded-md bg-gray-900 border border-gray-800 text-gray-600">
                  Start writing
                </span>
              ) : (review.longSentenceCount + review.passiveCount) > 0 ? (
                <button
                  type="button"
                  onClick={() => { setMode('review'); setShowPanel(false); }}
                  className="px-2 py-1 rounded-md bg-gray-900 border border-gray-800 text-amber-300 hover:text-amber-200 hover:border-gray-700 transition-colors"
                >
                  {'\u26a0\ufe0f '}
                  {[
                    review.longSentenceCount > 0 && `${review.longSentenceCount} long ${review.longSentenceCount === 1 ? 'sentence' : 'sentences'}`,
                    review.passiveCount > 0 && `${review.passiveCount} passive`,
                  ].filter(Boolean).join(' · ')}
                </button>
              ) : (
                <span className="px-2 py-1 rounded-md bg-gray-900 border border-gray-800 text-emerald-300">
                  All good
                </span>
              )}
            </div>
          )}

          {/* Formatting toolbar — fades in once body has content */}
          <div className={`flex gap-2 py-1 overflow-x-auto flex-shrink-0 top-0 z-10 ${!hasText ? 'opacity-0 pointer-events-none h-0 overflow-hidden' : focusMode ? 'opacity-60 hover:opacity-100 transition' : 'opacity-100 transition-opacity duration-200'}`}>
            <button
              type="button"
              onClick={() => wrapOrInsertPlaceholder('**', '**', 'bold text', 'Bold applied')}
              className={TOOLBTN}
            >
              Bold
            </button>
            <button
              type="button"
              onClick={() => wrapOrInsertPlaceholder('*', '*', 'italic text', 'Italic applied')}
              className={TOOLBTN}
            >
              Italic
            </button>
            <button
              type="button"
              onClick={() => { insertHeaderSmart(); }}
              className={TOOLBTN}
            >
              Header
            </button>
            <button
              type="button"
              onClick={() => { setBody((prev) => prev + '\n\n---\n\n'); flash('Scene break inserted'); revealFormatting(); }}
              className={TOOLBTN}
            >
              Scene break
            </button>
          </div>
          <p id="writespace-editor-hints" className="text-xs text-gray-500 flex-shrink-0">
            Formatting is Markdown — use the toolbar, then Preview to see it.
          </p>

          {!hasText && mode === 'write' && (
            <p className="text-gray-500 text-sm text-center mt-8">
              Start writing — tools will appear automatically.
            </p>
          )}

          {mode === 'review' && (
            <p className="text-xs text-gray-500 flex-shrink-0">
              Suggestions appear in the side panel.
            </p>
          )}

          {mode === 'preview' ? (
            <div
              className={`flex-1 min-h-0 rounded-2xl p-4 md:p-5 ${surfaceMode === 'paper' ? PAPER_LIGHT : PAPER} ${EDITOR_TEXT} ${EDITOR_LEADING} ${EDITOR_FONT} ${EDITOR_TRACKING} ${surfaceMode === 'paper' ? 'text-[#1C1917]' : 'text-gray-200'} overflow-y-auto`}
              onClick={(e) => {
                // Grammar underline click → switch to Review and jump to range
                const gEl = (e.target as HTMLElement).closest('[data-ws-grammar-offset]');
                if (gEl) {
                  const offset = Number(gEl.getAttribute('data-ws-grammar-offset'));
                  const length = Number(gEl.getAttribute('data-ws-grammar-length'));
                  setMode('review');
                  setTimeout(() => jumpToRange(offset, length), 50);
                  return;
                }
                // Sentence / paragraph underline click
                const el = (e.target as HTMLElement).closest('[data-ws-id]');
                const id = el?.getAttribute('data-ws-id');
                if (!id) return;
                const s = review.suggestions.find((s) => s.id === id);
                if (s) handleSuggestionClick(s.id, s.kind, s.matchText, 'review');
              }}
            >
              <div className={`${surfaceMode === 'paper' ? 'text-[#1C1917]' : 'text-gray-200'} ${EDITOR_TEXT} ${EDITOR_LEADING} ${EDITOR_FONT} ${EDITOR_TRACKING} space-y-4`}>
                {renderPreview(body)}
              </div>
            </div>
          ) : (
            <div
              className="relative flex-1 min-h-0"
              onMouseMove={mode === 'write' ? (e) => {
                // Works for both ws-long (pointer-events:auto) and ws-repeat/ws-filler spans.
                // Events from those spans bubble to this wrapper even though the overlay div is pointer-events:none.
                const el = (e.target as HTMLElement).closest?.('[data-ws-hint]') as HTMLElement | null;
                if (!el) { if (wsTip.show) setWsTip((s) => ({ ...s, show: false })); return; }
                const label = el.getAttribute('data-ws-label') ?? '';
                const hint  = el.getAttribute('data-ws-hint')  ?? '';
                setWsTip({ show: true, x: e.clientX, y: e.clientY, label, hint });
              } : undefined}
              onMouseLeave={mode === 'write' ? () => setWsTip((s) => ({ ...s, show: false })) : undefined}
              onClick={mode === 'write' ? (e) => {
                setWsTip((s) => ({ ...s, show: false }));
                const target = e.target as HTMLElement;

                // Long sentence → try inline split first; fall back to Review
                const longEl = target.closest?.('[data-ws-long="1"]') as HTMLElement | null;
                if (longEl) {
                  const rawSentence = longEl.getAttribute('data-ws-sentence') ?? '';
                  if (rawSentence) {
                    const newBody = splitLongSentence(body, rawSentence);
                    if (newBody !== body) {
                      setBody(newBody);
                      requestAnimationFrame(() => textareaRef.current?.focus());
                      return;
                    }
                  }
                  // Fallback: no good split point found → go to Review
                  const key = longEl.getAttribute('data-ws-key') ?? '';
                  const match = review.suggestions.find(
                    (s) => s.kind === 'sentence' && s.matchKey && s.matchKey === key
                  );
                  if (match) {
                    handleSuggestionClick(match.id, match.kind, match.matchText, 'review');
                  } else {
                    setMode('review');
                    setShowPanel(false);
                  }
                  return;
                }

                // Fixable inline mark (ws-repeat, single-word ws-filler) → quick fix
                const fixEl = target.closest?.('[data-ws-fix-type]') as HTMLElement | null;
                if (fixEl) {
                  const fixType = fixEl.getAttribute('data-ws-fix-type') ?? '';
                  const offset  = parseInt(fixEl.getAttribute('data-ws-offset')  ?? '-1', 10);
                  const length  = parseInt(fixEl.getAttribute('data-ws-length')  ?? '0',  10);
                  applyQuickFix(fixType, offset, length);
                  return;
                }

                // Non-fixable marks (multi-word filler etc.) → just refocus the textarea
                if (target.closest?.('[data-ws-hint]')) {
                  textareaRef.current?.focus();
                }
              } : undefined}
            >
              <textarea
                ref={textareaRef}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder="Start writing..."
                spellCheck={true}
                autoCorrect="on"
                autoCapitalize="sentences"
                inputMode="text"
                aria-label="WriteSpace editor"
                aria-describedby="writespace-editor-hints"
                onScroll={(e) => {
                  if (overlayRef.current) overlayRef.current.scrollTop = e.currentTarget.scrollTop;
                }}
                className={`absolute inset-0 w-full h-full rounded-2xl p-4 md:p-5 ${surfaceMode === 'paper' ? PAPER_LIGHT : PAPER} ${EDITOR_TEXT} ${EDITOR_LEADING} ${EDITOR_FONT} ${EDITOR_TRACKING} ${surfaceMode === 'paper' ? 'text-[#1C1917] caret-emerald-700 ws-paper-surface' : 'text-gray-200 caret-emerald-300 placeholder-gray-600'} resize-none outline-none`}
              />
              {mode === 'write' && renderWriteOverlay(body)}
            </div>
          )}

          {mode === 'write' && (
            <div className={hasText ? 'opacity-100 transition-opacity duration-200' : 'opacity-0 pointer-events-none h-0 overflow-hidden'}>
              {renderLiveChecks()}
            </div>
          )}
        </div>{/* end focus wrapper */}
        </div>

        {/* C) Desktop sidebar */}
        <aside
          className={`hidden lg:flex flex-col w-[340px] shrink-0 border-l border-gray-800 bg-gray-950 p-4 overflow-y-auto${focusMode ? ' opacity-0 pointer-events-none' : ''}`}
        >
          {renderSidebarContent('desktop')}
        </aside>
      </div>

      {/* D) Mobile slide-over drawer */}
      {showPanel && !focusMode && (
        <div className="fixed inset-0 z-40 flex">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setShowPanel(false)}
          />
          <div className="relative ml-auto w-[85%] max-w-sm h-full bg-gray-950 border-l border-gray-800 p-4 overflow-y-auto">
            {renderSidebarContent('drawer')}
          </div>
        </div>
      )}

      {/* E) Mobile sticky bottom bar */}
      <div className="lg:hidden sticky bottom-0 border-t border-gray-800 bg-gray-950 px-4 py-3 flex gap-2">
        <button
          onClick={handlePublishToCommons}
          disabled={publishing || !body.trim()}
          className="flex-1 text-sm h-11 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white font-semibold transition disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Publish
        </button>
        <button
          className="btn btn-secondary flex-1 text-sm h-11 rounded-xl"
          onClick={() => setMode('preview')}
        >
          Preview
        </button>
        <button
          className="btn btn-secondary flex-1 text-sm h-11 rounded-xl"
          onClick={() => setMode('review')}
        >
          Review
        </button>
      </div>

      {mode === 'write' && wsTip.show && (
        <div className="ws-tip" style={{ left: wsTip.x, top: wsTip.y }}>
          <div style={{ fontWeight: 600, color: '#f3f4f6' }}>{wsTip.label}</div>
          {wsTip.hint && <div style={{ color: '#d1d5db', marginTop: 2 }}>{wsTip.hint}</div>}
        </div>
      )}
    </div>
  );
}

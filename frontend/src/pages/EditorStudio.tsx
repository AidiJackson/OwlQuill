import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ImageIcon, Loader2, UploadCloud, Wand2, X, XCircle } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Character } from '@/lib/types';
import {
  EDITOR_DEFAULT_STRENGTH,
  EDITOR_MAX_SOURCE_IMAGES,
  EDITOR_MAX_STRENGTH,
  EDITOR_MIN_STRENGTH,
  EDITOR_JOB_POLL_MS,
  EDITOR_PROVIDERS,
  EDITOR_PROVIDER_HINTS,
  EDITOR_PROVIDER_LABELS,
  type EditorGenerateResult,
  type EditorJob,
  acceptSourceFiles,
  buildEditorFormData,
  describeEditorJob,
  isEditorJobActive,
  loadEditorProvider,
  resolveEditorImageUrl,
  saveEditorProvider,
  validateEditorForm,
} from '@/features/editorStudio/editorGenerate';

/**
 * Editor Studio — Sprint E1 foundation.
 *
 * Edits/transforms 1-3 EXISTING character images with a prompt via the
 * gpt-image edit backend (POST /editor/generate). Character-preserving
 * transformation only — separate from Canon Studio generation and the
 * Adult Studio pipeline.
 */
export default function EditorStudio() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.is_admin;

  const [characters, setCharacters] = useState<Character[]>([]);
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [strength, setStrength] = useState(EDITOR_DEFAULT_STRENGTH);
  const [provider, setProvider] = useState(() => loadEditorProvider(localStorage));
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EditorGenerateResult | null>(null);
  const [job, setJob] = useState<EditorJob | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Poll an active self-hosted job until it reaches a terminal state (E5).
  useEffect(() => {
    if (!job || !isEditorJobActive(job.state)) return;
    const timer = setInterval(async () => {
      try {
        const next = await apiClient.editorJobGet(job.id);
        setJob(next);
      } catch (e) {
        console.error('EDITOR_JOB_POLL_ERROR', e);
      }
    }, EDITOR_JOB_POLL_MS);
    return () => clearInterval(timer);
  }, [job]);

  // Resume the latest self-hosted job on mount/refresh (admin only).
  useEffect(() => {
    if (!isAdmin || !characterId) return;
    apiClient
      .editorJobLatest(characterId)
      .then((latest) => {
        if (latest) setJob(latest);
      })
      .catch(() => undefined);
  }, [isAdmin, characterId]);

  useEffect(() => {
    apiClient
      .getCharacters()
      .then((chars) => {
        setCharacters(chars);
        if (chars.length === 0) return;
        // Default to Summer for admin/test mode, else the first character.
        const summer = isAdmin ? chars.find((c) => c.name.toLowerCase().startsWith('summer')) : undefined;
        setCharacterId((summer ?? chars[0]).id);
      })
      .catch(() => setError('Could not load your characters.'));
  }, [isAdmin]);

  // Object-URL previews for the selected source files.
  useEffect(() => {
    const urls = files.map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [files]);

  const addFiles = useCallback((incoming: File[]) => {
    setFiles((prev) => acceptSourceFiles(prev, incoming));
    setError(null);
  }, []);

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleGenerate() {
    const validationError = validateEditorForm({
      characterId,
      prompt,
      fileCount: files.length,
      provider: isAdmin ? provider : 'gpt-image',
    });
    if (validationError) {
      setError(validationError);
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const effectiveProvider = isAdmin ? provider : 'gpt-image';
      const form = buildEditorFormData({
        characterId: characterId!,
        prompt,
        provider: effectiveProvider,
        strength,
        files,
      });
      if (effectiveProvider === 'self_hosted') {
        // Async fire-and-poll (E5): the request returns immediately with a
        // job; polling renders the result. No multi-minute blocking request.
        setJob(await apiClient.editorJobStart(form));
      } else {
        const res = await apiClient.editorGenerate(form);
        setResult(res);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Editor generation failed.');
    } finally {
      setLoading(false);
    }
  }

  async function handleCancelJob() {
    if (!job || !isEditorJobActive(job.state)) return;
    try {
      setJob(await apiClient.editorJobCancel(job.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Cancel failed.');
    }
  }

  const jobOutcome = describeEditorJob(job);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <div className="max-w-3xl mx-auto px-4 py-8">
        <Link to="/" className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 mb-6">
          <ArrowLeft className="w-4 h-4" /> Back
        </Link>

        <div className="flex items-center gap-3 mb-2">
          <Wand2 className="w-6 h-6 text-violet-400" />
          <h1 className="text-2xl font-semibold tracking-tight">Editor Studio</h1>
          <span className="text-[11px] font-semibold uppercase tracking-wide text-violet-300 border border-violet-800/60 bg-violet-900/30 rounded-full px-2 py-0.5">
            Beta
          </span>
        </div>
        <p className="text-sm text-gray-400 mb-8">
          Transform an existing character image — same character, new scene or outfit. Upload 1–
          {EDITOR_MAX_SOURCE_IMAGES} source images and describe the change.
        </p>

        {/* Character select */}
        <label className="block text-sm font-medium text-gray-300 mb-1.5">Character</label>
        <select
          value={characterId ?? ''}
          onChange={(e) => setCharacterId(e.target.value ? Number(e.target.value) : null)}
          className="w-full mb-6 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-600"
        >
          <option value="" disabled>
            Select a character…
          </option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>

        {/* Source images: drag/drop uploader */}
        <label className="block text-sm font-medium text-gray-300 mb-1.5">
          Source images <span className="text-gray-500">(1–{EDITOR_MAX_SOURCE_IMAGES})</span>
        </label>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            addFiles(Array.from(e.dataTransfer.files));
          }}
          onClick={() => fileInputRef.current?.click()}
          className={`mb-3 border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
            dragOver ? 'border-violet-500 bg-violet-900/10' : 'border-gray-800 hover:border-gray-700 bg-gray-900/50'
          }`}
        >
          <UploadCloud className="w-6 h-6 mx-auto mb-2 text-gray-500" />
          <p className="text-sm text-gray-400">
            Drag &amp; drop images here, or <span className="text-violet-400">browse</span>
          </p>
          <p className="text-xs text-gray-600 mt-1">PNG, JPEG, or WebP</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            className="hidden"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []));
              e.target.value = '';
            }}
          />
        </div>
        {files.length > 0 && (
          <div className="flex gap-3 mb-6">
            {files.map((f, i) => (
              <div key={`${f.name}-${i}`} className="relative w-24 h-24 rounded-lg overflow-hidden border border-gray-800">
                <img src={previews[i]} alt={f.name} className="w-full h-full object-cover" />
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  className="absolute top-1 right-1 bg-black/70 rounded-full p-0.5 text-gray-300 hover:text-white"
                  aria-label={`Remove ${f.name}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Prompt */}
        <label className="block text-sm font-medium text-gray-300 mb-1.5">Prompt</label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="e.g. Summer in a different scene on the beach wearing a blue bikini."
          className="w-full mb-6 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm resize-y focus:outline-none focus:border-violet-600"
        />

        {/* Strength slider */}
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-sm font-medium text-gray-300">Transformation strength</label>
          <span className="text-sm text-gray-400 tabular-nums">{strength.toFixed(2)}</span>
        </div>
        <input
          type="range"
          min={EDITOR_MIN_STRENGTH}
          max={EDITOR_MAX_STRENGTH}
          step={0.05}
          value={strength}
          onChange={(e) => setStrength(Number(e.target.value))}
          className="w-full mb-1 accent-violet-500"
          aria-label="Transformation strength"
        />
        <div className="flex justify-between text-xs text-gray-600 mb-6">
          <span>Subtle (preserve more)</span>
          <span>Stronger change</span>
        </div>

        {/* Provider selector — admin only */}
        {isAdmin && (
          <>
            <label className="block text-sm font-medium text-gray-300 mb-1.5">
              Provider <span className="text-gray-500">(admin)</span>
            </label>
            <select
              value={provider}
              onChange={(e) => {
                setProvider(e.target.value as typeof provider);
                saveEditorProvider(localStorage, e.target.value);
              }}
              className="w-full mb-6 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-600"
            >
              {EDITOR_PROVIDERS.map((p) => (
                <option key={p} value={p}>
                  {EDITOR_PROVIDER_LABELS[p]}
                </option>
              ))}
            </select>
            {EDITOR_PROVIDER_HINTS[provider as keyof typeof EDITOR_PROVIDER_HINTS] && (
              <p className="-mt-4 mb-6 text-xs text-violet-300/80">
                {EDITOR_PROVIDER_HINTS[provider as keyof typeof EDITOR_PROVIDER_HINTS]}
              </p>
            )}
          </>
        )}

        {/* Generate */}
        <button
          type="button"
          onClick={handleGenerate}
          disabled={loading || isEditorJobActive(job?.state)}
          className="w-full inline-flex items-center justify-center gap-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-medium rounded-lg px-4 py-2.5 text-sm transition-colors"
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" /> Editing image…
            </>
          ) : (
            <>
              <Wand2 className="w-4 h-4" /> Generate edit
            </>
          )}
        </button>

        {/* Error state */}
        {error && (
          <div className="mt-4 flex items-start gap-2 text-sm text-red-300 border border-red-900/60 bg-red-950/40 rounded-lg px-3 py-2.5">
            <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Async self-hosted job (E5): running / needs_review / success / failed */}
        {jobOutcome && (
          <div className="mt-6">
            {jobOutcome.kind === 'running' && (
              <div className="flex items-center justify-between text-sm border border-violet-900/60 bg-violet-950/30 rounded-lg px-3 py-2.5">
                <span className="flex items-center gap-2 text-violet-200">
                  <Loader2 className="w-4 h-4 animate-spin" /> {jobOutcome.message}
                </span>
                <button
                  type="button"
                  onClick={handleCancelJob}
                  className="text-red-300 hover:text-red-200 font-medium"
                >
                  Cancel
                </button>
              </div>
            )}
            {jobOutcome.kind === 'failed' && (
              <div className="flex items-start gap-2 text-sm text-red-300 border border-red-900/60 bg-red-950/40 rounded-lg px-3 py-2.5">
                <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                <span>{jobOutcome.message}</span>
              </div>
            )}
            {(jobOutcome.kind === 'success' || jobOutcome.kind === 'needs_review') && (
              <div>
                <h2 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
                  <ImageIcon className="w-4 h-4 text-violet-400" /> Result
                  {jobOutcome.kind === 'needs_review' && (
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-amber-300 border border-amber-800/60 bg-amber-900/30 rounded-full px-2 py-0.5">
                      Needs review
                    </span>
                  )}
                </h2>
                {jobOutcome.kind === 'needs_review' && (
                  <p className="text-xs text-amber-300/90 mb-3">{jobOutcome.message}</p>
                )}
                {jobOutcome.imageUrl && (
                  <img
                    src={jobOutcome.imageUrl}
                    alt={job?.prompt ?? 'Editor result'}
                    className="w-full rounded-xl border border-gray-800"
                  />
                )}
                <div className="mt-3 flex items-center justify-between text-sm">
                  <span className="text-gray-500">
                    Saved to the character's image library
                    {job?.image_id ? ` (image #${job.image_id})` : ''}.
                  </span>
                  {jobOutcome.imageUrl && (
                    <a
                      href={jobOutcome.imageUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="text-violet-400 hover:text-violet-300"
                    >
                      Open saved image
                    </a>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Output preview — render on success even if the URL key is absent,
            so a saved image never shows as a silent/false failure. */}
        {result?.success && (
          <div className="mt-8">
            <h2 className="text-sm font-medium text-gray-300 mb-3 flex items-center gap-2">
              <ImageIcon className="w-4 h-4 text-violet-400" /> Result
            </h2>
            {resolveEditorImageUrl(result) && (
              <img
                src={resolveEditorImageUrl(result)!}
                alt={result.prompt}
                className="w-full rounded-xl border border-gray-800"
              />
            )}
            <div className="mt-3 flex items-center justify-between text-sm">
              <span className="text-gray-500">
                Saved to the character's image library
                {result.image ? ` (image #${result.image.id})` : ''}.
              </span>
              {resolveEditorImageUrl(result) && (
                <a
                  href={resolveEditorImageUrl(result)!}
                  target="_blank"
                  rel="noreferrer"
                  className="text-violet-400 hover:text-violet-300"
                >
                  Open saved image
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

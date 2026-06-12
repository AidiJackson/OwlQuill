/**
 * Editor Studio — pure UI logic (Sprint E1).
 *
 * Editor Studio transforms 1-3 EXISTING character images with a prompt via
 * POST /editor/generate (gpt-image edit). This module holds only pure,
 * DOM-free logic so it is unit-testable in the node vitest env.
 */

export const EDITOR_MIN_STRENGTH = 0.1;
export const EDITOR_MAX_STRENGTH = 0.5;
export const EDITOR_DEFAULT_STRENGTH = 0.25;
export const EDITOR_MAX_SOURCE_IMAGES = 3;
export const EDITOR_DEFAULT_PROVIDER = 'gpt-image';

export const EDITOR_ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

/** Available editor providers (E2: grok; E4: self_hosted premium; admin-only in the UI, GPT default). */
export const EDITOR_PROVIDERS = ['gpt-image', 'grok', 'self_hosted'] as const;
export type EditorProvider = (typeof EDITOR_PROVIDERS)[number];

export const EDITOR_PROVIDER_LABELS: Record<EditorProvider, string> = {
  'gpt-image': 'GPT Image',
  grok: 'Grok',
  self_hosted: 'Self Hosted Premium',
};

/** Selector hint shown for providers that need explanation. */
export const EDITOR_PROVIDER_HINTS: Partial<Record<EditorProvider, string>> = {
  self_hosted: 'Best for unrestricted outfit, swimwear, lingerie, adult scene edits',
};

/** self_hosted runs a full RunPod transform on exactly one source image. */
export const SELF_HOSTED_MAX_SOURCE_IMAGES = 1;

const PROVIDER_STORAGE_KEY = 'ficshon.editor_studio.provider';

/** Minimal storage interface so persistence is testable without a DOM. */
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export function isEditorProvider(value: string | null): value is EditorProvider {
  return !!value && (EDITOR_PROVIDERS as readonly string[]).includes(value);
}

/** Load the persisted provider selection; falls back to the GPT default. */
export function loadEditorProvider(storage: KeyValueStorage): EditorProvider {
  const stored = storage.getItem(PROVIDER_STORAGE_KEY);
  return isEditorProvider(stored) ? stored : EDITOR_DEFAULT_PROVIDER;
}

/** Persist the provider selection (no-op for unknown values). */
export function saveEditorProvider(storage: KeyValueStorage, provider: string): void {
  if (isEditorProvider(provider)) storage.setItem(PROVIDER_STORAGE_KEY, provider);
}

export interface EditorGenerateResult {
  success: boolean;
  image_url: string | null;
  character_id: number;
  provider: string;
  prompt: string;
  strength: number;
  image: { id: number; file_path: string; url?: string } | null;
  error?: string | null;
}

// ── Async editor jobs (Sprint E5, self_hosted only) ─────────────────────────

export const EDITOR_JOB_POLL_MS = 5000;

export type EditorJobState = 'queued' | 'running' | 'completed' | 'failed';
export type EditorQualityStatus = 'pass' | 'needs_review' | 'failed';

export interface EditorJob {
  id: number;
  character_id: number;
  provider: string;
  prompt: string;
  state: EditorJobState | string;
  run_id: string;
  quality_status?: EditorQualityStatus | string | null;
  final_image_url?: string | null;
  image_id?: number | null;
  image?: { id: number; file_path: string; url?: string } | null;
  result?: { quality_reasons?: string[]; spend_usd?: number; [k: string]: unknown } | null;
  error?: string | null;
}

export function isEditorJobActive(state: string | null | undefined): boolean {
  return state === 'queued' || state === 'running';
}

export interface EditorJobOutcome {
  kind: 'running' | 'success' | 'needs_review' | 'failed';
  message: string;
  imageUrl: string | null;
}

/**
 * Map a job snapshot to what the UI should show. A completed job whose quality
 * gate said `needs_review` is NOT presented as a clean success — the image is
 * shown with a review warning instead (Sprint E5 Part B).
 */
export function describeEditorJob(job: EditorJob | null): EditorJobOutcome | null {
  if (!job) return null;
  if (isEditorJobActive(job.state)) {
    return {
      kind: 'running',
      message: 'Transforming on self-hosted GPU — this can take a few minutes…',
      imageUrl: null,
    };
  }
  const imageUrl = job.final_image_url ?? job.image?.url ?? null;
  if (job.state === 'completed') {
    if (job.quality_status === 'needs_review') {
      const reasons = job.result?.quality_reasons ?? [];
      return {
        kind: 'needs_review',
        message: `Result needs review${reasons.length ? `: ${reasons.join('; ')}` : '.'}`,
        imageUrl,
      };
    }
    return { kind: 'success', message: 'Transform complete.', imageUrl };
  }
  return {
    kind: 'failed',
    message: job.error || 'Editor job failed.',
    imageUrl: null,
  };
}

/**
 * Resolve the displayable image URL from an editor response, tolerating both
 * the top-level `image_url` and the nested `image.url` shape (E4.1).
 */
export function resolveEditorImageUrl(res: EditorGenerateResult | null): string | null {
  if (!res) return null;
  return res.image_url ?? res.image?.url ?? null;
}

/** Clamp strength into the allowed editor range [0.1, 0.5]. */
export function clampStrength(value: number): number {
  if (Number.isNaN(value)) return EDITOR_DEFAULT_STRENGTH;
  return Math.max(EDITOR_MIN_STRENGTH, Math.min(EDITOR_MAX_STRENGTH, value));
}

/**
 * Validate the editor form. Returns null when valid, otherwise a
 * human-readable error message.
 */
export function validateEditorForm(opts: {
  characterId: number | null;
  prompt: string;
  fileCount: number;
  provider?: string;
}): string | null {
  if (!opts.characterId) return 'Select a character first.';
  if (!opts.prompt.trim()) return 'Enter a prompt describing the change.';
  if (opts.fileCount < 1) return 'Add at least one source image.';
  if (opts.fileCount > EDITOR_MAX_SOURCE_IMAGES) {
    return `At most ${EDITOR_MAX_SOURCE_IMAGES} source images are allowed.`;
  }
  if (opts.provider === 'self_hosted' && opts.fileCount !== SELF_HOSTED_MAX_SOURCE_IMAGES) {
    return 'Self Hosted Premium transforms exactly 1 source image.';
  }
  return null;
}

/** Filter a dropped/selected file list to accepted image types, capped at the max. */
export function acceptSourceFiles(existing: File[], incoming: File[]): File[] {
  const merged = [...existing];
  for (const f of incoming) {
    if (!EDITOR_ACCEPTED_TYPES.includes(f.type)) continue;
    if (merged.length >= EDITOR_MAX_SOURCE_IMAGES) break;
    merged.push(f);
  }
  return merged;
}

/** Build the multipart FormData for POST /editor/generate. */
export function buildEditorFormData(opts: {
  characterId: number;
  prompt: string;
  provider: string;
  strength: number;
  files: File[];
}): FormData {
  const form = new FormData();
  form.append('character_id', String(opts.characterId));
  form.append('prompt', opts.prompt.trim());
  form.append('provider', opts.provider);
  form.append('strength', String(clampStrength(opts.strength)));
  for (const file of opts.files.slice(0, EDITOR_MAX_SOURCE_IMAGES)) {
    form.append('images', file);
  }
  return form;
}

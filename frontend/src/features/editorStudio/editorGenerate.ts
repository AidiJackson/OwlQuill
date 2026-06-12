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
}): string | null {
  if (!opts.characterId) return 'Select a character first.';
  if (!opts.prompt.trim()) return 'Enter a prompt describing the change.';
  if (opts.fileCount < 1) return 'Add at least one source image.';
  if (opts.fileCount > EDITOR_MAX_SOURCE_IMAGES) {
    return `At most ${EDITOR_MAX_SOURCE_IMAGES} source images are allowed.`;
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

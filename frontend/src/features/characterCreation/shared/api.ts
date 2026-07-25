/** Typed API helpers for the character visual endpoints. */
import type {
  CharacterCanonRead,
  CharacterDNARead,
  CharacterImageRead,
  IdentityPackResponse,
  IdentitySpec,
  SketchResponse,
  V2PackJob,
  V2PackResponse,
} from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

function getToken(): string | null {
  return localStorage.getItem('token');
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Something went wrong' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  if (response.status === 204) return null as T;
  return response.json();
}

/**
 * Resolve an image URL returned by the API to something the browser can load.
 *
 * In dev the Vite proxy handles `/static` → backend.
 * In production with a full VITE_API_BASE_URL, derive the backend origin.
 */
export function resolveImageUrl(url: string): string {
  if (!url) return '';
  if (url.startsWith('http')) return url;
  const apiBase = import.meta.env.VITE_API_BASE_URL || '';
  if (apiBase && !apiBase.startsWith('/')) {
    try {
      const origin = new URL(apiBase).origin;
      return `${origin}${url.startsWith('/') ? url : '/' + url}`;
    } catch {
      return url;
    }
  }
  return url;
}

// ── Character Image List ────────────────────────────────────────────
//
// Deliberately absent: a `listCharacterImages` helper. GET /characters/{id}/images
// is viewer-aware — it returns the owner's working set or the curated public
// gallery depending on who asks — and typing it as CharacterImageRead[] told a
// lie to every public viewer. It lives on apiClient as listCharacterImages(),
// returning CharacterGalleryImage[], and there is one client for it, not two.

export async function setCharacterAvatar(
  characterId: number,
  imageId: number,
): Promise<CharacterImageRead> {
  return request(`/characters/${characterId}/images/${imageId}/set-avatar`, {
    method: 'POST',
  });
}

// ── Character Visual API ────────────────────────────────────────────

export async function upsertDNA(
  characterId: number,
  data: {
    species?: string;
    gender_presentation?: string;
    visual_traits_json?: Record<string, unknown>;
    structural_profile_json?: Record<string, unknown>;
  },
): Promise<CharacterDNARead> {
  return request(`/characters/${characterId}/dna`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateIdentityPack(
  characterId: number,
  tweaks?: Record<string, string>,
  promptVibe?: string,
  identitySpec?: IdentitySpec | null,
): Promise<IdentityPackResponse> {
  return request(`/characters/${characterId}/identity-pack/generate`, {
    method: 'POST',
    body: JSON.stringify({
      tweaks: tweaks && Object.keys(tweaks).length > 0 ? tweaks : null,
      prompt_vibe: promptVibe || null,
      identity_spec: identitySpec || null,
    }),
  });
}

// ── V2 canon pack (S24AN) — default self-serve generation path ───────

export async function generateV2Pack(
  characterId: number,
  opts?: {
    dryRun?: boolean;
    maxSpend?: number;
    adminFallback?: boolean;
    providerOption?: 'option1' | 'option2';
  },
): Promise<V2PackResponse> {
  return request(`/characters/${characterId}/identity-canon/generate-v2-pack`, {
    method: 'POST',
    body: JSON.stringify({
      dry_run: opts?.dryRun ?? false,
      max_spend: opts?.maxSpend ?? 8,
      admin_fallback: opts?.adminFallback ?? false,
      provider_option: opts?.providerOption ?? 'option2',
    }),
  });
}

/**
 * Read the current identity canon for a character.
 *
 * Used by the timeout-recovery path: a long v2 generation can complete and
 * persist every slot server-side even when the HTTP response is severed by a
 * proxy/edge timeout. Re-reading the canon lets the UI detect that and recover
 * without regenerating (S24AQ).
 */
export async function getIdentityCanon(
  characterId: number,
): Promise<CharacterCanonRead> {
  return request(`/characters/${characterId}/identity-canon`);
}

// ── Async v2 pack jobs (Sprint 35) ───────────────────────────────────
// Submit returns immediately (202) with a job to poll; the heavy pipeline
// runs server-side in a detached process, so refreshes and closed tabs
// never cancel a generation.

export async function startV2PackJob(
  characterId: number,
  opts?: { maxSpend?: number; idempotencyKey?: string },
): Promise<V2PackJob> {
  return request(`/characters/${characterId}/identity-canon/generate-v2-pack/jobs`, {
    method: 'POST',
    body: JSON.stringify({
      provider_option: 'option2',
      max_spend: opts?.maxSpend ?? 8,
      idempotency_key: opts?.idempotencyKey ?? null,
    }),
  });
}

export async function getV2PackJob(
  characterId: number,
  jobId: string,
): Promise<V2PackJob> {
  return request(`/characters/${characterId}/identity-canon/pack-jobs/${jobId}`);
}

/** Latest job (any status) — lets a refreshed page rediscover an active run. */
export async function getLatestV2PackJob(
  characterId: number,
): Promise<V2PackJob | null> {
  return request(`/characters/${characterId}/identity-canon/pack-jobs/latest`);
}

/** Persist body morphology onto the canon before v2 generation reads it. */
export async function patchBodyCanon(
  characterId: number,
  data: { height?: string; build?: string },
): Promise<unknown> {
  return request(`/characters/${characterId}/identity-canon/body`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function lockFaceCanon(characterId: number): Promise<unknown> {
  return request(`/characters/${characterId}/identity-canon/face/lock`, { method: 'POST' });
}

export async function lockBodyCanon(characterId: number): Promise<unknown> {
  return request(`/characters/${characterId}/identity-canon/body/lock`, { method: 'POST' });
}

export async function generateMomentImage(
  characterId: number,
  data: Record<string, string>,
): Promise<CharacterImageRead> {
  return request(`/characters/${characterId}/images/generate`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function generateSceneImage(
  characterId: number,
  prompt: string,
  style: string = 'realistic',
): Promise<CharacterImageRead> {
  return request(`/characters/${characterId}/scene-images/generate`, {
    method: 'POST',
    body: JSON.stringify({ prompt, style }),
  });
}

export async function generateImage(
  characterId: number,
  prompt: string,
  includeCharacter: boolean,
  providerOption: 'option1' | 'option2' | 'option3' | 'option4' | 'option5' | 'option6',
  isCover = false,
): Promise<CharacterImageRead> {
  return request(`/characters/${characterId}/image-generator/generate`, {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      include_character: includeCharacter,
      provider_option: providerOption,
      is_cover: isCover,
    }),
  });
}

export async function generateIdentitySketch(
  characterId: number,
  style: string = 'pencil',
): Promise<SketchResponse> {
  return request(`/characters/${characterId}/identity-sketch/generate`, {
    method: 'POST',
    body: JSON.stringify({ style }),
  });
}

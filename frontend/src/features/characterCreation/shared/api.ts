/** Typed API helpers for the character visual endpoints. */
import type {
  CharacterDNARead,
  CharacterImageRead,
  IdentityPackResponse,
  IdentityPackAcceptResponse,
  IdentitySpec,
  SketchResponse,
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

export async function listCharacterImages(
  characterId: number,
): Promise<CharacterImageRead[]> {
  return request(`/characters/${characterId}/images`);
}

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

export async function acceptIdentityPack(
  characterId: number,
  packId: string,
): Promise<IdentityPackAcceptResponse> {
  return request(`/characters/${characterId}/identity-pack/accept`, {
    method: 'POST',
    body: JSON.stringify({ pack_id: packId }),
  });
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
  providerOption: 'option1' | 'option2',
  generateCover = false,
): Promise<CharacterImageRead> {
  return request(`/characters/${characterId}/image-generator/generate`, {
    method: 'POST',
    body: JSON.stringify({
      prompt,
      include_character: includeCharacter,
      provider_option: providerOption,
      generate_cover: generateCover,
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

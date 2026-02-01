/** Typed API helpers for the character visual endpoints. */
import type {
  CharacterDNARead,
  CharacterImageRead,
  IdentityPackResponse,
  IdentityPackAcceptResponse,
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
): Promise<IdentityPackResponse> {
  return request(`/characters/${characterId}/identity-pack/generate`, {
    method: 'POST',
    body: JSON.stringify({
      tweaks: tweaks && Object.keys(tweaks).length > 0 ? tweaks : null,
      prompt_vibe: promptVibe || null,
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

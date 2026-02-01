/** Types for the character creation onboarding flow. */

// ── Backend response types ──────────────────────────────────────────

export interface CharacterImageRead {
  id: number;
  character_id: number;
  kind: string;
  status: string;
  visibility: string;
  provider?: string;
  prompt_summary?: string;
  seed?: string;
  metadata_json?: Record<string, unknown>;
  file_path: string;
  url: string;
  created_at: string;
}

export interface CharacterDNARead {
  id: number;
  character_id: number;
  species?: string;
  gender_presentation?: string;
  visual_traits_json?: Record<string, unknown>;
  structural_profile_json?: Record<string, unknown>;
  style_permissions_json?: Record<string, unknown>;
  anchor_version: number;
  created_at: string;
  updated_at: string;
}

export interface IdentityPackResponse {
  pack_id: string;
  images: CharacterImageRead[];
}

export interface IdentityPackAcceptResponse {
  anchors: CharacterImageRead[];
  dna: CharacterDNARead | null;
}

// ── Flow state slices ───────────────────────────────────────────────

export interface CreationBasics {
  name: string;
  age: string;
  species: string;
  gender_presentation: string;
}

export interface CreationSeeds {
  traits: string[];
  vibeText: string;
}

export interface CreationProfile {
  short_bio: string;
  long_bio: string;
  tags: string;
  era: string;
  visibility: 'public' | 'friends' | 'private';
}

// ── Tweaks ──────────────────────────────────────────────────────────

export interface TweakCategory {
  key: string;
  label: string;
  options: { value: string; label: string }[];
}

export const TWEAK_CATEGORIES: TweakCategory[] = [
  {
    key: 'age_band',
    label: 'Age',
    options: [
      { value: 'younger', label: 'Younger' },
      { value: 'as-is', label: 'As-is' },
      { value: 'older', label: 'Older' },
    ],
  },
  {
    key: 'facial_structure',
    label: 'Structure',
    options: [
      { value: 'softer', label: 'Softer' },
      { value: 'balanced', label: 'Balanced' },
      { value: 'sharper', label: 'Sharper' },
    ],
  },
  {
    key: 'skin_texture',
    label: 'Texture',
    options: [
      { value: 'smoother', label: 'Smoother' },
      { value: 'natural', label: 'Natural' },
      { value: 'textured', label: 'Textured' },
    ],
  },
  {
    key: 'hair',
    label: 'Hair',
    options: [
      { value: 'keep', label: 'Keep' },
      { value: 'different style', label: 'Different style' },
      { value: 'different length', label: 'Different length' },
    ],
  },
  {
    key: 'expression',
    label: 'Expression',
    options: [
      { value: 'neutral', label: 'Neutral' },
      { value: 'calm', label: 'Calm' },
      { value: 'intense', label: 'Intense' },
    ],
  },
];

export const PERSONALITY_TRAITS = [
  'Brave',
  'Cunning',
  'Gentle',
  'Fierce',
  'Mysterious',
  'Loyal',
  'Rebellious',
  'Wise',
  'Playful',
  'Stoic',
  'Charismatic',
  'Reserved',
  'Passionate',
  'Calculated',
  'Compassionate',
  'Haunted',
];

export const STEP_LABELS = [
  'Basics',
  'Personality',
  'Generate',
  'Select',
  'Lock',
  'Details',
];

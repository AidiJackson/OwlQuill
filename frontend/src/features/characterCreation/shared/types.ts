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
  /** Which generation tier produced the final pack (A/B/C/stub). */
  tier_used?: 'A' | 'B' | 'C' | 'stub';
  /** True if the backend rewrote the user's description for consistency. */
  rewrite_applied?: boolean;
  /** Roles that failed moderation in earlier tiers, e.g. ["A:anchor_front"]. */
  blocked_roles?: string[];
}

export interface IdentityPackAcceptResponse {
  anchors: CharacterImageRead[];
  dna: CharacterDNARead | null;
}

// ── Identity Spec types ─────────────────────────────────────────────

export interface IdentityCore {
  hair_color: string;
  hair_length: string;
  eye_color: string;
  skin_tone: string;
  face_features: string[];
}

export interface IdentityBuild {
  body_type: string;
  height_band: string;
}

export interface WardrobeSpec {
  outfit_type: string;
  primary_color: string;
  secondary_color: string;
  footwear: string;
  accessory: string;
  notes: string;
}

export interface IdentitySpec {
  style: string;
  identity: IdentityCore;
  build: IdentityBuild;
  marks_accessories: { items: string[] };
  wardrobe: WardrobeSpec;
  extra_notes: string;
}

// ── Identity Spec option constants ──────────────────────────────────

export const HAIR_COLORS = ['Blonde', 'Brunette', 'Black', 'Red', 'Auburn', 'Silver', 'Platinum', 'Copper', 'Strawberry', 'Gray'];
export const HAIR_LENGTHS = ['Short', 'Medium', 'Long', 'Shaved'];
export const EYE_COLORS = ['Brown', 'Blue', 'Green', 'Hazel', 'Amber', 'Gray', 'Violet'];
export const SKIN_TONES = ['Fair', 'Light', 'Olive', 'Tan', 'Brown', 'Dark', 'Pale', 'Golden', 'Porcelain', 'Caramel'];
export const FACE_FEATURES = ['High cheekbones', 'Strong jaw', 'Dimples', 'Freckles', 'Sharp features', 'Soft features', 'Angular', 'Round face'];
export const BODY_TYPES = ['Slim', 'Athletic', 'Muscular', 'Curvy', 'Average', 'Stocky', 'Petite', 'Tall and lean'];
export const HEIGHT_BANDS = ['Short', 'Average', 'Tall'];
export const OUTFIT_TYPES = ['Dress', 'Suit', 'Casual', 'Armor', 'Uniform', 'Robes', 'Sportswear', 'Streetwear', 'Formal gown', 'Jacket and jeans'];
export const PRIMARY_COLORS = ['Black', 'White', 'Red', 'Blue', 'Navy', 'Green', 'Purple', 'Gold', 'Silver', 'Brown', 'Burgundy', 'Pink', 'Gray'];
export const FOOTWEAR_OPTIONS = ['Heels', 'Boots', 'Sneakers', 'Sandals', 'Loafers', 'Barefoot', 'Combat boots', 'Flats'];
export const ACCESSORY_OPTIONS = ['Necklace', 'Watch', 'Belt', 'Scarf', 'Hat', 'Gloves', 'Bracelet', 'Earrings'];
export const MARKS_ACCESSORIES = ['Glasses', 'Sunglasses', 'Tattoos', 'Scars', 'Piercings', 'Facial hair', 'Mask', 'Birthmark'];

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
  identitySpec: IdentitySpec | null;
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

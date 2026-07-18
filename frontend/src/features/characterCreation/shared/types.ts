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

// ── V2 canon pack (S24AN) ───────────────────────────────────────────
// The self-serve path now generates all 13 v2 canon cards directly instead of
// the legacy 4 anchors. A card maps 1:1 to a canon slot.

export interface V2PackCard {
  slot: string;
  section: 'face' | 'body';
  role: string;
  url?: string | null;
  status: string;          // planned | generated | skipped | gate_failed | error
  provider?: string | null;
  similarity?: number | null;
  estimated_cost?: number | null;
  prompt?: string | null;
  grounds_on?: string[] | null;
}

export interface V2PackMark {
  label: string;
  mark_id: string;
  detail_crop_url?: string | null;
  skipped?: boolean | null;
  estimated_cost?: number | null;
}

export interface V2PackResponse {
  pack_id: string;
  dry_run: boolean;
  cards: V2PackCard[];
  marks: V2PackMark[];
  total_spend: number;
  image_count: number;
  estimated_cost?: number | null;
  regenerations: string[];
  openai_fallback: string[];
  gate_failed: string[];
  errors: string[];
  clean_pass: boolean;
  stopped?: string | null;
}

// ── Async v2 pack jobs (Sprint 35) ──────────────────────────────────
// Generation runs as a background job; the wizard polls this view. A
// completed job embeds the same V2PackResponse the sync endpoint returned.

export type V2PackJobStatus = 'queued' | 'running' | 'completed' | 'failed';

export interface V2PackJob {
  job_id: string;
  character_id: number;
  status: V2PackJobStatus;
  stage?: string | null;
  progress_message?: string | null;
  progress_percent?: number | null;
  attempt_count: number;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  reused: boolean;
  /** Completed job predates an accepted/locked canon — never re-adopt it. */
  superseded?: boolean;
  result?: V2PackResponse | null;
}

// ── Identity canon read (GET /identity-canon) ───────────────────────
// Used for timeout recovery (S24AQ): if a long v2 generation request is
// severed by a proxy/edge timeout after the backend already persisted every
// slot, the UI re-reads the canon and reconstructs the pack instead of showing
// a false failure.

export interface FaceCanonData {
  face_front_image_url?: string | null;
  face_left_3q_image_url?: string | null;
  face_right_3q_image_url?: string | null;
  face_profile_image_url?: string | null;
  face_expression_image_url?: string | null;
  [key: string]: unknown;
}

export interface PermanentBodyMark {
  id: string;
  label: string;
  type?: string;
  detail_crop_url?: string | null;
  reference_image_url?: string | null;
}

export interface BodyCanonData {
  body_front_image_url?: string | null;
  body_left_image_url?: string | null;
  body_right_image_url?: string | null;
  body_back_image_url?: string | null;
  torso_front_image_url?: string | null;
  torso_side_image_url?: string | null;
  standing_relaxed_image_url?: string | null;
  seated_relaxed_image_url?: string | null;
  permanent_body_marks?: PermanentBodyMark[];
  [key: string]: unknown;
}

export interface CharacterCanonRead {
  id: number;
  character_id: number;
  status: string;
  face_canon?: FaceCanonData | null;
  body_canon?: BodyCanonData | null;
  face_locked: boolean;
  body_locked: boolean;
}

// Friendly labels for v2 canon slots, shared across creation steps.
export const V2_SLOT_LABELS: Record<string, string> = {
  face_front: 'Front Face',
  face_left_3q: 'Left ¾',
  face_right_3q: 'Right ¾',
  face_profile: 'Profile',
  face_expression: 'Expression',
  body_front: 'Body Front',
  body_left: 'Body Left',
  body_right: 'Body Right',
  body_back: 'Body Back',
  torso_front: 'Torso Front',
  torso_side: 'Torso Side',
  standing_relaxed: 'Standing',
  seated_relaxed: 'Seated',
};

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
  gender: string;
  age_band: string;
  species: Species;
  species_tells: string[];
  identity: IdentityCore;
  build: IdentityBuild;
  marks_accessories: { items: string[] };
  wardrobe: WardrobeSpec;  // accepted by backend but ignored — neutral outfit enforced
  extra_notes: string;

  // Facial geometry (B14) — all optional
  face_shape?: string;
  jaw_type?: string;
  cheekbone_type?: string;
  eye_shape?: string;
  eye_spacing?: string;
  brow_type?: string;
  nose_type?: string;
  lip_type?: string;
  hairline_type?: string;
  facial_hair_type?: string;

  // B15 — all optional
  hair_texture?: string;    // straight | wavy | curly | coily | messy
  hair_style?: string;      // loose | layered | tied_back | side_parted | slicked_back | short_cut
  eyebrow_shape?: string;   // soft | arched | straight | sharp | thick | thin

  // B16: Body morphology — all optional
  body_height?: 'short' | 'medium' | 'tall';
  body_build?: 'slim' | 'athletic' | 'muscular' | 'stocky' | 'heavy';
}

// ── Species ──────────────────────────────────────────────────────────

export type Species = 'human' | 'vampire' | 'werewolf' | 'witch' | 'demon' | 'angel' | 'fae' | 'other';

export const SPECIES_OPTIONS: { label: string; value: Species }[] = [
  { label: 'Human',     value: 'human'    },
  { label: 'Vampire',   value: 'vampire'  },
  { label: 'Werewolf',  value: 'werewolf' },
  { label: 'Witch',     value: 'witch'    },
  { label: 'Demon',     value: 'demon'    },
  { label: 'Angel',     value: 'angel'    },
  { label: 'Fae',       value: 'fae'      },
  { label: 'Other',     value: 'other'    },
];

/** Suggested chip-only tells per species. Underscores render as spaces in prompts. */
export const SPECIES_TELLS_MAP: Record<Species, string[]> = {
  human:    [],
  vampire:  ['subtle_fangs', 'predatory_gaze', 'faint_eye_glow', 'pallid_complexion'],
  werewolf: ['golden_eyes', 'claw_scars', 'rugged_features', 'wild_brows'],
  witch:    ['faint_sigils', 'luminous_irises', 'ink_stained_fingers', 'silver_streak'],
  demon:    ['subtle_horns', 'slit_pupils', 'ashen_skin', 'claw_tips'],
  angel:    ['luminous_irises', 'ethereal_glow', 'silver_streak', 'serene_expression'],
  fae:      ['pointed_ears', 'iridescent_skin', 'luminous_irises', 'floral_markings'],
  other:    ['glowing_eyes', 'unusual_markings', 'ethereal_glow', 'pointed_ears'],
};

// ── Identity Spec option constants ──────────────────────────────────

export const STYLE_OPTIONS = [
  { label: 'Realistic', value: 'realistic' },
  { label: 'Cinematic Realistic', value: 'cinematic' },
  { label: 'Illustration', value: 'illustration' },
  { label: 'Anime', value: 'anime' },
  { label: 'Comic', value: 'comic' },
  { label: '3D / Animated', value: '3d_animated' },
] as const;

// label = display text; value = canonical backend enum (lowercase)
export const GENDER_OPTIONS = [
  { label: 'Woman',      value: 'female' },
  { label: 'Man',        value: 'male'   },
  { label: 'Non-binary', value: 'other'  },
] as const;
export const AGE_BAND_OPTIONS = ['18-25', '26-35', '36-50', '50+'] as const;

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

// ── Facial geometry option constants (B14) ───────────────────────────

export const FACE_SHAPES = [
  { label: 'Oval',     value: 'oval'     },
  { label: 'Round',    value: 'round'    },
  { label: 'Square',   value: 'square'   },
  { label: 'Angular',  value: 'angular'  },
  { label: 'Long',     value: 'long'     },
] as const;

export const JAW_TYPES = [
  { label: 'Soft',    value: 'soft'   },
  { label: 'Narrow',  value: 'narrow' },
  { label: 'Square',  value: 'square' },
  { label: 'Sharp',   value: 'sharp'  },
] as const;

export const CHEEKBONE_TYPES = [
  { label: 'Subtle', value: 'subtle' },
  { label: 'High',   value: 'high'   },
  { label: 'Wide',   value: 'wide'   },
] as const;

export const EYE_SHAPES = [
  { label: 'Almond',    value: 'almond'   },
  { label: 'Round',     value: 'round'    },
  { label: 'Narrow',    value: 'narrow'   },
  { label: 'Deep-set',  value: 'deep_set' },
] as const;

export const EYE_SPACINGS = [
  { label: 'Close-set',  value: 'close_set'  },
  { label: 'Average',    value: 'average'    },
  { label: 'Wide-set',   value: 'wide_set'   },
] as const;

export const BROW_TYPES = [
  { label: 'Straight', value: 'straight' },
  { label: 'Arched',   value: 'arched'   },
  { label: 'Thick',    value: 'thick'    },
  { label: 'Sharp',    value: 'sharp'    },
] as const;

export const NOSE_TYPES = [
  { label: 'Straight',  value: 'straight'  },
  { label: 'Narrow',    value: 'narrow'    },
  { label: 'Broad',     value: 'broad'     },
  { label: 'Hooked',    value: 'hooked'    },
  { label: 'Roman',     value: 'roman'     },
  { label: 'Upturned',  value: 'upturned'  },
] as const;

export const LIP_TYPES = [
  { label: 'Thin',        value: 'thin'       },
  { label: 'Balanced',    value: 'balanced'   },
  { label: 'Full',        value: 'full'       },
  { label: 'Cupid bow',   value: 'cupid_bow'  },
] as const;

export const HAIRLINE_TYPES = [
  { label: 'Straight',     value: 'straight'    },
  { label: 'Messy',        value: 'messy'       },
  { label: "Widow's peak", value: 'widows_peak' },
  { label: 'Receding',     value: 'receding'    },
] as const;

export const FACIAL_HAIR_TYPES = [
  { label: 'None',       value: 'none'        },
  { label: 'Stubble',    value: 'stubble'     },
  { label: 'Mustache',   value: 'mustache'    },
  { label: 'Goatee',     value: 'goatee'      },
  { label: 'Short beard',  value: 'short_beard'  },
  { label: 'Full beard',   value: 'full_beard'   },
  { label: 'Long beard',   value: 'long_beard'   },
] as const;

// ── B15 option constants ─────────────────────────────────────────────

export const HAIR_TEXTURE_OPTIONS = [
  { label: 'Straight', value: 'straight' },
  { label: 'Wavy',     value: 'wavy'     },
  { label: 'Curly',    value: 'curly'    },
  { label: 'Coily',    value: 'coily'    },
  { label: 'Messy',    value: 'messy'    },
] as const;

export const HAIR_STYLE_OPTIONS = [
  { label: 'Loose',        value: 'loose'        },
  { label: 'Layered',      value: 'layered'      },
  { label: 'Tied back',    value: 'tied_back'    },
  { label: 'Side parted',  value: 'side_parted'  },
  { label: 'Slicked back', value: 'slicked_back' },
  { label: 'Short cut',    value: 'short_cut'    },
] as const;

export const EYEBROW_SHAPE_OPTIONS = [
  { label: 'Soft',     value: 'soft'     },
  { label: 'Arched',   value: 'arched'   },
  { label: 'Straight', value: 'straight' },
  { label: 'Sharp',    value: 'sharp'    },
  { label: 'Thick',    value: 'thick'    },
  { label: 'Thin',     value: 'thin'     },
] as const;

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

// ── Identity Sketch ──────────────────────────────────────────────────

export interface SketchResponse {
  image_url: string;
  image_id: number;
  style: string;
  prompt_preview: string;
  provider_used?: string;
}

export const SKETCH_STYLES = [
  { value: 'pencil',   label: 'Pencil',   description: 'Fine graphite lines, delicate hatching' },
  { value: 'charcoal', label: 'Charcoal', description: 'Bold strokes, dramatic shading' },
  { value: 'dossier',  label: 'Dossier',  description: 'Clean line art, official identity aesthetic' },
] as const;

export type SketchStyle = 'pencil' | 'charcoal' | 'dossier';

export const STEP_LABELS = [
  'Basics',
  'Interview',
  'Sketch',
  'Identity Pack',
  'Choose Canon',
  'Dossier',
];

// ── B16: Body morphology ─────────────────────────────────────────────

export type BodyHeight = 'short' | 'medium' | 'tall';
export type BodyBuild = 'slim' | 'athletic' | 'muscular' | 'stocky' | 'heavy';

export interface BodyMorphology {
  height: BodyHeight;
  build: BodyBuild;
}

export const BODY_HEIGHT_OPTIONS: { value: BodyHeight; label: string }[] = [
  { value: 'short',  label: 'Short'   },
  { value: 'medium', label: 'Medium'  },
  { value: 'tall',   label: 'Tall'    },
];

export const BODY_BUILD_OPTIONS: { value: BodyBuild; label: string }[] = [
  { value: 'slim',      label: 'Slim'      },
  { value: 'athletic',  label: 'Athletic'  },
  { value: 'muscular',  label: 'Muscular'  },
  { value: 'stocky',    label: 'Stocky'    },
  { value: 'heavy',     label: 'Heavy'     },
];

export const DEFAULT_BODY_MORPHOLOGY: BodyMorphology = {
  height: 'medium',
  build: 'athletic',
};

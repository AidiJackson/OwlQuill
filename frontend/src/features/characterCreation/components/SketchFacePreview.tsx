/**
 * SketchFacePreview — progressive SVG face that builds live as the
 * sketch interview is answered.  No AI calls; purely local state rendering.
 *
 * Layers responded to: face_shape, jaw_type, eye_shape, nose_type,
 * lip_type, hair_length, hairline_type, facial_hair_type, eye_color.
 */

import type { IdentitySpec } from '../shared/types';

// ── Face outline paths (viewBox 0 0 100 130) ─────────────────────────

const FACE_OUTLINE: Record<string, string> = {
  oval:    'M50,12 C28,12 14,35 14,65 C14,95 28,115 50,115 C72,115 86,95 86,65 C86,35 72,12 50,12 Z',
  round:   'M50,18 C30,18 16,40 16,64 C16,88 30,110 50,110 C70,110 84,88 84,64 C84,40 70,18 50,18 Z',
  square:  'M20,18 L80,18 C84,18 86,22 86,28 L86,82 C86,96 72,112 50,112 C28,112 14,96 14,82 L14,28 C14,22 16,18 20,18 Z',
  angular: 'M50,10 L82,28 L88,66 L72,100 L50,112 L28,100 L12,66 L18,28 Z',
  long:    'M50,8 C32,8 18,30 18,68 C18,104 32,122 50,122 C68,122 82,104 82,68 C82,30 68,8 50,8 Z',
  _default:'M50,12 C28,12 14,35 14,65 C14,95 28,115 50,115 C72,115 86,95 86,65 C86,35 72,12 50,12 Z',
};

// Jaw accent paths (drawn below main face outline for extra shaping)
const JAW_ACCENTS: Record<string, string | null> = {
  sharp:   'M28,100 Q50,118 72,100',
  square:  'M24,95 L50,108 L76,95',
  soft:    'M30,100 Q50,113 70,100',
  narrow:  'M34,98 Q50,112 66,98',
};

// ── Eye paths (L = left eye, R = right eye) ──────────────────────────

type EyePaths = { L: string; R: string };

const EYE_SHAPES: Record<string, EyePaths> = {
  almond: {
    L: 'M26,52 Q34,46 42,52 Q34,58 26,52 Z',
    R: 'M58,52 Q66,46 74,52 Q66,58 58,52 Z',
  },
  round: {
    L: 'M27,52 A7,7 0 1,0 41,52 A7,7 0 1,0 27,52 Z',
    R: 'M59,52 A7,7 0 1,0 73,52 A7,7 0 1,0 59,52 Z',
  },
  narrow: {
    L: 'M26,52 Q34,49 42,52 Q34,55 26,52 Z',
    R: 'M58,52 Q66,49 74,52 Q66,55 58,52 Z',
  },
  deep_set: {
    L: 'M26,53 Q34,47 42,53 Q34,59 26,53 Z',
    R: 'M58,53 Q66,47 74,53 Q66,59 58,53 Z',
  },
};

// Brow paths (eyebrow lines above each eye)
const BROW_SHAPES: Record<string, EyePaths> = {
  straight: {
    L: 'M26,44 L42,44',
    R: 'M58,44 L74,44',
  },
  arched: {
    L: 'M26,46 Q34,40 42,46',
    R: 'M58,46 Q66,40 74,46',
  },
  thick: {
    L: 'M25,45 Q34,41 43,45',
    R: 'M57,45 Q66,41 75,45',
  },
  sharp: {
    L: 'M26,46 L34,41 L42,45',
    R: 'M58,45 L66,41 L74,46',
  },
};

// ── Nose paths ────────────────────────────────────────────────────────

const NOSE_PATHS: Record<string, string> = {
  straight: 'M47,62 L47,73 M53,62 L53,73 M47,73 Q50,75 53,73',
  narrow:   'M48,62 L48,73 M52,62 L52,73 M48,73 Q50,75 52,73',
  broad:    'M45,63 L45,73 M55,63 L55,73 M44,73 Q50,76 56,73',
  hooked:   'M47,62 C47,67 46,71 47,73 M53,62 C53,67 54,71 53,73 M47,73 Q50,75 53,73',
  roman:    'M47,62 C47,64 46,66 47,68 L47,73 M53,62 C53,64 54,66 53,68 L53,73 M47,73 Q50,75 53,73',
  upturned: 'M47,65 L47,72 Q44,74 44,73 M53,65 L53,72 Q56,74 56,73',
  _default: 'M47,62 L47,73 M53,62 L53,73 M47,73 Q50,75 53,73',
};

// ── Lip paths ─────────────────────────────────────────────────────────

const LIP_PATHS: Record<string, string> = {
  thin:       'M40,83 Q50,81 60,83',
  balanced:   'M40,83 Q45,80 50,80 Q55,80 60,83 Q55,87 50,87 Q45,87 40,83 Z',
  full:       'M40,82 Q45,77 50,77 Q55,77 60,82 Q55,89 50,90 Q45,89 40,82 Z',
  cupid_bow:  'M40,83 Q44,81 47,79 Q50,77 53,79 Q56,81 60,83 Q55,88 50,89 Q45,88 40,83 Z',
  _default:   'M40,83 Q50,81 60,83',
};

// ── Hair paths ────────────────────────────────────────────────────────

const HAIR_PATHS: Record<string, string | null> = {
  Shaved:  null,
  Short:   'M14,55 Q14,12 50,8 Q86,12 86,55 Q78,30 50,26 Q22,30 14,55 Z',
  Medium:  'M13,65 Q11,15 50,7 Q89,15 87,65 Q84,38 68,28 L68,78 Q84,65 87,65 M13,65 Q16,50 32,28 L32,78 Q16,65 13,65 Z',
  Long:    'M12,80 Q8,15 50,6 Q92,15 88,80 Q85,40 70,28 L70,110 Q85,90 88,80 M12,80 Q15,45 30,28 L30,110 Q15,90 12,80 Z',
};

const HAIRLINE_PATHS: Record<string, string | null> = {
  straight:    null,  // normal hairline — use base hair path
  messy:       'M20,26 Q28,22 36,25 Q44,20 50,24 Q56,20 64,25 Q72,22 80,26',
  widows_peak: 'M20,28 Q35,24 50,18 Q65,24 80,28',
  receding:    'M22,32 Q36,26 50,26 Q64,26 78,32',
};

// ── Facial hair paths ─────────────────────────────────────────────────

const FACIAL_HAIR_PATHS: Record<string, string | null> = {
  none:       null,
  stubble:    null,  // rendered via dots/opacity, not a path
  mustache:   'M40,80 Q45,77 50,78 Q55,77 60,80 Q55,82 50,82 Q45,82 40,80 Z',
  goatee:     'M44,84 Q50,90 56,84 Q53,96 50,98 Q47,96 44,84 Z',
  short_beard:'M28,88 Q34,100 50,106 Q66,100 72,88 Q80,76 78,68 Q64,78 50,80 Q36,78 22,68 Q20,76 28,88 Z',
  full_beard: 'M26,85 Q30,102 50,110 Q70,102 74,85 Q80,70 78,60 Q64,74 50,76 Q36,74 22,60 Q20,70 26,85 Z',
  long_beard: 'M24,84 Q26,104 50,118 Q74,104 76,84 Q82,65 78,55 Q64,72 50,74 Q36,72 22,55 Q18,65 24,84 Z',
};

// ── Ear paths ─────────────────────────────────────────────────────────

const EAR_PATHS = {
  L: 'M14,57 Q8,62 8,70 Q8,78 14,83',
  R: 'M86,57 Q92,62 92,70 Q92,78 86,83',
};

// ── Eye colour mapping ────────────────────────────────────────────────

const EYE_COLOR_MAP: Record<string, string> = {
  Brown:  '#8B5E3C',
  Blue:   '#4A90D9',
  Green:  '#4CAF6B',
  Hazel:  '#8B7355',
  Amber:  '#C8872A',
  Gray:   '#8A9BA8',
  Violet: '#7C5CBF',
};

// ── Helpers ───────────────────────────────────────────────────────────

function pct(v: boolean | string | undefined): number {
  return v ? 1 : 0.18;
}

// ── Component ─────────────────────────────────────────────────────────

interface Props {
  spec: Partial<IdentitySpec>;
}

export default function SketchFacePreview({ spec }: Props) {
  const faceOutlinePath = FACE_OUTLINE[spec.face_shape ?? '_default'] ?? FACE_OUTLINE._default;
  const jawAccent = spec.jaw_type ? JAW_ACCENTS[spec.jaw_type] : null;
  const eyes = EYE_SHAPES[spec.eye_shape ?? ''] ?? EYE_SHAPES.almond;
  const brows = spec.brow_type ? BROW_SHAPES[spec.brow_type] : null;
  const nosePath = NOSE_PATHS[spec.nose_type ?? '_default'] ?? NOSE_PATHS._default;
  const lipPath = LIP_PATHS[spec.lip_type ?? '_default'] ?? LIP_PATHS._default;

  const hairLength = spec.identity?.hair_length ?? '';
  const hairPath = hairLength ? (HAIR_PATHS[hairLength] ?? null) : null;
  const hairlinePath = spec.hairline_type ? (HAIRLINE_PATHS[spec.hairline_type] ?? null) : null;
  const faceHairPath = spec.facial_hair_type ? (FACIAL_HAIR_PATHS[spec.facial_hair_type] ?? null) : null;
  const isStubble = spec.facial_hair_type === 'stubble';

  const eyeColor = spec.identity?.eye_color
    ? (EYE_COLOR_MAP[spec.identity.eye_color] ?? '#8A9BA8')
    : null;

  // Determine how "complete" the sketch is for the progress ring
  const filledFields = [
    spec.gender, spec.age_band, spec.face_shape, spec.jaw_type,
    spec.eye_shape, spec.nose_type, spec.lip_type,
    spec.identity?.hair_color, spec.identity?.eye_color,
  ].filter(Boolean).length;
  const totalFields = 9;
  const progress = filledFields / totalFields;

  const baseStroke = '#9CA3AF'; // gray-400
  const accentStroke = '#34D399'; // emerald-400

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="relative rounded-2xl bg-gray-900/80 border border-gray-800"
        style={{ width: 160, height: 200 }}
      >
        {/* Progress ring overlay */}
        <svg
          width={160}
          height={200}
          viewBox="0 0 160 200"
          className="absolute inset-0 pointer-events-none"
          style={{ opacity: 0.25 }}
        >
          <circle cx={80} cy={100} r={72} fill="none" stroke={accentStroke} strokeWidth={1}
            strokeDasharray={`${2 * Math.PI * 72}`}
            strokeDashoffset={`${2 * Math.PI * 72 * (1 - progress)}`}
            style={{ transition: 'stroke-dashoffset 0.6s ease' }}
            transform="rotate(-90 80 100)"
          />
        </svg>

        <svg
          width={160}
          height={200}
          viewBox="0 0 100 130"
          className="w-full h-full"
          style={{ overflow: 'visible' }}
        >
          {/* ── Hair (behind face) ─────────────────── */}
          {hairPath && (
            <path
              d={hairPath}
              fill="none"
              stroke={baseStroke}
              strokeWidth={1.2}
              style={{ opacity: pct(!!hairPath), transition: 'opacity 0.5s' }}
            />
          )}
          {hairlinePath && (
            <path
              d={hairlinePath}
              fill="none"
              stroke={baseStroke}
              strokeWidth={1.0}
              style={{ opacity: pct(!!hairlinePath), transition: 'opacity 0.5s' }}
            />
          )}

          {/* ── Face outline ───────────────────────── */}
          <path
            d={faceOutlinePath}
            fill="none"
            stroke={spec.face_shape ? accentStroke : baseStroke}
            strokeWidth={1.4}
            style={{ opacity: 0.8, transition: 'stroke 0.5s, opacity 0.5s' }}
          />

          {/* ── Jaw accent ─────────────────────────── */}
          {jawAccent && (
            <path
              d={jawAccent}
              fill="none"
              stroke={accentStroke}
              strokeWidth={1.0}
              style={{ opacity: pct(!!spec.jaw_type), transition: 'opacity 0.5s' }}
            />
          )}

          {/* ── Ears ───────────────────────────────── */}
          <path d={EAR_PATHS.L} fill="none" stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.4 }} />
          <path d={EAR_PATHS.R} fill="none" stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.4 }} />

          {/* ── Eyebrows ───────────────────────────── */}
          {brows ? (
            <>
              <path d={brows.L} fill="none" stroke={accentStroke} strokeWidth={1.4}
                style={{ opacity: pct(!!spec.brow_type), transition: 'opacity 0.5s' }} />
              <path d={brows.R} fill="none" stroke={accentStroke} strokeWidth={1.4}
                style={{ opacity: pct(!!spec.brow_type), transition: 'opacity 0.5s' }} />
            </>
          ) : (
            <>
              <path d={BROW_SHAPES.straight.L} fill="none" stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.18 }} />
              <path d={BROW_SHAPES.straight.R} fill="none" stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.18 }} />
            </>
          )}

          {/* ── Eyes ───────────────────────────────── */}
          <path
            d={eyes.L}
            fill={eyeColor ?? 'none'}
            fillOpacity={eyeColor ? 0.35 : 0}
            stroke={spec.eye_shape ? accentStroke : baseStroke}
            strokeWidth={1.1}
            style={{ opacity: pct(!!spec.eye_shape), transition: 'opacity 0.5s, fill 0.5s' }}
          />
          <path
            d={eyes.R}
            fill={eyeColor ?? 'none'}
            fillOpacity={eyeColor ? 0.35 : 0}
            stroke={spec.eye_shape ? accentStroke : baseStroke}
            strokeWidth={1.1}
            style={{ opacity: pct(!!spec.eye_shape), transition: 'opacity 0.5s, fill 0.5s' }}
          />

          {/* ── Nose ───────────────────────────────── */}
          <path
            d={nosePath}
            fill="none"
            stroke={spec.nose_type ? accentStroke : baseStroke}
            strokeWidth={1.0}
            style={{ opacity: pct(!!spec.nose_type), transition: 'opacity 0.5s, stroke 0.5s' }}
          />

          {/* ── Lips ───────────────────────────────── */}
          <path
            d={lipPath}
            fill="none"
            stroke={spec.lip_type ? accentStroke : baseStroke}
            strokeWidth={1.0}
            style={{ opacity: pct(!!spec.lip_type), transition: 'opacity 0.5s, stroke 0.5s' }}
          />

          {/* ── Facial hair ────────────────────────── */}
          {isStubble && (
            <>
              {[32, 37, 42, 47, 52, 57, 62, 67].map((x) => (
                <circle key={x} cx={x} cy={90 + (x % 3)} r={0.7}
                  fill={baseStroke}
                  style={{ opacity: pct(true), transition: 'opacity 0.5s' }} />
              ))}
            </>
          )}
          {faceHairPath && (
            <path
              d={faceHairPath}
              fill="none"
              stroke={baseStroke}
              strokeWidth={1.1}
              style={{ opacity: pct(!!spec.facial_hair_type), transition: 'opacity 0.5s' }}
            />
          )}

          {/* ── Neck ───────────────────────────────── */}
          <line x1={43} y1={115} x2={40} y2={128} stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.25 }} />
          <line x1={57} y1={115} x2={60} y2={128} stroke={baseStroke} strokeWidth={1.0} style={{ opacity: 0.25 }} />
        </svg>
      </div>

      {/* Progress label */}
      <p className="text-xs text-gray-600 tracking-wide">
        {filledFields === 0
          ? 'Face forming…'
          : filledFields < 4
          ? 'Taking shape…'
          : filledFields < 7
          ? 'Almost there…'
          : 'Ready for the sketch.'}
      </p>
    </div>
  );
}

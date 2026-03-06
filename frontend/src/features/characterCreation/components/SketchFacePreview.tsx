/**
 * SketchFacePreview — rough working-sketch SVG that builds live
 * as the interview is answered.  Looks like an artist's graphite
 * sketch-pad, not a finished portrait.  No AI calls.
 *
 * Paper background + SVG displacement filter gives a hand-drawn feel.
 * Construction guide lines (centre axis, eye / nose / mouth rules)
 * are always faintly visible — they are the artist's initial marks.
 *
 * Unanswered features appear as near-invisible ghost guides (opacity 0.06).
 * Answered features come through as confident graphite marks (opacity 0.82).
 */

import type { IdentitySpec } from '../shared/types';

// ── Palette ───────────────────────────────────────────────────────────

const PAPER  = '#f7f3ec';  // warm parchment
const INK    = '#2e2010';  // dark warm graphite
const GUIDE  = '#8b6840';  // ochre construction-line colour
const GHOST  = 0.06;       // opacity for unanswered features
const SOLID  = 0.82;       // opacity for answered features

// ── Face outline paths (viewBox 0 0 100 130) ──────────────────────────

const FACE_OUTLINE: Record<string, string> = {
  oval:    'M50,12 C28,12 14,35 14,65 C14,95 28,115 50,115 C72,115 86,95 86,65 C86,35 72,12 50,12 Z',
  round:   'M50,18 C30,18 16,40 16,64 C16,88 30,110 50,110 C70,110 84,88 84,64 C84,40 70,18 50,18 Z',
  square:  'M20,18 L80,18 C84,18 86,22 86,28 L86,82 C86,96 72,112 50,112 C28,112 14,96 14,82 L14,28 C14,22 16,18 20,18 Z',
  angular: 'M50,10 L82,28 L88,66 L72,100 L50,112 L28,100 L12,66 L18,28 Z',
  long:    'M50,8 C32,8 18,30 18,68 C18,104 32,122 50,122 C68,122 82,104 82,68 C82,30 68,8 50,8 Z',
};
const FACE_DEFAULT = FACE_OUTLINE.oval;

// Jaw accent
const JAW_ACCENTS: Record<string, string> = {
  sharp:  'M28,100 Q50,118 72,100',
  square: 'M24,95 L50,108 L76,95',
  soft:   'M30,100 Q50,113 70,100',
  narrow: 'M34,98 Q50,112 66,98',
};

// ── Eyes ──────────────────────────────────────────────────────────────

type LR = { L: string; R: string };

const EYE_SHAPES: Record<string, LR> = {
  almond:   { L: 'M26,52 Q34,46 42,52 Q34,58 26,52 Z', R: 'M58,52 Q66,46 74,52 Q66,58 58,52 Z' },
  round:    { L: 'M27,52 A7,7 0 1,0 41,52 A7,7 0 1,0 27,52 Z', R: 'M59,52 A7,7 0 1,0 73,52 A7,7 0 1,0 59,52 Z' },
  narrow:   { L: 'M26,52 Q34,49 42,52 Q34,55 26,52 Z', R: 'M58,52 Q66,49 74,52 Q66,55 58,52 Z' },
  deep_set: { L: 'M26,53 Q34,47 42,53 Q34,59 26,53 Z', R: 'M58,53 Q66,47 74,53 Q66,59 58,53 Z' },
};
const EYE_DEFAULT = EYE_SHAPES.almond;

// Pupil marks — tiny graphite dot at eye centre
const PUPIL = { Lx: 34, Ly: 52, Rx: 66, Ry: 52 };

// Brows
const BROW_SHAPES: Record<string, LR> = {
  straight: { L: 'M26,44 L42,44',          R: 'M58,44 L74,44' },
  arched:   { L: 'M26,46 Q34,40 42,46',    R: 'M58,46 Q66,40 74,46' },
  thick:    { L: 'M25,45 Q34,40 43,45',    R: 'M57,45 Q66,40 75,45' },
  sharp:    { L: 'M26,46 L34,41 L42,45',   R: 'M58,45 L66,41 L74,46' },
};
const BROW_DEFAULT = BROW_SHAPES.straight;

// ── Nose ──────────────────────────────────────────────────────────────

const NOSE_PATHS: Record<string, string> = {
  straight: 'M47,62 L47,73 M53,62 L53,73 M47,73 Q50,75 53,73',
  narrow:   'M48,62 L48,73 M52,62 L52,73 M48,73 Q50,75 52,73',
  broad:    'M45,63 L45,73 M55,63 L55,73 M44,73 Q50,76 56,73',
  hooked:   'M47,62 C47,67 46,71 47,73 M53,62 C53,67 54,71 53,73 M47,73 Q50,75 53,73',
  roman:    'M47,62 C47,64 46,66 47,68 L47,73 M53,62 C53,64 54,66 53,68 L53,73 M47,73 Q50,75 53,73',
  upturned: 'M47,65 L47,72 Q44,74 44,73 M53,65 L53,72 Q56,74 56,73',
};
const NOSE_DEFAULT = NOSE_PATHS.straight;

// ── Lips ──────────────────────────────────────────────────────────────

const LIP_PATHS: Record<string, string> = {
  thin:      'M40,83 Q50,81 60,83',
  balanced:  'M40,83 Q45,80 50,80 Q55,80 60,83 Q55,87 50,87 Q45,87 40,83 Z',
  full:      'M40,82 Q45,77 50,77 Q55,77 60,82 Q55,89 50,90 Q45,89 40,82 Z',
  cupid_bow: 'M40,83 Q44,81 47,79 Q50,77 53,79 Q56,81 60,83 Q55,88 50,89 Q45,88 40,83 Z',
};
const LIP_DEFAULT = LIP_PATHS.thin;

// ── Hair ──────────────────────────────────────────────────────────────
// Rendered as open-stroke silhouettes — no fill, just graphite lines.

const HAIR_PATHS: Record<string, string | null> = {
  Shaved:  null,
  Short:   'M14,55 Q14,12 50,8 Q86,12 86,55 Q78,30 50,26 Q22,30 14,55 Z',
  Medium:  'M13,65 Q11,15 50,7 Q89,15 87,65 Q84,38 68,28 L68,80 Q84,65 87,65 M13,65 Q16,50 32,28 L32,80 Q16,65 13,65 Z',
  Long:    'M12,80 Q8,15 50,6 Q92,15 88,80 Q85,40 70,28 L70,112 Q85,90 88,80 M12,80 Q15,45 30,28 L30,112 Q15,90 12,80 Z',
};

const HAIRLINE_PATHS: Record<string, string | null> = {
  straight:    null,
  messy:       'M20,26 Q28,22 36,25 Q44,20 50,24 Q56,20 64,25 Q72,22 80,26',
  widows_peak: 'M20,28 Q35,24 50,18 Q65,24 80,28',
  receding:    'M22,32 Q36,26 50,26 Q64,26 78,32',
};

// ── Facial hair ────────────────────────────────────────────────────────

const FACIAL_HAIR_PATHS: Record<string, string | null> = {
  none:        null,
  stubble:     null,
  mustache:    'M40,80 Q45,77 50,78 Q55,77 60,80 Q55,82 50,82 Q45,82 40,80 Z',
  goatee:      'M44,84 Q50,90 56,84 Q53,96 50,98 Q47,96 44,84 Z',
  short_beard: 'M28,88 Q34,100 50,106 Q66,100 72,88 Q80,76 78,68 Q64,78 50,80 Q36,78 22,68 Q20,76 28,88 Z',
  full_beard:  'M26,85 Q30,102 50,110 Q70,102 74,85 Q80,70 78,60 Q64,74 50,76 Q36,74 22,60 Q20,70 26,85 Z',
  long_beard:  'M24,84 Q26,104 50,118 Q74,104 76,84 Q82,65 78,55 Q64,72 50,74 Q36,72 22,55 Q18,65 24,84 Z',
};

// ── Ears ──────────────────────────────────────────────────────────────

const EARS: LR = {
  L: 'M14,57 Q8,62 8,70 Q8,78 14,83',
  R: 'M86,57 Q92,62 92,70 Q92,78 86,83',
};

// ── Component ─────────────────────────────────────────────────────────

interface Props {
  spec: Partial<IdentitySpec>;
}

function op(answered: boolean): number {
  return answered ? SOLID : GHOST;
}

export default function SketchFacePreview({ spec }: Props) {
  const faceOutlinePath = (spec.face_shape && FACE_OUTLINE[spec.face_shape]) ?? FACE_DEFAULT;
  const jawPath  = spec.jaw_type ? JAW_ACCENTS[spec.jaw_type] : null;
  const eyes     = (spec.eye_shape ? EYE_SHAPES[spec.eye_shape] : null) ?? EYE_DEFAULT;
  const eyeAnswered = !!spec.eye_shape;
  const brows    = (spec.brow_type ? BROW_SHAPES[spec.brow_type] : null) ?? BROW_DEFAULT;
  const browAnswered = !!spec.brow_type;
  const nosePath = (spec.nose_type && NOSE_PATHS[spec.nose_type]) ?? NOSE_DEFAULT;
  const lipPath  = (spec.lip_type  && LIP_PATHS[spec.lip_type])  ?? LIP_DEFAULT;
  const hairLength = spec.identity?.hair_length ?? '';
  const hairPath   = hairLength ? (HAIR_PATHS[hairLength] ?? null) : null;
  const hairlinePath = spec.hairline_type ? (HAIRLINE_PATHS[spec.hairline_type] ?? null) : null;
  const faceHairPath = spec.facial_hair_type ? (FACIAL_HAIR_PATHS[spec.facial_hair_type] ?? null) : null;
  const isStubble  = spec.facial_hair_type === 'stubble';

  return (
    <div
      className="rounded-xl overflow-hidden shadow-md shrink-0"
      style={{ width: 154, height: 200 }}
    >
      <svg
        width={154}
        height={200}
        viewBox="0 0 100 130"
        style={{ display: 'block' }}
      >
        <defs>
          {/* Rough hand-drawn displacement filter */}
          <filter id="sfp-rough" x="-6%" y="-6%" width="112%" height="112%">
            <feTurbulence type="fractalNoise" baseFrequency="0.04 0.07"
              numOctaves="4" seed="11" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise"
              scale="0.85" xChannelSelector="R" yChannelSelector="G" />
          </filter>
          {/* Thicker brow roughness */}
          <filter id="sfp-brow" x="-10%" y="-30%" width="120%" height="160%">
            <feTurbulence type="fractalNoise" baseFrequency="0.05 0.09"
              numOctaves="3" seed="4" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise"
              scale="1.1" xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </defs>

        {/* Paper background */}
        <rect width="100" height="130" fill={PAPER} />

        {/* ── Construction guide lines (always visible) ─────────────── */}
        <g stroke={GUIDE} strokeWidth="0.28" strokeDasharray="1.5,2.5" opacity="0.13">
          {/* Vertical centre axis */}
          <line x1="50" y1="6" x2="50" y2="124" />
          {/* Eye rule */}
          <line x1="11" y1="52" x2="89" y2="52" />
          {/* Nose tip rule */}
          <line x1="20" y1="73" x2="80" y2="73" />
          {/* Mouth rule */}
          <line x1="25" y1="83" x2="75" y2="83" />
        </g>

        {/* ── Sketch features (displacement filter applied) ─────────── */}
        <g filter="url(#sfp-rough)">

          {/* Hair — behind the face outline */}
          {hairPath && (
            <>
              <path d={hairPath} fill="none" stroke={INK} strokeWidth="1.1"
                style={{ opacity: SOLID, transition: 'opacity 0.45s' }} />
              {/* second pass for rough texture */}
              <path d={hairPath} fill="none" stroke={INK} strokeWidth="0.4"
                transform="translate(0.3,0.4)"
                style={{ opacity: 0.25, transition: 'opacity 0.45s' }} />
            </>
          )}
          {hairlinePath && (
            <path d={hairlinePath} fill="none" stroke={INK} strokeWidth="0.9"
              style={{ opacity: SOLID, transition: 'opacity 0.45s' }} />
          )}

          {/* Ears — always faint */}
          <path d={EARS.L} fill="none" stroke={INK} strokeWidth="0.9" opacity="0.22" />
          <path d={EARS.R} fill="none" stroke={INK} strokeWidth="0.9" opacity="0.22" />

          {/* Face outline — ghost until face_shape answered */}
          <path d={faceOutlinePath} fill="none" stroke={INK} strokeWidth="1.4"
            style={{ opacity: op(!!spec.face_shape) || 0.14, transition: 'opacity 0.45s, d 0.5s' }} />
          {/* second pass */}
          <path d={faceOutlinePath} fill="none" stroke={INK} strokeWidth="0.5"
            transform="translate(0.35,0.25)"
            style={{ opacity: spec.face_shape ? 0.28 : 0.04, transition: 'opacity 0.45s' }} />

          {/* Jaw accent */}
          {jawPath && (
            <path d={jawPath} fill="none" stroke={INK} strokeWidth="1.0"
              style={{ opacity: SOLID, transition: 'opacity 0.45s' }} />
          )}

          {/* Eyebrows */}
          <path d={brows.L} fill="none" stroke={INK}
            strokeWidth={browAnswered ? 2.0 : 0.8} strokeLinecap="round"
            filter={browAnswered ? 'url(#sfp-brow)' : undefined}
            style={{ opacity: op(browAnswered), transition: 'opacity 0.45s' }} />
          <path d={brows.R} fill="none" stroke={INK}
            strokeWidth={browAnswered ? 2.0 : 0.8} strokeLinecap="round"
            filter={browAnswered ? 'url(#sfp-brow)' : undefined}
            style={{ opacity: op(browAnswered), transition: 'opacity 0.45s' }} />

          {/* Eyes */}
          <path d={eyes.L} fill="none" stroke={INK} strokeWidth="1.05"
            style={{ opacity: op(eyeAnswered), transition: 'opacity 0.45s' }} />
          <path d={eyes.R} fill="none" stroke={INK} strokeWidth="1.05"
            style={{ opacity: op(eyeAnswered), transition: 'opacity 0.45s' }} />
          {/* Pupil dot */}
          {eyeAnswered && (
            <>
              <circle cx={PUPIL.Lx} cy={PUPIL.Ly} r={1.6} fill={INK}
                style={{ opacity: 0.65, transition: 'opacity 0.45s' }} />
              <circle cx={PUPIL.Rx} cy={PUPIL.Ry} r={1.6} fill={INK}
                style={{ opacity: 0.65, transition: 'opacity 0.45s' }} />
            </>
          )}

          {/* Nose */}
          <path d={nosePath} fill="none" stroke={INK} strokeWidth="1.0"
            style={{ opacity: op(!!spec.nose_type), transition: 'opacity 0.45s' }} />

          {/* Lips */}
          <path d={lipPath} fill="none" stroke={INK} strokeWidth="1.05"
            style={{ opacity: op(!!spec.lip_type), transition: 'opacity 0.45s' }} />

          {/* Stubble dots */}
          {isStubble && (
            <g style={{ opacity: SOLID, transition: 'opacity 0.45s' }}>
              {[30,34,38,42,46,50,54,58,62,66,70].map((x) => (
                <circle key={x} cx={x} cy={90 + ((x * 7) % 5)} r={0.65} fill={INK} opacity={0.55} />
              ))}
              {[33,37,41,45,49,53,57,61,65].map((x) => (
                <circle key={x + 100} cx={x} cy={95 + ((x * 3) % 4)} r={0.55} fill={INK} opacity={0.4} />
              ))}
            </g>
          )}

          {/* Other facial hair */}
          {faceHairPath && (
            <path d={faceHairPath} fill="none" stroke={INK} strokeWidth="1.05"
              style={{ opacity: SOLID, transition: 'opacity 0.45s' }} />
          )}

          {/* Neck — always faint */}
          <line x1="43" y1="114" x2="40" y2="127" stroke={INK} strokeWidth="0.85" opacity="0.14" />
          <line x1="57" y1="114" x2="60" y2="127" stroke={INK} strokeWidth="0.85" opacity="0.14" />

        </g>{/* end filter group */}

        {/* Corner pencil-texture marks — purely aesthetic */}
        <g stroke={GUIDE} strokeWidth="0.2" opacity="0.10">
          <line x1="2" y1="2" x2="10" y2="2" />
          <line x1="2" y1="2" x2="2" y2="10" />
          <line x1="98" y1="2" x2="90" y2="2" />
          <line x1="98" y1="2" x2="98" y2="10" />
          <line x1="2" y1="128" x2="10" y2="128" />
          <line x1="2" y1="128" x2="2" y2="120" />
          <line x1="98" y1="128" x2="90" y2="128" />
          <line x1="98" y1="128" x2="98" y2="120" />
        </g>
      </svg>
    </div>
  );
}

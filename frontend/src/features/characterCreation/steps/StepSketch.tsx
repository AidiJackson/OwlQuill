// The Sketch — a quick preview of how the artist reads the Interview.
//
// Polish Phase 1 (C12, C16). The product truth, stated on the page: the
// sketch is a preview of the system's reading of the Interview; the Identity
// Pack is generated from the Interview's answers, not from this image
// (product decision P1 — the sketch does not seed the V2 pack, and nothing
// here pretends otherwise). Actions say what they do: Generate sketch, Try
// again, Yes — that's them, Skip the sketch.
//
// The B15.5/B15.6 DEV debug panel and trace logging that lived here were
// removed in the same pass (authorised touch-when-modifying cleanup); the
// session guard they observed is unchanged and still enforced.
import { useState, useEffect } from 'react';
import { PenLine, RefreshCw, CheckCircle } from 'lucide-react';
import type { SketchAllowance, SketchResponse, SketchStyle, IdentitySpec } from '../shared/types';
import { GENDER_OPTIONS, SKETCH_STYLES, SPECIES_OPTIONS } from '../shared/types';
import { generateIdentitySketch, getSketchAllowance, resolveImageUrl } from '../shared/api';
import { isSketchBlocked } from '../shared/sessionGuard';
import { allowanceCopy, allowanceFromError } from '../shared/sketchAllowance';
import InlineNotice from '@/components/InlineNotice';

interface Props {
  characterId: number;
  identitySpec?: IdentitySpec | null;
  /** The creator accepted the sketch, or chose to skip it. Either way, on to the pack. */
  onConfirmed: () => void;
  onBack: () => void;
  // B15.6: session hardening — optional so the component stays usable in isolation
  /** The flow's authoritative active character id. Must match characterId or sketch is blocked. */
  activeCreationCharacterId?: number | null;
}

/**
 * Compute a lightweight fingerprint of the identity fields that affect the
 * sketch prompt.  If this changes, any displayed sketch is stale.
 */
function specFingerprint(spec?: IdentitySpec | null): string {
  if (!spec) return '';
  return [
    spec.gender,
    spec.age_band,
    spec.species,
    (spec.species_tells ?? []).join(','),
    spec.face_shape,
    spec.jaw_type,
    spec.cheekbone_type,
    spec.eye_shape,
    spec.eye_spacing,
    spec.eyebrow_shape,
    spec.nose_type,
    spec.lip_type,
    spec.hairline_type,
    spec.facial_hair_type,
    spec.identity?.hair_color,
    spec.identity?.hair_length,
    spec.hair_texture,
    spec.hair_style,
    spec.identity?.eye_color,
    spec.identity?.skin_tone,
  ].join('|');
}

/** Compact row shown in the artist notes summary card. */
function NoteRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-ink-3 w-20 flex-shrink-0">{label}</span>
      <span className="text-ink-2">{value}</span>
    </div>
  );
}

export default function StepSketch({
  characterId,
  identitySpec,
  onConfirmed,
  onBack,
  activeCreationCharacterId,
}: Props) {
  const [selectedStyle, setSelectedStyle] = useState<SketchStyle>('pencil');
  const [sketch, setSketch] = useState<SketchResponse | null>(null);
  const [sketchSpecKey, setSketchSpecKey] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // The Sketch allowance — Polish Phase 2 (C10). Always the server's number:
  // read on mount, replaced by what the generate response carries, and
  // replaced again by what an exhausted-allowance refusal carries. Never
  // decremented locally, never stored in the browser, so a reload, a second
  // tab or a fresh session all show the same truth.
  const [allowance, setAllowance] = useState<SketchAllowance | null>(null);
  const [allowanceError, setAllowanceError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getSketchAllowance(characterId)
      .then((a) => { if (!cancelled) setAllowance(a); })
      .catch(() => { if (!cancelled) setAllowanceError(true); });
    return () => { cancelled = true; };
  }, [characterId]);
  const exhausted = allowance !== null && !allowance.allowed;

  // B15.6: explicit mismatch guard — true when this component's characterId no
  // longer matches the flow's authoritative active creation character id. In
  // the normal flow this is always false; the key={nonce} remount handles
  // bfcache restores before they reach this component.
  const sketchBlocked = isSketchBlocked({ characterId, activeCreationCharacterId });

  // Clear a stale sketch whenever the identity spec changes after one was made.
  const currentSpecKey = specFingerprint(identitySpec);
  useEffect(() => {
    if (sketch && sketchSpecKey && currentSpecKey !== sketchSpecKey) {
      setSketch(null);
      setSketchSpecKey('');
    }
  }, [currentSpecKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async () => {
    if (sketchBlocked) {
      setError('Session mismatch — please go back and try again.');
      return;
    }
    // Clear any previously displayed sketch immediately so the user never sees
    // a stale image while the new one is loading.
    setSketch(null);
    setLoading(true);
    setError('');
    try {
      const result = await generateIdentitySketch(characterId, selectedStyle);
      if (!result.image_url) {
        setError('Sketch generated, but no image was returned. Please try again.');
        return;
      }
      const resolvedUrl = resolveImageUrl(result.image_url);
      await new Promise<void>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve();
        img.onerror = () =>
          reject(new Error('Sketch generated, but the image could not be loaded. Please try again.'));
        img.src = resolvedUrl;
      });
      setSketch(result);
      setSketchSpecKey(currentSpecKey);
      if (result.allowance) {
        setAllowance(result.allowance);
      } else {
        // Older server shape: ask rather than guess.
        getSketchAllowance(characterId).then(setAllowance).catch(() => {});
      }
    } catch (err) {
      // An exhausted allowance is the server's state, not a failure: reconcile
      // to it (another tab may have spent the attempts) and say so in the
      // allowance line rather than as an error.
      const refused = allowanceFromError(err);
      if (refused) {
        setAllowance(refused);
        return;
      }
      setError(err instanceof Error ? err.message : 'Failed to generate sketch.');
    } finally {
      setLoading(false);
    }
  };

  // Derive artist notes from identitySpec
  const spec = identitySpec;
  const hairParts = [spec?.identity.hair_length, spec?.hair_texture, spec?.hair_style?.replace(/_/g, ' '), spec?.identity.hair_color]
    .filter(Boolean);
  const hair = hairParts.join(' ') + (hairParts.length ? ' hair' : '');
  const eyes = spec?.identity.eye_color ?? '';
  const genderLabel = GENDER_OPTIONS.find((g) => g.value === spec?.gender)?.label ?? spec?.gender ?? '';
  const ageBand = spec?.age_band ?? '';
  const speciesLabel =
    spec?.species && spec.species !== 'human'
      ? [
          SPECIES_OPTIONS.find((o) => o.value === spec.species)?.label ?? spec.species,
          ...(spec.species_tells ?? []).map((t) => t.replace(/_/g, ' ')),
        ].join(', ')
      : '';
  const eyebrowLabel = spec?.eyebrow_shape ?? '';
  const facialHairLabel =
    spec?.facial_hair_type && spec.facial_hair_type !== 'none'
      ? spec.facial_hair_type.replace(/_/g, ' ')
      : '';
  const hasNotes = !!(genderLabel || ageBand || hair || eyes || speciesLabel);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="text-center">
        <div className="flex items-center justify-center gap-2 mb-1">
          <PenLine className="w-5 h-5 text-gem" />
          <h2 className="text-lg font-semibold text-ink">Sketch</h2>
        </div>
        <p className="text-sm text-ink-2">
          A quick preview of how the artist reads your answers.
        </p>
        {/* The relationship to the Identity Pack, stated once, where it matters (C16). */}
        <p className="text-xs text-ink-3 mt-1">
          Your Identity Pack is generated from your answers, not from this sketch — so it&apos;s
          fine to skip it, and fine to try a couple of styles.
        </p>
      </div>

      {/* Artist notes summary card */}
      {hasNotes && (
        <div className="rounded-lg border border-edge bg-surface px-4 py-3 space-y-1.5">
          <p className="text-xs text-ink-3 uppercase tracking-wider font-medium mb-2">
            What the artist was told
          </p>
          <NoteRow label="Gender" value={genderLabel} />
          <NoteRow label="Age range" value={ageBand} />
          <NoteRow label="Hair" value={hair} />
          <NoteRow label="Eyes" value={eyes} />
          {eyebrowLabel && <NoteRow label="Eyebrows" value={eyebrowLabel} />}
          {facialHairLabel && <NoteRow label="Facial hair" value={facialHairLabel} />}
          {speciesLabel && <NoteRow label="Species" value={speciesLabel} />}
        </div>
      )}

      {/* Style selector */}
      <div>
        <p className="text-xs text-ink-3 uppercase tracking-wider mb-2">Sketch style</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" role="group" aria-label="Sketch style">
          {SKETCH_STYLES.map((s) => (
            <button
              key={s.value}
              type="button"
              aria-pressed={selectedStyle === s.value}
              onClick={() => setSelectedStyle(s.value as SketchStyle)}
              className={`p-3 rounded-lg border text-left transition-colors ${
                selectedStyle === s.value
                  ? 'border-gem/50 bg-gem-soft text-gem'
                  : 'border-edge-md bg-surface-elevated text-ink-2 hover:border-gem/40'
              }`}
            >
              <p className="text-sm font-medium">{s.label}</p>
              <p className="text-xs mt-0.5 opacity-70">{s.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Lead-in copy before first generation */}
      {!sketch && !loading && !exhausted && (
        <p className="text-sm text-ink-3 text-center italic">
          &ldquo;Alright… let&apos;s see if I&apos;ve captured them.&rdquo;
        </p>
      )}

      {/* Allowance — the server's number, one quiet line (C10) */}
      {exhausted ? (
        <InlineNotice tone="info">
          <p>{allowanceCopy(allowance)}</p>
          <p className="text-xs text-ink-3 mt-1">
            The sketch is optional — skip it and build the Identity Pack from your answers.
          </p>
        </InlineNotice>
      ) : (
        allowance && (
          <p className="text-xs text-ink-3 text-center" data-testid="sketch-allowance">
            {allowanceCopy(allowance)}
          </p>
        )
      )}

      {/* Generate / Try again — absent once the allowance is spent */}
      {!exhausted && (
        <button
          type="button"
          onClick={handleGenerate}
          disabled={loading || sketchBlocked || allowance === null && !allowanceError}
          className="flex items-center justify-center gap-2 w-full py-3 rounded-lg bg-gem hover:bg-gem/90 text-gem-ink font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Sketching…
            </>
          ) : (
            <>
              <PenLine className="w-4 h-4" />
              {sketch ? 'Try again' : 'Generate sketch'}
            </>
          )}
        </button>
      )}

      {/* Error — provider/network/server, never the allowance */}
      {error && (
        <InlineNotice tone="warning" onDismiss={() => setError('')}>{error}</InlineNotice>
      )}

      {/* Sketch result */}
      {sketch && (
        <div className="flex flex-col items-center gap-4">
          <div className="w-full max-w-xs rounded-xl overflow-hidden border border-edge-md shadow-lg">
            <img
              src={resolveImageUrl(sketch.image_url)}
              alt={`${sketch.style} character sketch`}
              className="w-full object-cover"
            />
          </div>

          <p className="text-sm text-ink-2 font-medium">Do you recognise them?</p>

          <button
            type="button"
            onClick={onConfirmed}
            className="flex items-center justify-center gap-2 w-full max-w-xs py-3 rounded-lg bg-gem hover:bg-gem/90 text-gem-ink font-medium transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            Yes — that&apos;s them
          </button>
        </div>
      )}

      {/* Back / Skip */}
      <div className="flex gap-3">
        <button
          type="button"
          onClick={onBack}
          className="flex-1 py-2 rounded-lg border border-edge-md text-ink-2 hover:text-ink hover:border-gem/40 text-sm transition-colors"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onConfirmed}
          className="flex-1 py-2 rounded-lg border border-edge-md text-ink-3 hover:text-ink-2 hover:border-gem/40 text-sm transition-colors"
        >
          {sketch ? 'Skip — build the pack' : 'Skip the sketch'}
        </button>
      </div>
    </div>
  );
}

import { useState, useEffect, useRef } from 'react';
import { PenLine, RefreshCw, CheckCircle } from 'lucide-react';
import type { SketchResponse, SketchStyle, IdentitySpec, CreationBasics } from '../shared/types';
import { SKETCH_STYLES } from '../shared/types';
import { generateIdentitySketch, resolveImageUrl } from '../shared/api';

// ── B15.5: DEV-ONLY sketch trace ─────────────────────────────────────
// All logging and the on-screen debug panel are gated behind the Vite
// build-time flag so they are tree-shaken out of production bundles.
const _SKETCH_TRACE = import.meta.env.DEV;

function _traceLog(event: string, data?: Record<string, unknown>) {
  if (!_SKETCH_TRACE) return;
  // eslint-disable-next-line no-console
  console.info(`[SketchTrace] ${event}`, data ?? '');
}

// ── B15.5: Dev-only debug panel ───────────────────────────────────────
// Renders a collapsible on-screen overlay with live sketch trace state.
// Easy to inspect on mobile: visible directly in the viewport without
// needing desktop DevTools.
interface _DebugPanelProps {
  characterId: number;
  mountCharacterId: number;
  specFingerprint: string;
  sketch: SketchResponse | null;
  loading: boolean;
}
function _SketchDebugPanel({
  characterId,
  mountCharacterId,
  specFingerprint,
  sketch,
  loading,
}: _DebugPanelProps) {
  if (!_SKETCH_TRACE) return null;
  const idDrift = characterId !== mountCharacterId;
  const renderedUrl = sketch ? resolveImageUrl(sketch.image_url) : null;
  return (
    <details className="mt-2 rounded-lg border border-green-800 bg-black/80 px-3 py-2 text-xs font-mono">
      <summary className="cursor-pointer select-none text-green-400 font-semibold">
        ▶ [DEV] Sketch Trace
      </summary>
      <div className="mt-2 space-y-1 text-green-300 leading-relaxed">
        <div>
          <span className="text-green-600">characterId (prop):</span>{' '}
          <span className={idDrift ? 'text-red-400 font-bold' : ''}>{characterId}</span>
          {idDrift && (
            <span className="ml-2 text-red-400">⚠ DRIFTED from mount id={mountCharacterId}</span>
          )}
        </div>
        <div><span className="text-green-600">mountCharacterId:</span> {mountCharacterId}</div>
        <div><span className="text-green-600">specFingerprint:</span> <span className="break-all">{specFingerprint || '(none)'}</span></div>
        <div><span className="text-green-600">loading:</span> {String(loading)}</div>
        <div><span className="text-green-600">sketchImageId:</span> {sketch?.image_id ?? 'null'}</div>
        <div><span className="text-green-600">sketchImageUrl:</span> <span className="break-all">{sketch?.image_url ?? 'null'}</span></div>
        <div><span className="text-green-600">renderedUrl:</span> <span className="break-all">{renderedUrl ?? 'null'}</span></div>
        <div><span className="text-green-600">imageSource:</span> {sketch ? 'local-state' : 'none'}</div>
        <div><span className="text-green-600">providerUsed:</span> {sketch?.provider_used ?? 'n/a'}</div>
      </div>
    </details>
  );
}

interface Props {
  characterId: number;
  identitySpec?: IdentitySpec | null;
  basics?: CreationBasics | null;
  onConfirmed: (sketchImageId: number) => void;
  onBack: () => void;
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
    spec.face_shape,
    spec.jaw_type,
    spec.cheekbone_type,
    spec.eye_shape,
    spec.eye_spacing,
    spec.brow_type,
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
    (spec.identity?.face_features ?? []).join(','),
    spec.extra_notes,
  ].join('|');
}

/** Compact row shown in the artist notes summary card. */
function NoteRow({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-gray-500 w-20 flex-shrink-0">{label}</span>
      <span className="text-gray-300">{value}</span>
    </div>
  );
}

export default function StepSketch({
  characterId,
  identitySpec,
  basics: _basics,
  onConfirmed,
  onBack,
}: Props) {
  const [selectedStyle, setSelectedStyle] = useState<SketchStyle>('pencil');
  const [sketch, setSketch] = useState<SketchResponse | null>(null);
  const [sketchSpecKey, setSketchSpecKey] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // B15.5: record the characterId at mount time so we can detect drift
  const mountCharacterIdRef = useRef<number>(characterId);

  // Clear stale sketch whenever the identity spec changes after a sketch was made.
  // In the current creation flow the component unmounts on Back/Next, so this
  // mainly guards against edge cases where the prop updates while mounted.
  const currentSpecKey = specFingerprint(identitySpec);
  useEffect(() => {
    if (sketch && sketchSpecKey && currentSpecKey !== sketchSpecKey) {
      _traceLog('specFingerprint changed → clearing stale sketch', {
        old: sketchSpecKey,
        new: currentSpecKey,
        characterId,
      });
      setSketch(null);
      setSketchSpecKey('');
    }
  }, [currentSpecKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // B15.5: mount/unmount trace
  useEffect(() => {
    _traceLog('MOUNT', {
      characterId,
      mountCharacterId: mountCharacterIdRef.current,
      specFingerprint: currentSpecKey || '(none)',
    });
    return () => {
      _traceLog('UNMOUNT', {
        characterId,
        hadSketch: sketch !== null,
        sketchImageId: sketch?.image_id ?? null,
      });
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // B15.5: characterId drift trace — fires if the prop changes after mount
  // (should not happen in normal flow because CharacterCreationFlow uses key={characterId})
  useEffect(() => {
    if (characterId !== mountCharacterIdRef.current) {
      _traceLog('⚠ characterId DRIFT detected (prop changed after mount)', {
        mountCharacterId: mountCharacterIdRef.current,
        currentCharacterId: characterId,
        hasSketch: sketch !== null,
        sketchImageId: sketch?.image_id ?? null,
        sketchBelongsTo: mountCharacterIdRef.current,
      });
    }
  }, [characterId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async () => {
    _traceLog('GENERATE start', {
      characterId,
      mountCharacterId: mountCharacterIdRef.current,
      style: selectedStyle,
      specFingerprint: currentSpecKey,
      previousSketchId: sketch?.image_id ?? null,
    });
    // Clear any previously displayed sketch immediately so the user never sees
    // a stale image while the new one is loading.
    setSketch(null);
    _traceLog('setSketch(null) fired');
    setLoading(true);
    setError('');
    try {
      const result = await generateIdentitySketch(characterId, selectedStyle);
      if (!result.image_url) {
        _traceLog('GENERATE error: no image_url in response', { result });
        setError('Sketch generated, but no image was returned. Please try again.');
        return;
      }
      const resolvedUrl = resolveImageUrl(result.image_url);
      _traceLog('GENERATE response received', {
        image_id: result.image_id,
        image_url: result.image_url,
        resolvedUrl,
        style: result.style,
        provider_used: result.provider_used,
        prompt_preview: result.prompt_preview?.slice(0, 80),
      });
      await new Promise<void>((resolve, reject) => {
        const img = new Image();
        img.onload = () => {
          _traceLog('img preload SUCCESS', { resolvedUrl });
          resolve();
        };
        img.onerror = () => {
          _traceLog('img preload FAILED', { resolvedUrl });
          reject(new Error('Sketch generated, but the image could not be loaded. Please try again.'));
        };
        img.src = resolvedUrl;
      });
      setSketch(result);
      _traceLog('setSketch(result) committed', {
        image_id: result.image_id,
        image_url: result.image_url,
        renderedUrl: resolveImageUrl(result.image_url),
        imageSource: 'local-state (just set)',
      });
      setSketchSpecKey(currentSpecKey);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate sketch.');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = () => {
    if (sketch) {
      onConfirmed(sketch.image_id);
    }
  };

  // Derive artist notes from identitySpec
  const spec = identitySpec;

  // Core identity
  const hairParts = [spec?.identity.hair_length, spec?.hair_texture, spec?.hair_style?.replace(/_/g, ' '), spec?.identity.hair_color]
    .filter(Boolean);
  const hair = hairParts.join(' ') + (hairParts.length ? ' hair' : '');
  const eyes = spec?.identity.eye_color ?? '';
  const features = spec?.identity.face_features?.join(', ') ?? '';
  const genderLabel = spec?.gender === 'female' ? 'Woman' : spec?.gender === 'male' ? 'Man' : spec?.gender ?? '';
  const ageBand = spec?.age_band ?? '';
  const speciesLabel =
    spec?.species && spec.species !== 'human'
      ? [spec.species, ...(spec.species_tells ?? []).map((t) => t.replace(/_/g, ' '))]
          .join(', ')
      : '';

  // B15.2 — additional fields for verification
  const eyebrowLabel = spec?.eyebrow_shape ?? spec?.brow_type ?? '';
  const facialHairLabel =
    spec?.facial_hair_type && spec.facial_hair_type !== 'none'
      ? spec.facial_hair_type.replace(/_/g, ' ')
      : '';

  const hasNotes = !!(genderLabel || ageBand || hair || eyes || features || speciesLabel);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="text-center">
        <div className="flex items-center justify-center gap-2 mb-1">
          <PenLine className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-semibold text-gray-100">Sketch</h2>
        </div>
        <p className="text-sm text-gray-400">
          We've briefed the artist. Now let's see if you recognise them.
        </p>
      </div>

      {/* Artist notes summary card */}
      {hasNotes && (
        <div className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3 space-y-1.5">
          <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-2">
            Sketch Artist Notes
          </p>
          <NoteRow label="Gender" value={genderLabel} />
          <NoteRow label="Age range" value={ageBand} />
          <NoteRow label="Hair" value={hair} />
          <NoteRow label="Eyes" value={eyes} />
          {eyebrowLabel && <NoteRow label="Eyebrows" value={eyebrowLabel} />}
          {facialHairLabel && <NoteRow label="Facial hair" value={facialHairLabel} />}
          {features && <NoteRow label="Features" value={features} />}
          {speciesLabel && <NoteRow label="Species" value={speciesLabel} />}
        </div>
      )}

      {/* Style selector */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Sketch Style</p>
        <div className="grid grid-cols-3 gap-2">
          {SKETCH_STYLES.map((s) => (
            <button
              key={s.value}
              onClick={() => setSelectedStyle(s.value as SketchStyle)}
              className={`p-3 rounded-lg border text-left transition-colors ${
                selectedStyle === s.value
                  ? 'border-emerald-500 bg-emerald-900/30 text-emerald-300'
                  : 'border-gray-700 bg-gray-800/50 text-gray-400 hover:border-gray-600'
              }`}
            >
              <p className="text-sm font-medium">{s.label}</p>
              <p className="text-xs mt-0.5 opacity-70">{s.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Lead-in copy before first generation */}
      {!sketch && !loading && (
        <p className="text-sm text-gray-500 text-center italic">
          "Alright… let's see if I've captured them."
        </p>
      )}

      {/* Generate / Refine button */}
      <button
        onClick={handleGenerate}
        disabled={loading}
        className="flex items-center justify-center gap-2 w-full py-3 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Generating…
          </>
        ) : (
          <>
            <PenLine className="w-4 h-4" />
            {sketch ? 'Refine sketch' : 'Generate Sketch'}
          </>
        )}
      </button>

      {/* Error */}
      {error && (
        <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 text-center">
          {error}
        </p>
      )}

      {/* Sketch result */}
      {sketch && (
        <div className="flex flex-col items-center gap-4">
          <div className="w-full max-w-xs rounded-xl overflow-hidden border border-gray-700 shadow-lg">
            <img
              src={resolveImageUrl(sketch.image_url)}
              alt={`${sketch.style} character sketch`}
              className="w-full object-cover"
            />
          </div>

          <p className="text-sm text-gray-300 font-medium">Do you recognise them?</p>

          {/* Confirm button */}
          <button
            onClick={handleConfirm}
            className="flex items-center justify-center gap-2 w-full max-w-xs py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            Yes — that's them
          </button>
        </div>
      )}

      {/* Skip / Back */}
      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600 text-sm transition-colors"
        >
          Back
        </button>
        <button
          onClick={() => onConfirmed(sketch?.image_id ?? 0)}
          className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600 text-sm transition-colors"
        >
          Skip for now
        </button>
      </div>

      {/* B15.5: DEV-ONLY debug panel — tree-shaken in production */}
      <_SketchDebugPanel
        characterId={characterId}
        mountCharacterId={mountCharacterIdRef.current}
        specFingerprint={currentSpecKey}
        sketch={sketch}
        loading={loading}
      />
    </div>
  );
}

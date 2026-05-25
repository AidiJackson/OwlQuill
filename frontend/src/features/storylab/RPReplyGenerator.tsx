import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type {
  Character,
  RPReplyFormatting,
  RPReplyHeatLevel,
  RPReplyIntensity,
  RPModelOption,
  RPReplyPerspective,
  RPReplyResponseLength,
  RPReplyStyleMatch,
  RPStyleArchetype,
} from '@/lib/types';

// ── Internal bake-off model options ──────────────────────────────────────────
// Only visible when VITE_INTERNAL_TESTING=true or in Vite dev mode.

const RP_MODEL_OPTIONS: RPModelOption[] = [
  { profile: 'default',       label: 'Default' },
  { profile: 'mixtral_8x22b', label: 'Mixtral 8x22B' },
  { profile: 'mixtral_8x7b',  label: 'Mixtral 8x7B' },
  { profile: 'llama_70b',     label: 'Llama 3.1 70B' },
  { profile: 'qwen_72b',      label: 'Qwen 2.5 72B' },
];

const CONTENT_LEVEL_OPTIONS: { val: RPReplyIntensity; label: string; desc: string }[] = [
  { val: 'standard', label: 'Standard', desc: 'Slow burn, restrained tension' },
  { val: 'mature',   label: 'Mature',   desc: 'Mature intimacy, unresolved' },
  { val: 'explicit', label: 'Explicit', desc: 'Explicit content, collaboration-preserving' },
];

// ── Internal style archetype options ──────────────────────────────────────────
const ARCHETYPE_OPTIONS: { val: RPStyleArchetype; label: string; desc: string }[] = [
  { val: 'cinematic_dark_romance', label: 'Cinematic Dark Romance', desc: 'Visual, atmospheric, emotionally dangerous' },
  { val: 'gothic_obsession',       label: 'Gothic Obsession',       desc: 'Dense, claustrophobic, haunted fixation' },
  { val: 'slow_burn_tension',      label: 'Slow Burn',              desc: 'Withholding, charged silence, almost-touch' },
  { val: 'dangerous_devotion',     label: 'Dangerous Devotion',     desc: 'Possessive love with edges, urgent devotion' },
  { val: 'primal_restraint',       label: 'Primal Restraint',       desc: 'Coiled control on the edge of breaking' },
];

const IS_INTERNAL =
  import.meta.env.VITE_INTERNAL_TESTING === 'true' || import.meta.env.DEV === true;

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  preselectedCharacterId?: number | null;
  preselectedStoryId?: string | null;
}

export default function RPReplyGenerator({ preselectedCharacterId, preselectedStoryId }: Props) {
  const [partnerReply, setPartnerReply] = useState('');
  const [instructions, setInstructions] = useState('');
  const [characterId, setCharacterId] = useState<number | null>(preselectedCharacterId ?? null);
  const [characters, setCharacters] = useState<Character[]>([]);

  const [responseLength, setResponseLength] = useState<RPReplyResponseLength>('match');
  const [styleMatch, setStyleMatch] = useState<RPReplyStyleMatch>('soft');
  const [perspective, setPerspective] = useState<RPReplyPerspective>('third_person_limited');
  const [formatting, setFormatting] = useState<RPReplyFormatting>('plain');
  const [contentLevel, setContentLevel] = useState<RPReplyIntensity>('mature');
  const [modelProfile, setModelProfile] = useState<string>('default');
  const [styleArchetype, setStyleArchetype] = useState<RPStyleArchetype>('cinematic_dark_romance');

  const [reply, setReply] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [pacingWarnings, setPacingWarnings] = useState<string[]>([]);
  const [styleWarnings, setStyleWarnings] = useState<string[]>([]);
  const [modelUsed, setModelUsed] = useState('');
  const [generationTimeMs, setGenerationTimeMs] = useState(0);
  const [detectedStage, setDetectedStage] = useState('');
  const [continuationScore, setContinuationScore] = useState<number | null>(null);
  // Scene beat engine state (internal dev mode)
  const [nextSceneGoal, setNextSceneGoal] = useState('');
  const [repetitionScore, setRepetitionScore] = useState<number | null>(null);
  const [progressionSuccess, setProgressionSuccess] = useState<boolean | null>(null);
  // Orchestration stabilization diagnostics (internal)
  const [aiCadenceRisk, setAiCadenceRisk] = useState<boolean | null>(null);
  const [spatialPosition, setSpatialPosition] = useState('');
  // Beat planner diagnostics (internal)
  const [multiBeatDetected, setMultiBeatDetected] = useState<boolean | null>(null);
  const [requestedBeats, setRequestedBeats] = useState<string[]>([]);
  // Length profile diagnostics (internal)
  const [resolvedLengthProfile, setResolvedLengthProfile] = useState('');
  const [maxTokensUsed, setMaxTokensUsed] = useState<number | null>(null);
  const [beatCompletionMode, setBeatCompletionMode] = useState('');
  const [spatialDominance, setSpatialDominance] = useState('');
  const [resolvedHeat, setResolvedHeat] = useState('');
  // Godmod output gate diagnostics (internal)
  const [godmodDetected, setGodmodDetected] = useState<boolean | null>(null);
  const [godmodSeverity, setGodmodSeverity] = useState('');
  const [godmodWarnings, setGodmodWarnings] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [benchmarkCopied, setBenchmarkCopied] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    apiClient.getCharacters()
      .then(setCharacters)
      .catch(() => { /* non-fatal */ });
  }, []);

  // Derive internal heat_level from user-facing content level
  const heatLevel: RPReplyHeatLevel = contentLevel === 'explicit' ? 'inferno' : contentLevel === 'mature' ? 'flame' : 'embers';

  async function handleGenerate() {
    if (!partnerReply.trim()) return;
    setLoading(true);
    setError(null);
    setWarnings([]);
    setPacingWarnings([]);
    setStyleWarnings([]);
    setModelUsed('');
    setGenerationTimeMs(0);
    setDetectedStage('');
    setContinuationScore(null);
    setNextSceneGoal('');
    setRepetitionScore(null);
    setProgressionSuccess(null);
    setAiCadenceRisk(null);
    setSpatialPosition('');
    setSpatialDominance('');
    setResolvedHeat('');
    setMultiBeatDetected(null);
    setRequestedBeats([]);
    setResolvedLengthProfile('');
    setMaxTokensUsed(null);
    setBeatCompletionMode('');
    setGodmodDetected(null);
    setGodmodSeverity('');
    setGodmodWarnings([]);
    try {
      const result = await apiClient.generateRPReply({
        partner_reply: partnerReply.trim(),
        instructions: instructions.trim() || undefined,
        character_id: characterId ?? undefined,
        story_id: preselectedStoryId ?? undefined,
        response_length: responseLength,
        style_match: styleMatch,
        perspective,
        formatting,
        intensity: contentLevel,
        heat_level: heatLevel,
        model_profile: IS_INTERNAL ? modelProfile : undefined,
        style_archetype: IS_INTERNAL ? styleArchetype : undefined,
      });
      setReply(result.reply);
      setWarnings(result.warnings ?? []);
      setPacingWarnings(result.pacing_warnings ?? []);
      setStyleWarnings(result.style_warnings ?? []);
      setModelUsed(result.model_used ?? '');
      setGenerationTimeMs(result.generation_time_ms ?? 0);
      setDetectedStage(result.detected_stage ?? '');
      setContinuationScore(result.continuation_score ?? null);
      setNextSceneGoal(result.next_scene_goal ?? '');
      setRepetitionScore(result.repetition_score ?? null);
      setProgressionSuccess(result.progression_success ?? null);
      setAiCadenceRisk(result.ai_cadence_risk ?? null);
      setSpatialPosition(result.spatial_position ?? '');
      setSpatialDominance(result.spatial_dominance ?? '');
      setResolvedHeat(result.resolved_heat ?? '');
      setMultiBeatDetected(result.multi_beat_detected ?? null);
      setRequestedBeats(result.requested_beats ?? []);
      setResolvedLengthProfile(result.resolved_length_profile ?? '');
      setMaxTokensUsed(result.max_tokens_used ?? null);
      setBeatCompletionMode(result.beat_completion_mode ?? '');
      setGodmodDetected(result.godmod_detected ?? null);
      setGodmodSeverity(result.godmod_severity ?? '');
      setGodmodWarnings(result.godmod_warnings ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Try again.');
    } finally {
      setLoading(false);
    }
  }

  function handleCopy() {
    navigator.clipboard.writeText(reply).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function handleBenchmarkCopy() {
    const bundle = {
      benchmark_bundle: {
        input: {
          partner_reply: partnerReply.trim(),
          instructions: instructions.trim() || null,
          character_id: characterId,
          response_length: responseLength,
          style_match: styleMatch,
          perspective,
          formatting,
          content_level: contentLevel,
          heat_level: heatLevel,
          intensity: contentLevel,
          style_archetype: styleArchetype,
        },
        model_profile: modelProfile,
        output: {
          reply,
          model_used: modelUsed,
          generation_time_ms: generationTimeMs,
          warnings,
          pacing_warnings: pacingWarnings,
          style_warnings: styleWarnings,
          detected_stage: detectedStage,
          continuation_score: continuationScore,
        },
      },
    };
    navigator.clipboard.writeText(JSON.stringify(bundle, null, 2)).then(() => {
      setBenchmarkCopied(true);
      setTimeout(() => setBenchmarkCopied(false), 2500);
    });
  }

  return (
    <div className="max-w-2xl w-full mx-auto px-4 py-10 space-y-7">

      {/* Partner Reply */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-300">
          Partner's reply
        </label>
        <textarea
          value={partnerReply}
          onChange={(e) => setPartnerReply(e.target.value)}
          placeholder="Paste your writing partner's reply here…"
          rows={9}
          className="w-full bg-gray-900/70 border border-gray-800 rounded-2xl px-4 py-3.5 text-sm text-gray-100 placeholder-gray-700 resize-y focus:outline-none focus:border-gray-600 transition leading-relaxed"
        />
      </div>

      {/* Character selector */}
      {characters.length > 0 && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-300">
            Your character <span className="text-gray-600 font-normal">(optional)</span>
          </label>
          <select
            value={characterId ?? ''}
            onChange={(e) => setCharacterId(e.target.value ? Number(e.target.value) : null)}
            className="w-full bg-gray-900/70 border border-gray-800 rounded-2xl px-4 py-3 text-sm text-gray-100 focus:outline-none focus:border-gray-600 transition"
          >
            <option value="">No character selected</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
      )}

      {/* Instructions */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-300">
          Your guidance <span className="text-gray-600 font-normal">(optional)</span>
        </label>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="e.g. He doesn't kiss her yet. Restrained, deliberate. Do not control her reactions."
          rows={3}
          className="w-full bg-gray-900/70 border border-gray-800 rounded-2xl px-4 py-3.5 text-sm text-gray-100 placeholder-gray-700 resize-y focus:outline-none focus:border-gray-600 transition leading-relaxed"
        />
      </div>

      {/* Content level */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-300">Content level</label>
        <div className="flex gap-2">
          {CONTENT_LEVEL_OPTIONS.map(({ val, label }) => (
            <button
              key={val}
              type="button"
              onClick={() => setContentLevel(val)}
              className={`flex-1 py-2.5 rounded-xl border text-sm font-medium transition ${
                contentLevel === val
                  ? 'border-orange-600/60 bg-orange-950/30 text-orange-200'
                  : 'border-gray-800 text-gray-500 hover:border-gray-700 hover:text-gray-300'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {contentLevel === 'explicit' && (
          <p className="text-xs text-orange-700/70 leading-relaxed">
            Explicit prose is permitted. Partner agency and collaboration space are still enforced.
          </p>
        )}
      </div>

      {/* Advanced options — collapsed by default */}
      <div className="border border-gray-800/50 rounded-2xl overflow-hidden">
        <button
          type="button"
          onClick={() => setShowAdvanced(v => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-500 hover:text-gray-300 hover:bg-gray-900/30 transition"
        >
          <span className="font-medium">Advanced options</span>
          <span className="text-gray-700 select-none">{showAdvanced ? '▲' : '▼'}</span>
        </button>

        {showAdvanced && (
          <div className="px-4 pb-5 pt-1 space-y-5 border-t border-gray-800/40">

            {/* Length + Style Match */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Length</label>
                <div className="flex flex-col gap-1.5">
                  {(['short', 'match', 'long', 'novella'] as RPReplyResponseLength[]).map((val) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setResponseLength(val)}
                      className={`text-left text-sm px-3 py-2 rounded-lg border transition ${
                        responseLength === val
                          ? 'border-emerald-600/60 bg-emerald-950/30 text-emerald-300'
                          : 'border-gray-800 text-gray-500 hover:border-gray-700 hover:text-gray-300'
                      }`}
                    >
                      {val.charAt(0).toUpperCase() + val.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Style match</label>
                <div className="flex flex-col gap-1.5">
                  {(['off', 'soft', 'strong'] as RPReplyStyleMatch[]).map((val) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setStyleMatch(val)}
                      className={`text-left text-sm px-3 py-2 rounded-lg border transition ${
                        styleMatch === val
                          ? 'border-emerald-600/60 bg-emerald-950/30 text-emerald-300'
                          : 'border-gray-800 text-gray-500 hover:border-gray-700 hover:text-gray-300'
                      }`}
                    >
                      {val.charAt(0).toUpperCase() + val.slice(1)}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Perspective + Formatting */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Perspective</label>
                <div className="flex flex-col gap-1.5">
                  {([
                    { val: 'first_person' as RPReplyPerspective, label: '1st Person' },
                    { val: 'third_person_limited' as RPReplyPerspective, label: '3rd Limited' },
                  ]).map(({ val, label }) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setPerspective(val)}
                      className={`text-left text-sm px-3 py-2 rounded-lg border transition ${
                        perspective === val
                          ? 'border-emerald-600/60 bg-emerald-950/30 text-emerald-300'
                          : 'border-gray-800 text-gray-500 hover:border-gray-700 hover:text-gray-300'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Formatting</label>
                <div className="flex flex-col gap-1.5">
                  {([
                    { val: 'plain' as RPReplyFormatting, label: 'Plain prose' },
                    { val: 'roleplay_bars' as RPReplyFormatting, label: '||RP Bars||' },
                  ]).map(({ val, label }) => (
                    <button
                      key={val}
                      type="button"
                      onClick={() => setFormatting(val)}
                      className={`text-left text-sm px-3 py-2 rounded-lg border transition ${
                        formatting === val
                          ? 'border-emerald-600/60 bg-emerald-950/30 text-emerald-300'
                          : 'border-gray-800 text-gray-500 hover:border-gray-700 hover:text-gray-300'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Internal bake-off — gated, inside advanced */}
            {IS_INTERNAL && (
              <div className="border border-violet-900/30 bg-violet-950/10 rounded-xl p-4 space-y-3">
                <span className="text-[10px] font-semibold text-violet-500/80 uppercase tracking-widest">
                  Internal — Bake-off
                </span>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Model profile</label>
                  <select
                    value={modelProfile}
                    onChange={(e) => setModelProfile(e.target.value)}
                    className="w-full bg-gray-900/60 border border-violet-800/40 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-600/60 transition"
                  >
                    {RP_MODEL_OPTIONS.map((opt) => (
                      <option key={opt.profile} value={opt.profile}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">Story style</label>
                  <select
                    value={styleArchetype}
                    onChange={(e) => setStyleArchetype(e.target.value as RPStyleArchetype)}
                    className="w-full bg-gray-900/60 border border-violet-800/40 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-violet-600/60 transition"
                  >
                    {ARCHETYPE_OPTIONS.map((opt) => (
                      <option key={opt.val} value={opt.val}>{opt.label}</option>
                    ))}
                  </select>
                  {styleArchetype && (
                    <p className="text-[10px] text-violet-400/60">
                      {ARCHETYPE_OPTIONS.find(o => o.val === styleArchetype)?.desc}
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Generate button — primary action */}
      <button
        type="button"
        onClick={handleGenerate}
        disabled={loading || !partnerReply.trim()}
        className="w-full py-3.5 rounded-2xl bg-emerald-700 hover:bg-emerald-600 disabled:bg-gray-800 disabled:text-gray-600 text-white font-semibold text-sm tracking-wide transition-colors"
      >
        {loading ? 'Generating…' : 'Generate Reply'}
      </button>

      {/* Error */}
      {error && (
        <p className="text-sm text-red-400 bg-red-950/20 border border-red-900/30 rounded-xl px-4 py-3">
          {error}
        </p>
      )}

      {/* User-facing warnings */}
      {warnings.length > 0 && (
        <div className="space-y-1.5">
          {warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-500/80 bg-amber-950/10 border border-amber-900/20 rounded-xl px-4 py-2.5">
              {w}
            </p>
          ))}
        </div>
      )}

      {pacingWarnings.length > 0 && (
        <div className="space-y-1.5">
          {pacingWarnings.map((w, i) => (
            <p key={i} className="text-xs text-orange-500/70 bg-orange-950/10 border border-orange-900/20 rounded-xl px-4 py-2.5">
              {w}
            </p>
          ))}
        </div>
      )}

      {IS_INTERNAL && styleWarnings.length > 0 && (
        <div className="space-y-1.5">
          {styleWarnings.map((w, i) => (
            <p key={i} className="text-xs text-violet-400/70 bg-violet-950/10 border border-violet-900/20 rounded-xl px-4 py-2.5">
              {w}
            </p>
          ))}
        </div>
      )}

      {/* Output */}
      {reply && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-gray-300">
              Generated reply
            </label>
            <div className="flex items-center gap-2">
              {IS_INTERNAL && (
                <button
                  type="button"
                  onClick={handleBenchmarkCopy}
                  className="text-xs text-violet-500/70 hover:text-violet-400 transition px-2 py-1 rounded border border-violet-900/30 hover:border-violet-700/40"
                >
                  {benchmarkCopied ? 'Bundle copied' : 'Copy bundle'}
                </button>
              )}
              <button
                type="button"
                onClick={handleCopy}
                className="text-xs text-gray-500 hover:text-gray-300 transition px-2.5 py-1.5 rounded-lg border border-gray-800 hover:border-gray-600"
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
          </div>

          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            rows={12}
            className="w-full bg-gray-900/70 border border-gray-700 rounded-2xl px-4 py-4 text-sm text-gray-100 resize-y focus:outline-none focus:border-gray-500 transition leading-relaxed"
          />

          {/* Internal diagnostics */}
          {IS_INTERNAL && (modelUsed || generationTimeMs > 0 || detectedStage || continuationScore !== null) && (
            <div className="flex flex-wrap items-center gap-4 text-[11px] text-gray-600 px-1">
              {modelUsed && <span><span className="text-gray-700">model</span> <span className="text-gray-500 font-mono">{modelUsed}</span></span>}
              {generationTimeMs > 0 && <span><span className="text-gray-700">time</span> <span className="text-gray-500">{generationTimeMs.toLocaleString()}ms</span></span>}
              {detectedStage && <span><span className="text-gray-700">stage</span> <span className="text-gray-500">{detectedStage}</span></span>}
              {continuationScore !== null && (
                <span>
                  <span className="text-gray-700">cont.</span>{' '}
                  <span className={continuationScore >= 0.65 ? 'text-emerald-600/80' : continuationScore >= 0.40 ? 'text-gray-500' : 'text-amber-600/80'}>
                    {continuationScore.toFixed(2)}
                  </span>
                </span>
              )}
              <span>
                <span className="text-gray-700">warns</span>{' '}
                <span className={warnings.length + pacingWarnings.length + styleWarnings.length > 0 ? 'text-amber-600/80' : 'text-gray-500'}>
                  {warnings.length + pacingWarnings.length + styleWarnings.length}
                </span>
              </span>
            </div>
          )}

          {/* Godmod gate — internal only */}
          {IS_INTERNAL && godmodDetected !== null && (
            <div className={`border rounded-xl p-3 space-y-2 ${godmodDetected ? 'border-red-800/50 bg-red-950/20' : 'border-gray-800/40 bg-gray-900/20'}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] font-semibold text-red-500/80 uppercase tracking-widest">Godmod Gate</span>
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${
                  godmodDetected ? 'bg-red-900/40 text-red-400 border-red-700/50'
                  : godmodSeverity === 'soft' ? 'bg-amber-900/30 text-amber-400/80 border-amber-800/30'
                  : 'bg-emerald-900/30 text-emerald-400/80 border-emerald-800/30'
                }`}>
                  {godmodDetected ? 'violation in output' : godmodSeverity === 'soft' ? 'soft (advisory)' : 'clean'}
                </span>
                {godmodSeverity && <span className="text-[10px] text-gray-600 font-mono">{godmodSeverity}</span>}
              </div>
              {godmodWarnings.length > 0 && (
                <div className="space-y-1">
                  {godmodWarnings.map((w, i) => (
                    <p key={i} className="text-[11px] text-red-400/70 font-mono bg-red-950/30 rounded px-2 py-1 leading-relaxed">{w}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Scene beat engine — internal only */}
          {IS_INTERNAL && (nextSceneGoal || repetitionScore !== null || progressionSuccess !== null || aiCadenceRisk !== null || spatialPosition || resolvedHeat || multiBeatDetected !== null || resolvedLengthProfile || maxTokensUsed !== null) && (
            <div className="border border-violet-900/30 bg-violet-950/10 rounded-xl p-3 space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] font-semibold text-violet-500/80 uppercase tracking-widest">Scene Beat Engine</span>
                {progressionSuccess !== null && (
                  <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${progressionSuccess ? 'bg-emerald-900/40 text-emerald-400/80 border border-emerald-800/40' : 'bg-amber-900/30 text-amber-500/70 border border-amber-800/30'}`}>
                    {progressionSuccess ? 'progressed' : 'stalled'}
                  </span>
                )}
                {aiCadenceRisk && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-900/30 text-red-400/70 border border-red-800/30">ai cadence</span>
                )}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                {nextSceneGoal && <span><span className="text-violet-700/80">next goal</span> <span className="text-violet-400/70">{nextSceneGoal}</span></span>}
                {repetitionScore !== null && (
                  <span>
                    <span className="text-violet-700/80">rep.</span>{' '}
                    <span className={repetitionScore < 0.2 ? 'text-emerald-600/70' : repetitionScore < 0.5 ? 'text-amber-600/70' : 'text-red-500/70'}>
                      {repetitionScore.toFixed(2)}
                    </span>
                  </span>
                )}
                {detectedStage && <span><span className="text-violet-700/80">input stage</span> <span className="text-violet-400/70">{detectedStage}</span></span>}
                {resolvedHeat && resolvedHeat !== heatLevel && <span><span className="text-violet-700/80">resolved heat</span> <span className="text-orange-400/70">{resolvedHeat}</span></span>}
              </div>
              {(spatialPosition || spatialDominance) && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] border-t border-violet-900/20 pt-2 mt-1">
                  <span className="text-[10px] text-violet-600/60 uppercase tracking-widest w-full">Spatial</span>
                  {spatialPosition && <span><span className="text-violet-700/80">position</span> <span className="text-violet-400/70">{spatialPosition}</span></span>}
                  {spatialDominance && spatialDominance !== 'neutral' && <span><span className="text-violet-700/80">dynamic</span> <span className="text-violet-400/70">{spatialDominance}</span></span>}
                </div>
              )}
              {(multiBeatDetected !== null || resolvedLengthProfile || maxTokensUsed !== null) && (
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] border-t border-violet-900/20 pt-2 mt-1">
                  <span className="text-[10px] text-violet-600/60 uppercase tracking-widest w-full">Beat Planner / Length</span>
                  {resolvedLengthProfile && <span><span className="text-violet-700/80">length</span> <span className="text-violet-400/70">{resolvedLengthProfile}</span></span>}
                  {maxTokensUsed !== null && maxTokensUsed > 0 && <span><span className="text-violet-700/80">max_tok</span> <span className="text-violet-400/70">{maxTokensUsed.toLocaleString()}</span></span>}
                  {multiBeatDetected !== null && (
                    <span>
                      <span className="text-violet-700/80">multi-beat</span>{' '}
                      <span className={multiBeatDetected ? 'text-emerald-400/80' : 'text-gray-600'}>{multiBeatDetected ? 'detected' : 'no'}</span>
                    </span>
                  )}
                  {beatCompletionMode && beatCompletionMode !== 'single' && <span><span className="text-violet-700/80">mode</span> <span className="text-emerald-400/70">{beatCompletionMode}</span></span>}
                  {requestedBeats.length > 0 && (
                    <span className="w-full">
                      <span className="text-violet-700/80">beats</span>{' '}
                      <span className="text-violet-400/70">{requestedBeats.join(' → ')}</span>
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  );
}

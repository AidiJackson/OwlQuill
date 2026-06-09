/**
 * Adult Studio FOUNDER GENERATE — pure UI logic (Phase 3, Sprint 8).
 *
 * Founder/admin-only path that runs the VALIDATED Adult Studio pipeline (active LoRA +
 * enforcement plan + tattoo-enforcement executor + both Summer routes) — NOT the old
 * OpenAI gpt-image generate path. This module holds only pure, DOM-free logic so it is
 * unit-testable in the node vitest env: gating (when the panel is allowed) and result
 * formatting (how the response renders).
 */

// The single Summer character the founder Generate path is wired to.
export const SUMMER_CHARACTER_ID = 60;

export interface FounderRouteExecuted {
  route: string;
  status?: string;
  region?: string | null;
  side?: string | null;
  artifact_kind?: string | null;
  artifact_url?: string | null;
}

export interface FounderGenerateResult {
  final_image_url: string | null;
  intermediate_artifact_urls: string[];
  cost: number;
  runtime: number;
  routes_executed: FounderRouteExecuted[];
  manual_review_required: boolean;
  success: boolean;
  blocking_reasons: string[];
  orphaned_workers: string[];
}

export interface FounderGateInput {
  isAdmin: boolean;
  characterId: number | null;
  status: string | undefined;
  activeVersionId: number | null | undefined;
}

/**
 * Whether the founder Generate panel may be shown for the current selection.
 *
 * Mirrors the backend gates exactly: admin/founder only, Summer only (id=60),
 * identity status 'ready', and a resolvable active version. (Prompt-required and
 * prompt-safety are enforced at submit time / on the backend, not here.)
 */
export function canFounderGenerate(input: FounderGateInput): boolean {
  return (
    input.isAdmin === true &&
    input.characterId === SUMMER_CHARACTER_ID &&
    input.status === 'ready' &&
    input.activeVersionId != null
  );
}

/** Whether the Generate button should be enabled (panel shown + non-empty prompt + idle). */
export function canSubmitFounderPrompt(prompt: string, generating: boolean): boolean {
  return !generating && prompt.trim().length > 0;
}

export interface FounderResultView {
  finalImageUrl: string | null;
  intermediateUrls: string[];
  costLabel: string;
  runtimeLabel: string;
  routeLabels: string[];
  manualReviewRequired: boolean;
}

/** Map a backend result into the display strings the UI renders. */
export function formatFounderResult(res: FounderGenerateResult): FounderResultView {
  return {
    finalImageUrl: res.final_image_url,
    intermediateUrls: res.intermediate_artifact_urls ?? [],
    costLabel: `$${(res.cost ?? 0).toFixed(4)}`,
    runtimeLabel: `${(res.runtime ?? 0).toFixed(1)}s`,
    routeLabels: (res.routes_executed ?? []).map(
      (r) => `${r.route}${r.status ? ` · ${r.status}` : ''}`,
    ),
    manualReviewRequired: res.manual_review_required === true,
  };
}

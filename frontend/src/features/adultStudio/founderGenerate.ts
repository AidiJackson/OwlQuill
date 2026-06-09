/**
 * Adult Studio FOUNDER GENERATE — pure UI logic (Phase 3, Sprints 8 + 13).
 *
 * Founder/admin-only path that runs the VALIDATED Adult Studio pipeline (active LoRA +
 * enforcement plan + tattoo-enforcement executor + both Summer routes) — NOT the old
 * OpenAI gpt-image generate path. Sprint 13 makes it ASYNC (fire-and-poll): start a job,
 * poll its state, render the real RunPod 99_final on completion. This module holds only
 * pure, DOM-free logic so it is unit-testable in the node vitest env.
 */

// The single Summer character the founder Generate path is wired to.
export const SUMMER_CHARACTER_ID = 60;

export type FounderJobState = 'queued' | 'running' | 'completed' | 'failed';

export interface FounderRouteExecuted {
  route: string;
  status?: string;
  region?: string | null;
  side?: string | null;
  canon_mark_id?: string | null;
  reference_uri?: string | null;
  result_artifact_url?: string | null;
}

/** A founder async job snapshot, mirroring the backend FounderJobResponse. */
export interface FounderJob {
  job_id: number;
  character_id: number;
  state: FounderJobState;
  run_id: string;
  final_image_url: string | null;
  intermediate_artifact_urls: string[];
  cost: number;
  runtime: number;
  routes_executed: FounderRouteExecuted[];
  manual_review_required: boolean;
  blocking_reasons: string[];
  orphaned_workers: string[];
  error?: string | null;
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
 * Mirrors the backend gates: admin/founder only, Summer only (id=60), identity status
 * 'ready', and a resolvable active version.
 */
export function canFounderGenerate(input: FounderGateInput): boolean {
  return (
    input.isAdmin === true &&
    input.characterId === SUMMER_CHARACTER_ID &&
    input.status === 'ready' &&
    input.activeVersionId != null
  );
}

/** A job in queued/running is active and blocks a new launch. */
export function isJobActive(state: FounderJobState | null | undefined): boolean {
  return state === 'queued' || state === 'running';
}

/** Generate is allowed only with a non-empty prompt, no active job, and not mid-submit. */
export function canSubmitFounderPrompt(
  prompt: string,
  submitting: boolean,
  activeState: FounderJobState | null | undefined,
): boolean {
  return !submitting && !isJobActive(activeState) && prompt.trim().length > 0;
}

export interface FounderJobView {
  state: FounderJobState;
  statusLabel: string;
  isActive: boolean;
  finalImageUrl: string | null;
  intermediateUrls: string[];
  costLabel: string;
  runtimeLabel: string;
  routeLabels: string[];
  manualReviewRequired: boolean;
  errorText: string | null;
}

const STATE_LABEL: Record<FounderJobState, string> = {
  queued: 'Queued…',
  running: 'Generating… (RunPod masked diffusion)',
  completed: 'Completed',
  failed: 'Failed',
};

/** Map a backend job into the display fields the UI renders. */
export function formatFounderJob(job: FounderJob): FounderJobView {
  const errorText =
    job.state === 'failed'
      ? job.error || (job.blocking_reasons && job.blocking_reasons[0]) || 'Generation failed.'
      : null;
  return {
    state: job.state,
    statusLabel: STATE_LABEL[job.state] ?? job.state,
    isActive: isJobActive(job.state),
    finalImageUrl: job.state === 'completed' ? job.final_image_url : null,
    intermediateUrls: job.intermediate_artifact_urls ?? [],
    costLabel: `$${(job.cost ?? 0).toFixed(4)}`,
    runtimeLabel: `${(job.runtime ?? 0).toFixed(1)}s`,
    routeLabels: (job.routes_executed ?? []).map(
      (r) => `${r.route}${r.status ? ` · ${r.status}` : ''}`,
    ),
    manualReviewRequired: job.manual_review_required === true,
    errorText,
  };
}

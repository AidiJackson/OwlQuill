import { describe, it, expect } from 'vitest';
import {
  SUMMER_CHARACTER_ID,
  canFounderGenerate,
  canSubmitFounderPrompt,
  isJobActive,
  formatFounderJob,
  type FounderJob,
} from '../founderGenerate';

const READY = {
  isAdmin: true,
  characterId: SUMMER_CHARACTER_ID,
  status: 'ready',
  activeVersionId: 7,
};

function job(overrides: Partial<FounderJob> = {}): FounderJob {
  return {
    job_id: 1,
    character_id: 60,
    state: 'completed',
    run_id: 'founder_x',
    final_image_url: 'https://r2.dev/proof/run/99_final.png',
    intermediate_artifact_urls: ['https://r2.dev/proof/run/01_base.png', 'https://r2.dev/proof/run/03.png'],
    cost: 0.0141,
    runtime: 317.5,
    routes_executed: [
      { route: 'ip_adapter', status: 'executed' },
      { route: 'controlnet_canny', status: 'executed' },
    ],
    manual_review_required: true,
    blocking_reasons: [],
    orphaned_workers: [],
    error: null,
    ...overrides,
  };
}

describe('canFounderGenerate gating', () => {
  it('allows admin + Summer + ready + active version', () => {
    expect(canFounderGenerate(READY)).toBe(true);
  });
  it('blocks non-admin', () => {
    expect(canFounderGenerate({ ...READY, isAdmin: false })).toBe(false);
  });
  it('blocks non-Summer characters', () => {
    expect(canFounderGenerate({ ...READY, characterId: 12 })).toBe(false);
    expect(canFounderGenerate({ ...READY, characterId: null })).toBe(false);
  });
  it('blocks when status is not ready', () => {
    expect(canFounderGenerate({ ...READY, status: 'prepared' })).toBe(false);
    expect(canFounderGenerate({ ...READY, status: undefined })).toBe(false);
  });
  it('blocks when there is no active version', () => {
    expect(canFounderGenerate({ ...READY, activeVersionId: null })).toBe(false);
    expect(canFounderGenerate({ ...READY, activeVersionId: undefined })).toBe(false);
  });
});

describe('isJobActive', () => {
  it('queued and running are active', () => {
    expect(isJobActive('queued')).toBe(true);
    expect(isJobActive('running')).toBe(true);
  });
  it('completed/failed/none are not active', () => {
    expect(isJobActive('completed')).toBe(false);
    expect(isJobActive('failed')).toBe(false);
    expect(isJobActive(null)).toBe(false);
    expect(isJobActive(undefined)).toBe(false);
  });
});

describe('canSubmitFounderPrompt', () => {
  it('requires a non-empty prompt, no active job, not submitting', () => {
    expect(canSubmitFounderPrompt('', false, null)).toBe(false);
    expect(canSubmitFounderPrompt('   ', false, null)).toBe(false);
    expect(canSubmitFounderPrompt('summer poolside', false, null)).toBe(true);
  });
  it('is blocked while a job is active', () => {
    expect(canSubmitFounderPrompt('summer poolside', false, 'running')).toBe(false);
    expect(canSubmitFounderPrompt('summer poolside', false, 'queued')).toBe(false);
  });
  it('is blocked while submitting', () => {
    expect(canSubmitFounderPrompt('summer poolside', true, null)).toBe(false);
  });
  it('is allowed again once a job is completed/failed', () => {
    expect(canSubmitFounderPrompt('summer poolside', false, 'completed')).toBe(true);
    expect(canSubmitFounderPrompt('summer poolside', false, 'failed')).toBe(true);
  });
});

describe('formatFounderJob (response renders)', () => {
  it('maps a completed job to the real final image (no montage)', () => {
    const view = formatFounderJob(job());
    expect(view.state).toBe('completed');
    expect(view.isActive).toBe(false);
    expect(view.finalImageUrl).toBe('https://r2.dev/proof/run/99_final.png');
    expect(view.costLabel).toBe('$0.0141');
    expect(view.runtimeLabel).toBe('317.5s');
    expect(view.routeLabels).toEqual(['ip_adapter · executed', 'controlnet_canny · executed']);
    expect(view.manualReviewRequired).toBe(true);
    expect(view.errorText).toBeNull();
  });

  it('running job shows active and no final image', () => {
    const view = formatFounderJob(job({ state: 'running', final_image_url: null }));
    expect(view.isActive).toBe(true);
    expect(view.statusLabel).toMatch(/Generating/);
    expect(view.finalImageUrl).toBeNull();
  });

  it('failed job surfaces the error text', () => {
    const view = formatFounderJob(
      job({ state: 'failed', final_image_url: null, error: 'Timed out after 1500s' }),
    );
    expect(view.state).toBe('failed');
    expect(view.finalImageUrl).toBeNull();
    expect(view.errorText).toBe('Timed out after 1500s');
  });

  it('failed job falls back to the first blocking reason', () => {
    const view = formatFounderJob(
      job({ state: 'failed', final_image_url: null, error: null, blocking_reasons: ['pod crashed'] }),
    );
    expect(view.errorText).toBe('pod crashed');
  });
});

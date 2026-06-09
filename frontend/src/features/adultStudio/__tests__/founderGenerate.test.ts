import { describe, it, expect } from 'vitest';
import {
  SUMMER_CHARACTER_ID,
  canFounderGenerate,
  canSubmitFounderPrompt,
  formatFounderResult,
  type FounderGenerateResult,
} from '../founderGenerate';

const READY = {
  isAdmin: true,
  characterId: SUMMER_CHARACTER_ID,
  status: 'ready',
  activeVersionId: 7,
};

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

describe('canSubmitFounderPrompt', () => {
  it('requires a non-empty prompt', () => {
    expect(canSubmitFounderPrompt('', false)).toBe(false);
    expect(canSubmitFounderPrompt('   ', false)).toBe(false);
    expect(canSubmitFounderPrompt('summer poolside', false)).toBe(true);
  });

  it('is disabled while generating', () => {
    expect(canSubmitFounderPrompt('summer poolside', true)).toBe(false);
  });
});

describe('formatFounderResult (response renders)', () => {
  it('maps a successful result into display fields', () => {
    const res: FounderGenerateResult = {
      final_image_url: 'https://fake.local/final.png',
      intermediate_artifact_urls: ['https://fake.local/base.png', 'https://fake.local/a.png'],
      cost: 0.0182,
      runtime: 19.42,
      routes_executed: [
        { route: 'ip_adapter', status: 'prepared' },
        { route: 'controlnet_canny', status: 'prepared' },
      ],
      manual_review_required: true,
      success: true,
      blocking_reasons: [],
      orphaned_workers: [],
    };
    const view = formatFounderResult(res);
    expect(view.finalImageUrl).toBe('https://fake.local/final.png');
    expect(view.intermediateUrls).toHaveLength(2);
    expect(view.costLabel).toBe('$0.0182');
    expect(view.runtimeLabel).toBe('19.4s');
    expect(view.routeLabels).toEqual(['ip_adapter · prepared', 'controlnet_canny · prepared']);
    expect(view.manualReviewRequired).toBe(true);
  });
});

import { describe, it, expect } from 'vitest';
import { extractApiErrorMessage } from '../errorMessage';

describe('extractApiErrorMessage', () => {
  it('reads detail.detail from a structured StoryLab error (quota / canon / failure)', () => {
    const payload = {
      detail: {
        error: 'quota_exceeded',
        detail: 'Daily chapter limit reached (5/5).',
        hint: 'Limit resets at midnight UTC.',
      },
    };
    expect(extractApiErrorMessage(payload, 429)).toBe('Daily chapter limit reached (5/5).');
  });

  it('does NOT stringify a structured detail object to "[object Object]"', () => {
    const payload = { detail: { error: 'storylab_failed', detail: 'Story generation failed.' } };
    expect(extractApiErrorMessage(payload, 502)).not.toBe('[object Object]');
    expect(extractApiErrorMessage(payload, 502)).toBe('Story generation failed.');
  });

  it('falls back to detail.message when detail.detail is absent', () => {
    const payload = { detail: { message: 'Boundary conflict.' } };
    expect(extractApiErrorMessage(payload, 422)).toBe('Boundary conflict.');
  });

  it('handles a plain string detail (FastAPI default shape)', () => {
    expect(extractApiErrorMessage({ detail: 'Chapter not found' }, 404)).toBe('Chapter not found');
  });

  it('falls back to an HTTP status string when no detail is present', () => {
    expect(extractApiErrorMessage({}, 500)).toBe('HTTP 500');
    expect(extractApiErrorMessage(null, 503)).toBe('HTTP 503');
  });
});

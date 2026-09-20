import { describe, expect, it } from 'vitest';
import {
  EDITOR_DEFAULT_PROVIDER,
  EDITOR_DEFAULT_STRENGTH,
  EDITOR_MAX_SOURCE_IMAGES,
  EDITOR_PROVIDERS,
  EDITOR_PROVIDER_HINTS,
  EDITOR_PROVIDER_LABELS,
  type KeyValueStorage,
  acceptSourceFiles,
  buildEditorFormData,
  clampStrength,
  type EditorGenerateResult,
  type EditorJob,
  describeEditorJob,
  isEditorJobActive,
  isEditorProvider,
  loadEditorProvider,
  resolveEditorImageUrl,
  SELF_HOSTED_EDITOR_CHARACTER_ID,
  SELF_HOSTED_UNAVAILABLE_HINT,
  resolveProviderForCharacter,
  saveEditorProvider,
  selfHostedEditorSupportsCharacter,
  validateEditorForm,
} from '../editorGenerate';

function fakeStorage(initial: Record<string, string> = {}): KeyValueStorage & { data: Record<string, string> } {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v;
    },
  };
}

function fakeFile(name: string, type = 'image/png'): File {
  return new File(['x'], name, { type });
}

describe('clampStrength', () => {
  it('clamps below the minimum to 0.1', () => {
    expect(clampStrength(0.01)).toBe(0.1);
  });
  it('clamps above the maximum to 0.5', () => {
    expect(clampStrength(0.9)).toBe(0.5);
  });
  it('passes through in-range values', () => {
    expect(clampStrength(0.25)).toBe(0.25);
  });
  it('falls back to the default for NaN', () => {
    expect(clampStrength(Number.NaN)).toBe(EDITOR_DEFAULT_STRENGTH);
  });
});

describe('validateEditorForm', () => {
  const valid = { characterId: 60, prompt: 'Beach scene', fileCount: 1 };

  it('accepts a valid form', () => {
    expect(validateEditorForm(valid)).toBeNull();
  });
  it('requires a character', () => {
    expect(validateEditorForm({ ...valid, characterId: null })).toMatch(/character/i);
  });
  it('requires a non-empty prompt', () => {
    expect(validateEditorForm({ ...valid, prompt: '   ' })).toMatch(/prompt/i);
  });
  it('requires at least one image', () => {
    expect(validateEditorForm({ ...valid, fileCount: 0 })).toMatch(/source image/i);
  });
  it('rejects more than the max images', () => {
    expect(validateEditorForm({ ...valid, fileCount: 4 })).toMatch(/3/);
  });
});

describe('acceptSourceFiles', () => {
  it('keeps accepted image types', () => {
    const out = acceptSourceFiles([], [fakeFile('a.png'), fakeFile('b.jpg', 'image/jpeg')]);
    expect(out).toHaveLength(2);
  });
  it('drops non-image files', () => {
    const out = acceptSourceFiles([], [fakeFile('a.txt', 'text/plain')]);
    expect(out).toHaveLength(0);
  });
  it('caps the total at the max', () => {
    const existing = [fakeFile('1.png'), fakeFile('2.png'), fakeFile('3.png')];
    const out = acceptSourceFiles(existing, [fakeFile('4.png')]);
    expect(out).toHaveLength(EDITOR_MAX_SOURCE_IMAGES);
  });
});

describe('editor providers (E2)', () => {
  it('includes grok in the provider list', () => {
    expect(EDITOR_PROVIDERS).toContain('grok');
  });
  it('keeps gpt-image as the default', () => {
    expect(EDITOR_DEFAULT_PROVIDER).toBe('gpt-image');
  });
  it('validates provider names', () => {
    expect(isEditorProvider('grok')).toBe(true);
    expect(isEditorProvider('gpt-image')).toBe(true);
    expect(isEditorProvider('dall-e-1')).toBe(false);
    expect(isEditorProvider(null)).toBe(false);
  });
  it('persists and reloads a grok selection', () => {
    const storage = fakeStorage();
    saveEditorProvider(storage, 'grok');
    expect(loadEditorProvider(storage)).toBe('grok');
  });
  it('falls back to the default for missing or unknown stored values', () => {
    expect(loadEditorProvider(fakeStorage())).toBe(EDITOR_DEFAULT_PROVIDER);
    const storage = fakeStorage();
    saveEditorProvider(storage, 'not-a-provider');
    expect(loadEditorProvider(storage)).toBe(EDITOR_DEFAULT_PROVIDER);
  });
});

describe('self_hosted provider (E4)', () => {
  it('includes self_hosted in the provider list with its premium label', () => {
    expect(EDITOR_PROVIDERS).toContain('self_hosted');
    expect(isEditorProvider('self_hosted')).toBe(true);
    expect(EDITOR_PROVIDER_LABELS.self_hosted).toBe('Self Hosted Premium');
    expect(EDITOR_PROVIDER_HINTS.self_hosted).toMatch(/unrestricted/i);
  });
  it('persists and reloads a self_hosted selection', () => {
    const storage = fakeStorage();
    saveEditorProvider(storage, 'self_hosted');
    expect(loadEditorProvider(storage)).toBe('self_hosted');
  });
  it('requires exactly one source image for self_hosted', () => {
    const base = { characterId: 60, prompt: 'Blue bikini at a beach resort', provider: 'self_hosted' };
    expect(validateEditorForm({ ...base, fileCount: 1 })).toBeNull();
    expect(validateEditorForm({ ...base, fileCount: 2 })).toMatch(/exactly 1/i);
  });
  it('does not apply the single-image rule to other providers', () => {
    expect(
      validateEditorForm({ characterId: 60, prompt: 'x', fileCount: 2, provider: 'grok' }),
    ).toBeNull();
  });
});

describe('self_hosted character compatibility (Phase 6.3B)', () => {
  it('pins the one supported character — widening this is a deliberate act', () => {
    // Mirror of SELF_HOSTED_EDITOR_CHARACTER_ID in
    // backend/app/services/editor_studio.py; the server refuses every other
    // character, so a drift here would only make the UI lie.
    expect(SELF_HOSTED_EDITOR_CHARACTER_ID).toBe(60);
    expect(selfHostedEditorSupportsCharacter(60)).toBe(true);
    for (const other of [1, 59, 61, 0, null]) {
      expect(selfHostedEditorSupportsCharacter(other)).toBe(false);
    }
  });
  it('refuses self_hosted for any other character before the request is built', () => {
    const base = { prompt: 'Blue bikini at a beach resort', provider: 'self_hosted', fileCount: 1 };
    expect(validateEditorForm({ ...base, characterId: 60 })).toBeNull();
    const err = validateEditorForm({ ...base, characterId: 61 });
    expect(err).toMatch(/not available for this character/);
    expect(err).toContain(SELF_HOSTED_UNAVAILABLE_HINT);
    // Truthful and non-internal: no character name, id, model or token.
    expect(err).not.toMatch(/summer|60|lora|tok\b/i);
  });
  it('is self_hosted\'s rule alone', () => {
    for (const provider of ['gpt-image', 'grok']) {
      expect(validateEditorForm({ characterId: 61, prompt: 'x', fileCount: 1, provider })).toBeNull();
    }
  });
  it('falls a held self_hosted choice back to the default for an incompatible character', () => {
    expect(resolveProviderForCharacter('self_hosted', 60)).toBe('self_hosted');
    expect(resolveProviderForCharacter('self_hosted', 61)).toBe(EDITOR_DEFAULT_PROVIDER);
    expect(resolveProviderForCharacter('self_hosted', null)).toBe(EDITOR_DEFAULT_PROVIDER);
    expect(resolveProviderForCharacter('grok', 61)).toBe('grok');
    expect(resolveProviderForCharacter('gpt-image', 61)).toBe('gpt-image');
  });
});

describe('async editor jobs (E5)', () => {
  const baseJob: EditorJob = {
    id: 7,
    character_id: 60,
    provider: 'self_hosted',
    prompt: 'Black bikini on the beach',
    state: 'running',
    run_id: 'editor_job_x',
  };

  it('classifies active states', () => {
    expect(isEditorJobActive('queued')).toBe(true);
    expect(isEditorJobActive('running')).toBe(true);
    expect(isEditorJobActive('completed')).toBe(false);
    expect(isEditorJobActive('failed')).toBe(false);
    expect(isEditorJobActive(null)).toBe(false);
  });

  it('returns null for no job', () => {
    expect(describeEditorJob(null)).toBeNull();
  });

  it('describes a running job', () => {
    const out = describeEditorJob(baseJob)!;
    expect(out.kind).toBe('running');
    expect(out.imageUrl).toBeNull();
  });

  it('describes a clean completed job as success with its image', () => {
    const out = describeEditorJob({
      ...baseJob,
      state: 'completed',
      quality_status: 'pass',
      final_image_url: '/static/final.png',
    })!;
    expect(out.kind).toBe('success');
    expect(out.imageUrl).toBe('/static/final.png');
  });

  it('does NOT call a needs_review result a success', () => {
    const out = describeEditorJob({
      ...baseJob,
      state: 'completed',
      quality_status: 'needs_review',
      final_image_url: '/static/final.png',
      result: { quality_reasons: ['harsh person/background seam (ratio 3.1)'] },
    })!;
    expect(out.kind).toBe('needs_review');
    expect(out.message).toMatch(/seam/);
    expect(out.imageUrl).toBe('/static/final.png');
  });

  it('describes a failed job with its error', () => {
    const out = describeEditorJob({ ...baseJob, state: 'failed', error: 'spend cap hit' })!;
    expect(out.kind).toBe('failed');
    expect(out.message).toBe('spend cap hit');
    expect(out.imageUrl).toBeNull();
  });

  it('falls back to the nested image url for completed jobs', () => {
    const out = describeEditorJob({
      ...baseJob,
      state: 'completed',
      quality_status: 'pass',
      image: { id: 9, file_path: 'x', url: '/static/nested.png' },
    })!;
    expect(out.imageUrl).toBe('/static/nested.png');
  });
});

describe('resolveEditorImageUrl (E4.1)', () => {
  const base: EditorGenerateResult = {
    success: true,
    image_url: null,
    character_id: 60,
    provider: 'self_hosted',
    prompt: 'x',
    strength: 0.25,
    image: null,
  };

  it('prefers the top-level image_url', () => {
    expect(
      resolveEditorImageUrl({ ...base, image_url: '/static/a.png', image: { id: 1, file_path: 'a', url: '/static/b.png' } }),
    ).toBe('/static/a.png');
  });
  it('falls back to the nested image.url', () => {
    expect(
      resolveEditorImageUrl({ ...base, image: { id: 1, file_path: 'a', url: '/static/b.png' } }),
    ).toBe('/static/b.png');
  });
  it('returns null when no URL is present', () => {
    expect(resolveEditorImageUrl(base)).toBeNull();
    expect(resolveEditorImageUrl(null)).toBeNull();
  });
});

describe('buildEditorFormData', () => {
  it('builds the multipart payload with clamped strength', () => {
    const form = buildEditorFormData({
      characterId: 60,
      prompt: '  Summer on the beach  ',
      provider: 'gpt-image',
      strength: 0.9,
      files: [fakeFile('src.png')],
    });
    expect(form.get('character_id')).toBe('60');
    expect(form.get('prompt')).toBe('Summer on the beach');
    expect(form.get('provider')).toBe('gpt-image');
    expect(form.get('strength')).toBe('0.5');
    expect(form.getAll('images')).toHaveLength(1);
  });
  it('never sends more than the max files', () => {
    const form = buildEditorFormData({
      characterId: 60,
      prompt: 'p',
      provider: 'gpt-image',
      strength: 0.25,
      files: [fakeFile('1.png'), fakeFile('2.png'), fakeFile('3.png'), fakeFile('4.png')],
    });
    expect(form.getAll('images')).toHaveLength(EDITOR_MAX_SOURCE_IMAGES);
  });
});

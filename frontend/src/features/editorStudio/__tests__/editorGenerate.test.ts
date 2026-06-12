import { describe, expect, it } from 'vitest';
import {
  EDITOR_DEFAULT_STRENGTH,
  EDITOR_MAX_SOURCE_IMAGES,
  acceptSourceFiles,
  buildEditorFormData,
  clampStrength,
  validateEditorForm,
} from '../editorGenerate';

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

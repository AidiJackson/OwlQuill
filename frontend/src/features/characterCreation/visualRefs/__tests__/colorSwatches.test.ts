import { describe, it, expect } from 'vitest';
import { EYE_COLORS, HAIR_COLORS, SKIN_TONES } from '../../shared/types';
import { EYE_COLOR_SWATCHES, HAIR_COLOR_SWATCHES, SKIN_TONE_SWATCHES } from '../colorSwatches';

const HEX = /^#[0-9a-f]{6}$/i;

describe('colour swatches (C14) cover every current option and nothing else', () => {
  it.each([
    ['eye', EYE_COLORS, EYE_COLOR_SWATCHES],
    ['hair', HAIR_COLORS, HAIR_COLOR_SWATCHES],
    ['skin', SKIN_TONES, SKIN_TONE_SWATCHES],
  ] as const)('%s', (_name, options, swatches) => {
    expect(Object.keys(swatches).sort()).toEqual([...options].sort());
    for (const v of Object.values(swatches)) expect(v).toMatch(HEX);
  });
});

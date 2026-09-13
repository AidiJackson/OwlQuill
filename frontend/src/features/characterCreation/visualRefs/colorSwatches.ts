// Explanatory colour dots for the three colour chip rows (Polish Phase 3A, C14).
//
// Presentation only: a recognisable tint beside the existing text label, so
// "Hazel" or "Porcelain" reads at a glance. The stored values are the labels
// themselves and are untouched; nothing here is sent anywhere. Deliberately
// approximate — the dot aids recognition, it does not define the colour, and
// this is not a skin-tone taxonomy.
import { EYE_COLORS, HAIR_COLORS, SKIN_TONES } from '../shared/types';

export const EYE_COLOR_SWATCHES: Record<(typeof EYE_COLORS)[number], string> = {
  Brown: '#5b3a1e',
  Blue: '#5b8fd6',
  Green: '#4f8a5b',
  Hazel: '#8a6d3b',
  Amber: '#c98a2b',
  Gray: '#8e949a',
  Violet: '#7b5ea7',
};

export const HAIR_COLOR_SWATCHES: Record<(typeof HAIR_COLORS)[number], string> = {
  Blonde: '#d9b56b',
  Brunette: '#5a3b24',
  Black: '#1b1b1f',
  Red: '#a3341f',
  Auburn: '#7a3a1f',
  Silver: '#b9bcc2',
  Platinum: '#e8e2cf',
  Copper: '#b8602a',
  Strawberry: '#d98a68',
  Gray: '#8a8a8a',
};

export const SKIN_TONE_SWATCHES: Record<(typeof SKIN_TONES)[number], string> = {
  Fair: '#f3dccb',
  Light: '#ecc7a9',
  Olive: '#c9a27c',
  Tan: '#c68f5e',
  Brown: '#8d5a3b',
  Dark: '#5a3a26',
  Pale: '#f6e6da',
  Golden: '#d9a86c',
  Porcelain: '#f8ede4',
  Caramel: '#b57a4a',
};

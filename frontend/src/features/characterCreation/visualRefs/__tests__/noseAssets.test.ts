// The installed Nose reference images are where refAssetUrl resolves them.
//
// The catalog key doubles as the asset folder (public/creator-refs/<key>/),
// so an image installed under any other folder name — "nose/" instead of
// "nose_type/" — is silently a placeholder tile in the UI. This pins the
// twelve files (six values × two example sets) to the paths the picker
// actually requests. Nose only: categories whose images are not installed
// yet legitimately show placeholders.
import { describe, expect, it } from 'vitest';
import { EXAMPLE_SETS, NOSE_CATEGORY } from '../refCatalog';
import { CREATOR_REFS_BASE, refAssetUrl } from '../refAssetUrl';

// Vite globs the filesystem, so files under public/ are listed by path.
// Keys are relative to this file; only the part under public/ is compared.
const PUBLIC_PREFIX = '../../../../../public';
const installed = Object.keys(
  import.meta.glob('../../../../../public/creator-refs/nose_type/*/*.webp'),
).map((k) => k.slice(PUBLIC_PREFIX.length));

describe('nose reference assets', () => {
  it('exist at every path the picker resolves, for both example sets', () => {
    const expected: string[] = [];
    for (const { value: set } of EXAMPLE_SETS) {
      for (const { value } of NOSE_CATEGORY.options) {
        const url = refAssetUrl(NOSE_CATEGORY.key, set, value);
        expect(url.startsWith(`${CREATOR_REFS_BASE}/nose_type/`)).toBe(true);
        expected.push(url);
      }
    }
    expect(expected).toHaveLength(12);
    expect([...installed].sort()).toEqual([...expected].sort());
  });
});

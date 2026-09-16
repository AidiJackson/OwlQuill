// The installed Lips reference images are where refAssetUrl resolves them.
//
// Same guard as noseAssets.test.ts: the catalog key doubles as the asset
// folder (public/creator-refs/<key>/), so a set installed under any other
// name — "lips/" instead of "lip_type/" — is silently a placeholder tile
// in the UI. Pins the eight files (four values × two example sets) to the
// paths the picker actually requests.
import { describe, expect, it } from 'vitest';
import { EXAMPLE_SETS, LIP_CATEGORY } from '../refCatalog';
import { CREATOR_REFS_BASE, refAssetUrl } from '../refAssetUrl';

// Vite globs the filesystem, so files under public/ are listed by path.
// Keys are relative to this file; only the part under public/ is compared.
const PUBLIC_PREFIX = '../../../../../public';
const installed = Object.keys(
  import.meta.glob('../../../../../public/creator-refs/lip_type/*/*.webp'),
).map((k) => k.slice(PUBLIC_PREFIX.length));

describe('lips reference assets', () => {
  it('exist at every path the picker resolves, for both example sets', () => {
    const expected: string[] = [];
    for (const { value: set } of EXAMPLE_SETS) {
      for (const { value } of LIP_CATEGORY.options) {
        const url = refAssetUrl(LIP_CATEGORY.key, set, value);
        expect(url.startsWith(`${CREATOR_REFS_BASE}/lip_type/`)).toBe(true);
        expected.push(url);
      }
    }
    expect(expected).toHaveLength(8);
    expect([...installed].sort()).toEqual([...expected].sort());
  });
});

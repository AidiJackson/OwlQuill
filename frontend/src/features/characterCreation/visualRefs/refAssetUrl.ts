// Where an explanatory reference image lives.
//
// `public/creator-refs/<category>/<set>/<value>.webp`, served at
// `/creator-refs/...` by Vite in DEV and by the SPA fallback's exact-path
// FileResponse in production. The filename IS the stored option value, so
// adding a category is a folder and a catalog entry — never a filename map.
// A missing file answers with the SPA index (text/html), which an <img>
// reports as an error, and the picker degrades to its text tile.
import type { ExampleSet } from './refCatalog';

export const CREATOR_REFS_BASE = '/creator-refs';

export function refAssetUrl(category: string, set: ExampleSet, value: string): string {
  return `${CREATOR_REFS_BASE}/${category}/${set}/${value}.webp`;
}

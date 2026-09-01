// Which SURFACE asks for deliberate reference mode.
//
// The whole isolation guarantee is "Admin Creator sends reference_mode, the
// Image Generator sends nothing and therefore keeps the server default". That
// is a property of two source files, and it is exactly the kind of thing a
// well-meaning refactor breaks by hoisting a shared payload builder.
//
// This project has no jsdom or testing-library, so the components cannot be
// rendered and their submissions inspected. Reading the sources is the honest
// alternative: it pins the invariant that actually matters instead of pinning
// nothing at all. If a render harness is ever added, replace this file with a
// submission-capture test.
//
// Sources are pulled in with vite's raw glob rather than node's fs, because the
// frontend tsconfig has no node types and this test must typecheck alongside
// the app.
import { describe, it, expect } from 'vitest';

const SOURCES: Record<string, string> = {
  ...(import.meta.glob('/src/pages/*.tsx', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>),
  ...(import.meta.glob('/src/features/{adminCreator,images}/**/*.{ts,tsx}', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>),
};

function source(path: string): string {
  const text = SOURCES[path];
  // A renamed or moved file must fail loudly here, not quietly pass by
  // asserting nothing against an empty string.
  expect(text, `no source loaded for ${path}`).toBeTypeOf('string');
  return text;
}

describe('reference_mode wiring', () => {
  it('Admin Creator submits deliberate mode', () => {
    expect(source('/src/pages/AdminCreator.tsx')).toMatch(
      /reference_mode:\s*refs\.reference_mode/,
    );
    // …and the value it forwards is fixed by referenceSlots, not by the page.
    expect(source('/src/features/adminCreator/referenceSlots.ts')).toMatch(
      /ADMIN_CREATOR_REFERENCE_MODE\s*=\s*'deliberate'/,
    );
  });

  it('Admin Creator does not ask for the character to be included', () => {
    // The character is an ownership and storage destination; its canon is not
    // an input. The server enforces the same thing from reference_mode, so this
    // is the client half of a two-sided guarantee, not the guarantee itself.
    expect(source('/src/pages/AdminCreator.tsx')).toMatch(/include_character:\s*false/);
    expect(source('/src/pages/AdminCreator.tsx')).not.toMatch(/include_character:\s*true/);
  });

  it('the Image Generator sends no reference mode at all', () => {
    // Absence is the point: with no field in the body, the server applies
    // "augment" and /images behaves exactly as it did before this existed.
    expect(source('/src/features/images/components/SceneGeneratorPanel.tsx')).not.toMatch(
      /reference_mode/,
    );
    expect(source('/src/pages/Images.tsx')).not.toMatch(/reference_mode/);
  });

  it('the Image Generator keeps its own recovery semantics', () => {
    // /images must still use resume() — "latest job, only if still in flight".
    // resumeJob() restores TERMINAL jobs too, which is right for a surface that
    // remembered exactly what it submitted and wrong for one that did not.
    const panel = source('/src/features/images/components/SceneGeneratorPanel.tsx');
    expect(panel).not.toMatch(/resumeJob/);
    expect(panel).not.toMatch(/adminCreator/);
    expect(panel).not.toMatch(/draftStorage|sessionStorage/);

    const hook = source('/src/features/images/useGenerationJob.ts');
    // resume() still ignores finished jobs — the rule /images depends on.
    expect(hook).toMatch(/if \(latest\.status === 'queued' \|\| latest\.status === 'running'\)/);
  });

  it('Admin Creator resolves the provider from the character draft', () => {
    // The rule itself is unit-tested in draftStorage.test.ts; this pins that the
    // page actually routes through it rather than conditionally assigning, which
    // is how the previous character's provider leaked across a switch.
    const page = source('/src/pages/AdminCreator.tsx');
    expect(page).toMatch(/providerForDraft\(draft, isProviderOption, DEFAULT_PROVIDER\)/);
    expect(page).toMatch(/const DEFAULT_PROVIDER: ProviderOption = 'option2'/);
  });

  it('Admin Creator recovers its own submitted job by exact id', () => {
    const page = source('/src/pages/AdminCreator.tsx');
    expect(page).toMatch(/saveJobPointer\(/);
    expect(page).toMatch(/job\.resumeJob\(characterId, pointer\.jobId\)/);
    expect(page).toMatch(/clearJobPointer\(/);
  });

  it('the shared submission type leaves the mode optional', () => {
    // A required field would force every existing caller to name a mode, which
    // is precisely how a default gets changed by accident.
    expect(source('/src/features/images/useGenerationJob.ts')).toMatch(
      /reference_mode\?:\s*'augment'\s*\|\s*'deliberate'/,
    );
  });
});

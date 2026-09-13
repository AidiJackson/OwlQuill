// The example-set preference: which explanatory images the creator sees.
//
// Polish Phase 3A. A viewing preference, held here and in localStorage and
// nowhere in the creator's data model. Resolution order:
//   1. a set the user chose deliberately (persisted) — always wins;
//   2. otherwise the set the character's gender suggests, following gender
//      as it changes;
//   3. otherwise DEFAULT_EXAMPLE_SET.
// Once the user has chosen, a later gender change no longer overrides them.
import { useCallback, useEffect, useState } from 'react';
import { safeGet, safeSet } from '@/lib/safeStorage';
import {
  DEFAULT_EXAMPLE_SET,
  EXAMPLE_SET_STORAGE_KEY,
  exampleSetForGender,
  isExampleSet,
  type ExampleSet,
} from './refCatalog';

function storedChoice(): ExampleSet | null {
  const v = safeGet(EXAMPLE_SET_STORAGE_KEY);
  return isExampleSet(v) ? v : null;
}

export function resolveExampleSet(
  chosen: ExampleSet | null,
  gender: string | undefined | null,
): ExampleSet {
  return chosen ?? exampleSetForGender(gender) ?? DEFAULT_EXAMPLE_SET;
}

export function useExampleSet(gender: string | undefined | null): {
  exampleSet: ExampleSet;
  setExampleSet: (set: ExampleSet) => void;
} {
  const [chosen, setChosen] = useState<ExampleSet | null>(() => storedChoice());
  const [exampleSet, setResolved] = useState<ExampleSet>(() => resolveExampleSet(storedChoice(), gender));

  useEffect(() => {
    setResolved(resolveExampleSet(chosen, gender));
  }, [chosen, gender]);

  const setExampleSet = useCallback((set: ExampleSet) => {
    setChosen(set);
    safeSet(EXAMPLE_SET_STORAGE_KEY, set);
  }, []);

  return { exampleSet, setExampleSet };
}

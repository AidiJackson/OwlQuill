/**
 * CharacterTagPicker — "Tag characters" in a post composer (W-10A).
 *
 * A deliberate search-and-pick, not free-text @name addressing. Results come
 * from the PUBLIC-only search mode, so the caller's own PRIVATE/FRIENDS
 * characters are never offered; the server validates every submitted id
 * regardless. At most MAX_TAGGED_CHARACTERS can be selected, and each
 * selection is removable before posting.
 *
 * Tagging is not authorship: nothing here touches who the post is BY.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { MAX_TAGGED_CHARACTERS, type CharacterSearchResult, type TaggedCharacter } from '@/lib/types';

interface Props {
  selected: TaggedCharacter[];
  onChange: (next: TaggedCharacter[]) => void;
  /** Characters that cannot be tagged here — the authoring character. They
   *  are left out of results and dropped from the selection if present. */
  excludeCharacterIds?: number[];
  disabled?: boolean;
}

/** Search waits this long after the last keystroke. */
export const TAG_SEARCH_DEBOUNCE_MS = 250;

export default function CharacterTagPicker({ selected, onChange, excludeCharacterIds = [], disabled = false }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CharacterSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const inputId = useId();
  const helpId = useId();
  const requestRef = useRef(0);

  const excludedKey = excludeCharacterIds.join(',');

  // The authoring character can change after something was picked; a post
  // cannot tag its own author, so that selection is dropped rather than
  // left to fail on the server.
  useEffect(() => {
    if (!excludeCharacterIds.length) return;
    const kept = selected.filter((t) => !excludeCharacterIds.includes(t.character_id));
    if (kept.length !== selected.length) onChange(kept);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [excludedKey]);

  const atCap = selected.length >= MAX_TAGGED_CHARACTERS;

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || atCap) {
      setResults([]);
      setSearching(false);
      return;
    }
    const ticket = ++requestRef.current;
    setSearching(true);
    const timer = setTimeout(() => {
      apiClient
        .searchTaggableCharacters(q)
        .then((rows) => {
          if (ticket === requestRef.current) setResults(rows);
        })
        .catch(() => {
          if (ticket === requestRef.current) setResults([]);
        })
        .finally(() => {
          if (ticket === requestRef.current) setSearching(false);
        });
    }, TAG_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query, atCap]);

  const selectedIds = new Set(selected.map((t) => t.character_id));
  const visibleResults = results.filter(
    (r) => !selectedIds.has(r.id) && !excludeCharacterIds.includes(r.id),
  );

  const add = (r: CharacterSearchResult) => {
    if (atCap || selectedIds.has(r.id)) return;
    onChange([...selected, { character_id: r.id, name: r.name }]);
    setQuery('');
    setResults([]);
  };

  const remove = (characterId: number) => {
    onChange(selected.filter((t) => t.character_id !== characterId));
  };

  return (
    <div className="mb-3" data-testid="character-tag-picker">
      <label htmlFor={inputId} className="block text-xs font-medium text-ink-2 mb-1.5">
        Tag characters
      </label>

      {selected.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 mb-2" aria-label="Tagged characters">
          {selected.map((t) => (
            <li
              key={t.character_id}
              className="inline-flex items-center gap-1 pl-2.5 pr-1 py-0.5 rounded-full text-xs bg-surface-elevated border border-edge text-ink"
            >
              {t.name}
              <button
                type="button"
                onClick={() => remove(t.character_id)}
                disabled={disabled}
                aria-label={`Remove ${t.name}`}
                className="p-0.5 rounded-full text-ink-3 hover:text-ink hover:bg-surface-overlay transition-colors disabled:opacity-40"
              >
                <X className="w-3 h-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <input
        id={inputId}
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        disabled={disabled || atCap}
        aria-describedby={helpId}
        autoComplete="off"
        placeholder={atCap ? 'Tag limit reached' : 'Search public characters…'}
        className="w-full px-3 py-1.5 rounded-lg text-sm bg-surface-elevated border border-edge text-ink placeholder:text-ink-3 focus:outline-none focus:border-gem disabled:opacity-60"
      />
      <p id={helpId} className="mt-1 text-[11px] text-ink-3">
        {atCap
          ? `You can tag up to ${MAX_TAGGED_CHARACTERS} characters.`
          : `Their owners are notified. Up to ${MAX_TAGGED_CHARACTERS}.`}
      </p>

      {query.trim().length >= 2 && !atCap && (
        <div className="mt-1.5">
          {searching && visibleResults.length === 0 ? (
            <p className="text-xs text-ink-3">Searching…</p>
          ) : visibleResults.length === 0 ? (
            <p className="text-xs text-ink-3">No public characters match.</p>
          ) : (
            <ul className="max-h-48 overflow-y-auto rounded-lg border border-edge divide-y divide-edge" aria-label="Matching characters">
              {visibleResults.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => add(r)}
                    disabled={disabled}
                    className="w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-surface-elevated transition-colors"
                  >
                    Tag {r.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

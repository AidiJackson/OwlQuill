/**
 * CharacterTagPicker — "Featuring" in a post composer (W-10A).
 *
 * A compact, single-row control beneath the post text:
 *
 *     Featuring  [Kiera Fielding ×] [Grace Fielding ×]  + Add
 *
 * With nobody selected it is just "Featuring  + Add characters", so it never
 * competes with the writing itself. "+ Add" opens a small inline search over
 * PUBLIC characters only (the caller's own PRIVATE/FRIENDS characters are
 * never offered); the server validates every submitted id regardless. At most
 * MAX_TAGGED_CHARACTERS can be selected and each chip is removable before
 * posting.
 *
 * "Featuring" is the user-facing word for an explicit tag. It is not
 * authorship: nothing here touches who the post is BY.
 */
import { useEffect, useId, useRef, useState } from 'react';
import { Plus, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { MAX_TAGGED_CHARACTERS, type CharacterSearchResult, type TaggedCharacter } from '@/lib/types';

interface Props {
  selected: TaggedCharacter[];
  onChange: (next: TaggedCharacter[]) => void;
  /** Characters that cannot be featured here — the authoring character. They
   *  are left out of results and dropped from the selection if present. */
  excludeCharacterIds?: number[];
  disabled?: boolean;
}

/** Search waits this long after the last keystroke. */
export const TAG_SEARCH_DEBOUNCE_MS = 250;

const focusRing = 'focus:outline-none focus-visible:ring-2 focus-visible:ring-gem/60';

export default function CharacterTagPicker({ selected, onChange, excludeCharacterIds = [], disabled = false }: Props) {
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CharacterSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const addRef = useRef<HTMLButtonElement>(null);
  const resultsId = useId();
  const requestRef = useRef(0);

  const excludedKey = excludeCharacterIds.join(',');

  // The authoring character can change after something was picked; a post
  // cannot feature its own author, so that selection is dropped rather than
  // left to fail on the server.
  useEffect(() => {
    if (!excludeCharacterIds.length) return;
    const kept = selected.filter((t) => !excludeCharacterIds.includes(t.character_id));
    if (kept.length !== selected.length) onChange(kept);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [excludedKey]);

  const atCap = selected.length >= MAX_TAGGED_CHARACTERS;

  useEffect(() => {
    if (searchOpen) inputRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    const q = query.trim();
    if (!searchOpen || q.length < 2 || atCap) {
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
  }, [query, atCap, searchOpen]);

  const selectedIds = new Set(selected.map((t) => t.character_id));
  const visibleResults = results.filter(
    (r) => !selectedIds.has(r.id) && !excludeCharacterIds.includes(r.id),
  );

  const closeSearch = (refocus: boolean) => {
    setSearchOpen(false);
    setQuery('');
    setResults([]);
    if (refocus) requestAnimationFrame(() => addRef.current?.focus());
  };

  const add = (r: CharacterSearchResult) => {
    if (atCap || selectedIds.has(r.id)) return;
    onChange([...selected, { character_id: r.id, name: r.name }]);
    closeSearch(true);
  };

  const remove = (characterId: number) => {
    onChange(selected.filter((t) => t.character_id !== characterId));
  };

  const showResults = searchOpen && query.trim().length >= 2;

  return (
    <div className="mb-2" data-testid="character-tag-picker">
      <div
        role="group"
        aria-label="Featured characters"
        className="flex flex-wrap items-center gap-1.5 min-h-[1.75rem]"
      >
        <span className="text-xs text-ink-3 mr-0.5">Featuring</span>

        {selected.map((t) => (
          <span
            key={t.character_id}
            className="inline-flex items-center gap-0.5 max-w-full pl-2 pr-0.5 py-0.5 rounded-full text-xs bg-surface-elevated border border-edge text-ink"
          >
            <span className="truncate">{t.name}</span>
            <button
              type="button"
              onClick={() => remove(t.character_id)}
              disabled={disabled}
              aria-label={`Remove ${t.name} from Featuring`}
              className={`p-0.5 rounded-full text-ink-3 hover:text-ink hover:bg-surface-overlay transition-colors disabled:opacity-40 ${focusRing}`}
            >
              <X className="w-3 h-3" aria-hidden="true" />
            </button>
          </span>
        ))}

        {searchOpen ? (
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') { e.preventDefault(); closeSearch(true); }
            }}
            onBlur={() => { if (!query.trim()) closeSearch(false); }}
            disabled={disabled}
            aria-label="Add featured characters"
            aria-controls={showResults ? resultsId : undefined}
            autoComplete="off"
            placeholder="Search public characters…"
            className={`flex-1 min-w-[10rem] px-2 py-0.5 rounded-md text-xs bg-surface-elevated border border-edge text-ink placeholder:text-ink-3 focus:border-gem ${focusRing}`}
          />
        ) : atCap ? (
          <span className="text-[11px] text-ink-3">Up to {MAX_TAGGED_CHARACTERS}</span>
        ) : (
          <button
            ref={addRef}
            type="button"
            onClick={() => setSearchOpen(true)}
            disabled={disabled}
            aria-label="Add featured characters"
            className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-xs text-ink-3 hover:text-gem hover:bg-surface-elevated transition-colors disabled:opacity-40 ${focusRing}`}
          >
            <Plus className="w-3 h-3" aria-hidden="true" />
            {selected.length === 0 ? 'Add characters' : 'Add'}
          </button>
        )}
      </div>

      {showResults && (
        <div className="mt-1.5" id={resultsId}>
          {searching && visibleResults.length === 0 ? (
            <p className="text-xs text-ink-3" role="status">Searching…</p>
          ) : visibleResults.length === 0 ? (
            <p className="text-xs text-ink-3" role="status">No public characters match.</p>
          ) : (
            <ul
              className="max-h-44 overflow-y-auto rounded-lg border border-edge bg-surface divide-y divide-edge"
              aria-label="Matching characters"
            >
              {visibleResults.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    // Keep focus from blurring the input before the click lands.
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => add(r)}
                    disabled={disabled}
                    aria-label={`Feature ${r.name}`}
                    className={`w-full text-left px-3 py-1.5 text-sm text-ink hover:bg-surface-elevated transition-colors ${focusRing}`}
                  >
                    {r.name}
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

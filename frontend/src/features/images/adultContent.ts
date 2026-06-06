/**
 * Adult-adjacent prompt detection (advisory only).
 *
 * This does NOT block generation. It powers a soft nudge toward the upcoming
 * 18+ Studio when a prompt looks like swimwear / lingerie / mature content,
 * where stronger identity-locking would help. See SceneGeneratorPanel.
 */

// Lowercased terms. Multi-word phrases are matched as substrings; single words
// are matched on word boundaries so "bra" doesn't fire inside "brave".
const ADULT_ADJACENT_TERMS = [
  'bikini',
  'swimsuit',
  'swimwear',
  'lingerie',
  'underwear',
  'bra',
  'panties',
  'topless',
  'nude',
  'naked',
  'erotic',
  'adult',
  'bedroom scene',
  'poolside',
  'beachwear',
];

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Returns true when the prompt contains an adult-adjacent term.
 * Case-insensitive; single words require word boundaries.
 */
export function isAdultAdjacent(prompt: string): boolean {
  const text = (prompt || '').toLowerCase();
  if (!text.trim()) return false;
  return ADULT_ADJACENT_TERMS.some((term) => {
    if (term.includes(' ')) {
      return text.includes(term);
    }
    const re = new RegExp(`\\b${escapeRegExp(term)}\\b`, 'i');
    return re.test(text);
  });
}

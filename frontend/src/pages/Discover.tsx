import { useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { SearchResponse, SearchResult } from '@/lib/types';

export default function DiscoverPage() {
  const [query, setQuery] = useState('');
  const [searchType, setSearchType] = useState<'all' | 'user' | 'character' | 'realm'>('all');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    try {
      setLoading(true);
      setHasSearched(true);
      const data: SearchResponse = await apiClient.search({ q: query, type: searchType });
      setResults(data.results);

      // Log analytics event
      apiClient.logEvent('search', { query, type: searchType });
    } catch (error) {
      console.error('Search failed:', error);
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const renderResult = (result: SearchResult) => {
    switch (result.result_type) {
      case 'user':
        return (
          <Link
            key={`user-${result.id}`}
            to={`/u/${result.username}`}
            className="block border border-gray-700 rounded-lg p-4 hover:border-purple-500 hover:bg-gray-800/50 transition-all"
          >
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-600 to-pink-600 flex items-center justify-center text-white font-bold flex-shrink-0">
                {result.avatar_url ? (
                  <img src={result.avatar_url} alt={result.username} className="w-full h-full rounded-full object-cover" />
                ) : (
                  result.username.charAt(0).toUpperCase()
                )}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold truncate">
                  {result.display_name || result.username}
                </h3>
                <p className="text-sm text-gray-400 truncate">@{result.username}</p>
                {result.bio && (
                  <p className="text-sm text-gray-500 line-clamp-1 mt-1">{result.bio}</p>
                )}
              </div>
              <span className="px-2 py-1 bg-purple-900/30 text-purple-300 rounded text-xs flex-shrink-0">
                User
              </span>
            </div>
          </Link>
        );

      case 'character':
        return (
          <Link
            key={`character-${result.id}`}
            to={`/c/${result.id}`}
            className="block border border-gray-700 rounded-lg p-4 hover:border-pink-500 hover:bg-gray-800/50 transition-all"
          >
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-pink-600 to-purple-600 flex items-center justify-center text-white font-bold flex-shrink-0">
                {result.avatar_url ? (
                  <img src={result.avatar_url} alt={result.name} className="w-full h-full rounded-full object-cover" />
                ) : (
                  result.name.charAt(0).toUpperCase()
                )}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold truncate">{result.name}</h3>
                {result.owner_username && (
                  <p className="text-sm text-gray-400 truncate">by @{result.owner_username}</p>
                )}
                {result.short_bio && (
                  <p className="text-sm text-gray-500 line-clamp-1 mt-1">{result.short_bio}</p>
                )}
              </div>
              <span className="px-2 py-1 bg-pink-900/30 text-pink-300 rounded text-xs flex-shrink-0">
                Character
              </span>
            </div>
          </Link>
        );

      case 'realm':
        return (
          <Link
            key={`realm-${result.id}`}
            to={`/realms/${result.id}`}
            className="block border border-gray-700 rounded-lg p-4 hover:border-blue-500 hover:bg-gray-800/50 transition-all"
          >
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold truncate">{result.name}</h3>
                {result.tagline && (
                  <p className="text-sm text-gray-400 truncate">{result.tagline}</p>
                )}
                {result.description && (
                  <p className="text-sm text-gray-500 line-clamp-2 mt-1">{result.description}</p>
                )}
                {result.owner_username && (
                  <p className="text-xs text-gray-500 mt-2">Owner: @{result.owner_username}</p>
                )}
              </div>
              <span className="px-2 py-1 bg-blue-900/30 text-blue-300 rounded text-xs flex-shrink-0">
                Realm
              </span>
            </div>
          </Link>
        );

      default:
        return null;
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-8">
      <h1 className="text-2xl md:text-3xl font-bold mb-6">Discover</h1>

      {/* Search Form */}
      <div className="card mb-6">
        <form onSubmit={handleSearch} className="space-y-4">
          <div>
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for users, characters, or realms..."
              className="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-lg focus:outline-none focus:border-purple-500 text-white placeholder-gray-500"
            />
          </div>

          {/* Filter Pills */}
          <div className="flex flex-wrap gap-2">
            {(['all', 'user', 'character', 'realm'] as const).map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => setSearchType(type)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  searchType === type
                    ? 'bg-purple-600 text-white'
                    : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                }`}
              >
                {type.charAt(0).toUpperCase() + type.slice(1)}
              </button>
            ))}
          </div>

          <button
            type="submit"
            disabled={loading || !query.trim()}
            className="w-full md:w-auto btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>
      </div>

      {/* Results */}
      <div className="card">
        <h2 className="text-xl font-bold mb-4">
          {hasSearched ? `Results (${results.length})` : 'Search to discover'}
        </h2>

        {loading ? (
          <p className="text-gray-400 text-center py-8">Searching...</p>
        ) : hasSearched && results.length === 0 ? (
          <p className="text-gray-400 text-center py-8">No results found. Try a different search term.</p>
        ) : hasSearched ? (
          <div className="space-y-3">
            {results.map((result) => renderResult(result))}
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-gray-400 mb-2">Start searching to find users, characters, and realms</p>
            <p className="text-sm text-gray-500">Try searching for a name, username, or description</p>
          </div>
        )}
      </div>
    </div>
  );
}

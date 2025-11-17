# Phase 7 – Profiles, Discovery & Mobile Readiness

## Overview

Phase 7 adds professional profile pages, enhanced discovery features, and mobile-responsive layouts to make OwlQuill feel like a polished social network.

## New Features

### 1. User Profiles

Public user profile pages accessible at `/u/:username`:

- **Profile Information**: Avatar, display name, bio, username
- **Stats Dashboard**: Posts, realms joined, followers, following counts
- **Recent Activity**: Last 5 posts with realm and character context
- **Responsive Design**: Mobile-friendly layout

**API Endpoint**: `GET /api/profile/users/{username}`

### 2. Character Profiles

Detailed character pages accessible at `/c/:characterId`:

- **Character Sheet**: Name, alias, age, species, role, era
- **Owner Information**: Link to the user who created the character
- **Biographies**: Short and long bio sections
- **Stats**: Post count, active realms count
- **Recent Posts**: Latest character activity
- **Tags**: Character tags/themes
- **Privacy**: Respects character visibility settings

**API Endpoint**: `GET /api/profile/characters/{characterId}`

### 3. Discovery & Search

New Discover page at `/discover` with powerful search:

- **Universal Search**: Find users, characters, and realms in one place
- **Type Filtering**: Search all types or filter by user/character/realm
- **Smart Results**: Shows relevant information for each result type
- **Quick Navigation**: Click any result to view full profile/detail page

**API Endpoint**: `GET /api/discovery/search?q={query}&type={all|user|character|realm}`

### 4. Analytics Events (Backend)

Lightweight event logging for future analytics:

- **Event Types**: `profile_view`, `character_view`, `realm_view`, `post_view`, `search`
- **Privacy-Conscious**: Minimal data collection, internal use only
- **Non-Blocking**: Events fail silently and don't break UI

**API Endpoint**: `POST /api/analytics/events`

### 5. Mobile Responsiveness

All key screens now work smoothly on mobile:

- **Responsive Navigation**: Horizontal scrolling nav on mobile, vertical on desktop
- **Flexible Layouts**: Stack vertically on small screens
- **Touch-Friendly**: Properly sized buttons and touch targets
- **Readable Text**: Appropriate font sizes across devices

## API Endpoints

### Profile Endpoints

#### Get User Profile
```http
GET /api/profile/users/{username}
```

**Response:**
```json
{
  "id": 1,
  "username": "alice",
  "display_name": "Alice Wonderland",
  "bio": "RP enthusiast and storyteller",
  "avatar_url": "https://...",
  "created_at": "2025-01-01T00:00:00",
  "follower_count": 0,
  "following_count": 0,
  "total_posts": 42,
  "joined_realms_count": 5,
  "recent_posts": [...]
}
```

#### Get Current User Profile
```http
GET /api/profile/me
```
Requires authentication. Returns the same structure as above for the logged-in user.

#### Get Character Profile
```http
GET /api/profile/characters/{character_id}
```

**Response:**
```json
{
  "id": 1,
  "name": "Shadowheart",
  "alias": "The Wanderer",
  "species": "Elf",
  "role": "Rogue",
  "era": "Medieval Fantasy",
  "short_bio": "A mysterious elf with a dark past",
  "long_bio": "...",
  "avatar_url": "https://...",
  "portrait_url": "https://...",
  "tags": "fantasy,rogue,mysterious",
  "visibility": "public",
  "created_at": "2025-01-01T00:00:00",
  "owner": {
    "id": 1,
    "username": "alice",
    "display_name": "Alice",
    "avatar_url": "https://..."
  },
  "posts_count": 15,
  "realms_count": 3,
  "recent_posts": [...]
}
```

### Discovery Endpoints

#### Search
```http
GET /api/discovery/search?q={query}&type={type}&limit={limit}
```

**Query Parameters:**
- `q` (required): Search query string (1-100 chars)
- `type` (optional): `all` | `user` | `character` | `realm` (default: `all`)
- `limit` (optional): Max results to return (1-50, default: 20)

**Response:**
```json
{
  "results": [
    {
      "id": 1,
      "username": "alice",
      "display_name": "Alice",
      "avatar_url": "https://...",
      "bio": "...",
      "result_type": "user"
    },
    {
      "id": 2,
      "name": "Shadowheart",
      "avatar_url": "https://...",
      "short_bio": "...",
      "owner_username": "alice",
      "result_type": "character"
    },
    {
      "id": 3,
      "name": "Mystic Realms",
      "slug": "mystic-realms",
      "tagline": "...",
      "description": "...",
      "owner_username": "bob",
      "is_public": true,
      "result_type": "realm"
    }
  ],
  "total": 3
}
```

### Analytics Endpoints

#### Log Event
```http
POST /api/analytics/events
```

**Request Body:**
```json
{
  "event_type": "profile_view",
  "payload": {
    "username": "alice"
  }
}
```

**Allowed Event Types:**
- `profile_view`
- `character_view`
- `realm_view`
- `post_view`
- `search`

## Frontend Routes

### New Routes

- `/u/:username` - User profile page
- `/c/:characterId` - Character profile page
- `/discover` - Discovery and search page

### Updated Navigation

The main navigation now includes a "Discover" link for easy access to search functionality.

## Mobile Considerations

### Layout Changes

- **Navigation**: Horizontal scrolling on mobile, vertical sidebar on desktop
- **Content**: Single-column layouts on small screens
- **Typography**: Responsive font sizes with Tailwind's responsive classes
- **Spacing**: Adjusted padding and margins for mobile (`p-4 md:p-8`)

### Tested Screens

All screens work reasonably well on mobile devices:
- Home feed
- Realms list and detail
- Characters list
- User profiles
- Character profiles
- Discovery page
- Messages (if implemented in previous phases)

## Development Notes

### Database Migration

A new migration has been added for the `analytics_events` table:

```bash
# Migration file: backend/alembic/versions/a1b2c3d4e5f6_add_analytics_events_table.py
```

To apply:
```bash
cd backend
alembic upgrade head
```

### Analytics Implementation

Analytics events are logged with the `apiClient.logEvent()` method:

```typescript
// Log a profile view
apiClient.logEvent('profile_view', { username: 'alice' });

// Log a search
apiClient.logEvent('search', { query: 'dragon', type: 'character' });
```

Events fail silently to avoid breaking the UI if the analytics service is unavailable.

### Testing

New test files have been added:
- `backend/tests/test_profile.py` - Profile endpoint tests
- `backend/tests/test_discovery.py` - Discovery/search tests
- `backend/tests/test_analytics.py` - Analytics event tests

Run tests:
```bash
cd backend
pytest
```

## Future Enhancements (Phase 8 Ideas)

1. **Social Connections**: Implement actual follow/follower system
2. **Profile Customization**: Banner images, custom themes, profile sections
3. **Advanced Search**: Filters by tags, genre, activity level
4. **Activity Timeline**: More detailed activity feeds on profiles
5. **Moderation Tools**: Report system, user blocking
6. **Analytics Dashboard**: Admin view of platform usage and trends
7. **Badges & Achievements**: Recognition for active community members

## Changelog Summary

See [CHANGELOG.md](./CHANGELOG.md) for detailed changes.

**Phase 7 Highlights:**
- ✅ User profile pages with stats and recent posts
- ✅ Character profile pages with full character sheets
- ✅ Discovery page with universal search
- ✅ Analytics event logging foundation
- ✅ Mobile-responsive layouts across all pages
- ✅ Enhanced navigation with Discover link

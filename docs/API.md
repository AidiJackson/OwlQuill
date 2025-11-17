# OwlQuill API Documentation

## Base URL
- Development: `http://localhost:8000`
- API Prefix: `/api`

## Authentication
All protected endpoints require a Bearer token in the Authorization header:
```
Authorization: Bearer <token>
```

## Endpoints

### Authentication

#### POST /auth/register
Register a new user.
- **Request**: `{ email, username, password }`
- **Response**: `User` object
- **Status**: 201 Created

#### POST /auth/login
Login and get access token.
- **Query Params**: `email`, `password`
- **Response**: `{ access_token, token_type }`
- **Status**: 200 OK

#### GET /auth/me
Get current user profile (protected).
- **Response**: `User` object
- **Status**: 200 OK

### Users

#### PATCH /users/me
Update current user profile (protected).
- **Request**: `{ display_name?, bio?, avatar_url? }`
- **Response**: Updated `User` object
- **Status**: 200 OK

### Characters

#### GET /characters/
List user's characters (protected).
- **Response**: Array of `Character` objects
- **Status**: 200 OK

#### POST /characters/
Create a new character (protected).
- **Request**: `{ name, species?, role?, era?, short_bio?, long_bio?, portrait_url?, tags?, visibility }`
- **Response**: `Character` object
- **Status**: 201 Created

#### GET /characters/{id}
Get character details (protected).
- **Response**: `Character` object
- **Status**: 200 OK

#### PATCH /characters/{id}
Update character (protected).
- **Request**: Partial `Character` fields
- **Response**: Updated `Character` object
- **Status**: 200 OK

#### DELETE /characters/{id}
Delete character (protected).
- **Status**: 204 No Content

### Realms

#### GET /realms/
List public realms.
- **Query Params**: `search?`, `public_only=true`
- **Response**: Array of `Realm` objects
- **Status**: 200 OK

#### GET /realms/my-realms
Get realms the current user is a member of (protected).
- **Response**: Array of `Realm` objects
- **Status**: 200 OK

#### POST /realms/
Create a new realm (protected).
- **Request**: `{ name, slug, tagline?, description?, genre?, banner_url?, is_public }`
- **Response**: `Realm` object
- **Status**: 201 Created

#### GET /realms/{id}
Get realm details.
- **Response**: `Realm` object
- **Status**: 200 OK

#### POST /realms/{id}/join
Join a realm (protected).
- **Response**: `RealmMembership` object
- **Status**: 201 Created

#### GET /realms/{id}/members
List realm members.
- **Response**: Array of `RealmMembership` objects
- **Status**: 200 OK

### Scenes

#### GET /scenes/realms/{realm_id}/scenes
List scenes in a realm.
- **Query Params**: `skip=0`, `limit=50`
- **Response**: Array of `Scene` objects
- **Status**: 200 OK

#### POST /scenes/realms/{realm_id}/scenes
Create a new scene in a realm (protected, requires membership).
- **Request**: `{ title, description? }`
- **Response**: `Scene` object
- **Status**: 201 Created

#### GET /scenes/{id}
Get scene details.
- **Response**: `Scene` object
- **Status**: 200 OK

#### PATCH /scenes/{id}
Update scene (protected, requires creator or admin).
- **Request**: `{ title?, description? }`
- **Response**: Updated `Scene` object
- **Status**: 200 OK

#### DELETE /scenes/{id}
Delete scene (protected, requires creator or admin).
- **Status**: 204 No Content

### Posts

#### GET /posts/feed
Get feed of posts from user's realms (protected).
- **Query Params**: `skip=0`, `limit=50`
- **Response**: Array of `Post` objects
- **Status**: 200 OK

#### GET /posts/scenes/{scene_id}/posts
List posts in a scene.
- **Query Params**: `skip=0`, `limit=50`
- **Response**: Array of `Post` objects
- **Status**: 200 OK

#### POST /posts/scenes/{scene_id}/posts
Create a post in a scene (protected, requires realm membership).
- **Request**: `{ title?, content, content_type, character_id? }`
- **Response**: `Post` object
- **Status**: 201 Created

#### GET /posts/{id}
Get post details.
- **Response**: `Post` object
- **Status**: 200 OK

#### DELETE /posts/{id}
Delete post (protected, author only).
- **Status**: 204 No Content

### Comments

#### GET /comments/posts/{post_id}/comments
List comments on a post.
- **Response**: Array of `Comment` objects
- **Status**: 200 OK

#### POST /comments/posts/{post_id}/comments
Create a comment (protected).
- **Request**: `{ content, character_id? }`
- **Response**: `Comment` object
- **Status**: 201 Created

### Reactions

#### POST /reactions/posts/{post_id}/reactions
Add a reaction to a post (protected).
- **Request**: `{ type }`
- **Response**: `Reaction` object
- **Status**: 201 Created

### AI (Stub)

#### POST /ai/character-bio
Generate character bio (protected).
- **Request**: `{ name, species?, role?, era?, tags? }`
- **Response**: `{ short_bio, long_bio }`
- **Status**: 200 OK

#### POST /ai/scene
Generate scene content (protected).
- **Request**: `{ characters, setting, mood?, prompt }`
- **Response**: `{ scene, dialogue }`
- **Status**: 200 OK

## Data Models

### User
```typescript
{
  id: number
  email: string
  username: string
  display_name?: string
  bio?: string
  avatar_url?: string
  created_at: string
  updated_at: string
}
```

### Character
```typescript
{
  id: number
  owner_id: number
  name: string
  species?: string
  role?: string
  era?: string
  short_bio?: string
  long_bio?: string
  portrait_url?: string
  tags?: string
  visibility: 'public' | 'friends' | 'private'
  created_at: string
  updated_at: string
}
```

### Realm
```typescript
{
  id: number
  owner_id: number
  name: string
  slug: string
  tagline?: string
  description?: string
  genre?: string
  banner_url?: string
  is_public: boolean
  created_at: string
  updated_at: string
}
```

### Scene
```typescript
{
  id: number
  realm_id: number
  created_by: number
  title: string
  description?: string
  created_at: string
  updated_at: string
}
```

### Post
```typescript
{
  id: number
  scene_id: number
  realm_id: number // Denormalized for query performance
  author_user_id: number
  character_id?: number
  title?: string
  content: string
  content_type: 'ic' | 'ooc' | 'narration'
  created_at: string
  updated_at: string
}
```

## Architecture Notes

### Post → Scene → Realm Hierarchy
Posts belong to Scenes, which belong to Realms. The `realm_id` on Post is denormalized for query performance, particularly for the feed endpoint which filters posts by realm membership.

### Content Types
- **IC (In-Character)**: Roleplay as a character
- **OOC (Out-of-Character)**: Player commentary
- **Narration**: Scene-setting or storytelling

### Error Responses
All error responses follow this format:
```json
{
  "detail": "Error message here"
}
```

Common status codes:
- 400: Bad Request (validation errors)
- 401: Unauthorized (missing/invalid token)
- 403: Forbidden (insufficient permissions)
- 404: Not Found
- 500: Internal Server Error

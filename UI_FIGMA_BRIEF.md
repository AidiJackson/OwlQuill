# OwlQuill UI/UX Design Brief for Figma

This document provides design guidance for creating high-fidelity mockups in Figma (or with Figma AI) for the OwlQuill roleplay social network.

## Design Philosophy

OwlQuill should feel:
- **Cozy and Inviting**: Like a creative sanctuary for storytellers
- **Premium but Accessible**: High-quality design without being pretentious
- **Focused on Content**: Let the stories and characters shine
- **Magical/Mystical**: Subtle nods to storytelling and imagination
- **Professional**: Clean, organized, not cluttered

Think: "Notion meets AO3 meets Discord" — functional, beautiful, community-focused.

## Color Palette

### Primary Colors (Owl Theme)

**Deep Purple/Indigo** (Brand Color)
- Primary: `#8b5cf6` (Owl-500)
- Dark: `#6d28d9` (Owl-700)
- Light: `#a78bfa` (Owl-400)
- Very Light: `#ddd6fe` (Owl-200)

**Dark Background**
- Base: `#030712` (Gray-950)
- Cards: `#111827` (Gray-900)
- Elevated: `#1f2937` (Gray-800)

**Text**
- Primary: `#f9fafb` (Gray-100)
- Secondary: `#d1d5db` (Gray-300)
- Muted: `#9ca3af` (Gray-400)
- Disabled: `#6b7280` (Gray-500)

### Accent Colors

**Success**: `#10b981` (Emerald-500)
**Warning**: `#f59e0b` (Amber-500)
**Error**: `#ef4444` (Red-500)
**Info**: `#3b82f6` (Blue-500)

### Semantic Colors

**In-Character Posts**: Purple tint `#8b5cf6`
**Out-of-Character**: Blue tint `#3b82f6`
**Narration**: Amber tint `#f59e0b`

## Typography

### Font Families

**Headings**: Inter, SF Pro Display, or similar clean sans-serif
**Body**: Inter, system-ui, or similar readable sans-serif
**Code/Tags**: JetBrains Mono, Fira Code (for character tags, etc.)

### Type Scale

- **H1**: 36px, Bold, -0.02em tracking
- **H2**: 30px, Bold, -0.01em tracking
- **H3**: 24px, Semibold
- **H4**: 20px, Semibold
- **Body Large**: 18px, Regular, 1.6 line height
- **Body**: 16px, Regular, 1.5 line height
- **Body Small**: 14px, Regular, 1.4 line height
- **Caption**: 12px, Regular, 1.3 line height

## Pages to Design

### 1. Login / Register Page

**Layout**: Centered card on dark background

**Elements**:
- Large OwlQuill logo (owl icon + wordmark)
- Tagline: "Roleplay-first social network"
- Email input field
- Username input field (register only)
- Password input field
- Primary CTA button ("Login" or "Create Account")
- Link to alternate page ("Don't have an account? Register")
- Subtle background pattern or gradient

**Mood**: Welcoming, simple, magical

**Reference**: Notion login, Linear login, Discord login

### 2. Home Feed

**Layout**: Sidebar + Main Content + (Optional) Right Panel

**Sidebar (Left, 256px)**:
- OwlQuill logo at top
- Navigation items:
  - Home (icon + label)
  - Realms
  - Characters
  - Notifications (with badge)
  - Profile
- User card at bottom (avatar, username, logout)

**Main Content (Center, max 768px)**:
- Page title "Home Feed"
- "New Post" composer card (collapsed by default)
- Feed of post cards:
  - Author info (avatar, username, character name if IC)
  - Post title (optional)
  - Post content (preview or full)
  - Metadata (realm name, timestamp)
  - Action bar (like, comment, react)
  - Comment count
  - Engagement indicators

**Right Panel (Optional)**:
- Trending realms
- Suggested characters
- Activity summary

**Mood**: Content-focused, scannable, engaging

### 3. Realms Page

**Layout**: Same sidebar, main content

**Main Content**:
- Page title "Realms"
- "Create Realm" button (top right)
- Search/filter bar
- Grid or list of realm cards:
  - Realm name
  - Slug (e.g., /moonlight-academy)
  - Description (truncated)
  - Genre tag
  - Member count
  - "Join" button
  - Public/Private indicator

**Create Realm Modal/Form**:
- Name input
- Slug input
- Description textarea
- Genre dropdown/select
- Public/Private toggle
- Create/Cancel buttons

**Mood**: Discoverable, organized, inviting

### 4. Realm Detail Page

**Layout**: Sidebar + Main

**Main Content**:
- Realm header:
  - Realm name (large)
  - Description
  - Genre tag
  - Owner info
  - Member count
  - "Join" / "Joined" button
- Tabs: Posts, Members, About
- Post feed (same as home feed, filtered to this realm)
- "New Post in [Realm Name]" composer

**Mood**: Immersive, community-focused

### 5. Characters Page

**Layout**: Sidebar + Main

**Main Content**:
- Page title "My Characters"
- "Create Character" button
- Grid of character cards:
  - Character avatar (or placeholder)
  - Character name
  - Species tag
  - Short bio (truncated)
  - Tags (genre, traits)
  - Edit/Delete icons

**Create Character Form**:
- Name input
- Species input
- Tags input (comma-separated or pills)
- Short bio textarea
- Long bio textarea
- "Generate Bio with AI" button (near bio fields)
- Visibility dropdown (Public, Friends, Private)
- Create/Cancel buttons

**AI Generation Interaction**:
- Spinner/loading state while generating
- Bio fields populate with AI-generated text
- User can edit generated content

**Mood**: Creative, character-focused, playful

### 6. Character Detail Page (Optional for MVP)

**Layout**: Sidebar + Main

**Main Content**:
- Character header:
  - Large avatar
  - Character name
  - Species, age, other metadata
  - Visibility indicator
  - Edit button (if owner)
- Tabs: About, Posts, Relationships
- Biography section
- Tags section
- Recent posts by this character

**Mood**: Showcase, portfolio-like

### 7. Profile Page

**Layout**: Sidebar + Main

**Main Content**:
- Profile header:
  - Avatar (large)
  - Username
  - Display name
  - Join date
  - Edit button
- Bio section
- Stats (characters created, realms joined, posts)
- Recent activity

**Edit Profile Form**:
- Display name input
- Bio textarea
- Avatar URL input
- Save/Cancel buttons

**Mood**: Personal, simple, clean

### 8. Notifications Page (Future)

**Layout**: Sidebar + Main

**Main Content**:
- Page title "Notifications"
- Tabs: All, Mentions, Realms, Characters
- List of notification items:
  - Avatar of actor
  - Notification text
  - Timestamp
  - Read/unread indicator
  - Link to related content

**Mood**: Organized, scannable

## UI Components

### Buttons

**Primary Button**:
- Background: Owl-600 (`#7c3aed`)
- Hover: Owl-700 (`#6d28d9`)
- Text: White
- Padding: 12px 24px
- Border radius: 8px
- Font: 16px, Medium

**Secondary Button**:
- Background: Gray-800 (`#1f2937`)
- Hover: Gray-700 (`#374151`)
- Text: Gray-100
- Same sizing as primary

**Icon Button**:
- 40px × 40px
- Rounded
- Hover: Gray-800 background

### Input Fields

**Text Input**:
- Background: Gray-800
- Border: 1px solid Gray-700
- Focus: 2px ring Owl-600
- Padding: 12px 16px
- Border radius: 8px
- Text: Gray-100
- Placeholder: Gray-400

**Textarea**:
- Same as text input
- Min height: 100px
- Resize: vertical

### Cards

**Standard Card**:
- Background: Gray-900
- Border: 1px solid Gray-800
- Border radius: 12px
- Padding: 24px
- Shadow: subtle

**Post Card**:
- Same as standard
- Hover: slight elevation

### Navigation

**Sidebar Nav Item**:
- Padding: 12px 16px
- Border radius: 8px
- Hover: Gray-800 background
- Active: Owl-900 background + Owl-400 text
- Icon + Label (14px gap)

### Tags/Badges

**Tag**:
- Background: Owl-900/20
- Text: Owl-300
- Padding: 4px 12px
- Border radius: 6px
- Font: 12px, Medium

## Iconography

Use a consistent icon set like:
- **Heroicons** (recommended)
- **Lucide Icons**
- **Feather Icons**

Icon style: Outlined, 24px default size

## Spacing System

Use 8px base unit:
- **xs**: 4px
- **sm**: 8px
- **md**: 16px
- **lg**: 24px
- **xl**: 32px
- **2xl**: 48px
- **3xl**: 64px

## Layout Grid

- **Sidebar**: Fixed 256px
- **Main Content**: Max width 768px, centered
- **Container**: Max width 1440px
- **Gutter**: 24px

## Interactions & States

### Hover States
- Buttons: Darken or lighten background
- Links: Underline or color shift
- Cards: Slight elevation, border glow

### Active States
- Buttons: Pressed appearance (darker + slight scale)
- Nav items: Background + accent border/text

### Loading States
- Skeleton screens for content
- Spinners for actions
- Progress bars for uploads (future)

### Empty States
- Illustration or icon
- Helpful message
- CTA button to create content

## Mobile Considerations

- Sidebar becomes bottom tab bar
- Simplified navigation
- Full-width cards
- Reduced padding
- Larger touch targets (48px min)

## Accessibility

- Color contrast ratio: WCAG AA (4.5:1 for normal text)
- Focus indicators on all interactive elements
- Alt text for images
- ARIA labels for icons
- Keyboard navigation support

## Brand Elements

### Logo
- Icon: Stylized owl (wise, nocturnal, creative)
- Colors: Owl purple gradient
- Wordmark: Clean, modern sans-serif

### Mascot (Optional)
- Friendly owl character for empty states, onboarding

## Design Deliverables

For Figma AI or manual design:

1. **Style Guide Page**: Colors, typography, components
2. **Login Page**: Desktop + mobile
3. **Home Feed**: Desktop view
4. **Realms Page**: Desktop view
5. **Create Realm Modal**
6. **Characters Page**: Desktop view
7. **Create Character Form**
8. **Profile Page**: Desktop view
9. **Component Library**: Buttons, inputs, cards, etc.

## Figma AI Prompt Template

Use this prompt structure when working with Figma AI:

```
Design a [PAGE NAME] for OwlQuill, a roleplay social network.

Style:
- Dark theme with deep purple accents (#8b5cf6)
- Background: #030712
- Cards: #111827
- Clean, modern, cozy aesthetic

Layout:
- [Describe layout: sidebar, main content, etc.]

Key elements:
- [List main UI elements]

Mood: [Cozy, creative, premium, etc.]

Reference: [Notion, Discord, etc.]
```

## Example Figma AI Prompts

**Login Page**:
"Design a login page for OwlQuill, a roleplay social network. Dark theme (#030712 background), centered card (#111827), purple accent (#8b5cf6). Include logo, email/password inputs, login button, and link to register. Cozy, magical aesthetic. Reference: Notion login."

**Home Feed**:
"Design a home feed for OwlQuill. Dark theme with left sidebar (256px) containing navigation. Main content area (max 768px) with post cards showing author info, content, and engagement buttons. Purple accents. Clean, content-focused. Reference: Twitter/X dark mode."

**Character Creation Form**:
"Design a character creation form for OwlQuill. Dark card with fields for name, species, tags, and bio. Include an 'Generate with AI' button near bio field. Purple primary button, dark inputs. Creative, playful mood."

---

Use this brief to create consistent, beautiful designs that make OwlQuill feel premium and inviting for creative roleplayers!

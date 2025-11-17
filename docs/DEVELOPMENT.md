# OwlQuill Development Guide

## Architecture Overview

OwlQuill is a full-stack application with:
- **Backend**: FastAPI (Python) + SQLAlchemy + SQLite (dev) / PostgreSQL (production)
- **Frontend**: React + Vite + TypeScript + Tailwind CSS + shadcn/ui
- **Database Migrations**: Alembic
- **Testing**: pytest (backend), none yet (frontend)

---

## Project Structure

```
OwlQuill/
├── backend/
│   ├── alembic/              # Database migrations
│   │   └── versions/         # Migration files
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/       # API endpoint definitions
│   │   │       ├── auth.py
│   │   │       ├── users.py
│   │   │       ├── characters.py
│   │   │       ├── realms.py
│   │   │       ├── posts.py
│   │   │       ├── comments.py
│   │   │       ├── reactions.py
│   │   │       ├── ai.py
│   │   │       └── dm.py       # Direct messaging endpoints
│   │   ├── core/             # Core configuration
│   │   │   ├── config.py     # App settings
│   │   │   ├── database.py   # Database connection
│   │   │   ├── dependencies.py
│   │   │   └── security.py   # Auth and security
│   │   ├── models/           # SQLAlchemy models
│   │   │   ├── user.py
│   │   │   ├── character.py
│   │   │   ├── realm.py
│   │   │   ├── post.py
│   │   │   ├── comment.py
│   │   │   ├── reaction.py
│   │   │   ├── notification.py
│   │   │   └── dm.py         # DM models
│   │   ├── schemas/          # Pydantic schemas
│   │   │   ├── user.py
│   │   │   ├── character.py
│   │   │   ├── realm.py
│   │   │   ├── post.py
│   │   │   ├── comment.py
│   │   │   ├── reaction.py
│   │   │   └── dm.py         # DM schemas
│   │   └── main.py           # FastAPI app entry
│   ├── tests/                # Backend tests
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_characters.py
│   │   └── test_dm.py        # DM functionality tests
│   ├── requirements.txt
│   └── alembic.ini
├── frontend/
│   ├── src/
│   │   ├── components/       # React components
│   │   │   └── Layout.tsx
│   │   ├── pages/            # Page components
│   │   │   ├── Home.tsx
│   │   │   ├── Login.tsx
│   │   │   ├── Register.tsx
│   │   │   ├── Characters.tsx
│   │   │   ├── Realms.tsx
│   │   │   ├── RealmDetail.tsx
│   │   │   ├── Profile.tsx
│   │   │   └── Messages.tsx  # DM interface
│   │   ├── lib/
│   │   │   ├── apiClient.ts  # API client
│   │   │   ├── store.ts      # Zustand state management
│   │   │   └── types.ts      # TypeScript types
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
└── docs/
    ├── API.md                # API documentation
    ├── USER_GUIDE.md         # User guide
    └── DEVELOPMENT.md        # This file
```

---

## Database Models

### Core Models

- **User**: User accounts with authentication
- **Character**: Role-playing characters owned by users
- **Realm**: Communities/worlds for role-play
- **RealmMembership**: Users' membership in realms
- **Post**: Story posts in realms (IC/OOC/Narration)
- **Comment**: Comments on posts
- **Reaction**: Emoji reactions to posts
- **Notification**: User notifications

### Direct Messaging Models (Phase 5)

#### Conversation
Represents a messaging conversation between users.

```python
class Conversation(Base):
    id: int
    created_at: datetime
    updated_at: datetime

    # Relationships
    participants: List[ConversationParticipant]
    messages: List[Message]
```

#### ConversationParticipant
Represents a user's participation in a conversation.

```python
class ConversationParticipant(Base):
    id: int
    conversation_id: int
    user_id: int
    joined_at: datetime
    last_read_at: Optional[datetime]  # For tracking unread messages

    # Relationships
    conversation: Conversation
    user: User
```

**Note**: The `last_read_at` timestamp is used to calculate unread message counts. Messages created after this timestamp are considered unread for that user.

#### Message
Represents a single message in a conversation.

```python
class Message(Base):
    id: int
    conversation_id: int
    sender_id: int
    content: str
    created_at: datetime
    edited_at: Optional[datetime]

    # Relationships
    conversation: Conversation
    sender: User
```

### DM System Features

1. **One-to-One Conversations**: Currently focused on 1:1 messaging
2. **Unread Tracking**: Per-user tracking of unread messages using `last_read_at`
3. **Notification Integration**: New messages trigger notifications of type `dm_message`
4. **Conversation Deduplication**: Starting a conversation with an existing participant returns the existing conversation
5. **Message History**: Full message history is preserved and paginated

---

## Development Setup

### Backend Setup

1. **Create virtual environment** (optional but recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Set up environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Run migrations**:
   ```bash
   alembic upgrade head
   ```

5. **Run the development server**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

   Or use the Makefile:
   ```bash
   make run
   ```

### Frontend Setup

1. **Install dependencies**:
   ```bash
   cd frontend
   npm install
   ```

2. **Run development server**:
   ```bash
   npm run dev
   ```

3. **Build for production**:
   ```bash
   npm run build
   ```

---

## Creating Database Migrations

When you modify models:

1. **Generate migration**:
   ```bash
   cd backend
   alembic revision --autogenerate -m "description of changes"
   ```

2. **Review the generated migration** in `alembic/versions/`

3. **Apply migration**:
   ```bash
   alembic upgrade head
   ```

4. **Rollback if needed**:
   ```bash
   alembic downgrade -1
   ```

---

## Running Tests

### Backend Tests

```bash
cd backend
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_dm.py

# Run specific test
pytest tests/test_dm.py::test_send_message
```

### Test Structure

Tests use:
- **pytest**: Testing framework
- **TestClient**: FastAPI test client
- **SQLite in-memory database**: Fresh database for each test
- **Fixtures**: Defined in `conftest.py`

Example test pattern:
```python
def test_something(client: TestClient):
    # Setup: Create test data
    token = create_test_user(client, "test@example.com", "testuser")

    # Action: Make API call
    response = client.get("/endpoint", headers={"Authorization": f"Bearer {token}"})

    # Assert: Check results
    assert response.status_code == 200
    assert "expected_field" in response.json()
```

---

## API Client (Frontend)

The frontend API client (`frontend/src/lib/apiClient.ts`) provides a typed interface to the backend:

```typescript
// DM methods
apiClient.listConversations()
apiClient.getConversation(conversationId)
apiClient.startConversation(targetUsername)
apiClient.sendMessage(conversationId, content)
apiClient.markConversationRead(conversationId)

// Other methods
apiClient.login(email, password)
apiClient.register(email, username, password)
apiClient.getCharacters()
// ... etc
```

---

## Adding New Features

### Backend Checklist

1. Create/update models in `app/models/`
2. Create Pydantic schemas in `app/schemas/`
3. Create route handlers in `app/api/routes/`
4. Register router in `app/main.py`
5. Create Alembic migration
6. Write tests in `tests/`
7. Update API documentation

### Frontend Checklist

1. Add TypeScript types to `lib/types.ts`
2. Add API methods to `lib/apiClient.ts`
3. Create page/component in `pages/` or `components/`
4. Add route to `App.tsx`
5. Update navigation in `components/Layout.tsx` if needed

---

## Code Style

### Backend (Python)
- Follow PEP 8
- Use type hints
- Document functions with docstrings
- Keep routes focused and single-purpose

### Frontend (TypeScript)
- Use TypeScript strict mode
- Prefer functional components with hooks
- Use Tailwind for styling
- Keep components small and focused

---

## Common Development Tasks

### Adding a New API Endpoint

1. Define route in appropriate file in `app/api/routes/`:
   ```python
   @router.get("/endpoint")
   def my_endpoint(
       current_user: User = Depends(get_current_user),
       db: Session = Depends(get_db)
   ):
       # Implementation
       return result
   ```

2. Add to `app/main.py` if it's a new router

3. Add corresponding method to `apiClient.ts`

4. Write tests

### Adding a New Database Model

1. Create model in `app/models/`:
   ```python
   class MyModel(Base):
       __tablename__ = "my_models"

       id = Column(Integer, primary_key=True)
       # ... fields
   ```

2. Update `app/models/__init__.py` to export it

3. Create migration:
   ```bash
   alembic revision --autogenerate -m "add my_model"
   alembic upgrade head
   ```

4. Create Pydantic schemas in `app/schemas/`

---

## Troubleshooting

### Database Issues
- **Migrations fail**: Check that models are imported in `__init__.py`
- **Foreign key errors**: Ensure relationships are defined on both sides
- **Database locked**: Close any connections or restart the dev server

### Frontend Issues
- **Types not matching**: Regenerate types or check backend schemas
- **API 401 errors**: Check that token is being sent in Authorization header
- **Build errors**: Run `npm install` to ensure dependencies are up to date

---

## Phase Implementation History

- **Phase 1**: Initial scaffold (auth, users, basic structure)
- **Phase 2**: Characters, Realms, Posts, Comments, Reactions
- **Phase 3**: Advanced realm features, AI integration
- **Phase 4**: Notifications and discovery
- **Phase 5**: Direct Messaging (current)

---

## Future Enhancements

Potential features for future phases:
- WebSocket support for real-time messaging
- Group conversations (3+ participants)
- Message editing and deletion
- File/image attachments in messages
- Message search
- Typing indicators
- Read receipts
- Push notifications

# OwlQuill API Documentation

## Overview
OwlQuill is a social role-play network API built with FastAPI. This document covers all available endpoints.

Base URL: `/api`

## Authentication
Most endpoints require authentication using a Bearer token in the Authorization header:
```
Authorization: Bearer <token>
```

---

## Direct Messaging Endpoints

### List Conversations
Get all conversations for the current user with summary information.

**Endpoint:** `GET /dm/conversations`

**Authentication:** Required

**Response:**
```json
[
  {
    "id": 1,
    "other_participant": {
      "id": 2,
      "username": "alice",
      "display_name": "Alice Wonder",
      "avatar_url": null
    },
    "last_message": {
      "id": 10,
      "conversation_id": 1,
      "sender_id": 2,
      "content": "Hey, how are you?",
      "created_at": "2025-11-17T12:30:00",
      "edited_at": null
    },
    "last_message_at": "2025-11-17T12:30:00",
    "unread_count": 3,
    "created_at": "2025-11-17T10:00:00",
    "updated_at": "2025-11-17T12:30:00"
  }
]
```

---

### Start Conversation
Start a new conversation or return an existing one with another user.

**Endpoint:** `POST /dm/start`

**Authentication:** Required

**Request Body:**
```json
{
  "target_username": "alice"
  // OR
  // "target_user_id": 2
}
```

**Response:**
```json
{
  "id": 1,
  "participants": [
    {
      "id": 1,
      "username": "bob",
      "display_name": "Bob Smith",
      "avatar_url": null
    },
    {
      "id": 2,
      "username": "alice",
      "display_name": "Alice Wonder",
      "avatar_url": null
    }
  ],
  "messages": [],
  "created_at": "2025-11-17T10:00:00",
  "updated_at": "2025-11-17T10:00:00"
}
```

**Status Codes:**
- `200 OK` - Conversation returned successfully
- `400 Bad Request` - Invalid request (e.g., trying to message yourself)
- `404 Not Found` - Target user not found

---

### Get Conversation Detail
Get details of a specific conversation including messages.

**Endpoint:** `GET /dm/conversations/{conversation_id}`

**Authentication:** Required

**Query Parameters:**
- `skip` (optional, default: 0) - Number of messages to skip
- `limit` (optional, default: 50, max: 100) - Number of messages to return

**Response:**
```json
{
  "id": 1,
  "participants": [
    {
      "id": 1,
      "username": "bob",
      "display_name": "Bob Smith",
      "avatar_url": null
    },
    {
      "id": 2,
      "username": "alice",
      "display_name": "Alice Wonder",
      "avatar_url": null
    }
  ],
  "messages": [
    {
      "id": 1,
      "conversation_id": 1,
      "sender_id": 1,
      "content": "Hello Alice!",
      "created_at": "2025-11-17T10:05:00",
      "edited_at": null
    },
    {
      "id": 2,
      "conversation_id": 1,
      "sender_id": 2,
      "content": "Hi Bob!",
      "created_at": "2025-11-17T10:06:00",
      "edited_at": null
    }
  ],
  "created_at": "2025-11-17T10:00:00",
  "updated_at": "2025-11-17T10:06:00"
}
```

**Status Codes:**
- `200 OK` - Conversation returned successfully
- `403 Forbidden` - User is not a participant in this conversation
- `404 Not Found` - Conversation not found

---

### Send Message
Send a message in a conversation.

**Endpoint:** `POST /dm/conversations/{conversation_id}/messages`

**Authentication:** Required

**Request Body:**
```json
{
  "content": "This is my message"
}
```

**Response:**
```json
{
  "id": 3,
  "conversation_id": 1,
  "sender_id": 1,
  "content": "This is my message",
  "created_at": "2025-11-17T12:00:00",
  "edited_at": null
}
```

**Status Codes:**
- `201 Created` - Message sent successfully
- `403 Forbidden` - User is not a participant in this conversation
- `404 Not Found` - Conversation not found

**Notes:**
- Sending a message automatically creates a notification for other participants
- The sender's `last_read_at` is automatically updated

---

### Mark Messages as Read
Mark messages in a conversation as read to clear unread count.

**Endpoint:** `POST /dm/conversations/{conversation_id}/read`

**Authentication:** Required

**Request Body:**
```json
{
  "last_read_message_id": 10
  // OR
  // "read_up_to": "2025-11-17T12:00:00"
  // OR leave empty to mark all as read
}
```

**Response:**
`204 No Content`

**Status Codes:**
- `204 No Content` - Messages marked as read
- `403 Forbidden` - User is not a participant in this conversation

---

## Other Endpoints

(Other endpoint documentation for auth, users, characters, realms, posts, comments, reactions, etc. would go here)

---

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

Common status codes:
- `400 Bad Request` - Invalid request data
- `401 Unauthorized` - Authentication required or invalid token
- `403 Forbidden` - User doesn't have permission
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

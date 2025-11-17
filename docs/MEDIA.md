# Media & Avatars

OwlQuill supports uploading images for user avatars, character avatars, and post attachments.

## Features

- **User Avatars**: Upload profile pictures for your account
- **Character Avatars**: Upload avatars for each character you create
- **Post Images**: Attach images to posts (one per post)

## Storage

- **Development**: Files are stored locally in `backend/media/` directory
- **Production**: Storage is abstracted for easy migration to S3 or other cloud storage
- **Organization**: Files are organized by type and date: `{kind}/YYYY/MM/filename.ext`

## Limits & Validation

- **Max File Size**: 5 MB per file
- **Allowed Types**: JPEG, JPG, PNG, WebP
- **Validation**: Both client-side and server-side validation

## How to Use

### Upload User Avatar

1. Go to Profile page
2. Click "Upload Avatar" button
3. Select an image file (max 5MB, jpg/png/webp)
4. Avatar updates immediately

### Upload Character Avatar

1. Go to Characters page
2. Find the character card
3. Click the camera icon (📷) button
4. Select an image file
5. Avatar updates in the character list

### Upload Post Image

Use the API endpoint directly (UI coming soon):

```bash
POST /api/media/post/{post_id}/image
Content-Type: multipart/form-data

file: <image file>
```

## API Endpoints

### Upload User Avatar

```
POST /api/media/avatar/user
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: <image file>
```

**Response**:
```json
{
  "id": 1,
  "kind": "user_avatar",
  "filename": "avatar.jpg",
  "url": "/media/user_avatar/2025/01/abc123.jpg",
  "content_type": "image/jpeg",
  "size_bytes": 524288,
  "created_at": "2025-01-17T10:00:00Z"
}
```

### Upload Character Avatar

```
POST /api/media/avatar/character/{character_id}
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: <image file>
```

### Upload Post Image

```
POST /api/media/post/{post_id}/image
Authorization: Bearer <token>
Content-Type: multipart/form-data

file: <image file>
```

## Configuration

Media settings can be configured via environment variables:

```env
# Media uploads
MEDIA_ROOT=./media                    # Local storage directory
MEDIA_BASE_URL=/media                 # URL prefix for serving files
MAX_IMAGE_SIZE_BYTES=5242880         # 5 MB limit
ALLOWED_IMAGE_CONTENT_TYPES=["image/jpeg","image/jpg","image/png","image/webp"]
```

## Future Enhancements

- Multiple images per post
- Image cropping and editing
- S3/cloud storage integration
- AI image generation
- Thumbnails and optimization
- Alt text for accessibility

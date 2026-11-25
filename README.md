# clips
A credit-free, AI-inspired video clipping and editing website.

## URL import backend

The optional FastAPI backend accepts public, user-authorized YouTube and TikTok URLs.

### Render deployment

1. Create a Render **Web Service** from this repository.
2. Select the `Docker` runtime.
3. Set the Docker context to the repository root.
4. Deploy and copy the HTTPS service URL.
5. Set `CORS_ORIGINS` on Render to your GitHub Pages origin or `*` for testing.

Optional environment variables:

- `CORS_ORIGINS`: comma-separated allowed frontend origins
- `MAX_IMPORT_BYTES`: default `786432000`
- `TEMP_DIR`: temporary processing directory

### API

- `GET /health`
- `POST /api/import` with JSON `{ "url": "https://..." }`
- `GET /api/media/{job_id}`
- `DELETE /api/media/{job_id}`

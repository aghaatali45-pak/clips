# clips
A credit-free, AI-inspired video clipping and editing website.

## URL import backend and AI moment finder

The optional FastAPI backend imports public YouTube/TikTok videos and offers a no-paid-API best-moments endpoint. Use only videos you own or have permission to process, and comply with the applicable platform terms. Temporary video and clip files live in the service's temp directory; call the cleanup endpoint when finished. Hosting files on an ephemeral Render filesystem means they are not durable.

### Render deployment

1. Create a Render **Web Service** from this repository.
2. Select the `Docker` runtime and repository root as the Docker context.
3. Deploy and copy the HTTPS service URL.
4. Set `CORS_ORIGINS` to the frontend origin (avoid `*` for production).

Optional variables: `CORS_ORIGINS`, `MAX_IMPORT_BYTES` (default `786432000`), `TEMP_DIR`.

### Enable the browser UI

Add this script tag after `script.js` in `index.html` so the feature module is loaded:

```html
<script src="best-moments.js" defer></script>
```

The module injects a checkbox (off by default), URL field, and mobile-friendly results. On first analysis, enter the deployed FastAPI HTTPS URL. The base URL is stored in this browser's local storage.

### API

- `GET /health`
- `POST /api/import` with JSON `{ "url": "https://..." }`
- `POST /api/import/{job_id}/best-moments` — scores 15–30 second candidate moments using audio RMS/peaks/sudden changes plus available YouTube auto/manual English captions; falls back to audio only if captions are absent.
- `POST /api/import/{job_id}/clip` with `{ "start": 0, "end": 20 }` — returns an MP4 clip URL.
- `GET /api/import/{job_id}/clips/{filename}`
- `GET /api/media/{job_id}`
- `DELETE /api/media/{job_id}` — removes temporary files.

No paid API or API key is used. Clip selection uses free audio and caption signals; it is a heuristic, not semantic AI or a guarantee of viral quality.

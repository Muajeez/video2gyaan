"""
YouTube Summarizer Backend
Using FastAPI + Gemini AI (via Google AI Studio API Key)
"""

import os
import re
import logging
import httpx
import asyncio
import secrets
import time
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import json
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

from prompts import TONE_PROMPTS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Configure Gemini API with API Key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")

# Initialize FastAPI
app = FastAPI(title="YouTube Summarizer API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Rate Limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount frontend static files
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# ── In-memory share store ──────────────────────────────────────────────────────
# Each entry: { summary_md, video_id, video_title, tone, youtube_url, created_at }
# Max 2000 entries; oldest are evicted when limit is reached.
_share_store: dict[str, dict] = {}
_SHARE_MAX = 2000

# Request models
class SummarizeRequest(BaseModel):
    youtube_url: str
    tone: Literal["Hook", "Professional", "Compact"]

class ShareRequest(BaseModel):
    summary_md: str
    video_id: str
    video_title: Optional[str] = "Untitled Video"
    tone: Optional[str] = "Professional"
    youtube_url: Optional[str] = ""


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',  # Standard YouTube
        r'(?:embed\/)([0-9A-Za-z_-]{11})',   # Embed URL
        r'^([0-9A-Za-z_-]{11})$',             # Direct video ID
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError("Invalid YouTube URL")


def get_transcript(video_id: str) -> str:
    """Get transcript from YouTube video"""
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id)
        formatter = TextFormatter()
        return formatter.format_transcript(transcript)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not fetch transcript: {str(e)}"
        )


async def get_video_info(video_id: str) -> dict:
    """Get video info from YouTube Data API as fallback"""
    if not YOUTUBE_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="YOUTUBE_API_KEY not configured"
        )
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={YOUTUBE_API_KEY}&part=snippet,contentDetails",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to fetch video info from YouTube"
                )
            
            data = response.json()
            if not data.get('items'):
                raise HTTPException(
                    status_code=404,
                    detail="Video not found"
                )
            
            item = data['items'][0]
            snippet = item['snippet']
            
            return {
                'title': snippet.get('title', ''),
                'description': snippet.get('description', ''),
                'channel_title': snippet.get('channelTitle', ''),
                'published_at': snippet.get('publishedAt', ''),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching video info: {str(e)}"
        )


# Maximum transcript characters to send to Gemini (roughly ~30k tokens)
MAX_TRANSCRIPT_CHARS = 120000


async def generate_summary_stream_with_gemini(transcript: str, tone: str):
    """Generate summary using Gemini AI via API Key, yielding stream chunks"""
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY not configured"
        )
    
    # Truncate very long transcripts to avoid exceeding context window
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        logger.warning(f"Transcript truncated from {len(transcript)} to {MAX_TRANSCRIPT_CHARS} chars")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated due to length]"
    
    prompt = f"""
You are an expert AI assistant. Based on the transcript/text below, perform the following task EXACTLY as instructed.
Do NOT add any extra commentary, introduction, or summary unless explicitly asked for in the instructions.

Instructions:
{TONE_PROMPTS.get(tone, TONE_PROMPTS['Professional'])}

Transcript/Text:
{transcript}

Output:
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}"
            async with client.stream("POST", url, json=payload, headers={"Content-Type": "application/json"}, timeout=120.0) as response:
                if response.status_code != 200:
                    error_detail = await response.aread()
                    raise HTTPException(
                        status_code=500,
                        detail=f"Gemini API error: {error_detail.decode('utf-8')}"
                    )
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data_str)
                            if "candidates" in chunk and chunk["candidates"] and "content" in chunk["candidates"][0]:
                                text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                                yield text
                        except Exception:
                            pass
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error calling Gemini API: {str(e)}"
        )

@app.get("/")
def root():
    """Serve the main frontend HTML"""
    return FileResponse(os.path.join(frontend_path, "index.html"))


@app.post("/share")
@limiter.limit("10/minute")
async def create_share(request: Request, share_req: ShareRequest):
    """Save a summary and return a shareable short ID"""
    share_id = secrets.token_urlsafe(6)  # ~8 chars, URL-safe
    
    if len(_share_store) >= _SHARE_MAX:
        # Evict the oldest entry
        oldest_key = min(_share_store, key=lambda k: _share_store[k]["created_at"])
        del _share_store[oldest_key]

    _share_store[share_id] = {
        "summary_md": share_req.summary_md,
        "video_id": share_req.video_id,
        "video_title": share_req.video_title or "Untitled Video",
        "tone": share_req.tone or "Professional",
        "youtube_url": share_req.youtube_url or "",
        "created_at": time.time(),
    }
    logger.info(f"Share created: {share_id} for video {share_req.video_id}")
    return {"share_id": share_id}


@app.get("/api/share/{share_id}")
async def get_share_data(share_id: str):
    """Return share metadata as JSON (for the share page to render)"""
    entry = _share_store.get(share_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Share not found or expired")
    return entry


@app.get("/s/{share_id}", response_class=HTMLResponse)
async def shared_summary_page(share_id: str):
    """Serve the beautiful standalone share page"""
    entry = _share_store.get(share_id)
    if not entry:
        return HTMLResponse(content=_not_found_html(), status_code=404)
    return HTMLResponse(content=_share_html(share_id, entry))


def _not_found_html() -> str:
    return """
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Link Not Found — Video2Gyaan</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:'Inter',sans-serif;background:#09090b;color:#fafafa;min-height:100vh;
         display:flex;align-items:center;justify-content:center;text-align:center;padding:24px}
    h1{font-size:clamp(24px,5vw,40px);font-weight:800;letter-spacing:-1px;margin-bottom:12px}
    p{color:#a1a1aa;font-size:15px;margin-bottom:28px}
    a{display:inline-block;padding:12px 28px;background:#8b5cf6;color:#fff;border-radius:10px;
      text-decoration:none;font-weight:600;font-size:14px;transition:opacity .2s}
    a:hover{opacity:.85}
  </style>
</head>
<body>
  <div>
    <h1>🔗 Link Not Found</h1>
    <p>This shared summary may have expired or the link is invalid.</p>
    <a href="/">Generate a New Summary</a>
  </div>
</body>
</html>
"""


def _share_html(share_id: str, entry: dict) -> str:
    video_id    = entry["video_id"]
    video_title = entry["video_title"]
    tone        = entry["tone"]
    youtube_url = entry["youtube_url"]
    summary_md  = entry["summary_md"].replace("`", "\\`")  # escape backticks for JS template literal
    thumb_url   = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

    return f"""
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{video_title} — Video2Gyaan</title>
  <meta name="description" content="AI-generated summary of '{video_title}' on Video2Gyaan">
  <!-- Open Graph for rich link previews -->
  <meta property="og:title" content="{video_title} — Gyaan Summary">
  <meta property="og:description" content="Read the AI-generated summary of this YouTube video on Video2Gyaan.">
  <meta property="og:image" content="{thumb_url}">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    html{{font-size:16px;-webkit-font-smoothing:antialiased}}
    body{{font-family:'Inter',sans-serif;background:#09090b;color:#fafafa;min-height:100vh;
         display:flex;flex-direction:column;overflow-x:hidden;position:relative}}

    /* Ambient */
    .ambient{{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}}
    .blob{{position:absolute;border-radius:50%;filter:blur(100px);opacity:.16;will-change:transform}}
    .b1{{width:560px;height:560px;background:radial-gradient(circle,#8b5cf6,transparent 70%);
         top:-15%;left:-8%;animation:f1 20s ease-in-out infinite}}
    .b2{{width:460px;height:460px;background:radial-gradient(circle,#06b6d4,transparent 70%);
         bottom:-12%;right:-8%;animation:f2 24s ease-in-out infinite}}
    @keyframes f1{{0%,100%{{transform:translate(0,0)}}50%{{transform:translate(40px,30px)}}}}
    @keyframes f2{{0%,100%{{transform:translate(0,0)}}50%{{transform:translate(-30px,-20px)}}}}

    /* Header */
    header{{position:sticky;top:0;z-index:50;padding:0 24px;height:56px;
            backdrop-filter:blur(16px) saturate(1.6);background:rgba(9,9,11,.6);
            border-bottom:1px solid rgba(255,255,255,.06);display:flex;align-items:center}}
    .hrow{{max-width:900px;width:100%;margin:0 auto;display:flex;align-items:center;justify-content:space-between}}
    .brand{{display:flex;align-items:center;gap:10px;text-decoration:none;color:#fafafa}}
    .brand-icon{{width:34px;height:34px;display:flex;align-items:center;justify-content:center;
                background:rgba(167,139,250,.15);border-radius:8px;color:#a78bfa;flex-shrink:0}}
    .brand-name{{font-size:16px;font-weight:700;letter-spacing:-.4px}}
    .badge{{font-size:10px;font-weight:700;text-transform:uppercase;background:rgba(167,139,250,.15);
            color:#a78bfa;padding:2px 6px;border-radius:4px;border:1px solid #a78bfa;margin-left:2px;letter-spacing:.5px}}
    .btn-new{{padding:8px 18px;background:linear-gradient(135deg,#8b5cf6,#6d28d9);border:none;
              border-radius:8px;color:#fff;font-size:13px;font-weight:600;font-family:'Inter',sans-serif;
              cursor:pointer;text-decoration:none;transition:opacity .2s}}
    .btn-new:hover{{opacity:.85}}

    /* Main */
    main{{flex:1;position:relative;z-index:1;padding:48px 24px 60px;display:flex;justify-content:center}}
    .wrap{{width:100%;max-width:860px;display:flex;flex-direction:column;gap:28px}}

    /* Video card */
    .video-card{{display:flex;align-items:center;gap:18px;padding:18px;
                 background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
                 border-radius:14px;backdrop-filter:blur(12px)}}
    .thumb{{width:140px;height:78px;object-fit:cover;border-radius:8px;flex-shrink:0;background:#1a1a1e}}
    .vid-info{{flex:1;min-width:0}}
    .vid-title{{font-size:15px;font-weight:700;color:#fafafa;line-height:1.4;margin-bottom:6px;
                display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
    .vid-meta{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
    .tone-pill{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
                padding:3px 10px;border-radius:100px;background:rgba(167,139,250,.15);color:#a78bfa;
                border:1px solid rgba(167,139,250,.3)}}
    .yt-link{{font-size:12px;color:#a1a1aa;text-decoration:none;display:flex;align-items:center;gap:4px}}
    .yt-link:hover{{color:#fafafa}}

    /* Summary card */
    .summary-card{{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
                   border-radius:16px;padding:32px;backdrop-filter:blur(12px)}}
    .card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}}
    .card-label{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#71717a}}
    .actions{{display:flex;gap:8px}}
    .btn-act{{display:flex;align-items:center;gap:6px;padding:7px 14px;font-size:12px;font-weight:600;
              font-family:'Inter',sans-serif;background:rgba(255,255,255,.05);
              border:1px solid rgba(255,255,255,.08);border-radius:8px;color:#a1a1aa;
              cursor:pointer;transition:all .15s}}
    .btn-act:hover{{color:#fafafa;border-color:#a78bfa;background:rgba(167,139,250,.15)}}
    .summary{{font-size:14px;line-height:1.85;color:#fafafa}}
    .summary h1{{font-size:20px;font-weight:800;margin:0 0 12px;letter-spacing:-.5px}}
    .summary h2{{font-size:16px;font-weight:700;margin:24px 0 10px;padding-bottom:6px;
                 border-bottom:1px solid rgba(255,255,255,.06);letter-spacing:-.3px}}
    .summary h3{{font-size:14px;font-weight:700;margin:18px 0 6px;color:#a78bfa}}
    .summary p{{margin:10px 0}}
    .summary strong{{font-weight:700;color:#fafafa}}
    .summary ul,.summary ol{{padding-left:20px;margin:10px 0}}
    .summary li{{margin:5px 0}}
    .summary li::marker{{color:#a78bfa}}
    .summary blockquote{{border-left:3px solid #a78bfa;padding:10px 16px;margin:14px 0;
                          background:rgba(167,139,250,.1);border-radius:0 8px 8px 0;
                          color:#a1a1aa;font-style:italic}}
    .summary code{{font-size:12px;background:rgba(255,255,255,.06);padding:2px 6px;border-radius:4px;
                   font-family:monospace;color:#a78bfa}}
    .summary hr{{border:none;border-top:1px solid rgba(255,255,255,.06);margin:20px 0}}
    .summary a{{color:#a78bfa;text-decoration:none}}
    .summary a:hover{{text-decoration:underline}}

    /* CTA */
    .cta{{text-align:center;padding:16px;background:rgba(167,139,250,.08);
           border:1px solid rgba(167,139,250,.2);border-radius:14px}}
    .cta p{{font-size:14px;color:#a1a1aa;margin-bottom:14px}}
    .cta a{{display:inline-block;padding:12px 32px;background:linear-gradient(135deg,#8b5cf6,#6d28d9);
             color:#fff;border-radius:10px;text-decoration:none;font-weight:700;font-size:14px;
             box-shadow:0 4px 20px rgba(139,92,246,.35);transition:opacity .2s}}
    .cta a:hover{{opacity:.85}}

    /* Toast */
    .toast{{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(12px);
             background:#fafafa;color:#09090b;padding:10px 24px;border-radius:100px;
             font-size:13px;font-weight:600;opacity:0;pointer-events:none;
             transition:all .3s cubic-bezier(.4,0,.2,1);z-index:999;white-space:nowrap;
             box-shadow:0 8px 30px rgba(0,0,0,.3)}}
    .toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}

    /* Footer */
    footer{{position:relative;z-index:1;padding:28px 24px;border-top:1px solid rgba(255,255,255,.06);
             text-align:center}}
    footer p{{font-size:12px;color:#52525b}}
    footer a{{color:#71717a;text-decoration:none}}
    footer a:hover{{color:#fafafa}}
  </style>
</head>
<body>
  <div class="ambient" aria-hidden="true">
    <div class="blob b1"></div>
    <div class="blob b2"></div>
  </div>

  <header>
    <div class="hrow">
      <a class="brand" href="/">
        <div class="brand-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
               stroke-linecap="round" stroke-linejoin="round">
            <polygon points="23 7 16 12 23 17 23 7"/>
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
          </svg>
        </div>
        <span class="brand-name">Video2Gyaan</span>
        <span class="badge">Beta</span>
      </a>
      <a class="btn-new" href="/">Try it yourself →</a>
    </div>
  </header>

  <main>
    <div class="wrap">
      <!-- Video Info -->
      <div class="video-card">
        <img class="thumb" src="{thumb_url}" alt="Video thumbnail">
        <div class="vid-info">
          <div class="vid-title">{video_title}</div>
          <div class="vid-meta">
            <span class="tone-pill">{tone}</span>
            {'<a class="yt-link" href="' + youtube_url + '" target="_blank" rel="noopener">▶ Watch on YouTube</a>' if youtube_url else ''}
          </div>
        </div>
      </div>

      <!-- Summary -->
      <div class="summary-card">
        <div class="card-header">
          <span class="card-label">AI Summary</span>
          <div class="actions">
            <button class="btn-act" onclick="copyText()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
              </svg>
              Copy
            </button>
            <button class="btn-act" onclick="copyLink()">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round">
                <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
              </svg>
              Share Link
            </button>
          </div>
        </div>
        <div class="summary" id="summary-body"></div>
      </div>

      <!-- CTA -->
      <div class="cta">
        <p>Want to summarize your own YouTube videos? It's free!</p>
        <a href="/">Generate Your Summary →</a>
      </div>
    </div>
  </main>

  <footer>
    <p>Shared via <a href="/">Video2Gyaan</a> · Powered by Gemini AI</p>
  </footer>

  <div class="toast" id="toast"></div>

  <script>
    marked.setOptions({{gfm:true,breaks:true}});
    const md = `{summary_md}`;
    document.getElementById('summary-body').innerHTML = marked.parse(md);

    function showToast(msg) {{
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.classList.add('show');
      setTimeout(() => t.classList.remove('show'), 2400);
    }}
    function copyText() {{
      const txt = document.getElementById('summary-body').innerText;
      navigator.clipboard.writeText(txt).then(() => showToast('Copied!')).catch(() => showToast('Copy failed'));
    }}
    function copyLink() {{
      navigator.clipboard.writeText(window.location.href).then(() => showToast('Link copied!')).catch(() => showToast('Copy failed'));
    }}
  </script>
</body>
</html>
"""


@app.post("/summarize")
@limiter.limit("5/minute")
async def summarize(request: Request, summarize_request: SummarizeRequest):
    """Summarize YouTube video with Streaming"""
    try:
        # Step 1: Extract video ID
        video_id = extract_video_id(summarize_request.youtube_url)
        logger.info(f"Summarizing video {video_id} with tone '{summarize_request.tone}'")
        
        # Step 2: Try to get transcript, fallback to video info
        transcript = None
        video_info = None
        
        try:
            transcript = await asyncio.to_thread(get_transcript, video_id)
        except Exception as e:
            logger.warning(f"Transcript unavailable for {video_id}: {e}")
            if YOUTUBE_API_KEY:
                try:
                    video_info = await get_video_info(video_id)
                except Exception as fallback_err:
                    logger.error(f"Fallback video info also failed: {fallback_err}")
        
        if not transcript and not video_info:
            raise HTTPException(
                status_code=400,
                detail="Could not fetch transcript or video info. The video may not have captions available."
            )

        async def event_generator():
            # Send initial meta event
            meta_data = {
                "success": True,
                "video_id": video_id,
                "tone": summarize_request.tone,
                "source": "transcript" if transcript else "video_info"
            }
            if not transcript:
                meta_data["note"] = "Full transcript unavailable. Summary based on video title and description."
            
            yield f"data: {json.dumps({'type': 'meta', 'data': meta_data})}\n\n"
            
            try:
                # Decide which text to summarize
                if transcript:
                    stream = generate_summary_stream_with_gemini(transcript, summarize_request.tone)
                else:
                    text_fallback = f"Video Title: {video_info['title']}\n\nDescription: {video_info['description']}"
                    stream = generate_summary_stream_with_gemini(text_fallback, summarize_request.tone)

                async for text_chunk in stream:
                    yield f"data: {json.dumps({'type': 'chunk', 'text': text_chunk})}\n\n"
                    
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            except HTTPException as http_exc:
                 yield f"data: {json.dumps({'type': 'error', 'detail': http_exc.detail})}\n\n"
            except Exception as exc:
                 yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
            
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
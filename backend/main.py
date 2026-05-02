"""
YouTube Summarizer Backend
Using FastAPI + Gemini AI (via Google AI Studio API Key)
"""

import os
import re
import logging
import httpx
import asyncio
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import json
from fastapi.responses import FileResponse, StreamingResponse
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

# Request model
class SummarizeRequest(BaseModel):
    youtube_url: str
    tone: Literal["Hook", "Professional", "Compact"]


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
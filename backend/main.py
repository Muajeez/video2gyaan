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
from fastapi.responses import FileResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter

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
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
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


async def generate_summary_with_gemini(transcript: str, tone: str) -> str:
    """Generate summary using Gemini AI via API Key"""
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY not configured"
        )
    
    # Truncate very long transcripts to avoid exceeding context window
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        logger.warning(f"Transcript truncated from {len(transcript)} to {MAX_TRANSCRIPT_CHARS} chars")
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n\n[Transcript truncated due to length]"
    
    # Tone-specific prompts
    tone_prompts = {
        "Hook": """System Instruction:
            You are an expert storyteller and content strategist. Your task is to transform the provided video transcript into a long-form narrative post (300–800 words).
            Strict Structural Requirements:
            The Opening: Start with a single, punchy question that addresses a deep pain point or curiosity found in the transcript.
            The Narrative Bridge: Develop the content like a story. Instead of listing facts, describe a "journey of discovery" or a "conflict and resolution." Use short, rhythmic sentences to maintain momentum.
            Character Growth: Each paragraph should pull the reader deeper, making them feel like they are "leveling up" their knowledge as they read.
            The Final Twist: Near the end, introduce a "counter-intuitive" insight or a surprising "Plot Twist" from the transcript that goes against common wisdom.
            Conclusion: End with a thought-provoking question or a "moral of the story" that forces the reader to reflect on their own life/work.""",

        "Professional": """Create a professional, comprehensive summary suitable for business or academic use.
        Structure the summary with:
        - An executive overview (2-3 sentences)
        - Key sections with bold headings covering each major topic discussed
        - Important data points, statistics, or facts mentioned
        - Key takeaways and actionable conclusions as bullet points
        The summary should be thorough and cover ALL major topics discussed in the video.""",

        "Compact": """Create a well-organized summary using bullet points grouped by topic.
        Structure the summary with:
        - A one-line overview of the video
        - Bullet points grouped under bold topic headings for each major section
        - Key facts, numbers, or quotes worth noting
        Cover ALL major topics discussed in the video, even in compact form."""
    }

    prompt = f"""
You are an expert YouTube video summarizer. Based on the transcript below, create a DETAILED and COMPREHENSIVE summary.
The video is long, so make sure to cover ALL major topics, arguments, and insights discussed throughout the entire video.
Do NOT skip sections — the reader should get a thorough understanding of everything covered.

Tone: {tone}
{tone_prompts.get(tone, tone_prompts['Professional'])}

Transcript:
{transcript}

Detailed Summary:
"""

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.7,
                        "maxOutputTokens": 8192,
                    }
                },
                headers={"Content-Type": "application/json"},
                timeout=120.0
            )
            
            if response.status_code != 200:
                error_detail = response.json()
                raise HTTPException(
                    status_code=500,
                    detail=f"Gemini API error: {error_detail}"
                )
            
            result = response.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
            
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
    """Summarize YouTube video"""
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
            # Transcript not available, try YouTube Data API as fallback
            if YOUTUBE_API_KEY:
                try:
                    video_info = await get_video_info(video_id)
                except Exception as fallback_err:
                    logger.error(f"Fallback video info also failed: {fallback_err}")
        
        # Step 3: Generate summary with Gemini
        if transcript:
            summary = await generate_summary_with_gemini(transcript, summarize_request.tone)
            return {
                "success": True,
                "video_id": video_id,
                "summary": summary,
                "tone": summarize_request.tone,
                "source": "transcript"
            }
        elif video_info:
            # Use video info (title + description) as fallback
            summary = await generate_summary_with_gemini(
                f"Video Title: {video_info['title']}\n\nDescription: {video_info['description']}",
                summarize_request.tone
            )
            return {
                "success": True,
                "video_id": video_id,
                "summary": summary,
                "tone": summarize_request.tone,
                "source": "video_info",
                "note": "Full transcript unavailable. Summary based on video title and description."
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Could not fetch transcript or video info. The video may not have captions available."
            )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
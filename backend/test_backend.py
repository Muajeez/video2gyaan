import httpx
import asyncio
import json

async def test():
    try:
        async with httpx.AsyncClient() as client:
            print("Calling /summarize...")
            payload = {
                "youtube_url": "https://www.youtube.com/watch?v=MCX4YqcW7kU",
                "tone": "Hook"
            }
            async with client.stream('POST', 'http://localhost:8000/summarize', json=payload, timeout=60.0) as response:
                print(f"Status Code: {response.status_code}")
                async for line in response.aiter_lines():
                    print(f"Line: {line}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test())

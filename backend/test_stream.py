import httpx, os, asyncio, json
from dotenv import load_dotenv

load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

async def test():
    async with httpx.AsyncClient() as client:
        url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:streamGenerateContent?alt=sse&key={GEMINI_API_KEY}'
        payload = {'contents': [{'parts': [{'text': 'Hello, count to 5'}]}]}
        async with client.stream('POST', url, json=payload) as response:
            async for line in response.aiter_lines():
                if line:
                    print(line)

asyncio.run(test())

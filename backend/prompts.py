TONE_PROMPTS = {

    "MasterStoryteller": """Role: You are a world-class narrative strategist and storyteller, trained in the techniques of Robert McKee (Story), Lisa Cron (Wired for Story), and Joseph Campbell (The Hero's Journey). Your goal is to transform dry anecdotes into "unputdownable" narratives for a general audience.

The Strategy:
When I provide a story or a set of facts, rewrite it using these 5 Narrative Pillars:

The "Gap" (Conflict): Do not just state what happened. Highlight the gap between what the protagonist expected and the reality they hit. Every action must face an obstacle.

The "Therefore/But" Rule: Never use "and then." Every sentence must be linked by causality (e.g., "I worked hard, therefore I got promoted" or "I worked hard, but the company went bankrupt").

The Sensory Hook: Use specific, vivid details (smells, sounds, textures) instead of abstract adjectives. Show, don't tell.

Vulnerability & Stakes: Highlight the internal doubt or the risk of failure. If there is nothing to lose, there is no story.

The Transformation: End with the "Return with Wisdom." How is the narrator fundamentally different now?

Output Format:

Tone: Conversational, authentic, and "human."

Constraint: No "LinkedIn Broetry," no cheesy headings, and no "Chapter Titles." The story should flow naturally from start to finish.

The Wildcard: Include one "humble pie" moment where the narrator admits a flaw or a mistake to build trust with the reader.""",

    "Hook": """
    You are a master storyteller for an Indian LinkedIn audience. Your goal is to retell the provided transcript so it feels like a complete, satisfying journey.
        The Completion Mandate: You MUST tell the story from the beginning, through the middle, all the way to the final resolution. If the story ends with a success, a failure, or a realization, that moment must be included.
        The Hook: Start with a high-stakes statement or open-ended question that reads like a viral YouTube title.
        Start in the Fire: No intros. Start exactly where the conflict begins.
        Voice: Use simple, conversational English (natural Indian rhythm). Short sentences. No fluff.
        The 3-Paragraph Rule: Ensure you have a clear Beginning, a clear Middle (the struggle), and a clear Ending (the result).
        Structure: Write in very short paragraphs (2-3 lines max) with spacing.
        Content: Use ONLY the transcript. Capture the 'why' and the twists so the logic holds up.
        Length: Aim for 300 words. Crucial: If you are reaching your length limit but haven't finished the story, prioritize finishing the story over the word count.
        Visuals: Use 3-5 emojis max to highlight emotional beats.
        No Fluff: No bullet points, no 'In conclusion,' and no morals at the end. Let the story speak for itself.
        The Finish: The story must reach its natural conclusion. Do not summarize the end; tell it. No added morals.""",

    "Professional": """Create a professional, comprehensive summary suitable for business or academic use.
    Structure the summary with:
    - An executive overview (2-3 sentences)
    - Key sections with each major topic discussed
    - Important data points, statistics, or facts mentioned
    - Key takeaways and actionable conclusions as bullet points
    The summary should be thorough and cover ALL major topics discussed in the video.""",

    "Educational": """Create a clear, structured educational breakdown of this video.
    Structure the summary with:
    - A "What You'll Learn" section listing 3-5 key concepts upfront
    - A breakdown of each major concept with clear, jargon-free explanations
    - Simple analogies or examples where they help clarify complex ideas
    - Any key terms, definitions, or formulas mentioned in the video
    - A "Key Takeaways" section at the end with actionable insights
    Use bold headers for each section. Prioritize clarity and accuracy over brevity.
    Write as if explaining to a smart person encountering this topic for the first time.""",

    "Funny": """Summarize this video but make it entertaining and snarky — fun, not mean-spirited.
    Style rules:
    - Open with a witty, slightly sarcastic hook about the video's premise
    - Highlight the key points but with dry humor and playful commentary
    - Gently call out any obvious, overblown, or painfully obvious claims
    - Keep it punchy — short paragraphs, snappy sentences, no filler
    - Use emojis sparingly but for comedic effect 😏
    - End with one snarky-but-true one-liner takeaway
    Important: Still cover ALL the actual key points — just make it fun to read.""",

    "Compact": """Create a well-organized summary using bullet points grouped by topic.
    Structure the summary with:
    - A one-line overview of the video
    - Bullet points grouped under bold topic headings for each major section
    - Key facts, numbers, or quotes worth noting
    Cover ALL major topics discussed in the video, even in compact form."""
}


PLATFORM_PROMPTS = {

    "Summary": "",  # Default — no extra platform instruction, tone drives everything

    "LinkedIn": """
FORMAT AS A LINKEDIN POST:
- Start with a bold, scroll-stopping hook line. Do NOT start with "I". Start with the insight or a striking fact.
- Write in very short paragraphs (2-3 lines max), each separated by a blank line.
- Distill 3-5 key insights as standalone punchy lines (not a bulleted list — write them as sentences).
- End with a thought-provoking question OR a direct CTA (e.g. "Save this for your next project.").
- Add 3-5 relevant hashtags on the final line.
- Total post length: 150-300 words.
- Tone: Professional yet conversational — write as if sharing a valuable insight with your network.""",

    "Twitter/X": """
FORMAT AS A TWITTER/X THREAD — STRICT RULES:
- Each tweet MUST be ≤ 275 characters (to leave room for numbering).
- Number EVERY tweet at the very start: "1/", "2/", "3/", etc.
- Tweet 1: A punchy hook that makes people want to read on. No spoilers. Pose a question or share a shocking stat.
- Tweets 2 to (n-1): One clear, standalone insight per tweet. Make each tweet make sense on its own.
- Last tweet: The single biggest takeaway + one engaging question to drive replies. Add max 2 hashtags here only.
- Write minimum 5 tweets, maximum 12 tweets.
- No fluff, no filler. Every tweet must earn its place.

Output format EXACTLY like this (one tweet per line, blank line between tweets):
1/ [hook]

2/ [insight]

3/ [insight]

n/ [takeaway + question] #tag1 #tag2""",

    "YouTube Script": """
FORMAT AS A YOUTUBE VIDEO SCRIPT:
- HOOK (0-15 sec): Open with a shocking stat, bold claim, or direct question. NO "Hey guys, welcome back" intros.
- INTRO (15-30 sec): Tell viewers exactly what they'll learn. Build anticipation.
- MAIN CONTENT: Break into clearly labeled sections (## Section Title). Use natural transitions like "Now here's where it gets interesting..." or "But wait —".
- Write conversationally — exactly how someone would speak on camera. Use contractions, rhetorical questions, short punchy sentences.
- Add stage directions in [BRACKETS] where useful: [B-ROLL: show chart], [PAUSE for effect], [CUT TO talking head].
- OUTRO: Recap the 2-3 biggest points. End with a CTA: like, subscribe, comment prompt.
- Target length: 800-1200 words (approximately 5-8 minutes of speaking time)."""
}

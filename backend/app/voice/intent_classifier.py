import json
from groq import AsyncGroq
from app.config import settings

_groq_client : AsyncGroq | None = None

def get_groq_client() -> AsyncGroq:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=settings.GROQ_API_KEY)
    return _groq_client

CLASSIFIER_SYSTEM_PROMPT = """
You are a call intent classifier. Your only job is to decide if the user 
wants to end the phone call or continue it.
 
Respond with ONLY a JSON object in this exact format, nothing else:
{"intent": "ENDING"}   ← user wants to end the call
{"intent": "CONTINUE"} ← user has more questions or is still talking
{"intent": "UNCLEAR"}  ← cannot determine
 
Signs of ENDING: "no", "that's all", "bye", "goodbye", "thank you bye",
"nothing else", "that's it", "no thanks", "nope", "I'm good", "thanks".
 
Signs of CONTINUE: asking a question, mentioning a fund name, asking about
SIP, returns, portfolio, investment, or any financial topic.
 
No explanation. No markdown. Only the JSON object.
""".strip()

async def classify_intent(user_transcript: str) -> str:
    """
    Takes the latest user transcript and returns intent string.
 
    Returns:
        "CONTINUE" — keep the conversation going
        "ENDING"   — user is done, trigger call end
        "UNCLEAR"  — couldn't tell, treated as CONTINUE by caller
 
    Example:
        intent = await classify_intent("no that's all thank you")
        # intent → "ENDING"
 
        intent = await classify_intent("what about my SBI fund?")
        # intent → "CONTINUE"
    """
    client = get_groq_client()

    try:
      response = await client.chat.completions.create(
          model = settings.GROQ_MODEL,
          messages=[
              {"role": "system", "content": CLASSIFIER_SYSTEM_PROMPT},
              {"role": "user",   "content": f"User said: {user_transcript}"},
          ],
          max_tokens=20,
          temperature=0.0,
          stream=False,
      )

      raw = response.choices[0].message.content.strip()

      parsed = json.loads(raw)
      intent = parsed.get("intent", "UNCLEAR").upper()

      if intent in ("CONTINUE", "ENDING", "UNCLEAR"):
          return intent
      return "UNCLEAR"
    
    except (json.JSONDecodeError, KeyError, Exception):
        return "UNCLEAR"
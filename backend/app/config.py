import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(
            f"Missing required enviroment variable: '{key}'."
            f"Check your .env file."
        )
    return value

class Settings:
    DATABASE_URL: str = _require("DATABASE_URL")

    GROQ_API_KEY: str  = _require("GROQ_API_KEY")
    GROQ_MODEL: str    = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
 
    # Speech to text (Deepgram)
    DEEPGRAM_API_KEY: str = _require("DEEPGRAM_API_KEY")
 
    # Text to speech (ElevenLabs)
    ELEVENLABS_API_KEY: str = _require("ELEVENLABS_API_KEY")
    ELEVENLABS_VOICE_ID: str = _require("ELEVENLABS_VOICE_ID")
 
    # Telephony (Twilio)
    TWILIO_ACCOUNT_SID: str   = _require("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: str    = _require("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER: str  = _require("TWILIO_PHONE_NUMBER")
    TWILIO_TWIML_APP_SID: str = _require("TWILIO_TWIML_APP_SID")
    TWILIO_API_KEY      : str = _require("TWILIO_API_KEY")
    TWILIO_API_SECRET   : str = _require("TWILIO_API_SECRET")
 
    
    PUBLIC_BASE_URL: str = _require("PUBLIC_BASE_URL")
 
    
    REDIS_URL: str = _require("REDIS_URL")
 
    
    ENV: str = os.environ.get("ENV", "development")
 
    @property
    def is_dev(self) -> bool:
        return self.ENV == "development"
 

settings = Settings()
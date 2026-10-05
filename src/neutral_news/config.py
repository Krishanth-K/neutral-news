import os
from dotenv import load_dotenv
load_dotenv(override=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/neutral_news"
)

GEMINI_API_KEY_POOL = os.getenv("GEMINI_API_KEY", "").split(',')

print("API key pool, ", GEMINI_API_KEY_POOL)

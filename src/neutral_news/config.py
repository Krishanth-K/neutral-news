import os
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/neutral_news"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

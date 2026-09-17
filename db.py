import os
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

# Explicitly find and load the .env file in the same folder
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Pass the exact variable names defined in your .env
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(f"Missing SUPABASE_URL or SUPABASE_KEY in .env file at {env_path}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
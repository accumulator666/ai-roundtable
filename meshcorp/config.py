import os

# Service URLs (internal Docker network)
ROUTER_URL = os.getenv("ROUTER_URL", "http://ai-mesh-router:8000")
CLAUDE_CODE_URL = os.getenv("CLAUDE_CODE_URL", "http://ai-mesh-claude-code:8000")
CREWAI_URL = os.getenv("AGENTS_URL", "http://ai-mesh-crewai:8000")

# Database
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "prompt-template-db")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ai_mesh")
POSTGRES_USER = os.getenv("POSTGRES_USER", "admin")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

# Concurrency
MODEL_SEMAPHORE_LIMIT = int(os.getenv("MODEL_CONCURRENCY", "8"))

# Notifications
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
PUSHOVER_USER_KEY = os.getenv("PUSHOVER_USER_KEY", "")
PUSHOVER_API_TOKEN = os.getenv("PUSHOVER_API_TOKEN", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")

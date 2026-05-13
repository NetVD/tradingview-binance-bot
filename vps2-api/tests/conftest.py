import os

# Provide test-time defaults so importing app.main does not blow up.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/9")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "SUPABASE_JWT_JWKS_URL",
    "https://test.supabase.co/auth/v1/.well-known/jwks.json",
)
os.environ.setdefault("SUPABASE_JWT_ISSUER", "https://test.supabase.co/auth/v1")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("NOTIFY_FN_URL", "https://test.functions.supabase.co/notify-subscribers")
os.environ.setdefault("VPS1_BASE_URL", "https://dashboard.test.local")
os.environ.setdefault("SERVICE_TOKEN", "x" * 32)

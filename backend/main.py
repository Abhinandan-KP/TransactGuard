# Entry-point shim for Render / other hosts that run:
#   uvicorn main:app --host 0.0.0.0 --port $PORT
# The real application lives in app/main.py.
from app.main import app  # noqa: F401

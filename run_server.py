"""Convenient launcher for BusMate AI Web & API server."""

import sys
import uvicorn
from src.config import APP_HOST, APP_PORT

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000

    print("\n" + "=" * 60)
    print("  🚌 BusMate AI — Hyderabad City Bus Route Assistant")
    print("=" * 60)
    print(f"\n  Web App & API URL:")
    print(f"  👉 http://127.0.0.1:{port}")
    print(f"  👉 http://localhost:{port}")
    print(f"\n  API Docs (Swagger UI):")
    print(f"  👉 http://127.0.0.1:{port}/docs")
    print("\n  Press Ctrl+C to stop the server.\n" + "=" * 60 + "\n")

    uvicorn.run("src.api:app", host=host, port=port, reload=True)

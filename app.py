"""
Legacy entry point.

Project ini sudah pindah ke FastAPI di `main.py`. File ini dipertahankan agar
perintah lama `python app.py` tetap berjalan tanpa memecah arsitektur backend.
"""

import uvicorn

from main import app


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5000,
        reload=True,
        log_level="info",
    )

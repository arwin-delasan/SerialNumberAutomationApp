import multiprocessing
import sys
import uvicorn
from web_app.app import app  # explicit import so PyInstaller bundles web_app

if __name__ == "__main__":
    multiprocessing.freeze_support()  # required on Windows when frozen by PyInstaller
    no_console = getattr(sys, "frozen", False) and sys.stdout is None
    extras = {"log_config": None} if no_console else {}
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False, **extras)

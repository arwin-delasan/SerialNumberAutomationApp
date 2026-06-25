import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "serial_exporter"))

import uvicorn

if __name__ == "__main__":
    uvicorn.run("web_app.app:app", host="0.0.0.0", port=8000, reload=True)

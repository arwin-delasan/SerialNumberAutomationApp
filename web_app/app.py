import os
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from web_app.routers import dashboard, sessions, export, serials

app = FastAPI(title="Serial Management")

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(export.router)
app.include_router(serials.router)

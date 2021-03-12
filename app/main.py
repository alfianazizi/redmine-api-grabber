from functools import lru_cache
from typing import Optional, List

from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect

from jose import JWTError, jwt

from redminelib import Redmine

from apscheduler.schedulers.background import BackgroundScheduler

import mysql.connector

from app import config

import logging
import random 

@lru_cache()
def get_settings():
    return config.Settings()

redmine = Redmine(get_settings().redmine_url, key=get_settings().redmine_api_token)

app = FastAPI(title="Redmine API Grabber", root_path=get_settings().root_path)

mysql.connector.connect(
    host=get_settings().redmine_db_host,
    user=get_settings().redmine_db_user,
    password=get_settings().redmine_db_password,
    database=get_settings().redmine_db_name,
    pool_name="redmine",
    pool_size=10,
)

mysql.connector.connect(
    host=get_settings().portal_db_host,
    user=get_settings().portal_db_user,
    password=get_settings().portal_db_password,
    database=get_settings().portal_db_name,
    pool_name="portal",
    pool_size=10,
)


def sql_connection(pool_name):
    """Get a connection and a cursor from the pool"""
    db = mysql.connector.connect(pool_name=pool_name)
    return db


Schedule = None


from .routers import admin, issues, projects, users
from .services import scheduler
from app.dependencies import get_token_header


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def send_json(self, message: dict, websocket: WebSocket):
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)

@app.on_event("startup")
async def load_schedule_or_create_blank():
    """
    Instatialise the Schedule Object as a Global Param and also load existing Schedules from SQLite
    This allows for persistent schedules across server restarts.
    """
    global Schedule
    try:
        Schedule = BackgroundScheduler()
        Schedule.add_job(
            scheduler.insert_issues_statuses, "cron", hour="*/1", id="issues"
        )
        Schedule.start()
        print("Created Schedule Object")
    except:
        print("Unable to Create Schedule Object")


@app.on_event("shutdown")
async def pickle_schedule():
    """
    An Attempt at Shutting down the schedule to avoid orphan jobs
    """
    global Schedule
    Schedule.shutdown()
    print("Disabled Schedule")

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    print("Accepting client connection...")
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            response = {"value": "Testing Data WS " + str(random.uniform(0, 1))}
            await manager.broadcast(response)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(f"Client left server")
    print("Bye..")

origins = [
    "http://localhost",
    "http://localhost:8080",
    "http://localhost:5000",
    "http://highlight.kirei.co.id",
    "https://highlight.kirei.co.id",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    admin.router,
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_token_header)],
)
app.include_router(
    issues.router,
    prefix="/issues",
    tags=["issues"],
    dependencies=[Depends(get_token_header)],
)
app.include_router(
    projects.router,
    prefix="/projects",
    tags=["projects"],
    dependencies=[Depends(get_token_header)],
)
app.include_router(
    users.router,
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(get_token_header)],
)

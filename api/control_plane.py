from fastapi import APIRouter, WebSocket
from pydantic import BaseModel
import psycopg2
from typing import List

router = APIRouter()

class Limit(BaseModel):
    id: int
    value: int

class AutonomyThreshold(BaseModel):
    id: int
    threshold: float

class Compliance(BaseModel):
    id: int
    status: bool

class ValuationMatrix(BaseModel):
    id: int
    matrix: List[List[float]]

@router.get('/limits/')
def read_limits():
    conn = psycopg2.connect(
        database="hyperion_engine_v12",
        user="your_username",
        password="your_password",
        host="your_host",
        port="your_port"
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM limits")
    limits = cur.fetchall()
    conn.close()
    return limits

@router.get('/autonomy_thresholds/')
def read_autonomy_thresholds():
    conn = psycopg2.connect(
        database="hyperion_engine_v12",
        user="your_username",
        password="your_password",
        host="your_host",
        port="your_port"
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM autonomy_thresholds")
    autonomy_thresholds = cur.fetchall()
    conn.close()
    return autonomy_thresholds

@router.get('/compliance/')
def read_compliance():
    conn = psycopg2.connect(
        database="hyperion_engine_v12",
        user="your_username",
        password="your_password",
        host="your_host",
        port="your_port"
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM compliance")
    compliance = cur.fetchall()
    conn.close()
    return compliance

@router.get('/valuation_matrix/')
def read_valuation_matrix():
    conn = psycopg2.connect(
        database="hyperion_engine_v12",
        user="your_username",
        password="your_password",
        host="your_host",
        port="your_port"
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM valuation_matrix")
    valuation_matrix = cur.fetchall()
    conn.close()
    return valuation_matrix

@router.websocket('/ws/limits/')
def websocket_limits(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # Handle incoming message
        await websocket.send_text("Message received")

@router.websocket('/ws/autonomy_thresholds/')
def websocket_autonomy_thresholds(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # Handle incoming message
        await websocket.send_text("Message received")

@router.websocket('/ws/compliance/')
def websocket_compliance(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # Handle incoming message
        await websocket.send_text("Message received")

@router.websocket('/ws/valuation_matrix/')
def websocket_valuation_matrix(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        # Handle incoming message
        await websocket.send_text("Message received")
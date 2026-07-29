from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("BUTLER_DB_PATH", ROOT / "butler.db"))
GATEWAY_BASE_URL = os.getenv("BUTLER_GATEWAY_BASE_URL", "http://127.0.0.1:8317").rstrip("/")
GATEWAY_API_KEY = os.getenv("BUTLER_GATEWAY_API_KEY", "")
PRIMARY_MODEL = os.getenv("BUTLER_PRIMARY_MODEL", "")
REVIEW_MODEL = os.getenv("BUTLER_REVIEW_MODEL", "")
JUDGE_MODEL = os.getenv("BUTLER_JUDGE_MODEL", "")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=50000)
    mode: Literal["fast", "verified"] = "fast"


class GatewayClient:
    def __init__(self) -> None:
        headers = {"Content-Type": "application/json"}
        if GATEWAY_API_KEY:
            headers["Authorization"] = f"Bearer {GATEWAY_API_KEY}"
        self.client = httpx.AsyncClient(base_url=GATEWAY_BASE_URL, headers=headers, timeout=180.0)

    async def close(self) -> None:
        await self.client.aclose()

    async def list_models(self) -> list[str]:
        response = await self.client.get("/v1/models")
        response.raise_for_status()
        payload = response.json()
        models = payload.get("data", []) if isinstance(payload, dict) else []
        return [str(item.get("id")) for item in models if isinstance(item, dict) and item.get("id")]

    async def chat(self, model: str, messages: list[dict[str, str]]) -> str:
        response = await self.client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": messages, "temperature": 0.2},
        )
        response.raise_for_status()
        payload = response.json()
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected gateway response: {json.dumps(payload)[:1000]}") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id)
            );
            """
        )


def choose_models(models: list[str]) -> tuple[str, str, str]:
    if not models:
        raise RuntimeError("Gateway returned no models")

    def pick(preferred: str, keywords: tuple[str, ...], excluded: set[str]) -> str:
        if preferred and preferred in models and preferred not in excluded:
            return preferred
        for model in models:
            lowered = model.lower()
            if model not in excluded and any(keyword in lowered for keyword in keywords):
                return model
        for model in models:
            if model not in excluded:
                return model
        return models[0]

    primary = pick(PRIMARY_MODEL, ("gemini", "gpt", "claude"), set())
    reviewer = pick(REVIEW_MODEL, ("claude", "gemini", "gpt"), {primary})
    judge = pick(JUDGE_MODEL, ("gpt", "claude", "gemini"), {primary, reviewer})
    return primary, reviewer, judge


def save_message(project_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
    with connect_db() as db:
        db.execute(
            "INSERT INTO messages(id, project_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), project_id, role, content, json.dumps(metadata or {}), utc_now()),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    app.state.gateway = GatewayClient()
    yield
    await app.state.gateway.close()


app = FastAPI(title="Butler MVP", version="0.1.0", lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "gateway": GATEWAY_BASE_URL, "database": str(DB_PATH)}


@app.get("/api/models")
async def models() -> dict[str, Any]:
    try:
        available = await app.state.gateway.list_models()
        selected = choose_models(available)
        return {"models": available, "selected": {"primary": selected[0], "reviewer": selected[1], "judge": selected[2]}}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    with connect_db() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project = {"id": str(uuid.uuid4()), "name": payload.name.strip(), "description": payload.description.strip(), "created_at": utc_now()}
    with connect_db() as db:
        db.execute(
            "INSERT INTO projects(id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (project["id"], project["name"], project["description"], project["created_at"]),
        )
    return project


@app.get("/api/projects/{project_id}/messages")
def list_messages(project_id: str) -> list[dict[str, Any]]:
    with connect_db() as db:
        project = db.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        rows = db.execute("SELECT * FROM messages WHERE project_id = ? ORDER BY created_at", (project_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        result.append(item)
    return result


@app.post("/api/projects/{project_id}/chat")
async def chat(project_id: str, payload: ChatRequest) -> dict[str, Any]:
    with connect_db() as db:
        project = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    save_message(project_id, "user", payload.message, {"mode": payload.mode})
    try:
        available = await app.state.gateway.list_models()
        primary, reviewer, judge = choose_models(available)
        project_context = f"Project: {project['name']}\nDescription: {project['description']}"
        base_messages = [
            {"role": "system", "content": "You are the primary assistant in a project-scoped AI workbench. Be practical, explicit about uncertainty, and produce usable output."},
            {"role": "user", "content": f"{project_context}\n\nUser request:\n{payload.message}"},
        ]
        primary_answer = await app.state.gateway.chat(primary, base_messages)

        if payload.mode == "fast":
            final_answer = primary_answer
            metadata = {"mode": "fast", "primary_model": primary}
        else:
            reviewer_answer = await app.state.gateway.chat(
                reviewer,
                [
                    {"role": "system", "content": "Independently solve the user's request. Do not assume another model's answer is correct. Identify risks, missing information, and verification steps."},
                    {"role": "user", "content": f"{project_context}\n\nUser request:\n{payload.message}"},
                ],
            )
            final_answer = await app.state.gateway.chat(
                judge,
                [
                    {"role": "system", "content": "Act as a strict synthesis judge. Compare two independent answers, resolve disagreements using evidence and logic, preserve uncertainty, and return one deliverable answer."},
                    {"role": "user", "content": f"User request:\n{payload.message}\n\nPrimary answer ({primary}):\n{primary_answer}\n\nIndependent review ({reviewer}):\n{reviewer_answer}"},
                ],
            )
            metadata = {"mode": "verified", "primary_model": primary, "review_model": reviewer, "judge_model": judge}

        save_message(project_id, "assistant", final_answer, metadata)
        return {"answer": final_answer, "metadata": metadata}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Gateway request failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Butler MVP</title>
<style>body{font-family:system-ui;margin:0;background:#f5f5f5;color:#171717}main{max-width:980px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:260px 1fr;gap:16px}.card{background:white;border:1px solid #ddd;border-radius:12px;padding:16px}.projects button{display:block;width:100%;text-align:left;margin:6px 0;padding:10px}.messages{min-height:420px;max-height:60vh;overflow:auto}.msg{padding:10px 12px;margin:8px 0;border-radius:10px;white-space:pre-wrap}.user{background:#e8eefc}.assistant{background:#eee}textarea,input,select{width:100%;box-sizing:border-box;padding:10px;margin:6px 0}button{padding:9px 12px;cursor:pointer}.row{display:flex;gap:8px}.row>*{flex:1}@media(max-width:760px){.grid{grid-template-columns:1fr}}</style></head>
<body><main><h1>Agent Butler</h1><div class="grid"><section class="card projects"><h3>Projects</h3><input id="projectName" placeholder="New project name"><button onclick="createProject()">Create project</button><div id="projects"></div></section><section class="card"><h3 id="title">Select a project</h3><div id="messages" class="messages"></div><textarea id="message" rows="4" placeholder="Tell Butler what to do..."></textarea><div class="row"><select id="mode"><option value="fast">Fast</option><option value="verified">Verified</option></select><button onclick="sendMessage()">Send</button></div></section></div></main>
<script>let current=null;async function api(path,opt={}){const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opt});if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json()}async function loadProjects(){const ps=await api('/api/projects');const el=document.getElementById('projects');el.innerHTML='';ps.forEach(p=>{const b=document.createElement('button');b.textContent=p.name;b.onclick=()=>selectProject(p);el.appendChild(b)})}async function createProject(){const name=document.getElementById('projectName').value.trim();if(!name)return;const p=await api('/api/projects',{method:'POST',body:JSON.stringify({name,description:''})});document.getElementById('projectName').value='';await loadProjects();selectProject(p)}async function selectProject(p){current=p;document.getElementById('title').textContent=p.name;await loadMessages()}async function loadMessages(){if(!current)return;const ms=await api(`/api/projects/${current.id}/messages`);const el=document.getElementById('messages');el.innerHTML='';ms.forEach(m=>{const d=document.createElement('div');d.className='msg '+m.role;d.textContent=m.content;el.appendChild(d)});el.scrollTop=el.scrollHeight}async function sendMessage(){if(!current)return alert('Select a project');const box=document.getElementById('message');const message=box.value.trim();if(!message)return;box.value='';const el=document.getElementById('messages');el.innerHTML+=`<div class="msg user"></div>`;el.lastChild.textContent=message;el.innerHTML+=`<div class="msg assistant">Working...</div>`;try{await api(`/api/projects/${current.id}/chat`,{method:'POST',body:JSON.stringify({message,mode:document.getElementById('mode').value})});await loadMessages()}catch(e){el.lastChild.textContent='Error: '+e.message}}loadProjects();</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8318, reload=False)

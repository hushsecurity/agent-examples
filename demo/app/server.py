"""The demo's web app: chat with an agent whose tools come through the Hush AI
gateway, as itself or for you, and watch what the gateway sees and does.

    uvicorn server:app --port 8765
"""

import base64
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import boto3
import botocore.exceptions
import openai
from botocore.config import Config
import httpx
from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
AGENTCORE_RUNTIME_ARN = os.environ["AGENTCORE_RUNTIME_ARN"]
AGENTCORE_RESOURCE = os.environ["AGENTCORE_RESOURCE"]  # what users sign in for (Terraform output)
FOUNDRY_PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
API_KEY = (os.environ["HUSH_API_KEY_ID"], os.environ["HUSH_API_KEY_SECRET"])  # for the activity log
PORT = int(os.getenv("DEMO_PORT", "8765"))
REDIRECT_URI = f"http://localhost:{PORT}/callback"
DEMO_APPS = ("custom-deepwiki-demo", "hushsecurity")

# The gateway's authorization server, found the standard MCP way.
_base = GATEWAY_URL.removesuffix("/mcp")
ISSUER = httpx.get(f"{_base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()["authorization_servers"][0]
OAUTH = httpx.get(f"{ISSUER}/.well-known/oauth-authorization-server").raise_for_status().json()
HUSH_API = "https://" + urlsplit(ISSUER).netloc
DEPLOYMENT_ID = ISSUER.rstrip("/").split("/")[-2]

# A turn can take minutes, and retrying one would run its tool calls twice.
agentcore = boto3.client("bedrock-agentcore", region_name=AGENTCORE_RUNTIME_ARN.split(":")[3],
                         config=Config(read_timeout=600, retries={"max_attempts": 1}))
foundry = AIProjectClient(endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=DefaultAzureCredential())
foundry_openai = foundry.get_openai_client()

app = FastAPI()
store = {"tokens": None, "pending": {}, "client_id": None, "chats": {}, "api_token": (None, 0.0)}


def claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


# --- Signing the user in to Hush, for the AgentCore agent to act for them ---


def client_id() -> str:
    """This app's OAuth client, registered once (dynamic client registration)."""
    if not store["client_id"]:
        resp = httpx.post(OAUTH["registration_endpoint"], json={
            "client_name": "Hush gateway demo", "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none"})
        store["client_id"] = resp.raise_for_status().json()["client_id"]
    return store["client_id"]


def user_token() -> str:
    """The signed-in user's Hush token. It lasts a few minutes, so it's
    refreshed early enough to last the agent's whole turn."""
    tokens = store["tokens"]
    if not tokens:
        raise HTTPException(401, "Sign in first")
    if time.time() > tokens["expires_at"] - 240:
        resp = httpx.post(OAUTH["token_endpoint"], data={
            "grant_type": "refresh_token", "refresh_token": tokens["refresh"], "client_id": client_id()})
        if resp.status_code != 200:
            store["tokens"] = None
            raise HTTPException(401, "Your session expired: sign in again")
        save_tokens(resp.json())
    return store["tokens"]["access"]


def save_tokens(body: dict):
    previous = store["tokens"] or {}
    store["tokens"] = {
        "access": body["access_token"],
        "refresh": body.get("refresh_token") or previous.get("refresh"),
        "expires_at": time.time() + body["expires_in"],
    }


@app.get("/login")
def login():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    login_state = secrets.token_urlsafe(16)
    store["pending"][login_state] = verifier
    query = urlencode({
        "response_type": "code", "client_id": client_id(), "redirect_uri": REDIRECT_URI,
        "state": login_state, "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": AGENTCORE_RESOURCE,  # the token is for the AgentCore agent to act for you
    })
    return RedirectResponse(f"{OAUTH['authorization_endpoint']}?{query}")


@app.get("/callback")
def callback(state: str = "", code: str = "", error: str = "", error_description: str = ""):
    verifier = store["pending"].pop(state, None)
    if error or not code:
        raise HTTPException(400, f"Sign-in failed: {error_description or error or 'no code'}")
    if not verifier:
        raise HTTPException(400, "Unknown sign-in: try again")
    resp = httpx.post(OAUTH["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier, "client_id": client_id()})
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, resp.text)
    save_tokens(resp.json())
    return RedirectResponse("/")


@app.get("/api/me")
def me():
    if not store["tokens"]:
        return {"signed_in": False}
    user = claims(user_token())
    return {"signed_in": True, "email": user.get("email"), "name": user.get("name")}


@app.post("/api/logout")
def logout():
    store["tokens"] = None
    store["chats"] = {}  # the next person starts fresh
    return {}


# --- Chatting with the agents ---


class ChatIn(BaseModel):
    backend: str  # agentcore | foundry
    mode: str  # agent (as itself) | user (for me)
    message: str


def chat_agentcore(mode: str, message: str, chat: dict) -> dict:
    payload = {"prompt": message}
    if mode == "user":
        payload["user_token"] = user_token()
    try:
        resp = agentcore.invoke_agent_runtime(
            agentRuntimeArn=AGENTCORE_RUNTIME_ARN, runtimeSessionId=chat["id"],
            payload=json.dumps(payload).encode(), contentType="application/json", accept="application/json")
    except botocore.exceptions.ClientError as e:
        # E.g. expired AWS credentials: the app needs ones that can invoke the runtime.
        raise HTTPException(502, f"AgentCore: {e.response['Error'].get('Message', e)}")
    except botocore.exceptions.BotoCoreError as e:
        raise HTTPException(502, f"AgentCore: {e}")
    return json.loads(resp["response"].read())


def chat_foundry(mode: str, message: str, chat: dict) -> dict:
    agent = "hush-demo-for-user" if mode == "user" else "hush-demo-as-agent"
    # A failed turn leaves nothing in Foundry's history: carry it into this one.
    sent = message
    if dropped := chat.get("dropped"):
        sent = f'(My previous message, "{dropped[0]}", failed: {dropped[1]})\n\n{message}'
    try:
        reply = foundry_openai.responses.create(
            input=sent,
            extra_body={"agent_reference": {"name": agent, "type": "agent_reference"}},
            **({"previous_response_id": chat["previous"]} if chat.get("previous") else {}),
        )
    except openai.APIStatusError as e:
        # Foundry fails the whole turn when a tool call fails, even when the
        # gateway asks for the user's consent: then ask the agent to request it.
        detail = ((e.body or {}).get("message") if isinstance(e.body, dict) else None) or str(e)
        if (consent := re.search(r'Tool "([^"]+)" on "([^"]+)" requires the user\'s consent', detail)) and "consent" not in chat:
            chat["consent"] = True
            try:
                return chat_foundry(mode, f'The gateway needs my consent for {consent[1]} on {consent[2]}: '
                                          f'request it and give me the link. Then I\'ll ask you to retry: "{message}"', chat)
            finally:
                chat.pop("consent")
        # The gateway's message, without Foundry's wrapping and the model-only guidance.
        detail = re.sub(r"^An error occurred invoking '[^']*': |\s*Troubleshooting guide: \S+$", "", detail)
        if "BLOCKED BY HUSH GATEWAY" in detail:
            detail = detail.split("Policy notice from")[0].strip()
        elif "401 (Unauthorized)" in detail:
            # The gateway reads consent from the token, and Foundry doesn't refresh it on a 401.
            detail = ("The gateway needs a fresh token, e.g. after an approval. Foundry gets one "
                      "when its token expires, within about 5 minutes: try again then.")
        chat["dropped"] = (message, detail.splitlines()[-1][:300])
        return {"text": detail, "trace": [], "identity": None}
    chat.pop("dropped", None)
    chat["previous"] = reply.id
    out = {"text": reply.output_text or "", "trace": [], "identity": None}
    for item in reply.output:
        if item.type == "oauth_consent_request":
            # Foundry signs the user in to the gateway once, through this link.
            out["sign_in"] = item.consent_link
        elif item.type == "mcp_call":
            args = json.loads(item.arguments or "{}")
            name = args.get("name", item.name) if item.name == "hush_call_tool" else item.name
            out["trace"].append({
                "tool": name, "input": args.get("arguments", args) if item.name == "hush_call_tool" else args,
                "status": "error" if item.error else "success", "output": str(item.output or item.error or "")[:500]})
    out["identity"] = {"as": "user", "via": "Foundry"} if mode == "user" else {"as": "agent", "subject": "the Foundry agent's identity"}
    return out


@app.post("/api/foundry/connect")
def foundry_connect():
    """Whether Foundry has signed you in to the gateway yet, and if not, its
    sign-in link: a first call to the "for you" agent tells."""
    try:
        reply = foundry_openai.responses.create(
            input="Call hush_list_apps.", tool_choice="required",
            extra_body={"agent_reference": {"name": "hush-demo-for-user", "type": "agent_reference"}},
        )
    except openai.APIStatusError as e:
        raise HTTPException(502, f"Foundry: {e}")
    link = next((i.consent_link for i in reply.output if i.type == "oauth_consent_request"), None)
    return {"connected": link is None, "link": link}


@app.post("/api/chat")
def chat(body: ChatIn):
    key = f"{body.backend}:{body.mode}"
    conversation = store["chats"].setdefault(key, {"id": str(uuid.uuid4())})
    started = time.time()
    if body.backend == "agentcore":
        out = chat_agentcore(body.mode, body.message, conversation)
    else:
        out = chat_foundry(body.mode, body.message, conversation)
    out["seconds"] = round(time.time() - started, 1)
    return out


@app.post("/api/reset")
def reset():
    store["chats"] = {}
    return {}


# --- The gateway's activity log ---


def api_token() -> str:
    token, expires_at = store["api_token"]
    if time.time() > expires_at - 60:
        resp = httpx.post(f"{HUSH_API}/v1/oauth/token", auth=API_KEY, data={"grant_type": "client_credentials"})
        body = resp.raise_for_status().json()
        token, expires_at = body["access_token"], time.time() + body.get("expires_in", 300)
        store["api_token"] = (token, expires_at)
    return token


@app.get("/api/activity")
def activity():
    resp = httpx.post(f"{HUSH_API}/v1/applications/activity", json={"page_size": 200},
                      headers={"Authorization": f"Bearer {api_token()}"})
    events = []
    for e in resp.raise_for_status().json().get("items", []):
        if e.get("deployment_id") != DEPLOYMENT_ID or e.get("app_name") not in DEMO_APPS:
            continue
        user = e.get("user") or {}
        events.append({
            "time": e["event_time"], "app": e["app_name"], "tool": e["tool"],
            "action": e["action"], "reason": e.get("reason"),
            "who": user.get("user_email") or user.get("user_name"), "agent_id": e.get("agent_id")})
    return events[:20]


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")

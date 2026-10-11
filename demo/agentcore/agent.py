"""The demo's AgentCore agent: an LLM agent whose tools come through the Hush
AI gateway, as itself or for the user signed in to the demo.

It answers with what the demo shows: the reply, the tool calls it made through
the gateway, and the identity the gateway saw.
"""

import base64
import functools
import json
import os
import threading
import time

import boto3
import httpx
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
REGION = os.environ["AWS_REGION"]
MODEL_ID = os.environ["MODEL_ID"]

SYSTEM_PROMPT = """Your tools come through the Hush gateway. hush_list_apps
shows the apps you can use: call it first, and use the app names it gives
exactly. Find an app's tools with hush_search_tools and run them with
hush_call_tool.
- If an app the user needs is disconnected, call hush_connect and give the
  user the link exactly as returned.
- If a tool needs the user's consent, call hush_user_consent_methods, request
  it with hush_request_user_consent (if there's one method, use it without
  asking), and tell the user how to approve (give a
  link exactly as returned). When they say they approved, call hush_reauth and
  retry.
- Don't ask the user to confirm an action: call the tool. The gateway asks
  the user for consent itself when an action needs it.
- If a call is blocked, say so and why.
Keep answers short."""


@functools.cache  # once, on first use
def discover() -> tuple[str, str]:
    """The gateway's issuer and Hush's token endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return issuer, metadata["token_endpoint"]


sts = boto3.client("sts", region_name=REGION, endpoint_url=f"https://sts.{REGION}.amazonaws.com")


def aws_token() -> tuple[str, int]:
    """An AWS-signed token for the runtime's role, issued for the gateway."""
    resp = sts.get_web_identity_token(Audience=[discover()[0]], SigningAlgorithm="RS256", DurationSeconds=300)
    return resp["WebIdentityToken"], 300


def hush_token_for(user_token: str) -> tuple[str, int]:
    """A Hush token for the agent acting for the user (RFC 8693 exchange)."""
    resp = httpx.post(
        discover()[1],
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": user_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": aws_token()[0],
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Hush refused ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    return body["access_token"], body["expires_in"]


def claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class Bearer(httpx.Auth):
    """Sends the token `get_token` returns, getting a new one before it expires."""

    def __init__(self, get_token):
        self.get_token = get_token
        self.token, self.expires_at = None, 0.0

    def current(self) -> str:
        if time.time() > self.expires_at - 60:
            self.token, expires_in = self.get_token()
            self.expires_at = time.time() + expires_in
        return self.token

    def auth_flow(self, request):
        request.headers["Authorization"] = f"Bearer {self.current()}"
        response = yield request
        if response.status_code == 401:  # e.g. hush_reauth: get a fresh token, once
            self.expires_at = 0.0
            request.headers["Authorization"] = f"Bearer {self.current()}"
            yield request


def identity(token: str) -> dict:
    """What the gateway sees: the agent alone, or a user with the agent acting."""
    c = claims(token)
    if c.get("act"):  # a Hush token naming a user, and the agent acting for them
        return {"as": "user", "user": c.get("email") or c.get("name") or c["sub"], "agent": c["act"].get("sub")}
    return {"as": "agent", "subject": c.get("sub")}


def trace(messages: list) -> list[dict]:
    """The tool calls in `messages`, with their results."""
    calls, results = [], {}
    for message in messages:
        for block in message.get("content", []):
            if use := block.get("toolUse"):
                calls.append(use)
            elif result := block.get("toolResult"):
                results[result["toolUseId"]] = result
    out = []
    for use in calls:
        name, args = use["name"], use.get("input") or {}
        if name.endswith("hush_call_tool"):
            name, args = args.get("name", name), args.get("arguments") or {}
        result = results.get(use["toolUseId"], {})
        text = " ".join(c.get("text", "") for c in result.get("content", []) if "text" in c)
        out.append({"tool": name, "input": args, "status": result.get("status"), "output": text[:500]})
    return out


app = BedrockAgentCoreApp()
_sessions: dict[str, dict] = {}
_lock = threading.Lock()


def session(session_id: str, user_token: str | None) -> dict:
    """One agent, gateway connection and token per chat session and mode."""
    key = f"{session_id}:{'user' if user_token else 'agent'}"
    with _lock:
        s = _sessions.get(key)
        if s is not None:
            s["user_token"] = user_token  # the demo passes a fresh one each turn
            if user_token:
                s["auth"].expires_at = 0.0  # exchange it again with the fresh one
            return s
        s = {"user_token": user_token}
        s["auth"] = Bearer(lambda: hush_token_for(s["user_token"])) if user_token else Bearer(aws_token)
        s["gateway"] = MCPClient(url=GATEWAY_URL, auth_provider=s["auth"])
        s["gateway"].start()
        s["agent"] = Agent(
            model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
            tools=s["gateway"].list_tools_sync(),
            system_prompt=SYSTEM_PROMPT,
            callback_handler=None,
        )
        _sessions[key] = s  # only once it works
        return s


@app.entrypoint
def invoke(payload, context):
    s = session(context.session_id or "default", payload.get("user_token"))
    agent = s["agent"]
    before = len(agent.messages)
    reply = agent(payload.get("prompt") or "Which apps can you use?")
    return {
        "text": str(reply),
        "trace": trace(agent.messages[before:]),
        "identity": identity(s["auth"].current()),
    }


if __name__ == "__main__":
    app.run()

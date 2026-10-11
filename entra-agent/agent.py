"""An Entra agent calling the Hush AI gateway with its Entra token.

The agent gets a token for the gateway's API from Entra and sends it as is, as
the Bearer: the gateway exchanges it with Hush for the agent.

    python agent.py            the agent acts as itself
    python agent.py --as-user  the agent acts for the signed-in user

Standard library only. Needs the Azure CLI for --as-user (see user_token).
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

TENANT_ID = os.environ["ENTRA_TENANT_ID"]
BLUEPRINT_ID = os.environ["ENTRA_BLUEPRINT_ID"]  # the agent's blueprint (app id)
BLUEPRINT_SECRET = os.environ["ENTRA_BLUEPRINT_SECRET"]
AGENT_ID = os.environ["ENTRA_AGENT_ID"]  # the agent identity (app id)
GATEWAY_API_ID = os.environ["ENTRA_GATEWAY_API_ID"]  # the gateway's API (app id)
GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"


def entra(form: dict) -> str:
    """Requests a token from Entra."""
    req = urllib.request.Request(TOKEN_URL, urllib.parse.urlencode(form).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Entra refused ({e.code}): {e.read().decode()[:500]}")


def blueprint_token() -> str:
    """The blueprint vouching for its agent identity. An agent identity has no
    credential of its own: its blueprint signs in for it (fmi_path)."""
    return entra(
        {
            "grant_type": "client_credentials",
            "client_id": BLUEPRINT_ID,
            "client_secret": BLUEPRINT_SECRET,
            "scope": "api://AzureADTokenExchange/.default",
            "fmi_path": AGENT_ID,
        }
    )


def agent_token() -> str:
    """A token for the gateway, as the agent itself."""
    return entra(
        {
            "grant_type": "client_credentials",
            "client_id": AGENT_ID,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": blueprint_token(),
            "scope": f"api://{GATEWAY_API_ID}/.default",
        }
    )


def agent_token_for_user(user_token: str) -> str:
    """A token for the gateway, as the agent acting for the user of
    `user_token` (on-behalf-of): it names both the user and the agent."""
    return entra(
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "requested_token_use": "on_behalf_of",
            "client_id": AGENT_ID,
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": blueprint_token(),
            "assertion": user_token,
            "scope": f"api://{GATEWAY_API_ID}/gateway.access",
        }
    )


def user_token() -> str:
    """The signed-in user's token for the agent. In an app, it's the token your
    front end got when the user signed in; here, the Azure CLI's user."""
    az = shutil.which("az") or "az"  # az.cmd on Windows
    out = subprocess.run(
        [az, "account", "get-access-token", "--tenant", TENANT_ID,
         "--scope", f"api://{BLUEPRINT_ID}/access_as_user",
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if out.returncode:
        sys.exit(f"az failed: {out.stderr.strip()}")
    return out.stdout.strip()


class Gateway:
    """A minimal MCP client over streamable HTTP. `token` returns the Bearer
    to send; it's called on every request, so it can hand out a fresh one."""

    def __init__(self, url: str, token):
        self.url = url
        self.token = token
        self.session_id = None
        self.next_id = 1

    def _post(self, message: dict):
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, json.dumps(message).encode(), headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.session_id = resp.headers.get("Mcp-Session-Id", self.session_id)
                body = resp.read().decode()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            sys.exit(
                f"{e.code} from the gateway: {e.read().decode()[:300]}\n"
                f"www-authenticate: {e.headers.get('www-authenticate')}"
            )
        if not body:
            return None
        if ctype.startswith("text/event-stream"):
            # The response may follow notifications: pick it by its id.
            events = [
                json.loads(line[5:])
                for line in body.splitlines()
                if line.startswith("data:")
            ]
            return next(e for e in events if e.get("id") == message.get("id"))
        return json.loads(body)

    def request(self, method: str, params: dict | None = None) -> dict:
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        self.next_id += 1
        if params is not None:
            msg["params"] = params
        resp = self._post(msg)
        if "error" in resp:
            sys.exit(f"{method} failed: {resp['error']}")
        return resp["result"]

    def connect(self, client_name: str) -> dict:
        info = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return info

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})


def main():
    if "--as-user" in sys.argv:
        token = agent_token_for_user(user_token())
    else:
        token = agent_token()

    # Entra tokens last about an hour: a long-running agent gets a new one
    # before then.
    gw = Gateway(GATEWAY_URL, lambda: token)
    info = gw.connect("entra-agent-example")
    print("connected to", info["serverInfo"]["name"])

    tools = gw.request("tools/list")["tools"]
    print("tools:", ", ".join(t["name"] for t in tools))

    # The apps this agent (or, with --as-user, this user through this agent)
    # was granted. Connect one with hush_connect, then find and run its tools
    # with hush_search_tools and hush_call_tool.
    apps = gw.call_tool("hush_list_apps")
    print("apps:", json.dumps(apps.get("structuredContent", apps), indent=2))


if __name__ == "__main__":
    main()

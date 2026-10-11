"""A Kubernetes agent exchanging its service-account token for a Hush token.

The agent signs in to Hush itself (OAuth client credentials, with its
service-account token as the client assertion) and calls the Hush AI gateway
with the Hush token it gets back. It renews the token before it expires.
Standard library only, so it runs on a stock python image.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
TOKEN_FILE = os.environ.get("HUSH_TOKEN_FILE", "/var/run/secrets/hush/token")


def service_account_token() -> str:
    # The kubelet rotates the token: read it every time, never cache it.
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def token_endpoint() -> str:
    """Hush's token endpoint, found the standard MCP way: the gateway names
    its authorization server, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    issuer = get_json(f"{base}/.well-known/oauth-protected-resource/mcp")[
        "authorization_servers"
    ][0]
    return get_json(f"{issuer}/.well-known/oauth-authorization-server")["token_endpoint"]


class HushToken:
    """The agent's Hush token for the gateway, renewed a minute before it
    expires. Call it to get the current token."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint
        self.token = None
        self.expires_at = 0.0

    def __call__(self) -> str:
        if time.time() > self.expires_at - 60:
            self.token, expires_in = self._exchange()
            self.expires_at = time.time() + expires_in
        return self.token

    def _exchange(self) -> tuple[str, int]:
        form = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": service_account_token(),
        }
        req = urllib.request.Request(self.endpoint, urllib.parse.urlencode(form).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out = json.load(resp)
        except urllib.error.HTTPError as e:
            sys.exit(f"Hush refused ({e.code}): {e.read().decode()[:300]}")
        return out["access_token"], out["expires_in"]


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
    gw = Gateway(GATEWAY_URL, HushToken(token_endpoint()))
    info = gw.connect("k8s-token-exchange-example")
    print("connected to", info["serverInfo"]["name"])

    tools = gw.request("tools/list")["tools"]
    print("tools:", ", ".join(t["name"] for t in tools))

    # The apps this agent was granted. Connect one with hush_connect, then
    # find and run its tools with hush_search_tools and hush_call_tool.
    apps = gw.call_tool("hush_list_apps")
    print("apps:", json.dumps(apps.get("structuredContent", apps), indent=2))


if __name__ == "__main__":
    main()

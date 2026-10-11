"""A Kubernetes agent calling the Hush AI gateway with its service-account token.

The pod's projected token is sent as is, as the Bearer: the gateway exchanges
it with Hush for the agent. Standard library only, so it runs on a stock
python image.
"""

import json
import os
import sys
import urllib.error
import urllib.request

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
TOKEN_FILE = os.environ.get("HUSH_TOKEN_FILE", "/var/run/secrets/hush/token")


def token() -> str:
    # The kubelet rotates the token: read it on every request, never cache it.
    with open(TOKEN_FILE) as f:
        return f.read().strip()


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
    gw = Gateway(GATEWAY_URL, token)
    info = gw.connect("k8s-agent-example")
    print("connected to", info["serverInfo"]["name"])

    tools = gw.request("tools/list")["tools"]
    print("tools:", ", ".join(t["name"] for t in tools))

    # The apps this agent was granted. Connect one with hush_connect, then
    # find and run its tools with hush_search_tools and hush_call_tool.
    apps = gw.call_tool("hush_list_apps")
    print("apps:", json.dumps(apps.get("structuredContent", apps), indent=2))


if __name__ == "__main__":
    main()

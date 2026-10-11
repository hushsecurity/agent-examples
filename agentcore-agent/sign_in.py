"""Signs a user in to Hush for the agent, and saves the user's Hush token to
.user-token, for `invoke` to pass to the agent.

In an app, your front end does this sign-in, and passes the token to the agent
with each request.

    python sign_in.py <gateway MCP URL> <agent resource from terraform output>
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
GATEWAY_URL, AGENT_RESOURCE = sys.argv[1], sys.argv[2]


def get_json(url: str, data: dict | None = None, form: dict | None = None) -> dict:
    if data is not None:
        req = urllib.request.Request(
            url, json.dumps(data).encode(), {"Content-Type": "application/json"}
        )
    elif form is not None:
        req = urllib.request.Request(url, urllib.parse.urlencode(form).encode())
    else:
        req = url
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


# The gateway's authorization server, found the standard MCP way.
base = GATEWAY_URL.removesuffix("/mcp")
issuer = get_json(f"{base}/.well-known/oauth-protected-resource/mcp")["authorization_servers"][0]
server = get_json(f"{issuer}/.well-known/oauth-authorization-server")

# A public client for this script (dynamic client registration).
client_id = get_json(
    server["registration_endpoint"],
    data={
        "client_name": "Hush agent example sign-in",
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
    },
)["client_id"]

# Authorization code with PKCE. `resource` names the agent: only it can use
# the user's token.
verifier = secrets.token_urlsafe(48)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
state = secrets.token_urlsafe(16)
query = urllib.parse.urlencode(
    {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": AGENT_RESOURCE,
    }
)


class Callback(http.server.BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        if params.get("state") == state and "code" in params:
            Callback.code = params["code"]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Signed in. You can close this tab.")

    def log_message(self, *args):
        pass


url = f"{server['authorization_endpoint']}?{query}"
print(f"Sign in at (opening your browser):\n\n  {url}\n", flush=True)
webbrowser.open(url)
with http.server.HTTPServer(("localhost", PORT), Callback) as httpd:
    while Callback.code is None:
        httpd.handle_request()

token = get_json(
    server["token_endpoint"],
    form={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": Callback.code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    },
)["access_token"]
fd = os.open(".user-token", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, token.encode())
os.close(fd)
print("Saved the user's token to .user-token")

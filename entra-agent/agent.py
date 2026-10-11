"""An Entra agent calling the Hush AI gateway with its Entra token.

The agent gets a token for the gateway's API from Entra and sends it as the
Bearer: the gateway exchanges it with Hush for the agent.

    python agent.py            the agent acts as itself
    python agent.py --as-user  the agent acts for the user signed in to the Azure CLI
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

TENANT_ID = os.environ["ENTRA_TENANT_ID"]
BLUEPRINT_ID = os.environ["ENTRA_BLUEPRINT_ID"]  # the agent's blueprint (app id)
BLUEPRINT_SECRET = os.environ["ENTRA_BLUEPRINT_SECRET"]
AGENT_ID = os.environ["ENTRA_AGENT_ID"]  # the agent identity (app id)
GATEWAY_API_ID = os.environ["ENTRA_GATEWAY_API_ID"]  # the gateway's API (app id)
GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-entra-agent"

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
JWT_ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def entra(form: dict) -> str:
    """Requests a token from Entra."""
    resp = httpx2.post(TOKEN_URL, data=form)
    if resp.status_code != 200:
        sys.exit(f"Entra refused: {resp.text}")
    return resp.json()["access_token"]


def blueprint_token() -> str:
    """The blueprint vouching for its agent identity: an agent identity has no
    credential of its own, so its blueprint signs in for it (fmi_path)."""
    return entra({
        "grant_type": "client_credentials",
        "client_id": BLUEPRINT_ID,
        "client_secret": BLUEPRINT_SECRET,
        "scope": "api://AzureADTokenExchange/.default",
        "fmi_path": AGENT_ID,
    })


def agent_token() -> str:
    """A token for the gateway, as the agent itself."""
    return entra({
        "grant_type": "client_credentials",
        "client_id": AGENT_ID,
        "client_assertion_type": JWT_ASSERTION,
        "client_assertion": blueprint_token(),
        "scope": f"api://{GATEWAY_API_ID}/.default",
    })


def agent_token_for_user(user_token: str) -> str:
    """A token for the gateway, as the agent acting for the user of
    `user_token` (on-behalf-of): it names both the user and the agent."""
    return entra({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "requested_token_use": "on_behalf_of",
        "client_id": AGENT_ID,
        "client_assertion_type": JWT_ASSERTION,
        "client_assertion": blueprint_token(),
        "assertion": user_token,
        "scope": f"api://{GATEWAY_API_ID}/gateway.access",
    })


def user_token() -> str:
    """The user's token for the agent. In an app, it's the token your front
    end got when the user signed in; here, the Azure CLI's user."""
    az = shutil.which("az") or "az"  # az.cmd on Windows
    return subprocess.run(
        [az, "account", "get-access-token", "--tenant", TENANT_ID,
         "--scope", f"api://{BLUEPRINT_ID}/access_as_user", "--query", "accessToken", "-o", "tsv"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


async def main():
    if "--as-user" in sys.argv:
        token = agent_token_for_user(user_token())
    else:
        token = agent_token()

    # Any MCP client works: only the Authorization header is Hush's.
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with http, streamable_http_client(GATEWAY_URL, http_client=http) as (read, write):
        async with ClientSession(read, write) as gateway:
            await gateway.initialize()
            # One call through the gateway: find DeepWiki's tool, then run it.
            found = await gateway.call_tool(
                "hush_search_tools", {"app": DEEPWIKI_APP, "query": "read_wiki_structure"}
            )
            tool = json.loads(found.content[0].text)[0]["name"]
            result = await gateway.call_tool(
                "hush_call_tool",
                {"name": tool, "arguments": {"repoName": "modelcontextprotocol/python-sdk"}},
            )
            print(result.content[0].text[:300])


if __name__ == "__main__":
    asyncio.run(main())

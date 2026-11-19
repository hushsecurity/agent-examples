"""Two agents acting for the same user: the front agent hands the user off to a
specialist agent, which calls the Hush AI gateway for them.

Every step is an RFC 8693 token exchange at Hush:

1. The front agent exchanges the user's token for its own token for the user.
2. To pass the work on, it exchanges that token for a hand-off token addressed
   to the specialist (`resource` = the specialist's resource): only the
   specialist can use it.
3. The specialist exchanges the hand-off token for its own token for the user,
   which names both agents, and calls the gateway with it.

Both agents run in this script and sign in with a secret, to keep it short. In
practice they're separate services, signing in any way an agent can, and the
front agent sends the hand-off token with its request to the specialist.
"""

import asyncio
import base64
import functools
import json
import os
import sys

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
FRONT = (os.environ["FRONT_AGENT_ID"], os.environ["FRONT_AGENT_SECRET"])
SPECIALIST = (os.environ["SPECIALIST_AGENT_ID"], os.environ["SPECIALIST_AGENT_SECRET"])
SPECIALIST_RESOURCE = os.environ["SPECIALIST_RESOURCE"]
# The app terraform/ creates: a custom app is named "custom-<its name>".
DEEPWIKI_APP = "custom-deepwiki-hand-off-agents"


@functools.cache
def token_endpoint() -> str:
    """Hush's token endpoint, found the standard MCP way: the gateway names
    its issuer, whose metadata names the endpoint."""
    base = GATEWAY_URL.removesuffix("/mcp")
    resource = httpx2.get(f"{base}/.well-known/oauth-protected-resource/mcp").raise_for_status().json()
    issuer = resource["authorization_servers"][0]
    metadata = httpx2.get(f"{issuer}/.well-known/oauth-authorization-server").raise_for_status().json()
    return metadata["token_endpoint"]


def exchange(agent: tuple[str, str], subject_token: str, resource: str | None = None) -> str:
    """A Hush token for `agent` (its id and secret) acting for the user of
    `subject_token`; with `resource` naming another agent, a hand-off token
    for that agent."""
    data = {
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "subject_token": subject_token,
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
    }
    if resource:
        data["resource"] = resource
    resp = httpx2.post(token_endpoint(), auth=agent, data=data)
    if resp.status_code != 200:
        sys.exit(f"Hush refused ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def claims(token: str) -> dict:
    """The token's claims, unverified: only to show them."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


async def call_gateway(token: str):
    """One DeepWiki call through the gateway, as the specialist for the user."""
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with http, streamable_http_client(GATEWAY_URL, http_client=http) as (read, write):
        async with ClientSession(read, write) as gateway:
            await gateway.initialize()
            found = await gateway.call_tool(
                "hush_search_tools", {"app": DEEPWIKI_APP, "query": "read_wiki_structure"}
            )
            tool = json.loads(found.content[0].text)["tools"][0]["name"]
            result = await gateway.call_tool(
                "hush_call_tool",
                {"name": tool, "arguments": {"repoName": "modelcontextprotocol/python-sdk"}},
            )
            print(result.content[0].text[:300])


def main():
    with open(".user-token") as f:
        user_token = f.read().strip()

    # The front agent: its token for the user, then a hand-off token for the specialist.
    front_token = exchange(FRONT, user_token)
    hand_off_token = exchange(FRONT, front_token, resource=SPECIALIST_RESOURCE)

    # The specialist: its own token for the user, from the hand-off token.
    specialist_token = exchange(SPECIALIST, hand_off_token)
    token = claims(specialist_token)
    print(json.dumps({"sub": token["sub"], "act": token["act"]}, indent=2))

    asyncio.run(call_gateway(specialist_token))


if __name__ == "__main__":
    main()

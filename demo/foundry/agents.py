"""Creates the demo's two Foundry agents, one per connection setup.sh made,
and prints the identity of the one acting as itself, for Terraform.

    python agents.py
"""

import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]  # https://<account>.services.ai.azure.com/api/projects/<project>
MODEL = os.environ["FOUNDRY_MODEL"]  # a model deployment in the project
GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp

INSTRUCTIONS = """Your tools come through the Hush gateway. hush_list_apps
shows the apps you can use: call it first, and use the app names it gives
exactly. Find an app's tools with hush_search_tools and run them with
hush_call_tool.
- If an app the user needs is disconnected, call hush_connect and give the
  user the link exactly as returned.
- If a tool needs the user's consent, call hush_user_consent_methods, request
  it with hush_request_user_consent (if there's one method, use it without
  asking), and tell the user how to approve (give a
  link exactly as returned). When they say they approved, retry the call.
- Never call hush_reauth: after a connect or an approval, just retry.
- Don't ask the user to confirm an action: call the tool. The gateway asks
  the user for consent itself when an action needs it.
- If a call is blocked, say so and why.
Keep answers short."""

project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())

agents = {}
for name, connection in (("hush-demo-as-agent", "hush-demo-agent"), ("hush-demo-for-user", "hush-demo-user")):
    agents[name] = project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=MODEL,
            instructions=INSTRUCTIONS,
            tools=[MCPTool(server_label="hush", server_url=GATEWAY_URL,
                           project_connection_id=connection, require_approval="never")],
        ),
    )
    print("created", name)

print("\nexport TF_VAR_foundry_agent_identity_id=" + agents["hush-demo-as-agent"].instance_identity.principal_id)

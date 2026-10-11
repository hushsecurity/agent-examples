"""An Azure AI Foundry agent whose tools come through the Hush AI gateway.

Foundry runs the agent and calls the gateway itself, with a token for the
agent's own Entra agent identity: the gateway exchanges it with Hush. There is
no token code here, only the agent's definition.

    python agent.py create             create the agent, and print its identity
    python agent.py ask "<question>"   ask it something
"""

import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"]  # https://<account>.services.ai.azure.com/api/projects/<project>
MODEL = os.environ["FOUNDRY_MODEL"]  # a model deployment in the project
GATEWAY_URL = os.environ["HUSH_GATEWAY_URL"]  # https://<gateway>/mcp
AGENT = "hush-example-agent"

project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())


def create():
    agent = project.agents.create_version(
        agent_name=AGENT,
        definition=PromptAgentDefinition(
            model=MODEL,
            instructions=(
                "Your tools come through the Hush gateway. hush_list_apps shows the apps "
                "you can use; find an app's tools with hush_search_tools and run them "
                "with hush_call_tool. Keep answers short."
            ),
            # The gateway, through the project's connection (setup.sh): Foundry
            # signs in to it as this agent's identity.
            tools=[MCPTool(server_label="hush", server_url=GATEWAY_URL,
                           project_connection_id="hush-gateway", require_approval="never")],
        ),
    )
    print("agent identity:", agent.instance_identity.principal_id)


def ask(question: str):
    reply = project.get_openai_client().responses.create(
        input=question,
        extra_body={"agent_reference": {"name": AGENT, "type": "agent_reference"}},
    )
    for item in reply.output:
        if item.type == "mcp_call":
            print(f"[{item.name}] {item.arguments}")
    print(reply.output_text)


if __name__ == "__main__":
    if sys.argv[1:2] == ["create"]:
        create()
    else:
        ask(sys.argv[2] if len(sys.argv) > 2 else "Which apps can you use?")

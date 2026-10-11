# Azure agent: managed identity as the Bearer

An agent on Azure calls the Hush AI gateway as its managed identity: it asks
Azure for a token for the gateway's API and sends it as the Bearer, and the
gateway exchanges it with Hush. No secret, and no token exchange in the
agent's code. The agent acts as itself.

```
agent ──▶ Azure: a token for the gateway's API, as the managed identity
agent ──(Bearer: that token)──▶ gateway ──(exchange)──▶ Hush
```

The example runs the agent in Azure Container Instances; the same code runs
on any Azure compute with a managed identity (a VM, Container Apps, App
Service, Functions).

## Requirements

- A Hush AI gateway that the agent can reach: hosted, or on-prem (`hush-agw`
  chart 0.7.1 or later).
- An Azure subscription where you can create a resource group, a managed
  identity and a container (e.g. Contributor), and the Cloud Application
  Administrator role to run `setup.sh`.
- The Azure CLI, Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)).

## Files

| File | What it is |
| ---- | ---------- |
| [`setup.sh`](setup.sh) | The Azure side: the gateway's API in Entra, and the agent's managed identity |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the managed identity, and a DeepWiki app granted to it |
| [`agent.py`](agent.py) | The agent: gets its token from Azure, and makes one DeepWiki call through the gateway with the MCP Python SDK |

## Run it

1. **Create the Azure side.** It prints the `export` lines for the next
   steps; run them.

   ```sh
   az login --tenant <tenant>
   ./setup.sh <resource group> <region>
   ```

2. **Register the agent in Hush.** Terraform creates the service agent, and
   DeepWiki (a public MCP server that needs no sign-in) on your gateway,
   granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> -var tenant_id=$ENTRA_TENANT_ID \
     -var principal_id=$AZURE_PRINCIPAL_ID -var gateway_api_id=$ENTRA_GATEWAY_API_ID
   ```

3. **Run it in Container Instances**, with the managed identity. The agent's
   code is passed in an environment variable, so there's no image to build.

   ```sh
   az container create -g <resource group> -n hush-example-agent \
     --image mcr.microsoft.com/devcontainers/python:3.12 --os-type Linux --cpu 1 --memory 1.5 \
     --restart-policy Never --assign-identity $AZURE_IDENTITY \
     --environment-variables HUSH_GATEWAY_URL=https://<gateway>/mcp \
       ENTRA_GATEWAY_API_ID=$ENTRA_GATEWAY_API_ID AZURE_CLIENT_ID=$AZURE_CLIENT_ID \
       AGENT_PY="$(base64 < agent.py | tr -d '\n')" \
     --command-line "sh -c 'pip install -q \"mcp>=2.1,<3\" httpx2 azure-identity && echo \$AGENT_PY | base64 -d > agent.py && python agent.py'"
   az container logs -g <resource group> -n hush-example-agent
   ```

   After a minute (the container installs its packages first), the logs show
   DeepWiki's answer, through the gateway:

   ```
   Available pages for modelcontextprotocol/python-sdk:
   - 1 Overview
   ...
   ```

## Good to know

- **To exchange the token yourself** instead, for a standard OAuth token any
  client can use: post it to Hush's token endpoint as the client assertion,
  as [`k8s-agent-exchange`](../k8s-agent-exchange) does, and add `resource`
  (the gateway's issuer), since an Azure token's audience doesn't name the
  gateway.
- **The token is for the gateway's API**, an app registration you create for
  the gateway: the agent requests `api://<app id>/.default`, and the token's
  audience is the app id, which Terraform's `gateway_api_id` takes. Keep that
  app for Hush only: anything that receives its tokens could replay them.
- **`AZURE_CLIENT_ID` picks the managed identity** when the compute has a
  user-assigned one (or several); leave it unset for a system-assigned one.
  `azure-identity` gets, caches and renews the token.
- **As itself, the agent can use only apps that need no user's sign-in.**
  Grant it more apps with an assignment rule on `agent.id`.
- **A `401` from the gateway** usually means the identity isn't registered:
  `principal_id` (the identity's object id, not its client id), `tenant_id`
  and `gateway_api_id` must match.

## Clean up

```sh
terraform -chdir=terraform destroy
az group delete -n <resource group>
```

and delete the "Hush gateway (managed identity)" app in Entra.

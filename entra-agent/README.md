# Entra agent: Entra token as the Bearer, as itself and for a user

An [Entra agent](https://learn.microsoft.com/entra/agent-id/) calls the Hush
AI gateway with a token Entra issues for it, sent as the Bearer. The gateway
exchanges it with Hush for the agent.

- **As itself** (`python agent.py`): the agent uses the apps granted to it.
- **For a user** (`python agent.py --as-user`): Entra issues an on-behalf-of
  token that names both the user and the agent. The gateway applies the
  user's access through the agent.

```
agent ──▶ Entra: a token for the gateway, as the agent or for a user
agent ──(Bearer: Entra token)──▶ gateway ──(exchange)──▶ Hush
```

## Requirements

- A Hush AI gateway: hosted, or on-prem with the `hush-agw` chart 0.7.1 or later.
- For `--as-user`: the gateway signs users in with Entra, in the agent's
  tenant, and the user has signed in to it once (or is provisioned to Hush
  with SCIM).
- An Entra tenant with Agent ID, and the Agent ID Administrator and Cloud
  Application Administrator roles to run `setup.sh`.
- The Azure CLI, Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`setup.sh`](setup.sh) | The Entra side: the gateway's API, the agent's blueprint and agent identity, and consent |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the agent identity, and a DeepWiki app granted to it |
| [`agent.py`](agent.py) | The agent: gets its Entra token, and makes one DeepWiki call through the gateway with the MCP Python SDK |

## Run it

1. **Create the agent in Entra.** It prints the `export` lines for the next
   steps; run them.

   ```sh
   az login --tenant <tenant>
   ./setup.sh
   ```

2. **Register the agent in Hush.** Terraform creates the service agent, and
   DeepWiki (a public MCP server that needs no sign-in) on your gateway,
   granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> \
     -var tenant_id=$ENTRA_TENANT_ID -var agent_id=$ENTRA_AGENT_ID -var gateway_api_id=$ENTRA_GATEWAY_API_ID
   ```

3. **Run it.**

   ```sh
   pip install -r requirements.txt
   export HUSH_GATEWAY_URL=https://<gateway>/mcp
   python agent.py            # as itself
   python agent.py --as-user  # for the user signed in to the Azure CLI
   ```

   Each prints DeepWiki's answer, through the gateway:

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
- **An agent identity has no credential of its own**: its blueprint signs in
  for it (`blueprint_token()`), and the agent identity then gets a token for
  the gateway's API, as itself (`agent_token()`) or for a user
  (`agent_token_for_user()`).
- **In an app, the user's token comes from your front end's sign-in**; the
  example takes it from the Azure CLI.
- **Use a federated credential for the blueprint** (e.g. a managed identity)
  instead of a secret, and **keep the gateway's API for Hush only**: anything
  that receives its tokens could replay them.
- **Entra tokens last about an hour**: a long-running agent gets new ones.
- **A `401` from the gateway** usually means the Terraform's `agent_id`,
  `tenant_id` or `gateway_api_id` don't match the token, or, for a user, that
  the gateway doesn't sign users in with this tenant or the user hasn't
  signed in to it yet. **`Entra refused`** usually means a missing consent or
  a new app that hasn't propagated yet: wait a minute and retry.

## Clean up

```sh
terraform -chdir=terraform destroy
```

and delete the "Hush gateway" app and the "Hush example agent" objects
`setup.sh` created in Entra.

# Entra agent: Entra token as the Bearer

An [Entra agent](https://learn.microsoft.com/entra/agent-id/) calls the Hush AI
gateway with a token Entra issues for it. It sends the token as the
`Authorization: Bearer` header, and the gateway exchanges it with Hush for a
gateway token on the agent's behalf.

The agent can call the gateway in two ways:

- **As itself** (`python agent.py`): an autonomous agent, using the apps
  granted to the agent.
- **For a user** (`python agent.py --as-user`): Entra issues an on-behalf-of
  token that names both the user and the agent. The gateway sees who the user
  is and which agent acts for them, and applies the user's access through
  that agent.

```
agent ──▶ Entra: a token for the gateway, as the agent or for a user
agent ──(Bearer: Entra token)──▶ gateway ──(exchange)──▶ Hush
```

## Requirements

- A Hush AI gateway: hosted, or on-prem with the `hush-agw` chart 0.7.1 or later.
- For `--as-user`: the gateway signs users in with Entra, in the same tenant
  as the agent, and the user has signed in to it once (or is provisioned to
  Hush with SCIM).
- An Entra tenant with Agent ID, and the Agent ID Administrator and Cloud
  Application Administrator roles to run `setup.sh`.
- The Azure CLI, Terraform with a Hush API key (`HUSH_API_KEY_ID`,
  `HUSH_API_KEY_SECRET`, `HUSH_REALM`), and Python 3.10+.

## Files

| File | What it is |
| ---- | ---------- |
| [`setup.sh`](setup.sh) | The Entra side: the gateway's API, the agent's blueprint and agent identity, and consent |
| [`terraform/main.tf`](terraform/main.tf) | The service agent in Hush, bound to the agent identity |
| [`agent.py`](agent.py) | The agent: gets its Entra token and calls the gateway (standard library only) |

## Run it

1. **Create the agent in Entra.**

   ```sh
   az login --tenant <tenant>
   ./setup.sh
   ```

   It prints the `export` lines for the next steps; run them.

   | Entra object | Why |
   | ------------ | --- |
   | Gateway API (app registration) | The audience of the agent's tokens, with a `gateway.access` scope for acting for users |
   | Agent blueprint | Holds the credential (here a secret) the agent identity signs in with |
   | Agent identity | The agent itself: the identity the gateway sees |
   | Admin consent | Lets the agent identity call the gateway API for users |

2. **Register the agent in Hush.**

   ```sh
   cd terraform
   terraform init
   terraform apply -var tenant_id=$ENTRA_TENANT_ID -var agent_id=$ENTRA_AGENT_ID -var gateway_api_id=$ENTRA_GATEWAY_API_ID
   ```

3. **Grant it apps.** Assigning an app to all users does not cover service
   agents: add a rule on the agent's id to each app it should use as itself.
   Acting for a user, it gets the user's apps.

   ```hcl
   assignment {
     condition {
       match {
         source   = "agent"
         property = "id"
         op       = "eq"
         value    = hush_service_agent.example.id
       }
     }
   }
   ```

   As itself, the agent can use only apps that need no user's sign-in: an
   app with no authentication, or one connected with a service account or API
   key. Apps connected with each user's OAuth consent need an agent acting
   for a user.

4. **Run it.**

   ```sh
   export HUSH_GATEWAY_URL=https://<gateway>/mcp
   python agent.py            # as itself
   python agent.py --as-user  # for the user signed in to the Azure CLI
   ```

   ```
   connected to agentgateway
   tools: hush_call_tool, hush_connect, hush_disconnect, hush_list_apps, hush_search_tools, ...
   apps: {
     "apps": [
       {
         "name": "custom-deepwiki",
         "assigned": true,
         "connection": "not_required"
       }
     ]
   }
   ```

## How the agent gets its token

An agent identity has no credential of its own: its blueprint signs in for it.
Every token takes two requests to Entra (see [`agent.py`](agent.py)):

1. `blueprint_token()`: the blueprint, with its credential, gets a token for
   its agent identity (`fmi_path`).
2. With that token as its client assertion, the agent identity gets a token
   for the gateway's API:
   - `agent_token()`: as itself (`client_credentials`).
   - `agent_token_for_user()`: for a user (`jwt-bearer` on-behalf-of), from the
     user's token for the agent. In an app, that's the token your front end
     got when the user signed in; the example takes it from the Azure CLI.

The gateway accepts either token as is.

## In your own agent

- **Use a federated credential for the blueprint** (e.g. a managed identity)
  instead of a secret.
- **Get a new token before the old one expires.** Entra tokens last about an
  hour.
- **Keep the gateway API for Hush only.** Anything that receives its tokens
  could replay them to the gateway.
- **Any MCP client works.** Only the `Authorization` header is specific to
  Hush.

## Troubleshooting

A `401` from the gateway usually means one of:

- **The agent isn't registered** in Hush, or `agent_id`, `tenant_id` or
  `gateway_api_id` in the Terraform don't match the token.
- **With `--as-user`**: the gateway doesn't sign users in with Entra in the
  agent's tenant, the agent has no `acts_for_users`, or the user hasn't
  signed in to the gateway yet.
- **An on-prem gateway older than chart 0.7.1** doesn't accept the token
  directly: upgrade it with `helm upgrade`.

An error from Entra (`Entra refused: ...`) usually means the setup isn't
complete: a missing consent, or a new app that hasn't propagated yet (wait a
minute and retry). If `setup.sh` stops partway, delete what it created (the
"Hush gateway" app and the "Hush example agent" objects) before running it
again.

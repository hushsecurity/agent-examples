# Kubernetes agent: service-account token as the Bearer

An agent running in Kubernetes calls the Hush AI gateway with its own
identity: the pod's service-account token. No secret, no client id, no token
exchange in the agent's code. It sends the token as the `Authorization: Bearer`
header, and the gateway exchanges it with Hush for a gateway token on the
agent's behalf.

```
pod ──(Bearer: service-account token)──▶ gateway ──(exchange)──▶ Hush
                                            │
                                            └──▶ MCP apps granted to the agent
```

The agent acts as itself (an autonomous agent). To act for a user, see
[token exchange](https://registry.terraform.io/providers/hushsecurity/hush/latest/docs/resources/service_agent)
with `acts_for_users`.

## Requirements

- A Hush AI gateway: hosted, or on-prem with the `hush-agw` chart 0.7.1 or later.
- A cluster whose OIDC issuer is publicly reachable, so Hush can verify its
  tokens (`<issuer>/.well-known/openid-configuration` and its JWKS). EKS, GKE
  and AKS (with the OIDC issuer enabled) are.
- Terraform with a Hush API key (`HUSH_API_KEY_ID`, `HUSH_API_KEY_SECRET`,
  `HUSH_REALM`), and `kubectl`.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent in Hush, bound to the `hush-agents/example-agent` service account |
| [`agent.yaml`](agent.yaml) | The service account and the agent, as a Job with a projected token |
| [`agent.py`](agent.py) | The agent: a minimal MCP client (standard library only) |

## Run it

1. **Register the agent in Hush.**

   ```sh
   cd terraform
   terraform init
   terraform apply -var cluster_issuer="$(kubectl get --raw /.well-known/openid-configuration | jq -r .issuer)"
   ```

2. **Grant it apps.** Assigning an app to all users does not cover service
   agents: add a rule on the agent's id to each app it should use.

   ```hcl
   resource "hush_mcp_application" "example" {
     # ...
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
   }
   ```

   As itself, the agent can use only apps that need no user's sign-in: an
   app with no authentication, or one connected with a service account or API
   key. Apps connected with each user's OAuth consent need an agent acting
   for a user.

3. **Point the agent at your gateway.** In [`agent.yaml`](agent.yaml), set:
   - `HUSH_GATEWAY_URL`: the gateway's MCP URL, e.g. `https://<gateway>/mcp`.
   - the token's `audience`: the gateway's issuer. The gateway publishes it:

     ```sh
     curl -s https://<gateway>/.well-known/oauth-protected-resource/mcp | jq -r '.authorization_servers[0]'
     ```

4. **Run it.**

   ```sh
   kubectl apply -k .
   kubectl -n hush-agents logs -f job/example-agent
   ```

   ```
   connected to agentgateway ...
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

   The gateway lists all its apps; `assigned` shows the ones granted to
   this agent (step 2).

   A Job can't be changed in place: to run it again, or after editing
   `agent.py`, `kubectl -n hush-agents delete job example-agent` first.

## In your own agent

- **Use a projected token, not the default one.** Its `audience` must be the
  gateway's issuer; the default service-account token is for the Kubernetes
  API and is refused.
- **Read the token file on every request.** The kubelet rotates it before it
  expires; a token read once at start-up stops working.
- **Any MCP client works.** Only the `Authorization` header is specific to
  Hush. With the MCP Python SDK, for example, give `streamablehttp_client` an
  `httpx.Auth` that sets the header from the file on each request.
- **One service account per agent.** Each one is a separate identity in the
  gateway's activity log; an agent can have several (repeat the `kubernetes`
  block), but a service account belongs to one agent.

## Troubleshooting

A `401` from the gateway usually means one of:

- **The audience is wrong**: compare the token's `aud` with the gateway's
  issuer (step 3).
- **The identity is not registered**: the token's `iss` and `sub`
  (`system:serviceaccount:hush-agents:example-agent`) must match the
  `kubernetes` block exactly.
- **Hush can't verify the token**: the cluster's issuer must be publicly
  reachable.
- **An on-prem gateway older than chart 0.7.1** doesn't accept the token
  directly: upgrade it with `helm upgrade`.

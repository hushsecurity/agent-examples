# Kubernetes agent: token exchange

An agent running in Kubernetes signs in to Hush itself: it exchanges its
service-account token for a Hush token (OAuth client credentials, with the
service-account token as the client assertion) and calls the Hush AI gateway
with the Hush token.

```
pod ──(service-account token)──▶ Hush token endpoint ──▶ Hush token
pod ──(Bearer: Hush token)──▶ gateway ──▶ MCP apps granted to the agent
```

Compared with [`k8s-direct-bearer`](../k8s-direct-bearer), where the gateway
does the exchange for the agent, the agent:

- holds a standard OAuth token, which any MCP client or SDK can use;
- finds everything from the gateway's URL, with standard MCP discovery;
- can also [act for a user](https://registry.terraform.io/providers/hushsecurity/hush/latest/docs/resources/service_agent)
  by exchanging the user's Hush token (`acts_for_users`).

## Requirements

- A Hush AI gateway, hosted or on-prem.
- A cluster whose OIDC issuer is publicly reachable, so Hush can verify its
  tokens (`<issuer>/.well-known/openid-configuration` and its JWKS). EKS, GKE
  and AKS (with the OIDC issuer enabled) are.
- Terraform with a Hush API key (`HUSH_API_KEY_ID`, `HUSH_API_KEY_SECRET`,
  `HUSH_REALM`), and `kubectl`.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent in Hush, bound to the `hush-agents/token-exchange-agent` service account |
| [`agent.yaml`](agent.yaml) | The service account and the agent, as a Job with a projected token |
| [`agent.py`](agent.py) | The agent: the exchange, and a minimal MCP client (standard library only) |

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

3. **Point the agent at your gateway.** In [`agent.yaml`](agent.yaml), set:
   - `HUSH_GATEWAY_URL`: the gateway's MCP URL, e.g. `https://<gateway>/mcp`.
   - the token's `audience`: the gateway's issuer. The gateway publishes it:

     ```sh
     curl -s https://<gateway>/.well-known/oauth-protected-resource/mcp | jq -r '.authorization_servers[0]'
     ```

4. **Run it.**

   ```sh
   kubectl apply -k .
   kubectl -n hush-agents logs -f job/token-exchange-agent
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

   A Job can't be changed in place: to run it again, or after editing
   `agent.py`, `kubectl -n hush-agents delete job token-exchange-agent` first.

## How the agent gets its token

1. `token_endpoint()`: the gateway's
   `/.well-known/oauth-protected-resource/mcp` names its authorization server
   (the gateway's issuer), and the server's
   `/.well-known/oauth-authorization-server` names its token endpoint.
2. `HushToken`: posts to the token endpoint

   ```
   grant_type=client_credentials
   client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
   client_assertion=<service-account token>
   ```

   and keeps the Hush token until a minute before it expires.

## In your own agent

- **Use a projected token, not the default one.** Its `audience` must be the
  gateway's issuer.
- **Read the service-account token file on every exchange.** The kubelet
  rotates it; a token read once at start-up stops working.
- **Renew the Hush token before it expires** (`expires_in`), as `HushToken`
  does.
- **Any MCP client works.** Pass it the Hush token like any OAuth bearer
  token.

## Troubleshooting

`Hush refused (401): ...` from the exchange usually means one of:

- **The audience is wrong**: the token's `aud` must be the gateway's issuer
  (step 3).
- **The identity is not registered**: the token's `iss` and `sub`
  (`system:serviceaccount:hush-agents:token-exchange-agent`) must match the
  `kubernetes` block exactly.
- **Hush can't verify the token**: the cluster's issuer must be publicly
  reachable.

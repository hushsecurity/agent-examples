# Kubernetes agent: token exchange, as itself and for a user

An agent in Kubernetes signs in to Hush itself: it exchanges its pod's
service-account token for a Hush token, and calls the Hush AI gateway with
that standard OAuth token.

- **As itself**: OAuth client credentials, with the service-account token as
  the client assertion.
- **For a user**: a service-account token never names a user, so the agent
  exchanges it together with the user's Hush token (RFC 8693 token exchange)
  for a token naming both. The gateway applies the user's access through the
  agent.

```
pod ──(service-account token [+ user's Hush token])──▶ Hush ──▶ Hush token
pod ──(Bearer: Hush token)──▶ gateway
```

## Requirements

- A Hush AI gateway, hosted or on-prem.
- A cluster whose OIDC issuer is publicly reachable, so Hush can verify its
  tokens. EKS, GKE and AKS (with the OIDC issuer enabled) are.
- Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), `kubectl`, and Python
  3.10+ to sign a user in.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the `k8s-agent-exchange/example-agent` service account, and a DeepWiki app granted to it |
| [`agent.yaml`](agent.yaml) | The service account, and the agent as a Job with a projected token (and the user's token, when there is one) |
| [`agent.py`](agent.py) | The agent: the exchange, and one DeepWiki call through the gateway with the MCP Python SDK |
| [`sign_in.py`](sign_in.py) | Signs a user in for the agent (standard library only) |

## Run it

1. **Register the agent in Hush.** Terraform creates the service agent, and
   DeepWiki (a public MCP server that needs no sign-in) on your gateway,
   granted to the agent.

   ```sh
   terraform -chdir=terraform init
   terraform -chdir=terraform apply -var deployment_id=<deployment id> \
     -var cluster_issuer="$(kubectl get --raw /.well-known/openid-configuration | jq -r .issuer)"
   ```

2. **Point the agent at your gateway.** In [`agent.yaml`](agent.yaml), set
   `HUSH_GATEWAY_URL` to the gateway's MCP URL, and the token's `audience` to
   the gateway's issuer.

3. **Run it, as itself.**

   ```sh
   kubectl apply -k .
   kubectl -n k8s-agent-exchange logs -f job/example-agent
   ```

   It prints DeepWiki's answer, through the gateway:

   ```
   Available pages for modelcontextprotocol/python-sdk:
   - 1 Overview
   ...
   ```

4. **Run it, for a user.** Sign in (it opens your browser), hand the agent
   your token as the `user-token` Secret, and run it again:

   ```sh
   python sign_in.py https://<gateway>/mcp "$(terraform -chdir=terraform output -raw resource)"
   kubectl -n k8s-agent-exchange create secret generic user-token --from-file=token=.user-token
   kubectl -n k8s-agent-exchange delete job example-agent
   kubectl apply -k .
   ```

   A user's token lasts 5 minutes, so run it right after signing in (the Job
   installs its packages first, which takes a few seconds). In an app, your
   front end keeps the user signed in and hands the agent a fresh token with
   each request.

## Good to know

- **Hush's token endpoint is discovered from the gateway's URL**
  (`discover()`), the standard MCP way.
- **The service-account token's audience must be the gateway's issuer**, and
  the agent reads it fresh on every exchange: the kubelet rotates it.
- **The user's token must be for this agent**: users sign in with `resource`
  set to the agent's `resource` (Terraform output). The agent needs
  `acts_for_users`.
- **As itself, the agent can use only apps that need no user's sign-in.**
  Grant it more apps with an assignment rule on `agent.id`.
- **`Hush refused (401)`** usually means the audience is wrong, the identity
  isn't registered, or the cluster's issuer isn't public. **`Hush refused
  (400): invalid subject_token`** means the user's token expired or is for
  another agent.

## Clean up

```sh
kubectl delete -k .
terraform -chdir=terraform destroy
```

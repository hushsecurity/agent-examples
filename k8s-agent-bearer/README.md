# Kubernetes agent: service-account token as the Bearer

An agent in Kubernetes calls the Hush AI gateway with its pod's
service-account token as the Bearer. The gateway exchanges it with Hush for
the agent: no secret, and no token exchange in the agent's code. The agent
acts as itself.

```
pod ──(Bearer: service-account token)──▶ gateway ──(exchange)──▶ Hush
```

## Requirements

- A Hush AI gateway: hosted, or on-prem with the `hush-agw` chart 0.7.1 or later.
- A cluster whose OIDC issuer is publicly reachable, so Hush can verify its
  tokens. EKS, GKE and AKS (with the OIDC issuer enabled) are.
- Terraform, a Hush API key and your gateway's details (see
  [Before you start](../README.md#before-you-start)), and `kubectl`.

## Files

| File | What it is |
| ---- | ---------- |
| [`terraform/main.tf`](terraform/main.tf) | The service agent, bound to the `k8s-agent-bearer/example-agent` service account, and a DeepWiki app granted to it |
| [`agent.yaml`](agent.yaml) | The service account, and the agent as a Job with a projected token |
| [`agent.py`](agent.py) | The agent: one DeepWiki call through the gateway, with the MCP Python SDK |

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

3. **Run it.**

   ```sh
   kubectl apply -k .
   kubectl -n k8s-agent-bearer logs -f job/example-agent
   ```

   It prints DeepWiki's answer, through the gateway:

   ```
   Available pages for modelcontextprotocol/python-sdk:
   - 1 Overview
   ...
   ```

   To run it again, `kubectl -n k8s-agent-bearer delete job example-agent`
   first.

## Good to know

- **To exchange the token yourself** instead, for a standard OAuth token any
  client can use or to act for a user, see
  [`k8s-agent-exchange`](../k8s-agent-exchange).
- **The token's audience must be the gateway's issuer.** That's why the Job
  uses a projected token: the default one is for the Kubernetes API.
- **Read the token file on every request.** The kubelet rotates it.
- **As itself, the agent can use only apps that need no user's sign-in**: no
  authentication, or a service account or API key. Grant it more apps with an
  assignment rule on `agent.id`; assigning an app to all users doesn't cover
  service agents.
- **A `401` from the gateway** usually means the audience is wrong, the
  identity isn't registered (`system:serviceaccount:k8s-agent-bearer:example-agent`
  and the cluster's issuer must match the Terraform), or the cluster's issuer
  isn't public.

## Clean up

```sh
kubectl delete -k .
terraform -chdir=terraform destroy
```

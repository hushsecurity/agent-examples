# Hush agent examples

Example agents that connect to the [Hush](https://hush.security) AI gateway
with their own identity: the identity of the workload they run on, instead of
a person's sign-in or a static secret.

Each folder is one self-contained use case, with the Terraform for the Hush
side, the platform side and the agent's code.

| Example | The agent runs on | Signs in with |
| ------- | ----------------- | ------------- |
| [`k8s-direct-bearer`](k8s-direct-bearer) | Kubernetes | Its service-account token, sent to the gateway as the Bearer |
| [`entra-agent`](entra-agent) | Anywhere (an Entra agent identity) | Its Entra token, as itself or on behalf of a user, sent to the gateway as the Bearer |

## The basics

- A **service agent** in Hush
  ([`hush_service_agent`](https://registry.terraform.io/providers/hushsecurity/hush/latest/docs/resources/service_agent))
  names the workload identities it signs in with: a Kubernetes service
  account, an AWS IAM role, an Azure / Entra service principal, or any OIDC
  issuer.
- The workload's token must be issued **for the gateway**. Its audience is
  the gateway's issuer, which the gateway publishes at
  `https://<gateway>/.well-known/oauth-protected-resource/mcp`
  (`authorization_servers`). Entra is the exception: there, the audience is
  an app registration you create for the gateway (see
  [`entra-agent`](entra-agent)).
- Apps are granted to a service agent with an assignment rule on its id.
  Assigning an app to all users does not cover service agents.

## License

[Apache 2.0](LICENSE)

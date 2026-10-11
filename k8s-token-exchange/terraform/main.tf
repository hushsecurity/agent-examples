terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.28"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID, HUSH_API_KEY_SECRET and HUSH_REALM.
provider "hush" {}

variable "cluster_issuer" {
  description = "The cluster's OIDC issuer: kubectl get --raw /.well-known/openid-configuration | jq -r .issuer"
  type        = string
}

# The agent, signing in as one service account of the cluster.
resource "hush_service_agent" "example" {
  name = "k8s-token-exchange-agent"

  kubernetes {
    issuer          = var.cluster_issuer
    namespace       = "hush-agents"
    service_account = "token-exchange-agent"
  }
}

output "agent_id" {
  description = "Grant apps to the agent with an assignment rule on agent.id = this."
  value       = hush_service_agent.example.id
}

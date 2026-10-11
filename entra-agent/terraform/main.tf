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

variable "tenant_id" {
  description = "ENTRA_TENANT_ID from setup.sh"
  type        = string
}

variable "agent_id" {
  description = "ENTRA_AGENT_ID from setup.sh"
  type        = string
}

variable "gateway_api_id" {
  description = "ENTRA_GATEWAY_API_ID from setup.sh"
  type        = string
}

# The agent, signing in as its Entra agent identity. acts_for_users lets it
# act for users as well (--as-user).
resource "hush_service_agent" "example" {
  name           = "entra-example-agent"
  acts_for_users = true

  azure {
    tenant_id            = var.tenant_id
    service_principal_id = var.agent_id
    audience             = var.gateway_api_id
  }
}

output "agent_id" {
  description = "Grant apps to the agent with an assignment rule on agent.id = this."
  value       = hush_service_agent.example.id
}

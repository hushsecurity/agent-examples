terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.40"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID and HUSH_API_KEY_SECRET.
provider "hush" {}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

variable "api_audience" {
  description = "Your API's URI: the audience of its tokens. Unique in the organization."
  type        = string
  default     = "https://api.example.com/orders"
}

# The agent, acting for users. Here it signs in with a secret; any other way an
# agent signs in works the same.
resource "hush_service_agent" "example" {
  name           = "your-api-agent"
  acts_for_users = true
}

resource "hush_service_agent_client_secret" "example" {
  agent_id = hush_service_agent.example.id
}

# Your API, and the scopes it understands.
resource "hush_resource_server" "orders" {
  name         = "orders-your-api-example"
  display_name = "Orders API (your-api example)"
  audience     = var.api_audience

  scope {
    name        = "orders:read"
    description = "Read orders"
  }
  scope {
    name        = "orders:write"
    description = "Place orders"
  }
}

# Who gets tokens for it, and with which scopes: the agent, for every user
# (assign_all), reading only. Acting for a user, the agent needs both.
resource "hush_resource_application" "orders" {
  resource       = hush_resource_server.orders.name
  display_name   = "Orders API (your-api example)"
  deployment_ids = [var.deployment_id]
  scopes         = ["orders:read"]
  assign_all     = true

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

# The issuer of the tokens, which your API pins.
data "hush_agent_authorization_server" "gateway" {
  deployment_id = var.deployment_id
}

output "agent_id" {
  value = hush_service_agent.example.id
}

output "secret" {
  value     = hush_service_agent_client_secret.example.secret
  sensitive = true
}

output "resource" {
  description = "What users sign in for, to let the agent act for them (sign_in.py)."
  value       = hush_service_agent.example.resource
}

output "api_audience" {
  value = hush_resource_server.orders.audience
}

output "issuer" {
  description = "The issuer your API accepts."
  value       = data.hush_agent_authorization_server.gateway.issuer
}

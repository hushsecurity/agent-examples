terraform {
  required_providers {
    hush = {
      source  = "hushsecurity/hush"
      version = "~> 1.28"
    }
  }
}

# Credentials come from HUSH_API_KEY_ID and HUSH_API_KEY_SECRET.
provider "hush" {}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

variable "users" {
  description = "The emails of the people who will try the demo: they get the apps when an agent acts for them"
  type        = list(string)
}

variable "aws_issuer" {
  description = "The AWS account's issuer: aws iam get-outbound-web-identity-federation-info --query IssuerIdentifier --output text"
  type        = string
}

variable "agentcore_role_arn" {
  description = "The AgentCore runtime's execution role"
  type        = string
}

variable "tenant_id" {
  description = "The Entra tenant of the Foundry project"
  type        = string
}

variable "foundry_agent_identity_id" {
  description = "The Foundry agent's identity, as foundry/agents.py prints it"
  type        = string
}

variable "foundry_gateway_api_id" {
  description = "The gateway's API app id, as foundry/setup.sh prints it"
  type        = string
}

# The AgentCore agent: signs in as its runtime's role, as itself or for a user.
resource "hush_service_agent" "agentcore" {
  name           = "demo-agentcore-agent"
  acts_for_users = true

  aws_iam_role {
    issuer   = var.aws_issuer
    role_arn = var.agentcore_role_arn
  }
}

# The Foundry agent: signs in as its Entra agent identity, as itself. Acting
# for a user, Foundry signs the user in to the gateway instead (see foundry/).
resource "hush_service_agent" "foundry" {
  name = "demo-foundry-agent"

  azure {
    tenant_id            = var.tenant_id
    service_principal_id = var.foundry_agent_identity_id
    audience             = var.foundry_gateway_api_id
  }
}

locals {
  # Who an app is granted to: the demo's agents (as themselves, or acting for
  # any user), and the demo's users (signed in through Foundry).
  agents = [hush_service_agent.agentcore.id, hush_service_agent.foundry.id]
}

# DeepWiki's public MCP server. It needs no sign-in, so the agents can use it
# as themselves.
resource "hush_custom_mcp_application" "deepwiki" {
  name         = "deepwiki-demo"
  display_name = "DeepWiki (demo)"

  url {
    url = "https://mcp.deepwiki.com/mcp"
  }

  tool {
    name = "read_wiki_structure"
    type = "read"
  }
  tool {
    name = "read_wiki_contents"
    type = "read"
  }
  tool {
    name = "ask_wiki_question"
    type = "read"
  }
}

resource "hush_mcp_application" "deepwiki" {
  app_catalog_id = hush_custom_mcp_application.deepwiki.app_catalog_id
  display_name   = hush_custom_mcp_application.deepwiki.display_name
  deployment_ids = [var.deployment_id]

  assignment {
    condition {
      match {
        source   = "agent"
        property = "id"
        op       = "in"
        values   = local.agents
      }
    }
  }
  assignment {
    condition {
      match {
        source   = "user"
        property = "email"
        op       = "in"
        values   = var.users
      }
    }
  }
}

# Hush's own MCP server. Each user connects it with their own Hush sign-in,
# so an agent can use it only for a user, and then as that user. The gateway
# allows its read tools, asks the user before a write, and blocks the
# destructive ones.
resource "hush_mcp_application" "hush" {
  app_catalog_id = "hushsecurity"
  display_name   = "Hush (demo)"
  deployment_ids = [var.deployment_id]

  tool_defaults {
    read        = "allow"
    write       = "user_consent"
    destructive = "block"
  }

  assignment {
    condition {
      match {
        source   = "agent"
        property = "id"
        op       = "in"
        values   = local.agents
      }
    }
  }
  assignment {
    condition {
      match {
        source   = "user"
        property = "email"
        op       = "in"
        values   = var.users
      }
    }
  }
}

output "agentcore_agent_id" {
  value = hush_service_agent.agentcore.id
}

output "agentcore_resource" {
  description = "What users sign in for, to let the AgentCore agent act for them"
  value       = hush_service_agent.agentcore.resource
}

output "foundry_agent_id" {
  value = hush_service_agent.foundry.id
}

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

# The two agents, both acting for users. Here they sign in with a secret; any
# other way an agent signs in works the same.
resource "hush_service_agent" "front" {
  name           = "hand-off-front-agent"
  acts_for_users = true
}

resource "hush_service_agent_client_secret" "front" {
  agent_id = hush_service_agent.front.id
}

resource "hush_service_agent" "specialist" {
  name           = "hand-off-specialist-agent"
  acts_for_users = true
}

resource "hush_service_agent_client_secret" "specialist" {
  agent_id = hush_service_agent.specialist.id
}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

# DeepWiki's public MCP server, for the specialist to call. Its tools are
# listed as read, which the gateway allows.
resource "hush_custom_mcp_application" "deepwiki" {
  name         = "deepwiki-hand-off-agents"
  display_name = "DeepWiki (hand-off-agents example)"

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

# DeepWiki on the gateway, granted to the specialist: the agent that calls it.
# The front agent needs no apps to hand a user off. Acting for a user, the
# specialist also needs the app to admit that user: here, every user
# (assign_all).
resource "hush_mcp_application" "deepwiki" {
  app_catalog_id = hush_custom_mcp_application.deepwiki.app_catalog_id
  display_name   = hush_custom_mcp_application.deepwiki.display_name
  deployment_ids = [var.deployment_id]
  assign_all     = true

  assignment {
    condition {
      match {
        source   = "agent"
        property = "id"
        op       = "eq"
        value    = hush_service_agent.specialist.id
      }
    }
  }
}

output "front_agent_id" {
  value = hush_service_agent.front.id
}

output "front_secret" {
  value     = hush_service_agent_client_secret.front.secret
  sensitive = true
}

output "front_resource" {
  description = "What users sign in for, to let the front agent act for them (sign_in.py)."
  value       = hush_service_agent.front.resource
}

output "specialist_agent_id" {
  value = hush_service_agent.specialist.id
}

output "specialist_secret" {
  value     = hush_service_agent_client_secret.specialist.secret
  sensitive = true
}

output "specialist_resource" {
  description = "What the front agent names to hand a user off to the specialist."
  value       = hush_service_agent.specialist.resource
}

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

# The agent, and a secret it signs in with: for a workload with no identity of
# its own. To rotate, add a second secret, move the agent to it, then remove
# the first.
resource "hush_service_agent" "example" {
  name = "client-secret-agent"
}

resource "hush_service_agent_client_secret" "example" {
  agent_id = hush_service_agent.example.id
}

variable "deployment_id" {
  description = "The gateway's deployment id (dep-...)"
  type        = string
}

# DeepWiki's public MCP server. It needs no sign-in, so the agent can use it
# as itself. Its tools are listed as read, which the gateway allows.
resource "hush_custom_mcp_application" "deepwiki" {
  name         = "deepwiki-client-secret-agent"
  display_name = "DeepWiki (client-secret-agent example)"

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

# DeepWiki on the gateway, granted to the agent.
resource "hush_mcp_application" "deepwiki" {
  app_catalog_id = hush_custom_mcp_application.deepwiki.app_catalog_id
  display_name   = hush_custom_mcp_application.deepwiki.display_name
  deployment_ids = [var.deployment_id]

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

output "agent_id" {
  description = "Grant more apps to the agent with an assignment rule on agent.id = this."
  value       = hush_service_agent.example.id
}

output "secret" {
  description = "The agent's secret: terraform output -raw secret"
  value       = hush_service_agent_client_secret.example.secret
  sensitive   = true
}

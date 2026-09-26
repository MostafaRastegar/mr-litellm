# LiteLLM Skills & Hosted MCP Architecture Guide

This document explores Model Context Protocol (MCP) for connecting models to external tools and unified management of AI plugins via the LiteLLM Marketplace (Skills).

---

## 1. Introduction to MCP and External Tools

### Traditional Local MCP Model and Its Challenges:
The Model Context Protocol (MCP), introduced by Anthropic, enables AI models to connect to live data sources (databases, local file systems, internal corporate APIs, and wikis).
In the traditional local model, every developer must manually run an MCP server on their laptop using Node.js or Python:
- **Security Risks:** Production/staging database credentials and API keys must be copied and stored individually on every developer's local machine.
- **Setup Overhead:** Every developer faces package installation errors, local port collisions, and cross-operating system compatibility issues.

### Hosted MCP Architecture in LiteLLM:
The LiteLLM server acts as a **Secure Centralized Gateway for MCP Servers**. Database or document servers are configured once inside LiteLLM, and all users connect to them through a standard, unified endpoint:
`http://proxy:4000/<server_name>/mcp`

**Organizational Advantages:**
1. **Enhanced Security:** Database and service connection strings remain on the server; developers only connect using LiteLLM authentication tokens.
2. **Access Control:** Administrators define which teams or users have access to which specific tools.
3. **Full Logging & Auditing:** All queries and tool calls are centrally recorded for compliance.

---

## 2. Custom CLI Tools

To bridge the gap between Anthropic's standard Claude Code marketplace and other popular developer environments (such as Cline in VS Code or OpenCode in the terminal), two custom CLI tools were developed:

### A) The `litellm-mcp` Tool:
Manages and automatically connects MCP servers registered in LiteLLM to local agents:
- Detects the appropriate transport protocol for each agent:
  - **Cline:** Configured with `streamableHttp`
  - **OpenCode:** Configured as `remote` (preserving JSONC comments)
  - **Claude Code:** Configured as `http`
- Automatically injects the `Authorization: Bearer <token>` header from environment variables or the admin key.

### B) The `litellm-marketplace` Tool:
Manages downloading and installing Skills from the LiteLLM hosted marketplace (`/claude-code/marketplace.json`):
- Downloads plugins into an isolated cache (`~/.litellm-marketplace/git-cache`).
- Maps and copies `SKILL.md` files to standard agent paths:
  - Cline: `~/.cline/skills/<name>/SKILL.md`
  - OpenCode: `~/.config/opencode/skills/<name>/SKILL.md`
  - Claude: `~/.claude/skills/<name>/SKILL.md`
- Records installs in a local `manifest.json` to guarantee clean, residue-free removal.

---

## 3. End-to-End Walkthrough

Here is a complete scenario demonstrating the connection to an intelligent documentation server (`deepwiki`) and querying it using the Cline agent:

### Step 1: Verify Environment Health
```bash
litellm-marketplace doctor
```
This confirms the proxy is reachable and configuration files for all three agents were detected successfully.

### Step 2: Discover Available Tools on the Server
```bash
litellm-mcp list
# Output:
#   LiteLLM MCP Servers (http://localhost:4000/v1/mcp/server)
#     postgresql   Query and manage PostgreSQL databases with read-only access
#     deepwiki     DeepWiki public MCP
```

### Step 3: Register and Connect the Tool
The developer simply runs the following command to add the tool to their local environment:
```bash
litellm-mcp install deepwiki
```
Agent configuration files are updated atomically, making the tool immediately active in the IDE.

### Step 4: Execute Query in the Editor
The developer chats with the AI agent in VS Code:
> "Inspect the documentation structure of the BerriAI/litellm repository using the deepwiki tool and explain how Provider Fallback is configured."

**Behind the Scenes:**
1. The agent detects the `deepwiki` tool and sends a Tool Call request to the LiteLLM proxy.
2. The gateway authenticates the request, extracts the documentation, and returns it.
3. If the returned tool text is massive, the **RTK Saver** hook compresses the document without semantic loss so the context window does not overflow.
4. The model returns a precise, succinct, and focused final response.

---

## 4. Command Reference (CLI Cheat-Sheet)

```bash
# Environment and agent health checks
litellm-marketplace doctor

# Working with Skills & Plugins
litellm-marketplace list              # List available plugins
litellm-marketplace info <plugin>     # Show details and skills
litellm-marketplace install <plugin>  # Install skills on all agents
litellm-marketplace update <plugin>   # Pull latest changes from git
litellm-marketplace remove <plugin>   # Clean uninstall & manifest cleanup

# Working with Corporate Tools (Hosted MCP)

litellm-mcp list                      # Show available hosted servers
litellm-mcp install <server>          # Connect server on all agents
litellm-mcp install <server> --agent cline # Connect only to Cline editor
litellm-mcp sync                      # Sync all accessible servers
litellm-mcp remove <server>           # Disconnect and clean configuration

```

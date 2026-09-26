# LiteLLM Documentation Index

This directory contains technical architecture references, comparative engineering analyses, and practical guides for the LiteLLM Token Saver and Agent Discovery tooling.

---

## Documents

### 1. [RTK Architecture and Request Lifecycle Flow](./01-rtk-architecture-and-flow.md)
* **Audience:** Technical managers, DevOps engineers, and system architects.
* **Topics Covered:**
  - Deprecation of the 9Router network hop in favor of in-process execution.
  - End-to-end request lifecycle flow and fail-open resilience guarantees.
  - The 12 deterministic RTK filters for tool output compression.
  - Detailed character, line, and token metrics for Caveman and Ponytail prompt stylers.
  - Virtual key metadata configuration and predefined profiles (Programmer, Content, Disabled).
  - Real-time logging, metrics aggregation, and dollar savings estimation.

---

### 2. [Comparative Analysis: Gateway RTK vs Client-Side `Agent.md`](./02-rtk-vs-agents-md.md)
* **Audience:** Project managers and engineering leads.
* **Topics Covered:**
  - Technical matrix comparing gateway-level RTK filtering against repository-level `Agent.md`.
  - Why client-side prompts cannot shrink raw tool/terminal bytes or deduplicate history.
  - Context window degradation risks and token expenditure economics.
  - Recommended hybrid best-practice pattern for engineering teams.

---

### 3. [Agent Skills & Hosted MCP Architecture Guide](./03-skills-and-mcp-guide.md)
* **Audience:** Software developers, AI engineers, and IDE agent users.
* **Topics Covered:**
  - Traditional local MCP vs LiteLLM Hosted MCP security advantages.
  - Centralized credential management avoiding local distribution of database secrets.
  - The `litellm-marketplace` and `litellm-mcp` unified CLI tools.
  - End-to-end walkthrough using the `deepwiki` documentation tool with the Cline agent.
  - Command reference and everyday cheat-sheet.

---

### 4. Structural Module Guides
* **[Internal Architecture of `rtk_saver`](../rtk_saver/README.md):** Detailed breakdown of components ported from 9Router vs custom LiteLLM gateway code.
* **[Tooling & Scripts Categorization (`tools/`)](../tools/README.md):** Categorized index of CLI tools, financial reporting, parity validation, and testing harnesses.


# Comparative Analysis: Gateway RTK Compression vs Client-Side `Agent.md`

A fundamental question engineering teams face: **Would it be better to place all instructions and behaviors directly inside repository files (`Agent.md` or `SKILL.md`) instead of relying on server-side injection and filters in LiteLLM?**

This document provides an in-depth technical, traffic, economic, and security analysis comparing both approaches and outlines how they should work together.

---

## 1. Comprehensive Technical Comparison Matrix

| Technical Aspect | Approach 1: Gateway Layer (LiteLLM RTK Saver) | Approach 2: Client / Repository (`Agent.md`) |
|---|---|---|
| **Processing Location** | In-process proxy hook on the LiteLLM server | Inside the developer's local agent prompt |
| **Tool Output Compression (RTK)** | **Available** (shrinks heavy test, git, tree, build logs) | **Not available** (tools pass raw, heavy payloads) |
| **Historical Deduplication** | **Available** (removes repeated tool outputs from history) | **Not available** (history repeats full tool outputs) |
| **Context Window Utilization** | Highly efficient (reduces session traffic by 40% to 90%) | High overhead (rule file occupies context on every request) |
| **Independence from Client Tooling** | 100% independent (supports Cline, OpenCode, Claude Code, curl, ...) | Client-dependent (each client must parse the file format) |
| **Governance & Cost Caps** | Centralized; strict administrator control over the organization | Decentralized; developers can delete or edit files |
| **Adaptation to Business Domains** | Generic (optimizes traffic and styles brevity) | **Very high** (defines project-specific business rules and standards) |

---

## 2. Deep Dive: Gateway Compression (RTK Saver)

### Key Advantages:
1. **True Byte-Level Data Compression:**
   Client-side prompts like `Agent.md` can tell the model to "answer briefly," but they **cannot prevent** a failed test or `git diff` from spilling 100,000 characters of raw logs into the context window. This is handled exclusively in the gateway layer by deterministic RTK Python filters before it ever reaches the model.
2. **Financial Transparency & Unified Accounting:**
   Without requiring changes to developer tools, traffic for all teams is optimized, and dollar/token savings metadata is accurately calculated and recorded.
3. **Context Window Stability:**
   In long sessions, by removing duplicate outputs and truncating tool blobs, the context window fills up much slower, preventing Context Overflow errors.

### Limitations:
- Not suited for teaching highly specific company business concepts (the gateway should not be burdened with individual team domain details).

---

## 3. Deep Dive: Repository-Local Skills (`Agent.md` / `SKILL.md`)

### Key Advantages:
1. **Flexibility and Project Personalization:**
   Teams can write rules such as "Follow Clean Architecture in module X" or "Tests must always run via PyTest."
2. **No Gateway Admin Involvement:**
   Developers commit their agent rules directly to git without needing admin access to the proxy server.

### Limitations:
- **Repetitive Token Overhead:** On every agent call, the entire text of `Agent.md` is read and injected as input context, driving up input token costs.
- **No Control Over Tool Outputs:** These files cannot censor, optimize, or compress raw Bash and Terminal outputs.

---

## 4. Recommended Hybrid Strategy

The official recommendation for organizations is to adopt a hybrid pattern:

```
┌──────────────────────────────────────────────────────────────┐
│                  Recommended Organization Strategy            │
├───────────────────────────────┬──────────────────────────────┤
│ Infrastructure Layer (LiteLLM) │ Tool Compression (RTK)        │
│                               │ Data Deduplication (Dedupe)   │
│                               │ Tone Smoothing (Caveman)      │
├───────────────────────────────┼──────────────────────────────┤
│ Repository Layer (Agent.md)    │ Project Coding Standards      │
│                               │ Testing Rules                 │
│                               │ Architecture & Business Domain│
└───────────────────────────────┴──────────────────────────────┘
```


- The proxy infrastructure guarantees that the traffic sent to the model has the minimum possible byte size and cost.
- The client-side `Agent.md` guarantees that the generated code strictly adheres to the product's quality and architectural requirements.

By doing this:
- زیرساخت پروکسی تضمین می‌کند ترافیک ارسالی به مدل حداقل هزینه و حجم را دارد.
- فایل `Agent.md` کلاینت تضمین می‌کند که کد تولیدی با نیازمندی‌های کیفی محصول مطابقت دارد.

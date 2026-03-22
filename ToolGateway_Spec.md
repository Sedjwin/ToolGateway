# ToolGateway Specification

Status: Planning draft

## Purpose

This document proposes a new `ToolGateway` service for the local AI stack.

The intent is to make the service boundaries explicit:

- `AIGateway` manages LLM routing, model policy, provider connectivity, and LLM request logging.
- `AgentManager` manages agents, their memory, storage, private history, setup, and assigned permissions.
- `ToolGateway` manages tool registry, tool policy, execution control, approval workflow, and tool execution logging.

The design goal is to give the system the same level of control over tools that it already has over models.

## Core Position

`ToolGateway` should mirror the role of `AIGateway`, but for tools instead of models.

- `AIGateway` decides which brain can be used.
- `ToolGateway` decides which hands can be used.
- `AgentManager` decides what an agent is intended to have access to.

This preserves a clear separation between agent identity, model routing, and tool execution.

## Goals

- Centralize all tool execution behind one service boundary.
- Allow tools to be globally enabled, disabled, quarantined, or overruled at runtime.
- Support first-party custom tools as the main path.
- Support importing existing skills, MCP tools, and external tool packs in a controlled way.
- Require human approval before new external tools become runnable.
- Keep a full audit trail of tool installation, granting, denial, and execution.
- Make it possible to instantly revoke dangerous or broken tools without editing agents.

## Non-Goals

- `ToolGateway` is not a replacement for `AIGateway`.
- `ToolGateway` does not own agent memory, private storage, or conversation history.
- `AgentManager` should not execute tools directly.
- New tools should not auto-install, auto-enable, or auto-update.
- Imported skills should not automatically receive execution privileges.

## Service Responsibilities

### AIGateway

Owns:

- model registry
- provider connectivity
- smart routing and model selection
- allowed and blocked models
- local and external model configuration
- LLM request logging

Does not own:

- agent memory
- agent storage
- tool registry
- tool execution

### AgentManager

Owns:

- agent identity and metadata
- system prompt and personality profile
- memory and private agent storage
- session history and interaction logs
- desired per-agent grants and setup
- skill assignment

Does not own:

- model execution
- provider routing
- direct tool execution
- global tool approval

### ToolGateway

Owns:

- tool registry
- tool versions
- install and import workflow
- approval queue
- runtime policy enforcement
- emergency disable and override controls
- tool execution
- tool execution logs
- tool-level secrets and runtime configuration

Does not own:

- agent memory
- agent history
- model routing
- agent prompt/personality management

### Dashboard

Owns the human control plane for:

- tool review and approval
- tool install requests
- tool enable/disable actions
- tool grant management views
- execution logs and audit views

### UserManager

Owns:

- human authentication
- agent principals
- service-to-service validation

It should remain the identity source of truth for both humans and non-human principals.

## Recommended Access Model

Tool access should be split into two layers:

### Desired Access

Stored in `AgentManager`.

This expresses what an agent is intended to be allowed to use.

Examples:

- assigned tools, per agent
- assigned skills
- private agent storage location
- agent-specific configuration

`AgentManager` may assign a tool to an agent even if that tool is not currently executable in `ToolGateway`.

This is intentional. Assignment expresses agent configuration and prompt context, not final runtime authority.

### Effective Access

Enforced in `ToolGateway`.

This expresses what is actually runnable at the moment of execution.

Effective tool access should be:

- granted to the agent in `AgentManager`
- present in `ToolGateway`
- approved for use
- currently enabled
- not globally blocked or suspended
- correctly configured with any required secrets or setup

This gives the system a hard override layer. An agent may be configured to have a tool, but `ToolGateway` can still deny execution immediately.

Runtime denial by `ToolGateway` should be treated as a normal structured result, not as a system failure.

All effective tool access is per agent.

There is no group-based or role-based grant model in the current design. That may be added later, but it is out of scope for this version.

## Key Design Rule

`AgentManager` should never execute tools directly.

It should only request tool execution from `ToolGateway`, in the same way that it should rely on `AIGateway` for model execution.

This keeps:

- one enforcement point
- one logging point
- one emergency shutdown point

## Tool Prompting

If an agent has any assigned tools, `AgentManager` should add a standard tool preamble to the system prompt.

This preamble should explain:

- the agent may attempt to use tools when appropriate
- the listed tools are the tools configured for that agent
- `ToolGateway` is the final authority on whether a call is allowed
- tool access can change at any time
- a denied tool call should be handled gracefully rather than treated as a crash

After this preamble, the assigned tools should be listed with their usage guidance.

This gives every tool-capable agent a consistent operating model without requiring each prompt author to explain the same system behavior manually.

## Tool Categories

`ToolGateway` should support several tool classes:

### First-Party Tools

Tools written locally and maintained as trusted system tools.

Examples:

- internal service wrappers
- file or storage helpers
- device control integrations
- automation utilities

### Custom Local Tools

User-created tools that run locally and are versioned in the system.

This is expected to be the main tool path.

### External or Imported Tools

Tools brought in from outside the local codebase.

Examples:

- MCP-exposed tools
- imported tool packs
- remote wrappers

These must enter the system in a non-runnable state until approved by a human.

### Skills

Skills should be treated separately from executable tools.

A skill is a prompt or workflow package, not an executable capability by default.

Skills may:

- shape how an agent behaves
- tell an agent when to use certain tools
- bundle recommended tools

But a skill should not automatically grant runtime tool privileges.

Skills do not require a separate long-term versioning model in this design.

They remain static until an admin changes them manually.

## MCP and Imported Tool Policy

Imported MCP tools should not be trusted as a group.

Recommended rule:

- import source metadata may be stored
- each imported tool becomes a normal `ToolGateway` tool record
- each imported tool version must be reviewed and approved individually
- the source itself does not create blanket trust

This protects against compromised, badly maintained, or malicious tool sources.

## Approval Lifecycle

Recommended tool lifecycle:

1. `requested`
2. `pending_review`
3. `quarantined`
4. `approved`
5. `assignable`
6. `granted`
7. `active`
8. `suspended` or `blocked`
9. `retired`

All tools are treated equally at approval time.

Whether a tool was discovered by the admin directly or requested by an agent, it still requires admin installation and approval before use.

Built-in, local, requested, and imported tools all follow the same approval and installation path in this design.

### Request Flow

Agents may request a tool to be added.

That request should only create a review item. It must not install or enable the tool automatically.

### Human Approval Required For

- importing a new external tool
- installing a new tool
- enabling a new tool version
- assigning sensitive secrets
- granting dangerous tools to agents
- upgrading or replacing an existing imported tool version

Per-use approval is not a separate architectural layer.

If needed, it should be configured by the admin as part of the tool's normal policy and filter setup.

## Policy and Filter Layer

Every tool call may pass through an optional policy and filter layer before and after execution.

This layer is independent of whether the agent holds a grant for the tool.

- grants control whether the tool may be attempted
- filters control how request and response data are handled

Filters are authoritative. Agents must not be able to override, bypass, or weaken them through prompt instructions or tool arguments.

### Filter Phases

Filters are split into two phases:

- **Incoming filters** — run before the tool is called
- **Outgoing filters** — run after the tool returns, before the result is returned to the caller

The normal flow is:

1. `ToolGateway` receives the tool call
2. first matching incoming filter is applied
3. filtered request is sent to the tool
4. first matching outgoing filter is applied to the tool result
5. filtered result is returned by `ToolGateway`

If no filter matches in a phase, data passes through unchanged.

### Filter Priority

Each filter has an explicit priority.

If multiple filters could apply in the same phase, only the highest-priority matching filter is used.

This means:

- no chaining of multiple filters in the same phase
- no combining of multiple matching filters
- first applicable filter wins

Priority is therefore the conflict-resolution mechanism for overlapping filters.

### Filter Scope

Each filter is assigned one of:

- **All principals** — applies to every agent and human invoking the tool.
- **Selected principals** — a named list of agents or users. The filter only runs for those principals.

Filters assigned to selected principals do not affect others. Multiple principal-scoped filters can exist on the same tool with different named lists and different rules.

### Filter Types

#### Logical Filters

Deterministic, rule-based checks on tool call parameters.

These run instantly without calling a model and should be the default for simple restrictions.

Available conditions:

| Condition | Description |
|---|---|
| `contains` | Parameter value contains a given string |
| `not_contains` | Parameter value does not contain a given string |
| `matches` | Parameter value matches a regex pattern |
| `equals` | Parameter value exactly equals a given value |
| `in_list` | Parameter value is in a defined set |
| `not_in_list` | Parameter value is not in a defined set |
| `starts_with` | Parameter value starts with a given prefix |
| `ends_with` | Parameter value ends with a given suffix |

Conditions can be combined with `AND`, `OR`, and `NOT` operators to form compound rules.

Target can be:

- a named tool parameter (e.g. `destination`, `subject`, `body`)
- a tool variable (e.g. `allowed_domains`)
- the full serialised call (for a catch-all string scan)

Example:

```
IF destination NOT ends_with "@ourpersonalemail.com"
AND principal IS agent5
THEN reject: "agent5 may only send to ourpersonalemail.com"
```

#### Agent-Evaluated Filters

AI-evaluated checks where a logical condition is insufficient or too brittle to express.

The admin selects an evaluator agent from `AIGateway` and writes a natural language policy question. At execution time, `ToolGateway` sends the full tool call context to that evaluator agent and receives an allow or deny decision with a reason.

`ToolGateway` does not directly choose a model for this evaluation. Routing, model allowlists, fixed-model behavior, offline-only behavior, and smart routing remain under the chosen evaluator agent's existing `AIGateway` policy.

Configuration:

- **Evaluator agent**: a specific `AIGateway` agent selected by the admin
- **Policy question**: a natural language statement of the intent to evaluate, e.g. *"Will this email cause reputational harm to the organisation?"*
- **Confidence threshold**: optionally require the model to express confidence above a threshold before the decision is trusted
- **Fallback**: what happens if the model is unavailable — allow, deny, or escalate to human

Agent-evaluated filters are more expensive and slower than logical filters. They should be used where judgement is required, not as a substitute for simple string checks.

Example:

```
EVALUATOR AGENT: moderation_offline
QUESTION: "Does this message contain content that could embarrass the organisation or be considered harassment?"
ON DENY: reject with model's stated reason
ON MODEL UNAVAILABLE: deny and escalate to admin
```

The evaluator agent receives: tool name, parameters, calling agent identity, session context, and the policy question. It does not receive unrelated agent history.

For auditability, `ToolGateway` should log both:

- which evaluator agent was used
- which model `AIGateway` ultimately routed that evaluator agent to

### Rejection Response

When a filter rejects a call, `ToolGateway` returns a structured denial. The agent receives this as a tool result, not a crash.

```json
{
  "status": "rejected",
  "filter_type": "logical",
  "filter_name": "domain-restriction",
  "reason": "agent5 may only send to ourpersonalemail.com",
  "principal": "agent5",
  "tool": "email"
}
```

The agent can use this to explain the situation to the user, attempt an alternative, or surface it as a workflow block. All rejections are logged in `ToolGateway` with full context.

### Filter Actions

Depending on the phase, a filter may:

- pass data unchanged
- modify data
- redact data
- summarise data
- replace data with a minimal acknowledgement
- deny the call or deny the return

Incoming filters are intended for request shaping and request blocking.

Examples:

- remove a disallowed field before the tool sees it
- strip a password or token from the request
- deny a request entirely

Outgoing filters are intended for response shaping and response blocking.

Examples:

- redact sensitive content
- replace a long response with a summary
- return `tool complete, output redacted`

### Filter Transparency

Each filter should define whether its modification is:

- transparent to the agent
- explicitly disclosed in the returned metadata

This should be configurable per filter.

### Tool Variables

Each tool may declare a set of named variables — configuration values with defaults that affect how the tool behaves.

Examples:

- `allowed_domains` — list of permitted email recipient domains
- `max_attachment_size_mb` — upper limit on attachments
- `rate_limit_per_hour` — maximum calls allowed per hour

Defaults are set by the tool author. Admins may override tool variables at:

- **Tool level** — applies to all uses of the tool globally
- **Grant level** — applies only when a specific agent uses the tool

Variables can be referenced inside logical filters so that filter rules stay generic and the values remain configurable.

Example: a domain filter references `allowed_domains` rather than hard-coding domain strings. The admin then sets `allowed_domains` differently per agent grant.

### Filter Wizard

The Dashboard should provide a guided interface for creating filters without writing code.

#### Logical Filter Wizard

Step-by-step form that:

1. Selects scope (all principals / selected principals)
2. Selects target parameter or tool variable
3. Selects condition type from a dropdown
4. Enters the comparison value
5. Optionally adds more conditions with AND/OR
6. Sets the rejection message
7. Previews the rule in plain English before saving

#### Model Filter Wizard

Guided form that:

1. Selects scope
2. Selects evaluator agent from the `AIGateway` agent list
3. Provides a free-text policy question field with helper text
4. Sets fallback behaviour (allow / deny / escalate)
5. Shows a dry-run panel where the admin can paste a sample call and see what the model would decide

Both wizards save the filter as a versioned record in `ToolGateway`. Filters can be enabled, disabled, or deleted without removing the tool grant.

---

## Runtime Execution Flow

Recommended runtime flow:

1. A human starts an agent session through the UI.
2. `AgentManager` loads the agent, memory, grants, and assigned skills.
3. The agent decides a tool is needed.
4. `AgentManager` requests execution from `ToolGateway`.
5. `ToolGateway` validates:
   - calling principal
   - agent identity
   - session context
   - tool grant
   - tool state
   - version approval
   - required configuration and secrets
6. `ToolGateway` runs the incoming filter phase:
   - matching is based on scope and filter rules
   - only the highest-priority matching incoming filter is used
   - logical filters run inline; agent-evaluated filters call `AIGateway`
   - a rejection returns a structured denial immediately
7. `ToolGateway` either:
   - executes the tool using the filtered request
   - denies and returns a structured denial (from validation or incoming filters)
   - returns that approval or setup is required
8. `ToolGateway` runs the outgoing filter phase:
   - only the highest-priority matching outgoing filter is used
   - the result may be passed, redacted, summarised, replaced, or denied
9. `AgentManager` uses the returned result in the ongoing conversation.
10. `ToolGateway` logs the execution, filter outcomes, and result.

## Human-Run Tools

Normal users should not invoke tools directly. They should always do so through an agent.

The only direct human-to-tool path should be admin testing and administration through the Dashboard.

Agent-run tool calls should therefore use:

- the agent as the calling principal
- optional originating user or session data as audit metadata only

Admin test calls should use:

- the admin as the calling principal
- the same execution path and audit trail as normal calls, unless explicitly marked as a test mode in logs

## Logging

`ToolGateway` should log the full request and full response at the `ToolGateway` boundary.

This means:

- the incoming tool call as received by `ToolGateway`
- the filtered request actually sent to the tool
- the raw tool response returned to `ToolGateway`
- the filtered response returned by `ToolGateway`
- the filter decisions applied on the way in and out

This logging is limited to the `ToolGateway` call boundary.

`ToolGateway` is not responsible for building a sandbox-style internal execution trace of what the tool itself did after it received the request.

If a tool requires deeper internal logging, that is the tool's own responsibility.

## Data Ownership

### AgentManager should store

- agent records
- memory and conversation history
- private agent storage path
- assigned tools
- assigned skills
- agent-level configuration and access intent

### ToolGateway should store

- tools
- tool versions
- tool metadata
- install state
- approval state
- execution policy
- tool secrets or secret bindings
- execution logs
- install and upgrade requests

### AIGateway should store

- provider settings
- model registry
- model policy
- model availability
- LLM request logs

## Security Principles

- default deny
- explicit approval for imported tools
- explicit versioning
- no automatic activation
- no automatic upgrades
- central kill switch
- full execution logging
- least privilege by default

Each tool should declare its required capabilities, such as:

- network access
- filesystem reads
- filesystem writes
- subprocess access
- device access
- secret access
- long-running background behavior

Dangerous capabilities should be visible in the approval UI before a tool is enabled.

All tools are restricted to permitted agents only.

Tool use is never generally open. If an agent is not already permitted to use a tool, `ToolGateway` must deny the request.

## Relationship to VoiceService

`VoiceService` should remain core infrastructure for interaction agents.

It should not be converted into a normal optional tool for personality-based voice agents.

Reason:

- STT and TTS are part of the communication pipeline for interaction agents
- low latency and predictable behavior matter more than discretionary invocation
- voice is a modality layer, not just an optional capability

Optional future direction:

- `ToolGateway` may expose built-in speech helper tools backed by `VoiceService`
- this is useful for functional agents or human-run actions
- but the core voice path for interaction agents should remain direct infrastructure

## Recommended Rollout

### Phase 1

Create `ToolGateway` with:

- tool registry
- approval queue
- version tracking
- execution logging
- basic Dashboard admin views

### Phase 2

Add tool and skill grant models to `AgentManager`.

This makes `AgentManager` the source of truth for agent-level access intent.

### Phase 3

Add the runtime tool-execution loop between `AgentManager` and `ToolGateway`.

### Phase 4

Add agent-driven install requests that create approval items for humans.

### Phase 5

Optionally add built-in wrappers for internal services and selected infrastructure capabilities.

## Open Design Questions

No unresolved design questions remain in this draft.

## Final Recommendation

Proceed with a dedicated `ToolGateway` service.

The preferred long-term architecture is:

- `AIGateway` controls brains
- `ToolGateway` controls hands
- `AgentManager` controls identity, memory, setup, and intended permissions

This keeps the system understandable, auditable, and reversible under failure or compromise.

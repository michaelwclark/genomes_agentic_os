# Real Command Output Examples

Captured by `.agentic-atlas/tools/validate-cli.sh` against a scratch root.
Real stdout/stderr from a working install — safe to quote verbatim in docs.

## 01-init_scratch_root
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os init --target /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root
created: /private/tmp/aos-validate/root/.agentic_root
created: /private/tmp/aos-validate/root/harness
created: /private/tmp/aos-validate/root/harness/bin
created: /private/tmp/aos-validate/root/harness/commands
created: /private/tmp/aos-validate/root/harness/skills
created: /private/tmp/aos-validate/root/harness/mcp
created: /private/tmp/aos-validate/root/harness/plugins
created: /private/tmp/aos-validate/root/harness/libraries
created: /private/tmp/aos-validate/root/harness/hooks
created: /private/tmp/aos-validate/root/harness/rules
created: /private/tmp/aos-validate/root/harness/registries
created: /private/tmp/aos-validate/root/harness/registries/capabilities.yml
created: /private/tmp/aos-validate/root/harness/registries/commands.yml
created: /private/tmp/aos-validate/root/harness/registries/skills.yml
created: /private/tmp/aos-validate/root/harness/registries/mcp-servers.yml
created: /private/tmp/aos-validate/root/harness/registries/libraries.yml
created: /private/tmp/aos-validate/root/harness/registries/hooks.yml
created: /private/tmp/aos-validate/root/harness/registries/plugins.yml
created: /private/tmp/aos-validate/root/harness/registries/rules.yml
created: /private/tmp/aos-validate/root/harness/INVENTORY.md
created: /private/tmp/aos-validate/root/harness/hooks/README.md
created: /private/tmp/aos-validate/root/harness/hooks/context-mode-cache-heal.mjs
created: /private/tmp/aos-validate/root/harness/hooks/conversation-auto-log.py
created: /private/tmp/aos-validate/root/harness/hooks/harness-emit-trace.sh
created: /private/tmp/aos-validate/root/harness/hooks/memory-session-start.sh
created: /private/tmp/aos-validate/root/harness/hooks/memory-stop.sh
created: /private/tmp/aos-validate/root/harness/agentic-os.lock.json
created: /private/tmp/aos-validate/root/harness/UPDATE_POLICY.md
created: /private/tmp/aos-validate/root/harness/registries/updates.yml
created: /private/tmp/aos-validate/root/harness/security
created: /private/tmp/aos-validate/root/harness/security/ssh
created: /private/tmp/aos-validate/root/harness/logs
created: /private/tmp/aos-validate/root/harness/logs/updates
created: /private/tmp/aos-validate/root/harness/logs/backups
created: /private/tmp/aos-validate/root/harness/registries/customer-identity.json
created: /private/tmp/aos-validate/root/harness/registries/backup-policy.yml
created: /private/tmp/aos-validate/root/harness/README.md
created: /private/tmp/aos-validate/root/harness/ROUTER.md
created: /private/tmp/aos-validate/root/harness/AGENTS.md
created: /private/tmp/aos-validate/root/harness/CLAUDE.md
created: /private/tmp/aos-validate/root/harness/CONTEXT.md
created: /private/tmp/aos-validate/root/harness/RULES.md
created: /private/tmp/aos-validate/root/harness/TOOLS.md
created: /private/tmp/aos-validate/root/harness/config.toml
created: /private/tmp/aos-validate/root/harness/MEMORY.md
created: /private/tmp/aos-validate/root/harness/PROFILE.md
created: /private/tmp/aos-validate/root/harness/config/codex-profile.yml
created: /private/tmp/aos-validate/root/personal
created: /private/tmp/aos-validate/root/personal/README.md
created: /private/tmp/aos-validate/root/personal/ROUTER.md
created: /private/tmp/aos-validate/root/personal/AGENTS.md
created: /private/tmp/aos-validate/root/personal/CLAUDE.md
created: /private/tmp/aos-validate/root/personal/CONTEXT.md
created: /private/tmp/aos-validate/root/personal/RULES.md
created: /private/tmp/aos-validate/root/personal/TOOLS.md
created: /private/tmp/aos-validate/root/personal/REFERENCES.md
created: /private/tmp/aos-validate/root/personal/domain.yml
created: /private/tmp/aos-validate/root/personal/config.toml
created: /private/tmp/aos-validate/root/personal/MEMORY.md
created: /private/tmp/aos-validate/root/personal/PROFILE.md
created: /private/tmp/aos-validate/root/personal/config/codex-profile.yml
created: /private/tmp/aos-validate/root/personal/00-control-plane
created: /private/tmp/aos-validate/root/personal/01-inbox
created: /private/tmp/aos-validate/root/personal/02-projects
created: /private/tmp/aos-validate/root/personal/03-workflows
created: /private/tmp/aos-validate/root/personal/04-automations
created: /private/tmp/aos-validate/root/personal/05-knowledge
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/personal/07-metrics
created: /private/tmp/aos-validate/root/personal/08-archive
created: /private/tmp/aos-validate/root/personal/00-control-plane/README.md
created: /private/tmp/aos-validate/root/personal/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/personal/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/personal/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/personal/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/personal/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/personal/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/personal/01-inbox/triage.md
created: /private/tmp/aos-validate/root/personal/02-projects/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/engineering
created: /private/tmp/aos-validate/root/personal/04-automations/engineering
created: /private/tmp/aos-validate/root/personal/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/marketing
created: /private/tmp/aos-validate/root/personal/04-automations/marketing
created: /private/tmp/aos-validate/root/personal/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/sales
created: /private/tmp/aos-validate/root/personal/04-automations/sales
created: /private/tmp/aos-validate/root/personal/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/support
created: /private/tmp/aos-validate/root/personal/04-automations/support
created: /private/tmp/aos-validate/root/personal/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/support/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/operations
created: /private/tmp/aos-validate/root/personal/04-automations/operations
created: /private/tmp/aos-validate/root/personal/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/finance
created: /private/tmp/aos-validate/root/personal/04-automations/finance
created: /private/tmp/aos-validate/root/personal/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/personal/04-automations/personal_admin
created: /private/tmp/aos-validate/root/personal/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/personal/03-workflows/learning
created: /private/tmp/aos-validate/root/personal/04-automations/learning
created: /private/tmp/aos-validate/root/personal/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/personal/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/personal/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/personal/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/personal/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/personal/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/personal/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/personal/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/personal/08-archive/README.md
created: /private/tmp/aos-validate/root/clarks_consulting
created: /private/tmp/aos-validate/root/clarks_consulting/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/ROUTER.md
created: /private/tmp/aos-validate/root/clarks_consulting/AGENTS.md
created: /private/tmp/aos-validate/root/clarks_consulting/CLAUDE.md
created: /private/tmp/aos-validate/root/clarks_consulting/CONTEXT.md
created: /private/tmp/aos-validate/root/clarks_consulting/RULES.md
created: /private/tmp/aos-validate/root/clarks_consulting/TOOLS.md
created: /private/tmp/aos-validate/root/clarks_consulting/REFERENCES.md
created: /private/tmp/aos-validate/root/clarks_consulting/domain.yml
created: /private/tmp/aos-validate/root/clarks_consulting/config.toml
created: /private/tmp/aos-validate/root/clarks_consulting/MEMORY.md
created: /private/tmp/aos-validate/root/clarks_consulting/PROFILE.md
created: /private/tmp/aos-validate/root/clarks_consulting/config/codex-profile.yml
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane
created: /private/tmp/aos-validate/root/clarks_consulting/01-inbox
created: /private/tmp/aos-validate/root/clarks_consulting/02-projects
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations
created: /private/tmp/aos-validate/root/clarks_consulting/05-knowledge
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/clarks_consulting/07-metrics
created: /private/tmp/aos-validate/root/clarks_consulting/08-archive
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/clarks_consulting/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/clarks_consulting/01-inbox/triage.md
created: /private/tmp/aos-validate/root/clarks_consulting/02-projects/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/engineering
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/engineering
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/marketing
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/marketing
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/sales
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/sales
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/support
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/support
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/support/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/operations
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/operations
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/finance
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/finance
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/personal_admin
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/learning
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/learning
created: /private/tmp/aos-validate/root/clarks_consulting/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/clarks_consulting/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/clarks_consulting/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/clarks_consulting/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/clarks_consulting/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/clarks_consulting/08-archive/README.md
created: /private/tmp/aos-validate/root/los
created: /private/tmp/aos-validate/root/los/README.md
created: /private/tmp/aos-validate/root/los/ROUTER.md
created: /private/tmp/aos-validate/root/los/AGENTS.md
created: /private/tmp/aos-validate/root/los/CLAUDE.md
created: /private/tmp/aos-validate/root/los/CONTEXT.md
created: /private/tmp/aos-validate/root/los/RULES.md
created: /private/tmp/aos-validate/root/los/TOOLS.md
created: /private/tmp/aos-validate/root/los/REFERENCES.md
created: /private/tmp/aos-validate/root/los/domain.yml
created: /private/tmp/aos-validate/root/los/config.toml
created: /private/tmp/aos-validate/root/los/MEMORY.md
created: /private/tmp/aos-validate/root/los/PROFILE.md
created: /private/tmp/aos-validate/root/los/config/codex-profile.yml
created: /private/tmp/aos-validate/root/los/00-control-plane
created: /private/tmp/aos-validate/root/los/01-inbox
created: /private/tmp/aos-validate/root/los/02-projects
created: /private/tmp/aos-validate/root/los/03-workflows
created: /private/tmp/aos-validate/root/los/04-automations
created: /private/tmp/aos-validate/root/los/05-knowledge
created: /private/tmp/aos-validate/root/los/06-runs-and-logs
created: /private/tmp/aos-validate/root/los/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/los/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/los/07-metrics
created: /private/tmp/aos-validate/root/los/08-archive
created: /private/tmp/aos-validate/root/los/00-control-plane/README.md
created: /private/tmp/aos-validate/root/los/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/los/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/los/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/los/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/los/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/los/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/los/01-inbox/triage.md
created: /private/tmp/aos-validate/root/los/02-projects/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/README.md
created: /private/tmp/aos-validate/root/los/04-automations/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/engineering
created: /private/tmp/aos-validate/root/los/04-automations/engineering
created: /private/tmp/aos-validate/root/los/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/los/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/marketing
created: /private/tmp/aos-validate/root/los/04-automations/marketing
created: /private/tmp/aos-validate/root/los/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/los/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/sales
created: /private/tmp/aos-validate/root/los/04-automations/sales
created: /private/tmp/aos-validate/root/los/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/los/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/support
created: /private/tmp/aos-validate/root/los/04-automations/support
created: /private/tmp/aos-validate/root/los/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/los/04-automations/support/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/operations
created: /private/tmp/aos-validate/root/los/04-automations/operations
created: /private/tmp/aos-validate/root/los/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/los/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/finance
created: /private/tmp/aos-validate/root/los/04-automations/finance
created: /private/tmp/aos-validate/root/los/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/los/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/los/04-automations/personal_admin
created: /private/tmp/aos-validate/root/los/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/los/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/los/03-workflows/learning
created: /private/tmp/aos-validate/root/los/04-automations/learning
created: /private/tmp/aos-validate/root/los/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/los/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/los/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/los/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/los/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/los/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/los/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/los/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/los/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/los/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/los/08-archive/README.md
created: /private/tmp/aos-validate/root/archive
created: /private/tmp/aos-validate/root/archive/README.md
created: /private/tmp/aos-validate/root/archive/ROUTER.md
created: /private/tmp/aos-validate/root/archive/AGENTS.md
created: /private/tmp/aos-validate/root/archive/CLAUDE.md
created: /private/tmp/aos-validate/root/archive/CONTEXT.md
created: /private/tmp/aos-validate/root/archive/RULES.md
created: /private/tmp/aos-validate/root/archive/TOOLS.md
created: /private/tmp/aos-validate/root/archive/REFERENCES.md
created: /private/tmp/aos-validate/root/archive/domain.yml
created: /private/tmp/aos-validate/root/archive/config.toml
created: /private/tmp/aos-validate/root/archive/MEMORY.md
created: /private/tmp/aos-validate/root/archive/PROFILE.md
created: /private/tmp/aos-validate/root/archive/config/codex-profile.yml
created: /private/tmp/aos-validate/root/archive/00-control-plane
created: /private/tmp/aos-validate/root/archive/01-inbox
created: /private/tmp/aos-validate/root/archive/02-projects
created: /private/tmp/aos-validate/root/archive/03-workflows
created: /private/tmp/aos-validate/root/archive/04-automations
created: /private/tmp/aos-validate/root/archive/05-knowledge
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/archive/07-metrics
created: /private/tmp/aos-validate/root/archive/08-archive
created: /private/tmp/aos-validate/root/archive/00-control-plane/README.md
created: /private/tmp/aos-validate/root/archive/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/archive/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/archive/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/archive/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/archive/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/archive/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/archive/01-inbox/triage.md
created: /private/tmp/aos-validate/root/archive/02-projects/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/engineering
created: /private/tmp/aos-validate/root/archive/04-automations/engineering
created: /private/tmp/aos-validate/root/archive/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/marketing
created: /private/tmp/aos-validate/root/archive/04-automations/marketing
created: /private/tmp/aos-validate/root/archive/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/sales
created: /private/tmp/aos-validate/root/archive/04-automations/sales
created: /private/tmp/aos-validate/root/archive/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/support
created: /private/tmp/aos-validate/root/archive/04-automations/support
created: /private/tmp/aos-validate/root/archive/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/support/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/operations
created: /private/tmp/aos-validate/root/archive/04-automations/operations
created: /private/tmp/aos-validate/root/archive/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/finance
created: /private/tmp/aos-validate/root/archive/04-automations/finance
created: /private/tmp/aos-validate/root/archive/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/archive/04-automations/personal_admin
created: /private/tmp/aos-validate/root/archive/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/archive/03-workflows/learning
created: /private/tmp/aos-validate/root/archive/04-automations/learning
created: /private/tmp/aos-validate/root/archive/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/archive/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/archive/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/archive/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/archive/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/archive/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/archive/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/archive/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/archive/08-archive/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory
created: /private/tmp/aos-validate/root/harness/shared_factory/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/ROUTER.md
created: /private/tmp/aos-validate/root/harness/shared_factory/AGENTS.md
created: /private/tmp/aos-validate/root/harness/shared_factory/CLAUDE.md
created: /private/tmp/aos-validate/root/harness/shared_factory/CONTEXT.md
created: /private/tmp/aos-validate/root/harness/shared_factory/RULES.md
created: /private/tmp/aos-validate/root/harness/shared_factory/TOOLS.md
created: /private/tmp/aos-validate/root/harness/shared_factory/REFERENCES.md
created: /private/tmp/aos-validate/root/harness/shared_factory/domain.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/config.toml
created: /private/tmp/aos-validate/root/harness/shared_factory/MEMORY.md
created: /private/tmp/aos-validate/root/harness/shared_factory/PROFILE.md
created: /private/tmp/aos-validate/root/harness/shared_factory/config/codex-profile.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane
created: /private/tmp/aos-validate/root/harness/shared_factory/01-inbox
created: /private/tmp/aos-validate/root/harness/shared_factory/02-projects
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/harness/shared_factory/07-metrics
created: /private/tmp/aos-validate/root/harness/shared_factory/08-archive
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/harness/shared_factory/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/harness/shared_factory/01-inbox/triage.md
created: /private/tmp/aos-validate/root/harness/shared_factory/02-projects/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/engineering
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/engineering
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/marketing
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/marketing
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/sales
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/sales
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/support
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/support
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/support/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/operations
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/operations
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/finance
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/finance
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/personal_admin
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/learning
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/learning
created: /private/tmp/aos-validate/root/harness/shared_factory/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/harness/shared_factory/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/harness/shared_factory/08-archive/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/AGENTS.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/BRAIN.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/CLAUDE.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/CONTEXT.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/ROUTER.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/RULES.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/TOOLS.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/codex-config-layer-map.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/codex-profile-manifest.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/codex-profiles.toml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/otel-mcp-contract.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/agent-config/prompt-stitching-map.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/automation
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/automation/automation.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/automation/failure-modes.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/automation/permissions.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/customer
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/customer/automation-fit-matrix.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/customer/client-automation-brief.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/customer/customer-handoff-checklist.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/domain
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/domain/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/domain/context.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/domain/domain.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/memory
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/memory/memory-policy.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/notion
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/notion/agentic-os-control-plane.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/notion/control-plane-database-spec.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/notion/domain-control-plane.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/notion/runtime-tracking-database-spec.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/planning
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/planning/feature-spec.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/planning/future-idea.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/profile
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/profile/customer-os-profile.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference/decision-log.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference/naming-conventions.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference/source-priority.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference/style-and-output-rules.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/reference/tool-index.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/room
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/room/context.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/room/router.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/room/routing-table.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/backup-policy.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/chain-rule.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/composio-debug-bundle.env.example
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/composio-debug-bundle.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/connected-system.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/dead-letter-event.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/event-envelope.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/event-ledger-index.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/event-processing-result.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/execution-target.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/heartbeat.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/integration.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/managed-templates.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/run-queue-item.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/schedule.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/self-improvement-proposal.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/self-improvement-review.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/self-improvement-usage-sidecar.json
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/self-improvement-workflow.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/self-improvement.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/source-event.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/source-provider.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/supervisor.launchd.plist.template
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/trigger-rule.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/update-grant.json
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/watch-cursor.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/runtime/watch-source.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/stage
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/stage/stage-context.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/system
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/system/host-tool-registry.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/system/shell-shape.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/HOLDOUT_QA.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/HOLDOUT_QA_RESULTS.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/IDEA.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/INVESTIGATION.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/JUDGMENT.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/MEMORY.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/NEXT.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/PLAN.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/SPEC.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/SUMMARY.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/work-item/WORKLOG.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/alignment-questions.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/approval-rules.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/context-pack.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/dispatch-handoff.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/implementation-plan.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/outcome-brief.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/prd.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/progress.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/quick-reference.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/run-log.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/templates/workflow/workflow.md
created: /private/tmp/aos-validate/root/harness/bin/README.md
created: /private/tmp/aos-validate/root/harness/commands/composio-debug-bundle.md
created: /private/tmp/aos-validate/root/harness/commands/os-capture-plan.md
created: /private/tmp/aos-validate/root/harness/commands/os-chain.md
created: /private/tmp/aos-validate/root/harness/commands/os-client-automation-brief.md
created: /private/tmp/aos-validate/root/harness/commands/os-context-audit.md
created: /private/tmp/aos-validate/root/harness/commands/os-control-plane-bootstrap.md
created: /private/tmp/aos-validate/root/harness/commands/os-create-automation.md
created: /private/tmp/aos-validate/root/harness/commands/os-create-workflow.md
created: /private/tmp/aos-validate/root/harness/commands/os-discover-rooms.md
created: /private/tmp/aos-validate/root/harness/commands/os-doctor.md
created: /private/tmp/aos-validate/root/harness/commands/os-event.md
created: /private/tmp/aos-validate/root/harness/commands/os-heartbeat.md
created: /private/tmp/aos-validate/root/harness/commands/os-integration-setup.md
created: /private/tmp/aos-validate/root/harness/commands/os-route.md
created: /private/tmp/aos-validate/root/harness/commands/os-run-build-runner.md
created: /private/tmp/aos-validate/root/harness/commands/os-run-log.md
created: /private/tmp/aos-validate/root/harness/commands/os-runtime-init.md
created: /private/tmp/aos-validate/root/harness/commands/os-self-improvement.md
created: /private/tmp/aos-validate/root/harness/commands/os-sync-notion.md
created: /private/tmp/aos-validate/root/harness/commands/os-update.md
created: /private/tmp/aos-validate/root/harness/commands/os-watch-source.md
created: /private/tmp/aos-validate/root/harness/commands/system-tool-registry.md
created: /private/tmp/aos-validate/root/harness/skills/automation-qualifier
created: /private/tmp/aos-validate/root/harness/skills/automation-qualifier/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/build-runner
created: /private/tmp/aos-validate/root/harness/skills/build-runner/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/client-automation-brief
created: /private/tmp/aos-validate/root/harness/skills/client-automation-brief/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/context-audit
created: /private/tmp/aos-validate/root/harness/skills/context-audit/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/context-pack-builder
created: /private/tmp/aos-validate/root/harness/skills/context-pack-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/control-plane-bootstrap
created: /private/tmp/aos-validate/root/harness/skills/control-plane-bootstrap/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/domain-setup
created: /private/tmp/aos-validate/root/harness/skills/domain-setup/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/event-graph-operator
created: /private/tmp/aos-validate/root/harness/skills/event-graph-operator/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/integration-setup
created: /private/tmp/aos-validate/root/harness/skills/integration-setup/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/learning-promoter
created: /private/tmp/aos-validate/root/harness/skills/learning-promoter/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/os-doctor
created: /private/tmp/aos-validate/root/harness/skills/os-doctor/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/os-navigator
created: /private/tmp/aos-validate/root/harness/skills/os-navigator/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/room-builder
created: /private/tmp/aos-validate/root/harness/skills/room-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/run-logger
created: /private/tmp/aos-validate/root/harness/skills/run-logger/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/runtime-operator
created: /private/tmp/aos-validate/root/harness/skills/runtime-operator/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/skill-registry.yml
created: /private/tmp/aos-validate/root/harness/skills/source-watcher
created: /private/tmp/aos-validate/root/harness/skills/source-watcher/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/toolsmith-reviewer
created: /private/tmp/aos-validate/root/harness/skills/toolsmith-reviewer/SKILL.md
created: /private/tmp/aos-validate/root/harness/skills/workflow-builder
created: /private/tmp/aos-validate/root/harness/skills/workflow-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/mcp/README.md
created: /private/tmp/aos-validate/root/harness/plugins/README.md
created: /private/tmp/aos-validate/root/harness/libraries/README.md
created: /private/tmp/aos-validate/root/harness/rules/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/00-start-here
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/00-start-here/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/00-start-here/update-contract.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/01-concepts
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/01-concepts/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/02-layer-map
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/02-layer-map/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/03-file-formats
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/03-file-formats/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/04-recipes
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/04-recipes/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/05-good-examples
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/05-good-examples/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/06-checklists
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/06-checklists/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/07-diagrams
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/07-diagrams/layer-map.svg
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/07-diagrams/running-os-loop.svg
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/08-harness-commands
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/08-harness-commands/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/09-troubleshooting
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/09-troubleshooting/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/index.html
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/operating-manual/manual-manifest.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/composio-debug-bundle.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-capture-plan.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-chain.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-client-automation-brief.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-context-audit.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-control-plane-bootstrap.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-create-automation.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-create-workflow.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-discover-rooms.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-doctor.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-event.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-heartbeat.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-integration-setup.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-route.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-run-build-runner.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-run-log.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-runtime-init.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-self-improvement.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-sync-notion.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-update.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/os-watch-source.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/commands/system-tool-registry.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/automation-qualifier
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/automation-qualifier/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/build-runner
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/build-runner/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/client-automation-brief
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/client-automation-brief/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/context-audit
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/context-audit/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/context-pack-builder
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/context-pack-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/control-plane-bootstrap
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/control-plane-bootstrap/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/domain-setup
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/domain-setup/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/event-graph-operator
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/event-graph-operator/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/integration-setup
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/integration-setup/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/learning-promoter
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/learning-promoter/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/os-doctor
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/os-doctor/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/os-navigator
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/os-navigator/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/room-builder
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/room-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/run-logger
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/run-logger/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/runtime-operator
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/runtime-operator/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/skill-registry.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/source-watcher
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/source-watcher/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/toolsmith-reviewer
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/toolsmith-reviewer/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/workflow-builder
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/skills/workflow-builder/SKILL.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/context-mode-cache-heal.mjs
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/conversation-auto-log.py
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/harness-emit-trace.sh
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/memory-session-start.sh
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/hooks/memory-stop.sh
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/00-current-state-and-gap-map.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/01-project-create-and-active-work.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/02-routing-and-context-builder.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/03-workflow-readiness-and-run-closeout.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/04-automation-maturity-and-reconfiguration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/05-customer-os-factory.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/06-notion-control-plane-sync.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/07-doctor-validation-and-migrations.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/08-losmon-replacement-validation.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/09-future-ideas-intake.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/10-notion-control-plane-bootstrap.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/11-room-first-installer-and-routing.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/12-factory-template-import-backlog.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/13-reference-and-skill-index-layer.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/14-client-automation-and-control-plane-playbooks.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/15-always-on-runtime-heartbeats-schedules-and-integrations.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/15-always-on-runtime-heartbeats-schedules-and-integrations.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/16-connected-source-watch-registry.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/16-connected-source-watch-registry.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/17-event-graph-and-chained-automations.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/17-event-graph-and-chained-automations.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/18-visible-capability-registry.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/18-visible-capability-registry.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/19-update-channel-and-customer-fleet.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/19-update-channel-and-customer-fleet.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/20-operator-pushed-customer-updates-and-backups.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/20-operator-pushed-customer-updates-and-backups.orchestration.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/21-harness-context-contract-and-config-toml.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/22-project-work-lifecycle-and-conversation-auto-logging.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/README.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/remaining-roadmap-orchestration-index.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/decision-log.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/naming-conventions.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/source-priority.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/style-and-output-rules.md
created: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/tool-index.md
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/self-improvement/runs
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/self-improvement/proposals
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/self-improvement/approvals
created: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/self-improvement/drafts
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/self-improvement.yml
created: /private/tmp/aos-validate/root/harness/shared_factory/04-workflows/self-improvement-review.md
created: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/managed-templates.yml
updated: /private/tmp/aos-validate/root/harness/AGENTS.md
updated: /private/tmp/aos-validate/root/personal/AGENTS.md
updated: /private/tmp/aos-validate/root/clarks_consulting/AGENTS.md
updated: /private/tmp/aos-validate/root/los/AGENTS.md
updated: /private/tmp/aos-validate/root/archive/AGENTS.md
updated: /private/tmp/aos-validate/root/harness/shared_factory/AGENTS.md
```

## 02-validate_root
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os validate --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
valid: /tmp/aos-validate/root
```

## 03-doctor
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os doctor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
ok: true
repairs: []
findings:
- severity: observation
  path: /private/tmp/aos-validate/root
  message: required files and folders are present
```

## 04-doctor_--fix-missing
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os doctor --root /tmp/aos-validate/root --fix-missing
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
ok: true
repairs:
- init os
- install docs
findings:
- severity: observation
  path: /private/tmp/aos-validate/root
  message: required files and folders are present
- severity: observation
  path: /private/tmp/aos-validate/root
  message: 'additive repair executed: init os, install docs'
```

## 05-domain_create_acme
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os domain create acme --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme
created: /private/tmp/aos-validate/root/acme/README.md
created: /private/tmp/aos-validate/root/acme/ROUTER.md
created: /private/tmp/aos-validate/root/acme/AGENTS.md
created: /private/tmp/aos-validate/root/acme/CLAUDE.md
created: /private/tmp/aos-validate/root/acme/CONTEXT.md
created: /private/tmp/aos-validate/root/acme/RULES.md
created: /private/tmp/aos-validate/root/acme/TOOLS.md
created: /private/tmp/aos-validate/root/acme/REFERENCES.md
created: /private/tmp/aos-validate/root/acme/domain.yml
created: /private/tmp/aos-validate/root/acme/config.toml
created: /private/tmp/aos-validate/root/acme/MEMORY.md
created: /private/tmp/aos-validate/root/acme/PROFILE.md
created: /private/tmp/aos-validate/root/acme/config/codex-profile.yml
created: /private/tmp/aos-validate/root/acme/00-control-plane
created: /private/tmp/aos-validate/root/acme/01-inbox
created: /private/tmp/aos-validate/root/acme/02-projects
created: /private/tmp/aos-validate/root/acme/03-workflows
created: /private/tmp/aos-validate/root/acme/04-automations
created: /private/tmp/aos-validate/root/acme/05-knowledge
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/failures
created: /private/tmp/aos-validate/root/acme/07-metrics
created: /private/tmp/aos-validate/root/acme/08-archive
created: /private/tmp/aos-validate/root/acme/00-control-plane/README.md
created: /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
created: /private/tmp/aos-validate/root/acme/00-control-plane/state-index.md
created: /private/tmp/aos-validate/root/acme/00-control-plane/decisions.md
created: /private/tmp/aos-validate/root/acme/00-control-plane/routing-rules.md
created: /private/tmp/aos-validate/root/acme/00-control-plane/approval-rules.md
created: /private/tmp/aos-validate/root/acme/01-inbox/raw-ideas.md
created: /private/tmp/aos-validate/root/acme/01-inbox/triage.md
created: /private/tmp/aos-validate/root/acme/02-projects/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/engineering
created: /private/tmp/aos-validate/root/acme/04-automations/engineering
created: /private/tmp/aos-validate/root/acme/03-workflows/engineering/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/engineering/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/marketing
created: /private/tmp/aos-validate/root/acme/04-automations/marketing
created: /private/tmp/aos-validate/root/acme/03-workflows/marketing/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/marketing/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/sales
created: /private/tmp/aos-validate/root/acme/04-automations/sales
created: /private/tmp/aos-validate/root/acme/03-workflows/sales/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/sales/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/support
created: /private/tmp/aos-validate/root/acme/04-automations/support
created: /private/tmp/aos-validate/root/acme/03-workflows/support/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/support/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/operations
created: /private/tmp/aos-validate/root/acme/04-automations/operations
created: /private/tmp/aos-validate/root/acme/03-workflows/operations/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/operations/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/finance
created: /private/tmp/aos-validate/root/acme/04-automations/finance
created: /private/tmp/aos-validate/root/acme/03-workflows/finance/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/finance/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/personal_admin
created: /private/tmp/aos-validate/root/acme/04-automations/personal_admin
created: /private/tmp/aos-validate/root/acme/03-workflows/personal_admin/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/personal_admin/README.md
created: /private/tmp/aos-validate/root/acme/03-workflows/learning
created: /private/tmp/aos-validate/root/acme/04-automations/learning
created: /private/tmp/aos-validate/root/acme/03-workflows/learning/README.md
created: /private/tmp/aos-validate/root/acme/04-automations/learning/README.md
created: /private/tmp/aos-validate/root/acme/05-knowledge/source-map.md
created: /private/tmp/aos-validate/root/acme/05-knowledge/glossary.md
created: /private/tmp/aos-validate/root/acme/05-knowledge/memory-policy.md
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/activity-log.md
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/README.md
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/failures/README.md
created: /private/tmp/aos-validate/root/acme/07-metrics/baselines.md
created: /private/tmp/aos-validate/root/acme/07-metrics/scorecards.md
created: /private/tmp/aos-validate/root/acme/08-archive/README.md
updated: /private/tmp/aos-validate/root/acme/AGENTS.md
```

## 06-project_create_acme_launch
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project create acme launch --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/02-projects/launch
created: /private/tmp/aos-validate/root/acme/02-projects/launch/README.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/decisions.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/artifacts
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config
created: /private/tmp/aos-validate/root/acme/02-projects/launch/ideas
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/02-active
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/03-complete
created: /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees
created: /private/tmp/aos-validate/root/acme/02-projects/launch/AGENTS.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/ROUTER.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/CONTEXT.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/RULES.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/TOOLS.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/MEMORY.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/README.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/index.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/ideas/README.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/ideas/raw-ideas.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/project-profile.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/workflows.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/work-lifecycle.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/output-artifacts.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/validation.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/worktrees.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/memory.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/mcps.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/tools.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config.toml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/CLAUDE.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/PROFILE.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/config/codex-profile.yml
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/AGENTS.md
updated: /private/tmp/aos-validate/root/acme/02-projects/README.md
updated: /private/tmp/aos-validate/root/acme/02-projects/README.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/state-index.md
```

## 07-project_link-source_acme_launch
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project link-source acme launch --root /tmp/aos-validate/root --repo /tmp/aos-validate/source-repo
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/02-projects/launch/src
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
```

## 08-project_onboard_acme_launch
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project onboard acme launch --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
no changes
```

## 09-project_work-item_create_intake
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project work-item create acme launch --root /tmp/aos-validate/root --title Validation intake idea --summary capture the validation intake idea
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/001_validation_intake_idea.md
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/ideas/raw-ideas.md
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/state-index.md
updated: /private/tmp/aos-validate/root/acme/MEMORY.md
```

## 10-project_work-item_create_packet
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project work-item create acme launch --root /tmp/aos-validate/root --title Validation packet idea --summary capture the expanded validation packet --format packet
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/artifacts
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/logs
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/logs/conversations
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/work.yml
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/IDEA.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/SPEC.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/PLAN.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/INVESTIGATION.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/JUDGMENT.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/HOLDOUT_QA.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/HOLDOUT_QA_RESULTS.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/WORKLOG.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/SUMMARY.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/NEXT.md
created: /private/tmp/aos-validate/root/acme/02-projects/launch/work-items/01-intake/002_validation_packet_idea/MEMORY.md
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/ideas/raw-ideas.md
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
updated: /private/tmp/aos-validate/root/acme/00-control-plane/state-index.md
updated: /private/tmp/aos-validate/root/acme/MEMORY.md
```

## 11-project_worktree_add_acme_launch
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os project worktree add acme launch source_worktree --root /tmp/aos-validate/root --path /tmp/aos-validate/source-worktree
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/source_worktree
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/index.yml
updated: /private/tmp/aos-validate/root/acme/02-projects/launch/config/worktrees.yml
```

## 12-route_a_request
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os route ship the launch blog post --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
domain: acme
lane: ''
object_type: project
target_path: /private/tmp/aos-validate/root/acme/02-projects/launch
sources_to_load:
- /private/tmp/aos-validate/root/harness/ROUTER.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/naming-conventions.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/tool-index.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/source-priority.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/style-and-output-rules.md
- /private/tmp/aos-validate/root/acme/ROUTER.md
- /private/tmp/aos-validate/root/acme/CONTEXT.md
- /private/tmp/aos-validate/root/acme/REFERENCES.md
- /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
- /private/tmp/aos-validate/root/acme/05-knowledge/memory-policy.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/AGENTS.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/ROUTER.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/CONTEXT.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/RULES.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/TOOLS.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/decisions.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/project-profile.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/workflows.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/work-lifecycle.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/output-artifacts.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/validation.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/worktrees.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/memory.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/mcps.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/tools.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/index.yml
approval_risks: []
known_gaps: []
handoff_prompt: Load the listed sources, work in /private/tmp/aos-validate/root/acme/02-projects/launch,
  follow approval rules, and record validation before closeout.
```

## 13-context_build_--domain
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os context build --domain acme --project launch --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
domain: acme
lane: ''
object_type: project
target_path: /private/tmp/aos-validate/root/acme/02-projects/launch
sources_to_load:
- /private/tmp/aos-validate/root/harness/ROUTER.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/naming-conventions.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/tool-index.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/source-priority.md
- /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/references/style-and-output-rules.md
- /private/tmp/aos-validate/root/acme/ROUTER.md
- /private/tmp/aos-validate/root/acme/CONTEXT.md
- /private/tmp/aos-validate/root/acme/REFERENCES.md
- /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
- /private/tmp/aos-validate/root/acme/05-knowledge/memory-policy.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/AGENTS.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/ROUTER.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/CONTEXT.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/RULES.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/TOOLS.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/decisions.md
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/project-profile.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/workflows.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/work-lifecycle.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/output-artifacts.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/validation.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/worktrees.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/memory.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/mcps.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/config/tools.yml
- /private/tmp/aos-validate/root/acme/02-projects/launch/worktrees/index.yml
approval_risks: []
known_gaps: []
handoff_prompt: Load the listed sources, work in /private/tmp/aos-validate/root/acme/02-projects/launch,
  follow approval rules, and record validation before closeout.
```

## 14-here_route_cwd-aware
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os here route update the launch project
# CWD: /tmp/aos-validate/root/acme
# ---
error: routing confidence is low: no domain or project matched
```

## 14-workflow_check_templated
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os workflow check acme engineering launch_blog --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
findings:
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/state-machine.md
  message: required workflow file is missing
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/output-contract.md
  message: required workflow file is missing
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/runbook.md
  message: required workflow file is missing
- severity: fix-soon
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/alignment-questions.md
  message: 'section has unresolved placeholders: Dispatch Decision'
- severity: cleanup
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/examples/README.md
  message: supporting workflow README is missing
- severity: cleanup
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/runs/README.md
  message: supporting workflow README is missing
```

## 15-automation_check_templated
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os automation check acme marketing weekly_report --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
level: observe
findings:
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/inputs.md
  message: required automation file is missing
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/outputs.md
  message: required automation file is missing
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/runbook.md
  message: required automation file is missing
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/tests.md
  message: required automation file is missing
- severity: fix-soon
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'section needs content: Outputs'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: trigger source'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: trigger frequency'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: idempotency key'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: duplicate handling'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: read permissions'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: write permissions'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: approval gates'
- severity: blocker
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  message: 'missing required evidence: outputs'
```

## 16-automation_attach_-_launch
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os automation attach acme marketing weekly_report --project launch --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
project: /private/tmp/aos-validate/root/acme/02-projects/launch
project_status: /private/tmp/aos-validate/root/acme/02-projects/launch/status.md
source_map: /private/tmp/aos-validate/root/acme/02-projects/launch/source-map.md
```

## 17-automation_set-maturity_prepare
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os automation set-maturity acme marketing weekly_report prepare --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
automation: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
old_level: observe
new_level: prepare
decision_log: /private/tmp/aos-validate/root/acme/00-control-plane/decisions.md
```

## 18-run-log_create
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os run-log create acme launch_blog --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260609T042422Z-acme-launch_blog
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260609T042422Z-acme-launch_blog/artifacts
created: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260609T042422Z-acme-launch_blog/run-log.md
```

## 19-run-log_close_20260609T042422Z-acme-launch_blog
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os run-log close acme 20260609T042422Z-acme-launch_blog --status done --summary shipped --validation manual QA passed --next-action monitor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
run_log: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260609T042422Z-acme-launch_blog/run-log.md
status: done
workflow_or_automation: launch_blog
activity_log: /private/tmp/aos-validate/root/acme/06-runs-and-logs/activity-log.md
```

## 20-profile_create
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os profile create --target /tmp/aos-validate/os.yml
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
profile: /private/tmp/aos-validate/os.yml
```

## 21-profile_validate
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os profile validate /tmp/aos-validate/os.yml
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
profile: /tmp/aos-validate/os.yml
rooms:
- writing_room
ok: true
```

## 22-runtime_init
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os runtime init --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
status: initialized
created:
- /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/heartbeats
- /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/runtime-registry.yml
- /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/integration-registry.yml
- /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/run-queue.yml
skipped:
- /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane
- /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/runs
docs_created: 0
docs_skipped: 314
```

## 23-runtime_doctor
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os runtime doctor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
ok: true
findings:
- severity: fix-soon
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/runtime-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
- severity: fix-soon
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/integration-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
```

## 24-runtime_run-next_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os runtime run-next --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
status: idle
dry_run: true
message: no queued runtime work
```

## 25-runtime_supervise_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os runtime supervise --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
tick: '2026-06-09T04:24:23Z'
root: /tmp/aos-validate/root
dry_run: true
ok: true
health_ok: true
steps:
- step: heartbeats
  ok: true
  summary:
    ok: true
    ran_count: 0
- step: schedules
  ok: true
  summary:
    status: dry-run
    queued_count: 1
    skipped_count: 1
- step: watch_sources
  ok: true
  summary:
    dry_run: true
    actions_count: 0
- step: events
  ok: true
  summary:
    dry_run: true
    actions_count: 0
- step: run_queue
  ok: true
  summary:
    status: idle
    dry_run: true
- step: health
  ok: true
  summary:
    ok: true
    findings_count: 2
```

## 26-runtime_supervise_apply
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os runtime supervise --root /tmp/aos-validate/root --apply
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
tick: '2026-06-09T04:24:23Z'
root: /tmp/aos-validate/root
dry_run: false
ok: true
health_ok: true
steps:
- step: heartbeats
  ok: true
  summary:
    ok: true
    ran_count: 0
- step: schedules
  ok: true
  summary:
    status: queued
    queued_count: 1
    skipped_count: 1
- step: watch_sources
  ok: true
  summary:
    dry_run: false
    actions_count: 0
- step: events
  ok: true
  summary:
    dry_run: false
    actions_count: 0
- step: run_queue
  ok: true
  summary:
    status: done
    dry_run: false
- step: health
  ok: true
  summary:
    ok: true
    findings_count: 2
```

## 27-heartbeat_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os heartbeat list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
heartbeats:
- id: granola_recent_notes_sync
  display_name: Granola recent notes sync
  domain: shared_factory
  enabled: false
  cadence: every_2_hours
  execution_target: script
  integration: granola
  context:
    read_first:
    - harness/shared_factory/00-control-plane/integration-registry.yml
    - harness/shared_factory/05-knowledge/source-map.md
  approval_policy:
    external_write: false
    customer_visible_output: false
    sensitive_transcript_handling: true
  success_means:
  - recent notes checked
  - run log written
  - Notion tracking updated or blocked with reason
  failure_escalation:
    after_consecutive_failures: 2
    notify: Genome
- id: agentmail_inbound_check
  display_name: AgentMail inbound check
  domain: shared_factory
  enabled: false
  cadence: hourly
  execution_target: agentmail_api
  integration: agentmail
  context:
    read_first:
    - harness/shared_factory/00-control-plane/integration-registry.yml
  approval_policy:
    external_write: false
    customer_visible_output: false
  success_means:
  - inbound queue checked
  - run log written
  failure_escalation:
    after_consecutive_failures: 2
    notify: Genome
```

## 28-heartbeat_doctor
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os heartbeat doctor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
ok: true
findings:
- severity: fix-soon
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/runtime-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
- severity: fix-soon
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/integration-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
```

## 29-schedule_create_demo
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os schedule create demo --cadence daily --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
status: created
schedule:
  id: demo
  display_name: Demo
  enabled: true
  cadence: daily
  timezone: America/Chicago
  execution_target: script
  command: agentic-os validate --root <root>
  outputs:
  - harness/shared_factory/06-runs-and-logs/runs/
  notion_update:
    object: Heartbeats
    status_field: Last Status
  next_due_at: null
  last_queued_at: null
registry: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/runtime-registry.yml
```

## 30-schedule_run-due_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os schedule run-due --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
status: dry-run
queued:
- id: queue_19c5afd56801
  kind: schedule
  ref: demo
  status: dry-run
  approval_state: not_required
  created_at: '2026-06-09T04:24:23.561794+00:00'
  dry_run: true
  due_at: '2026-06-08T05:00:00Z'
  idempotency_key: schedule:demo:2026-06-08T05:00:00Z
  execution_target: script
  command: agentic-os validate --root <root>
  log: harness/shared_factory/06-runs-and-logs/runs/20260609T042423Z-19c5afd5-demo/run-log.yml
  evidence:
  - type: run_log
    path: harness/shared_factory/06-runs-and-logs/runs/20260609T042423Z-19c5afd5-demo/run-log.yml
  blocked_reason: null
  updated_at: '2026-06-09T04:24:23.561794+00:00'
  created: true
skipped:
- schedule: daily_agentic_os_doctor
  reason: not due
  next_due_at: '2026-06-09T05:00:00Z'
- schedule: self_improvement_review
  reason: disabled
```

## 31-integration_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os integration list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
integrations:
- id: orgo
  display_name: Orgo.io
  provider: orgo.io
  status: planned
  setup_tasks:
  - Confirm approved use cases for remote desktop execution.
  - Set ORGO_API_KEY in the host environment.
  - Run a dry-run desktop health check before external writes.
  health_checks:
  - id: credential_present
    type: env
    env_var: ORGO_API_KEY
  - id: operator_approval
    type: approval
    approval: desktop execution
  approval_gates:
  - credential_changes
  - production_changes
  - customer_visible_output
  credentials:
    env_vars:
    - ORGO_API_KEY
  notion_tracking:
    database: Integrations
    fields:
    - Status
    - Last Health Check
    - Approval Gate
    - Credential State
- id: composio
  display_name: Composio
  provider: composio
  status: planned
  setup_tasks:
  - Confirm target connected account and tool slug.
  - Set COMPOSIO_API_KEY or complete composio link.
  - Run tool schema discovery before any write action.
  health_checks:
  - id: credential_present
    type: env
    env_var: COMPOSIO_API_KEY
  - id: tool_schema
    type: manual
    command: composio search <tool>
  approval_gates:
  - external_write
  - credential_changes
  - provider_account_selection
  credentials:
    env_vars:
    - COMPOSIO_API_KEY
  notion_tracking:
    database: Integrations
    fields:
    - Status
    - Connected Account
    - Tool Slug
    - Last Health Check
- id: agentmail
  display_name: AgentMail
  provider: agentmail
  status: planned
  setup_tasks:
  - Confirm inbound mailbox and retention policy.
  - Set AGENTMAIL_API_KEY in the host environment.
  - Run an inbound dry-run heartbeat before outbound mail is enabled.
  health_checks:
  - id: credential_present
    type: env
    env_var: AGENTMAIL_API_KEY
  - id: inbound_read
    type: dry_run
    command: agentic-os heartbeat run agentmail_inbound_check --dry-run
  approval_gates:
  - external_write
  - customer_visible_output
  - mail_send
  credentials:
    env_vars:
    - AGENTMAIL_API_KEY
  notion_tracking:
    database: Integrations
    fields:
    - Status
    - Mailbox
    - Last Inbound Check
    - Send Approval
- id: granola
  display_name: Granola
  provider: granola
  status: planned
  setup_tasks:
  - Confirm transcript sensitivity handling.
  - Run a local recent-notes dry run.
  - Track any Notion write as blocked until workspace verification passes.
  health_checks:
  - id: local_access
    type: manual
    command: check Granola export or local app access
  - id: pilot_heartbeat
    type: dry_run
    command: agentic-os heartbeat run granola_recent_notes_sync --dry-run
  approval_gates:
  - sensitive_transcript_handling
  - external_write
  - notion_workspace_verification
  credentials:
    env_vars: []
  notion_tracking:
    database: Integrations
    fields:
    - Status
    - Transcript Handling
    - Last Sync
    - Workspace Verified
- id: notion
  display_name: Genome's Notion
  provider: notion
  status: planned
  setup_tasks:
  - Verify the active workspace is Genome's Notion.
  - Set GENOMES_NOTION_PAT or GENOMES_NOTION_CONNECTOR if direct API fallback is needed.
  - Run track-runtime dry-run before apply.
  health_checks:
  - id: workspace_guard
    type: workspace
    expected: Genome's Notion
  - id: credential_present
    type: env_any
    env_vars:
    - GENOMES_NOTION_PAT
    - GENOMES_NOTION_CONNECTOR
  approval_gates:
  - workspace_verification
  - external_write
  - credential_changes
  credentials:
    env_vars:
    - GENOMES_NOTION_PAT
    - GENOMES_NOTION_CONNECTOR
  notion_tracking:
    database: Integrations
    fields:
    - Status
    - Workspace
    - Parent Page
    - Last Runtime Sync
```

## 32-integration_doctor
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os integration doctor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
ok: true
findings:
- severity: fix-soon
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/integration-registry.yml
  message: 'credential environment variable is not set: AGENTMAIL_API_KEY'
```

## 33-event_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os event list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
events: []
ledger: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/events/event-ledger-index.md
```

## 34-event_summary
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os event summary --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
last_events: []
pending_follow_up: []
dead_letters: []
processing_results: []
ledger: /private/tmp/aos-validate/root/harness/shared_factory/06-runs-and-logs/events/event-ledger-index.md
run_queue: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/run-queue.yml
```

## 35-event_process-due_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os event process-due --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
dry_run: true
actions: []
```

## 36-chain_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os chain list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
chain_rules:
- id: feature_merged_to_docs_update
  display_name: Feature merged creates docs follow-up
  enabled: false
  when:
    event_type: github.pull_request.merged
    filters:
      repo: genomes_agentic_os
  then:
    enqueue:
      work_type: documentation_update
      route_to: shared_factory
      workflow: docs_update_after_merge
      context_profile: merged_feature_docs
      maturity: prepare
  approval:
    required: false
  limits:
    max_chain_depth: 3
    cooldown: 10_minutes
  idempotency:
    key: '{event_idempotency_key}:feature_merged_to_docs_update'
- id: email_sent_to_crm_update
  display_name: Email sent updates CRM follow-up
  enabled: false
  when:
    event_type: email.message.sent
    filters: {}
  then:
    enqueue:
      work_type: crm_update
      route_to: shared_factory
      workflow: email_to_crm_update
      context_profile: customer_communication
      maturity: prepare
  approval:
    required: true
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:email_sent_to_crm_update'
- id: transcript_to_followup_tasks
  display_name: Meeting transcript creates follow-up task review
  enabled: false
  when:
    event_type: granola.note.created
    filters: {}
  then:
    enqueue:
      work_type: task_extraction
      route_to: shared_factory
      workflow: transcript_followup_tasks
      context_profile: meeting_transcript
      maturity: prepare
  approval:
    required: false
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:transcript_to_followup_tasks'
- id: notion_card_to_worktree
  display_name: Notion work item starts worktree preparation
  enabled: false
  when:
    event_type: notion.card.ready
    filters: {}
  then:
    enqueue:
      work_type: worktree_prepare
      route_to: shared_factory
      workflow: work_item_worktree_prepare
      context_profile: notion_work_item
      maturity: prepare
  approval:
    required: false
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:notion_card_to_worktree'
- id: run_needs_approval_to_approval_item
  display_name: Run needs approval creates approval work item
  enabled: false
  when:
    event_type: os.run.closed.needs_approval
  then:
    enqueue:
      work_type: approval_review
      route_to: shared_factory
      workflow: approval_review
      context_profile: run_closeout
      maturity: prepare
  approval:
    required: true
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:approval_item'
- id: approval_granted_dispatch
  display_name: Approval granted dispatches guarded action
  enabled: false
  when:
    event_type: os.approval.granted
    filters: {}
  then:
    enqueue:
      work_type: approved_dispatch
      route_to: shared_factory
      workflow: dispatch_approved_action
      context_profile: approval_evidence
      maturity: execute_guarded
  approval:
    required: false
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:approval_granted_dispatch'
- id: ci_failure_investigation
  display_name: CI failure queues investigation workflow
  enabled: false
  when:
    event_type: github.check_suite.failed
    filters: {}
  then:
    enqueue:
      work_type: ci_failure_investigation
      route_to: shared_factory
      workflow: investigate_ci_failure
      context_profile: github_ci_failure
      maturity: prepare
  approval:
    required: false
  limits:
    max_chain_depth: 2
  idempotency:
    key: '{event_idempotency_key}:ci_failure_investigation'
```

## 37-chain_doctor
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os chain doctor --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
ok: true
findings: []
```

## 38-connected-system_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os connected-system list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
connected_systems:
- id: notion_genome
  display_name: Genome Notion
  system: notion
  status: planned
  owner: Genome
  provider_priority:
  - notion_mcp
  - notion_connector
  - direct_api
  credential_refs:
    env_vars:
    - GENOMES_NOTION_PAT
  workspace_verification:
    required: true
    expected_workspace: Genome's Notion
  permissions:
    read:
    - database.query
    write: []
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor notion_genome
  selected_provider: notion_mcp
- id: slack_genome
  display_name: Genome Slack
  system: slack
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - slack_mcp
  - slack_connector
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - channels:history
    - groups:history
    write:
    - chat:write
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor slack_genome
  selected_provider: composio
- id: jira_genome
  display_name: Genome Jira
  system: jira
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - jira_mcp
  - jira_connector
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - issue.read
    - project.read
    write:
    - issue.write
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor jira_genome
  selected_provider: composio
- id: linear_genome
  display_name: Genome Linear
  system: linear
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - linear_mcp
  - linear_connector
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - issues:read
    - teams:read
    write:
    - issues:write
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor linear_genome
  selected_provider: composio
- id: email_genome
  display_name: Genome Email
  system: email
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - gmail_mcp
  - email_connector
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - mail.read
    write:
    - mail.send
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor email_genome
  selected_provider: composio
- id: github_genome
  display_name: Genome GitHub
  system: github
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - github_mcp
  - github_cli
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    - GITHUB_TOKEN
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - repo:read
    - pull_request:read
    write:
    - issues:write
    - pull_request:write
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor github_genome
  selected_provider: composio
- id: granola_local
  display_name: Granola Notes
  system: granola
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - granola_local
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    account_aliases: []
  workspace_verification:
    required: false
    expected_workspace: null
  permissions:
    read:
    - notes:read
    write: []
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor granola_local
  selected_provider: composio
- id: agentmail_genome
  display_name: Genome AgentMail
  system: agentmail
  status: planned
  owner: OS Owner
  provider_priority:
  - composio
  - agentmail_api
  - direct_api
  credential_refs:
    env_vars:
    - COMPOSIO_API_KEY
    - AGENTMAIL_API_KEY
    account_aliases: []
  workspace_verification:
    required: true
    expected_workspace: Genome
  permissions:
    read:
    - inbox.read
    write:
    - message.send
  approval_required_for:
  - external_write
  - customer_visible_output
  health_check:
    command: agentic-os connected-system doctor agentmail_genome
  selected_provider: composio
- id: filesystem_local
  display_name: Local Filesystem
  system: filesystem
  status: available
  owner: OS Owner
  provider_priority:
  - filesystem
  credential_refs:
    env_vars: []
  workspace_verification:
    required: false
  permissions:
    read:
    - local files
    write:
    - source-events
  approval_required_for:
  - destructive_actions
  health_check:
    command: agentic-os connected-system doctor filesystem_local
  selected_provider: filesystem
```

## 39-watch-source_list
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os watch-source list --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
watch_sources: []
```

## 40-notion_plan-sync
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os notion plan-sync --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
workspace: Genome's Notion
mapping_path: /private/tmp/aos-validate/root/.notion-sync/mapping.yml
actions:
- action: create
  kind: domain
  key: acme
  title: acme
  path: /private/tmp/aos-validate/root/acme/domain.yml
  record_key: domain:acme
  notion_id: null
  fingerprint: f8019fd16a730137fcefa2c3ee1fc810b2cd1f31af54c5ed497eab81eddadced
- action: create
  kind: active_work
  key: acme
  title: acme active work
  path: /private/tmp/aos-validate/root/acme/00-control-plane/active-work.md
  record_key: active_work:acme
  notion_id: null
  fingerprint: b29301e0fe615fe4d53f23181cf270b13a46e66b2654c08f2c6d888150baa669
- action: create
  kind: approvals
  key: acme
  title: acme approvals
  path: /private/tmp/aos-validate/root/acme/00-control-plane/approval-rules.md
  record_key: approvals:acme
  notion_id: null
  fingerprint: eaa12682a0aa62a9b88e87b1d73bb1c43effbaaccbe958d90fe1cae8a12369e5
- action: create
  kind: decisions
  key: acme
  title: acme decisions
  path: /private/tmp/aos-validate/root/acme/00-control-plane/decisions.md
  record_key: decisions:acme
  notion_id: null
  fingerprint: 76752b0b98b47852c9bf3b5f9233b964e6d610a26c7540eec5f187182c72c696
- action: create
  kind: state_index
  key: acme
  title: acme state index
  path: /private/tmp/aos-validate/root/acme/00-control-plane/state-index.md
  record_key: state_index:acme
  notion_id: null
  fingerprint: b8928dfc6f45a21665c31c73244713ac00105e68fc19abcdbf8fe5856c36977d
- action: create
  kind: metrics
  key: acme
  title: acme metrics
  path: /private/tmp/aos-validate/root/acme/07-metrics/scorecards.md
  record_key: metrics:acme
  notion_id: null
  fingerprint: 08e2c85a8f13baee9d8e05d063cffdcdc12c877298032f86bd8e450fcccaf0ae
- action: create
  kind: project
  key: acme/launch
  title: launch
  path: /private/tmp/aos-validate/root/acme/02-projects/launch/project.yml
  record_key: project:acme/launch
  notion_id: null
  fingerprint: fd946975785328af66fbd8b7886ab83afd15d9739c8490ef4f87ea7d9cd09e8d
- action: create
  kind: workflow
  key: acme/engineering/launch_blog
  title: launch_blog
  path: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/workflow.md
  record_key: workflow:acme/engineering/launch_blog
  notion_id: null
  fingerprint: 96f225ed14369075296e777079849ca6608259df8870ef92a87413d07c47c649
- action: create
  kind: automation
  key: acme/marketing/weekly_report
  title: weekly_report
  path: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/automation.md
  record_key: automation:acme/marketing/weekly_report
  notion_id: null
  fingerprint: 2467a03437db66b972d87026ae73645a3b653003aea3a2c2dfbc7ca0ce8850a3
- action: create
  kind: run
  key: acme/20260609T042422Z-acme-launch_blog
  title: 20260609T042422Z-acme-launch_blog
  path: /private/tmp/aos-validate/root/acme/06-runs-and-logs/runs/20260609T042422Z-acme-launch_blog/run-log.md
  record_key: run:acme/20260609T042422Z-acme-launch_blog
  notion_id: null
  fingerprint: 2367d99ec30df3d3024be8ddf0d5808c6be549c8e5a47f9c351f52e734f2b131
- action: create
  kind: domain
  key: archive
  title: archive
  path: /private/tmp/aos-validate/root/archive/domain.yml
  record_key: domain:archive
  notion_id: null
  fingerprint: 492f6aec21f702df00bc1a643e4e6e15b6c3fc4818e68629434dc884f9755182
- action: create
  kind: active_work
  key: archive
  title: archive active work
  path: /private/tmp/aos-validate/root/archive/00-control-plane/active-work.md
  record_key: active_work:archive
  notion_id: null
  fingerprint: 597e0167cf07ef647995d9a26e8750d9de33a6393f4423c28666f904d6e2d1f7
- action: create
  kind: approvals
  key: archive
  title: archive approvals
  path: /private/tmp/aos-validate/root/archive/00-control-plane/approval-rules.md
  record_key: approvals:archive
  notion_id: null
  fingerprint: d08c2f45621f97b938250191f8b60faf3df41c364e02a8adf0697c6a101a72c1
- action: create
  kind: decisions
  key: archive
  title: archive decisions
  path: /private/tmp/aos-validate/root/archive/00-control-plane/decisions.md
  record_key: decisions:archive
  notion_id: null
  fingerprint: 3376fd353ec39fdefd4cd6675363dd0ec9d838c01af5c7b0cadc0c5b35dfb6e7
- action: create
  kind: state_index
  key: archive
  title: archive state index
  path: /private/tmp/aos-validate/root/archive/00-control-plane/state-index.md
  record_key: state_index:archive
  notion_id: null
  fingerprint: a27e4c9ab71ef5a01303943fbc07a22c3eb400e468123cb7b6e8bc3c72d4f151
- action: create
  kind: metrics
  key: archive
  title: archive metrics
  path: /private/tmp/aos-validate/root/archive/07-metrics/scorecards.md
  record_key: metrics:archive
  notion_id: null
  fingerprint: 11d203d83ead174d79a9e0e6854a2fa366974687ffc492c97216167e8ce701b4
- action: create
  kind: domain
  key: clarks_consulting
  title: clarks_consulting
  path: /private/tmp/aos-validate/root/clarks_consulting/domain.yml
  record_key: domain:clarks_consulting
  notion_id: null
  fingerprint: 6547bf46e8bf5f3b7b59cc0d07b55a8957d8759dec7c0edb9208bcd1090324ac
- action: create
  kind: active_work
  key: clarks_consulting
  title: clarks_consulting active work
  path: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/active-work.md
  record_key: active_work:clarks_consulting
  notion_id: null
  fingerprint: 63a3cfbbea1141b1795b7c6f65685901a88439fff699b19f6b3b9acedc38155b
- action: create
  kind: approvals
  key: clarks_consulting
  title: clarks_consulting approvals
  path: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/approval-rules.md
  record_key: approvals:clarks_consulting
  notion_id: null
  fingerprint: b6f587eb47b5c93e39f88575ebe8f8e923410af7858d5f25e7db5c8b943623a0
- action: create
  kind: decisions
  key: clarks_consulting
  title: clarks_consulting decisions
  path: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/decisions.md
  record_key: decisions:clarks_consulting
  notion_id: null
  fingerprint: e3dea52530f1c6b100401118f4fd620399afe16e5425045ad375539f1ef56cbe
- action: create
  kind: state_index
  key: clarks_consulting
  title: clarks_consulting state index
  path: /private/tmp/aos-validate/root/clarks_consulting/00-control-plane/state-index.md
  record_key: state_index:clarks_consulting
  notion_id: null
  fingerprint: 93ccf3cc3b6e242dbdc9744f27726c1c3018842037c86bad9f0f49674504be6e
- action: create
  kind: metrics
  key: clarks_consulting
  title: clarks_consulting metrics
  path: /private/tmp/aos-validate/root/clarks_consulting/07-metrics/scorecards.md
  record_key: metrics:clarks_consulting
  notion_id: null
  fingerprint: e8bfbbef25ec4ef92d574389514e1a793068f0a16efd983065751337704f37a1
- action: create
  kind: domain
  key: shared_factory
  title: shared_factory
  path: /private/tmp/aos-validate/root/harness/shared_factory/domain.yml
  record_key: domain:shared_factory
  notion_id: null
  fingerprint: a847affda91ff508412e6c75442ffcc8032784b82a4d55b79aab1cf2f2061702
- action: create
  kind: active_work
  key: shared_factory
  title: shared_factory active work
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/active-work.md
  record_key: active_work:shared_factory
  notion_id: null
  fingerprint: 42f81828f433370e7508460a07a04f491554ec547abffe727766147dfc223344
- action: create
  kind: approvals
  key: shared_factory
  title: shared_factory approvals
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/approval-rules.md
  record_key: approvals:shared_factory
  notion_id: null
  fingerprint: b4976569f7a3bd58feb9c99cb55ebc2fa3efe4a6cbfa360be680117e933b975e
- action: create
  kind: decisions
  key: shared_factory
  title: shared_factory decisions
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/decisions.md
  record_key: decisions:shared_factory
  notion_id: null
  fingerprint: 87c2359ef1f49815715f12ec2c1cf0b75aa709ee6d80466e121e52e2ad2cefdc
- action: create
  kind: state_index
  key: shared_factory
  title: shared_factory state index
  path: /private/tmp/aos-validate/root/harness/shared_factory/00-control-plane/state-index.md
  record_key: state_index:shared_factory
  notion_id: null
  fingerprint: 54aaf5d953161158bb74b7a7e6e0723d7cddad38f576eaba748f2cde0d5907ab
- action: create
  kind: metrics
  key: shared_factory
  title: shared_factory metrics
  path: /private/tmp/aos-validate/root/harness/shared_factory/07-metrics/scorecards.md
  record_key: metrics:shared_factory
  notion_id: null
  fingerprint: 3f54d9f32209e3892fde5623695664d72bb67804868f11eeb99402ce73487f36
- action: create
  kind: domain
  key: los
  title: los
  path: /private/tmp/aos-validate/root/los/domain.yml
  record_key: domain:los
  notion_id: null
  fingerprint: bc3ac1e8adb2c31f72282f59b1e1633861b26e6734b7e54cc4e0ba33cb68f804
- action: create
  kind: active_work
  key: los
  title: los active work
  path: /private/tmp/aos-validate/root/los/00-control-plane/active-work.md
  record_key: active_work:los
  notion_id: null
  fingerprint: 7faadd798e8bf0a9cd6f55af76ed8c22f45c81102d48b05e1a16a3df2c7e4c35
- action: create
  kind: approvals
  key: los
  title: los approvals
  path: /private/tmp/aos-validate/root/los/00-control-plane/approval-rules.md
  record_key: approvals:los
  notion_id: null
  fingerprint: 543dda41b324deb75f16294919ffe421ddfa033be991132396b11b861c10f8ef
- action: create
  kind: decisions
  key: los
  title: los decisions
  path: /private/tmp/aos-validate/root/los/00-control-plane/decisions.md
  record_key: decisions:los
  notion_id: null
  fingerprint: 970933b5171c8d85b8841c5b9c2cf112319df728329beda4439ad69ba4f70318
- action: create
  kind: state_index
  key: los
  title: los state index
  path: /private/tmp/aos-validate/root/los/00-control-plane/state-index.md
  record_key: state_index:los
  notion_id: null
  fingerprint: 95b8a46f687c468e53d7ef8dfcc821f0b54eecb7826b814f966634836c7a9bc1
- action: create
  kind: metrics
  key: los
  title: los metrics
  path: /private/tmp/aos-validate/root/los/07-metrics/scorecards.md
  record_key: metrics:los
  notion_id: null
  fingerprint: eb719ae48cdd1f6a94f6dd3632690188763af537503ace922a03090392485ec7
- action: create
  kind: domain
  key: personal
  title: personal
  path: /private/tmp/aos-validate/root/personal/domain.yml
  record_key: domain:personal
  notion_id: null
  fingerprint: 642278d2a3b957c9d02d6c417b03c4ac9f49d662765fc734a1386905ade1a93b
- action: create
  kind: active_work
  key: personal
  title: personal active work
  path: /private/tmp/aos-validate/root/personal/00-control-plane/active-work.md
  record_key: active_work:personal
  notion_id: null
  fingerprint: 4e428d9db33ce25f35b885ff3a9d1f9b2b3e828cacea56a272d41bf659fc7616
- action: create
  kind: approvals
  key: personal
  title: personal approvals
  path: /private/tmp/aos-validate/root/personal/00-control-plane/approval-rules.md
  record_key: approvals:personal
  notion_id: null
  fingerprint: c0ac72744220ab275b0f5fae3a39e6b7f12064622ffb81845feb4a7ca9340b17
- action: create
  kind: decisions
  key: personal
  title: personal decisions
  path: /private/tmp/aos-validate/root/personal/00-control-plane/decisions.md
  record_key: decisions:personal
  notion_id: null
  fingerprint: b634262615e311295bc1dfdd2d453cfc6e93dc5d14a8903ac435e14f3a536b3a
- action: create
  kind: state_index
  key: personal
  title: personal state index
  path: /private/tmp/aos-validate/root/personal/00-control-plane/state-index.md
  record_key: state_index:personal
  notion_id: null
  fingerprint: c3bebe9a29aeffa066fc81773294f3776a83697c2e686eaafbc3861bc7edc24d
- action: create
  kind: metrics
  key: personal
  title: personal metrics
  path: /private/tmp/aos-validate/root/personal/07-metrics/scorecards.md
  record_key: metrics:personal
  notion_id: null
  fingerprint: affb51b87794a757181e64eb51b56aaeaec56f4f0960a820256bba39d81eea0a
```

## 41-config_doctor_layer
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os config doctor --root /tmp/aos-validate/root --layer agentic_os_root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
ok: false
root: /private/tmp/aos-validate/root
layer: agentic_os_root
findings:
- severity: blocker
  path: /private/tmp/aos-validate/root/config.toml
  message: config.toml is missing
  remediation: Run agentic-os config install --root /private/tmp/aos-validate/root
    --layer agentic_os_root --dry-run, review the diff, then rerun with --apply.
```

## 42-config_install_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os config install --root /tmp/aos-validate/config-layer --layer agentic_os_root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/config-layer
layer: agentic_os_root
dry_run: true
created:
- /private/tmp/aos-validate/config-layer
- /private/tmp/aos-validate/config-layer/config.toml
- /private/tmp/aos-validate/config-layer/AGENTS.md
- /private/tmp/aos-validate/config-layer/CLAUDE.md
- /private/tmp/aos-validate/config-layer/ROUTER.md
- /private/tmp/aos-validate/config-layer/CONTEXT.md
- /private/tmp/aos-validate/config-layer/RULES.md
- /private/tmp/aos-validate/config-layer/TOOLS.md
- /private/tmp/aos-validate/config-layer/MEMORY.md
- /private/tmp/aos-validate/config-layer/config
- /private/tmp/aos-validate/config-layer/PROFILE.md
- /private/tmp/aos-validate/config-layer/config/codex-profile.yml
updated: []
skipped: []
backups: []
conflicts: []
blocked: false
diff: '--- /private/tmp/aos-validate/config-layer/config.toml:before

  +++ /private/tmp/aos-validate/config-layer/config.toml:after

  @@ -0,0 +1,53 @@

  +# Agentic OS Codex config template

  +# Layer: agentic_os_root

  +# Local edits are preserved by the installer. Review diffs before applying.

  +

  +model = "gpt-5.4-mini"

  +model_reasoning_effort = "medium"

  +approval_policy = "on-request"

  +sandbox_mode = "workspace-write"

  +project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", "pyproject.toml",
  "package.json"]

  +project_doc_fallback_filenames = ["PROFILE.md", "ROUTER.md", "CONTEXT.md", "RULES.md",
  "TOOLS.md", "MEMORY.md"]

  +

  +[profiles.agentic_os_root]

  +model = "gpt-5.4-mini"

  +model_reasoning_effort = "medium"

  +approval_policy = "on-request"

  +sandbox_mode = "workspace-write"

  +

  +[profiles.agentic_os_root.agentic_os]

  +layer = "agentic_os_root"

  +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md",
  "RULES.md", "TOOLS.md", "MEMORY.md"]

  +context_contract = "route-read-cd-repeat"

  +rules_file = "RULES.md"

  +tool_registry_file = "TOOLS.md"

  +mcp_availability = "source package and local filesystem tools"

  +environment = "local filesystem"

  +

  +

  +[otel]

  +log_user_prompt = false

  +exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"

  +headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

  +

  +[mcp_servers.filesystem_runtime]

  +command = "agentic-os"

  +args = ["config", "doctor"]

  +secret_policy = "no inline secrets"

  +

  +[mcp_servers.notion]

  +url = "https://mcp.notion.com/mcp"

  +secret_policy = "no inline secrets; env var names only"

  +

  +[mcp_servers.genomes_brain]

  +url = "http://127.0.0.1:3155/mcp"

  +secret_policy = "no inline secrets; env var names only"

  +

  +[mcp_servers.github]

  +url = "https://api.githubcopilot.com/mcp/"

  +bearer_token_env_var = "GITHUB_PAT_TOKEN"

  +secret_policy = "no inline secrets; env var names only"

  +

  +[mcp_servers.context_mode]

  +command = "/Users/genome/.local/bin/context-mode"

  +secret_policy = "no inline secrets; env var names only"

  --- /private/tmp/aos-validate/config-layer/PROFILE.md:before

  +++ /private/tmp/aos-validate/config-layer/PROFILE.md:after

  @@ -0,0 +1,11 @@

  +<!-- managed-by: genomes_agentic_os; feature: 62-role-aware-codex-config-layers;
  policy-version: 1 -->

  +

  +# Codex Profile

  +

  +Role: os_navigator

  +Layer: agentic_os_root

  +Profile: agentic_os_root

  +Default model: gpt-5.4-mini

  +Reasoning effort: medium

  +

  +Navigate the installed OS, read shared rules, and prepare context before routing
  work deeper.

  --- /private/tmp/aos-validate/config-layer/config/codex-profile.yml:before

  +++ /private/tmp/aos-validate/config-layer/config/codex-profile.yml:after

  @@ -0,0 +1,22 @@

  +layer: agentic_os_root

  +profile: agentic_os_root

  +legacy_profiles: []

  +role: os_navigator

  +role_summary: Navigate the installed OS, read shared rules, and prepare context
  before

  +  routing work deeper.

  +model: gpt-5.4-mini

  +model_reasoning_effort: medium

  +prompt_files:

  +- AGENTS.md

  +- PROFILE.md

  +- CLAUDE.md

  +- ROUTER.md

  +- CONTEXT.md

  +- RULES.md

  +- TOOLS.md

  +- MEMORY.md

  +mcp_availability: source package and local filesystem tools

  +customer_safe: false

  +managed_by: genomes_agentic_os

  +managed_feature: 62-role-aware-codex-config-layers

  +managed_policy_version: 1

  --- /private/tmp/aos-validate/config-layer/AGENTS.md:before

  +++ /private/tmp/aos-validate/config-layer/AGENTS.md:after

  @@ -0,0 +1,32 @@

  +# Agent Entry Point

  +

  +<!-- agentic-os-codex-profile:start -->

  +## Codex Profile

  +

  +Role: os_navigator

  +Layer: agentic_os_root

  +Profile: agentic_os_root

  +Default model: gpt-5.4-mini

  +Reasoning effort: medium

  +

  +Navigate the installed OS, read shared rules, and prepare context before routing
  work deeper.

  +<!-- agentic-os-codex-profile:end -->

  +

  +This file is the harness-neutral entrypoint for this Agentic OS layer.

  +

  +## Startup Loop

  +

  +1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.

  +2. Classify the request against `ROUTER.md`.

  +3. If the router points to a narrower directory, `cd` there and repeat this loop.

  +4. Act only after loading the final routed layer.

  +5. Record routing gaps, missing tools, and durable next actions in the run log
  or closeout artifact.

  +

  +## Precedence

  +

  +- Active user instructions win.

  +- The final routed layer is the working context.

  +- The strictest safety, approval, privacy, and destructive-action rule wins across
  all loaded `RULES.md` files.

  +- Use `TOOLS.md` as the visible tool contract before assuming a skill, MCP server,
  command, plugin, wrapper, or library is available.

  +

  +Read `MEMORY.md` when present before writing durable memory.

  '
```

## 43-config_install-tree_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os config install-tree --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
dry_run: true
blocked: false
targets:
- root: /private/tmp/aos-validate/root/harness
  layer: agentic_os_root
  reason: .agentic_root harness layer
- root: /private/tmp/aos-validate/root/acme
  layer: domain_or_lane
  reason: domain.yml
- root: /private/tmp/aos-validate/root/acme/02-projects/launch
  layer: project
  reason: project.yml
- root: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog
  layer: workflow_or_task
  reason: workflow.md
- root: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
  layer: automation
  reason: automation.md
- root: /private/tmp/aos-validate/root/archive
  layer: domain_or_lane
  reason: domain.yml
- root: /private/tmp/aos-validate/root/clarks_consulting
  layer: domain_or_lane
  reason: domain.yml
- root: /private/tmp/aos-validate/root/harness/shared_factory
  layer: domain_or_lane
  reason: domain.yml
- root: /private/tmp/aos-validate/root/los
  layer: domain_or_lane
  reason: domain.yml
- root: /private/tmp/aos-validate/root/personal
  layer: domain_or_lane
  reason: domain.yml
installations:
- root: /private/tmp/aos-validate/root/harness
  layer: agentic_os_root
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/acme
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/acme/02-projects/launch
  layer: project
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog
  layer: workflow_or_task
  dry_run: true
  created:
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config.toml
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/AGENTS.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/CLAUDE.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/ROUTER.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/CONTEXT.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/RULES.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/TOOLS.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/MEMORY.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/PROFILE.md
  - /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config/codex-profile.yml
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: '--- /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config.toml:before

    +++ /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config.toml:after

    @@ -0,0 +1,69 @@

    +# Agentic OS Codex config template

    +# Layer: workflow_or_task

    +# Local edits are preserved by the installer. Review diffs before applying.

    +

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", "pyproject.toml",
    "package.json"]

    +project_doc_fallback_filenames = ["PROFILE.md", "ROUTER.md", "CONTEXT.md", "RULES.md",
    "TOOLS.md", "MEMORY.md"]

    +

    +[profiles.workflow_orchestrator]

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +

    +[profiles.workflow_orchestrator.agentic_os]

    +layer = "workflow_or_task"

    +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md",
    "RULES.md", "TOOLS.md", "MEMORY.md"]

    +context_contract = "route-read-cd-repeat"

    +rules_file = "RULES.md"

    +tool_registry_file = "TOOLS.md"

    +mcp_availability = "workflow-approved systems only"

    +environment = "local filesystem"

    +

    +

    +[profiles.workflow_or_task]

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +

    +[profiles.workflow_or_task.agentic_os]

    +layer = "workflow_or_task"

    +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md",
    "RULES.md", "TOOLS.md", "MEMORY.md"]

    +context_contract = "route-read-cd-repeat"

    +rules_file = "RULES.md"

    +tool_registry_file = "TOOLS.md"

    +mcp_availability = "workflow-approved systems only"

    +environment = "local filesystem"

    +

    +

    +[otel]

    +log_user_prompt = false

    +exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"

    +headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

    +

    +[mcp_servers.filesystem_runtime]

    +command = "agentic-os"

    +args = ["config", "doctor"]

    +secret_policy = "no inline secrets"

    +

    +[mcp_servers.notion]

    +url = "https://mcp.notion.com/mcp"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.genomes_brain]

    +url = "http://127.0.0.1:3155/mcp"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.github]

    +url = "https://api.githubcopilot.com/mcp/"

    +bearer_token_env_var = "GITHUB_PAT_TOKEN"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.context_mode]

    +command = "/Users/genome/.local/bin/context-mode"

    +secret_policy = "no inline secrets; env var names only"

    --- /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/PROFILE.md:before

    +++ /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/PROFILE.md:after

    @@ -0,0 +1,11 @@

    +<!-- managed-by: genomes_agentic_os; feature: 62-role-aware-codex-config-layers;
    policy-version: 1 -->

    +

    +# Codex Profile

    +

    +Role: orchestrator

    +Layer: workflow_or_task

    +Profile: workflow_orchestrator

    +Default model: gpt-5.5

    +Reasoning effort: high

    +

    +Run workflow-scoped heavy work, track acceptance criteria, verify delegated outputs,
    and record evidence.

    --- /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config/codex-profile.yml:before

    +++ /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/config/codex-profile.yml:after

    @@ -0,0 +1,23 @@

    +layer: workflow_or_task

    +profile: workflow_orchestrator

    +legacy_profiles:

    +- workflow_or_task

    +role: orchestrator

    +role_summary: Run workflow-scoped heavy work, track acceptance criteria, verify
    delegated

    +  outputs, and record evidence.

    +model: gpt-5.5

    +model_reasoning_effort: high

    +prompt_files:

    +- AGENTS.md

    +- PROFILE.md

    +- CLAUDE.md

    +- ROUTER.md

    +- CONTEXT.md

    +- RULES.md

    +- TOOLS.md

    +- MEMORY.md

    +mcp_availability: workflow-approved systems only

    +customer_safe: true

    +managed_by: genomes_agentic_os

    +managed_feature: 62-role-aware-codex-config-layers

    +managed_policy_version: 1

    --- /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/AGENTS.md:before

    +++ /private/tmp/aos-validate/root/acme/03-workflows/engineering/launch_blog/AGENTS.md:after

    @@ -0,0 +1,32 @@

    +# Agent Entry Point

    +

    +<!-- agentic-os-codex-profile:start -->

    +## Codex Profile

    +

    +Role: orchestrator

    +Layer: workflow_or_task

    +Profile: workflow_orchestrator

    +Default model: gpt-5.5

    +Reasoning effort: high

    +

    +Run workflow-scoped heavy work, track acceptance criteria, verify delegated outputs,
    and record evidence.

    +<!-- agentic-os-codex-profile:end -->

    +

    +This file is the harness-neutral entrypoint for this Agentic OS layer.

    +

    +## Startup Loop

    +

    +1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.

    +2. Classify the request against `ROUTER.md`.

    +3. If the router points to a narrower directory, `cd` there and repeat this loop.

    +4. Act only after loading the final routed layer.

    +5. Record routing gaps, missing tools, and durable next actions in the run log
    or closeout artifact.

    +

    +## Precedence

    +

    +- Active user instructions win.

    +- The final routed layer is the working context.

    +- The strictest safety, approval, privacy, and destructive-action rule wins across
    all loaded `RULES.md` files.

    +- Use `TOOLS.md` as the visible tool contract before assuming a skill, MCP server,
    command, plugin, wrapper, or library is available.

    +

    +Read `MEMORY.md` when present before writing durable memory.

    '
- root: /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report
  layer: automation
  dry_run: true
  created:
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config.toml
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/AGENTS.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/CLAUDE.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/ROUTER.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/CONTEXT.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/RULES.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/TOOLS.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/MEMORY.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/PROFILE.md
  - /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config/codex-profile.yml
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: '--- /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config.toml:before

    +++ /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config.toml:after

    @@ -0,0 +1,69 @@

    +# Agentic OS Codex config template

    +# Layer: automation

    +# Local edits are preserved by the installer. Review diffs before applying.

    +

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +project_root_markers = [".agentic_root", ".git", "agentic-os.package.json", "pyproject.toml",
    "package.json"]

    +project_doc_fallback_filenames = ["PROFILE.md", "ROUTER.md", "CONTEXT.md", "RULES.md",
    "TOOLS.md", "MEMORY.md"]

    +

    +[profiles.automation_guard]

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +

    +[profiles.automation_guard.agentic_os]

    +layer = "automation"

    +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md",
    "RULES.md", "TOOLS.md", "MEMORY.md"]

    +context_contract = "route-read-cd-repeat"

    +rules_file = "RULES.md"

    +tool_registry_file = "TOOLS.md"

    +mcp_availability = "explicit automation contract only"

    +environment = "local filesystem"

    +

    +

    +[profiles.automation]

    +model = "gpt-5.5"

    +model_reasoning_effort = "high"

    +approval_policy = "on-request"

    +sandbox_mode = "workspace-write"

    +

    +[profiles.automation.agentic_os]

    +layer = "automation"

    +prompt_files = ["AGENTS.md", "PROFILE.md", "CLAUDE.md", "ROUTER.md", "CONTEXT.md",
    "RULES.md", "TOOLS.md", "MEMORY.md"]

    +context_contract = "route-read-cd-repeat"

    +rules_file = "RULES.md"

    +tool_registry_file = "TOOLS.md"

    +mcp_availability = "explicit automation contract only"

    +environment = "local filesystem"

    +

    +

    +[otel]

    +log_user_prompt = false

    +exporter_otlp_endpoint_env_var = "AGENTIC_OS_OTEL_EXPORTER_OTLP_ENDPOINT"

    +headers_env_var = "AGENTIC_OS_OTEL_HEADERS"

    +

    +[mcp_servers.filesystem_runtime]

    +command = "agentic-os"

    +args = ["config", "doctor"]

    +secret_policy = "no inline secrets"

    +

    +[mcp_servers.notion]

    +url = "https://mcp.notion.com/mcp"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.genomes_brain]

    +url = "http://127.0.0.1:3155/mcp"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.github]

    +url = "https://api.githubcopilot.com/mcp/"

    +bearer_token_env_var = "GITHUB_PAT_TOKEN"

    +secret_policy = "no inline secrets; env var names only"

    +

    +[mcp_servers.context_mode]

    +command = "/Users/genome/.local/bin/context-mode"

    +secret_policy = "no inline secrets; env var names only"

    --- /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/PROFILE.md:before

    +++ /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/PROFILE.md:after

    @@ -0,0 +1,11 @@

    +<!-- managed-by: genomes_agentic_os; feature: 62-role-aware-codex-config-layers;
    policy-version: 1 -->

    +

    +# Codex Profile

    +

    +Role: automation_guard

    +Layer: automation

    +Profile: automation_guard

    +Default model: gpt-5.5

    +Reasoning effort: high

    +

    +Execute only within the automation contract, preserve evidence, and stop when
    approvals or safety gates are missing.

    --- /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config/codex-profile.yml:before

    +++ /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/config/codex-profile.yml:after

    @@ -0,0 +1,23 @@

    +layer: automation

    +profile: automation_guard

    +legacy_profiles:

    +- automation

    +role: automation_guard

    +role_summary: Execute only within the automation contract, preserve evidence,
    and

    +  stop when approvals or safety gates are missing.

    +model: gpt-5.5

    +model_reasoning_effort: high

    +prompt_files:

    +- AGENTS.md

    +- PROFILE.md

    +- CLAUDE.md

    +- ROUTER.md

    +- CONTEXT.md

    +- RULES.md

    +- TOOLS.md

    +- MEMORY.md

    +mcp_availability: explicit automation contract only

    +customer_safe: true

    +managed_by: genomes_agentic_os

    +managed_feature: 62-role-aware-codex-config-layers

    +managed_policy_version: 1

    --- /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/AGENTS.md:before

    +++ /private/tmp/aos-validate/root/acme/04-automations/marketing/weekly_report/AGENTS.md:after

    @@ -0,0 +1,32 @@

    +# Agent Entry Point

    +

    +<!-- agentic-os-codex-profile:start -->

    +## Codex Profile

    +

    +Role: automation_guard

    +Layer: automation

    +Profile: automation_guard

    +Default model: gpt-5.5

    +Reasoning effort: high

    +

    +Execute only within the automation contract, preserve evidence, and stop when
    approvals or safety gates are missing.

    +<!-- agentic-os-codex-profile:end -->

    +

    +This file is the harness-neutral entrypoint for this Agentic OS layer.

    +

    +## Startup Loop

    +

    +1. Read `ROUTER.md`, `CONTEXT.md`, `RULES.md`, and `TOOLS.md` in this directory.

    +2. Classify the request against `ROUTER.md`.

    +3. If the router points to a narrower directory, `cd` there and repeat this loop.

    +4. Act only after loading the final routed layer.

    +5. Record routing gaps, missing tools, and durable next actions in the run log
    or closeout artifact.

    +

    +## Precedence

    +

    +- Active user instructions win.

    +- The final routed layer is the working context.

    +- The strictest safety, approval, privacy, and destructive-action rule wins across
    all loaded `RULES.md` files.

    +- Use `TOOLS.md` as the visible tool contract before assuming a skill, MCP server,
    command, plugin, wrapper, or library is available.

    +

    +Read `MEMORY.md` when present before writing durable memory.

    '
- root: /private/tmp/aos-validate/root/archive
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/clarks_consulting
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/harness/shared_factory
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/los
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
- root: /private/tmp/aos-validate/root/personal
  layer: domain_or_lane
  dry_run: true
  created: []
  updated: []
  skipped: []
  backups: []
  conflicts: []
  blocked: false
  diff: ''
```

## 44-license_activate
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os license activate --key VALIDATION-TEST-KEY --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
license:
  status: active
  activated_at: '2026-06-09T04:24:24Z'
  key_hash: 98f9006c28109fe76a6960274702c0b357b598b264e22716aa50ba6e18296bab
```

## 45-update_register
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os update register --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
grant_path: /private/tmp/aos-validate/root/harness/registries/update-grant.json
ssh_config: /private/tmp/aos-validate/root/harness/security/ssh/config
remotes:
  update:
    name: agentic-os-update
    url: git@github.com:genome/local-agentic-os-updates.git
    access: read-only
  backup:
    name: agentic-os-backup
    url: git@github.com:genome/local-agentic-os-backups.git
    access: write
public_keys:
  update: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICQOiyOH0HNNWtpuELSRavWV8atbOqPx6KICzlExIZwE
    agentic-os-update_ed25519
  backup: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPr42T+c6cfOwCcLMzXXaH1yEVqGc3v2iHerFRA50G7A
    agentic-os-backup_ed25519
private_keys: stored locally under harness/security/ssh with mode 0600
```

## 46-update_check
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os update check --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
installed_version: 0.1.0
available_version: 0.1.0
update_available: false
channel: stable
policy: operator_approved
mutated: false
risky_changes: []
```

## 47-update_status
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os update status --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
lock:
  installed_version: 0.1.0
  update_channel: stable
  update_policy: operator_approved
  status: installed
status:
  status: unknown
plan_path: ''
```

## 48-backup_run_dry
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os backup run --root /tmp/aos-validate/root --dry-run
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
log_path: /private/tmp/aos-validate/root/harness/logs/backups/backup-20260609042424.yml
status: planned
dry_run: true
created_at: '2026-06-09T04:24:24Z'
remote:
  name: agentic-os-backup
  url: git@github.com:genome/local-agentic-os-backups.git
  access: write
include:
- .agentic_root
- harness/AGENTS.md
- harness/ROUTER.md
- harness/CONTEXT.md
- harness/RULES.md
- harness/TOOLS.md
- harness/registries/
- harness/shared_factory/00-control-plane/
exclude:
- projects/
- harness/logs/
- harness/security/ssh/*
- '**/.env'
- '**/*secret*'
- '**/*token*'
manifest: []
```

## 49-migrate_plan
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os migrate plan --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/root
migrations:
- migration_id: notion-sync-readme-v1
  purpose: Add the local Notion sync mapping contract README.
  target: /private/tmp/aos-validate/root/.notion-sync/README.md
  expected_sha256: null
  approval_required: true
  rollback: Remove the README or restore the previous file content from version control.
  diff: '--- /private/tmp/aos-validate/root/.notion-sync/README.md

    +++ /private/tmp/aos-validate/root/.notion-sync/README.md (proposed)

    @@ -0,0 +1,9 @@

    +# Notion Sync Mapping

    +

    +This folder stores local Notion sync planning state.

    +

    +## Contract

    +

    +- Filesystem state remains the source of truth.

    +- Apply only after the target workspace is verified.

    +- Mapping IDs are local until a verified live Notion write replaces them.

    '
plan_path: /private/tmp/aos-validate/root/.migrations/notion-sync-readme-v1.yml
```

## 50-losmon_validate
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os losmon validate --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
project: /private/tmp/aos-validate/root/los/02-projects/losmon_replacement
created_or_verified:
- /private/tmp/aos-validate/root/los/02-projects/losmon_replacement
- /private/tmp/aos-validate/root/los/03-workflows/engineering/pr_review
- /private/tmp/aos-validate/root/los/03-workflows/engineering/failing_ci_triage
- /private/tmp/aos-validate/root/los/03-workflows/operations/deploy_planning
- /private/tmp/aos-validate/root/los/04-automations/support/thread_intake
run_logs:
- /private/tmp/aos-validate/root/los/06-runs-and-logs/runs/20260609T042425Z-los-pr_review/run-log.md
- /private/tmp/aos-validate/root/los/06-runs-and-logs/runs/20260609T042425Z-los-failing_ci_triage/run-log.md
- /private/tmp/aos-validate/root/los/06-runs-and-logs/runs/20260609T042425Z-los-deploy_planning/run-log.md
comparison: /private/tmp/aos-validate/root/los/02-projects/losmon_replacement/artifacts/losmon-comparison.md
```

## 51-plan_capture
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os plan capture --title weekly report automation --summary automate the weekly report --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
target: /private/tmp/aos-validate/root/harness/shared_factory/05-knowledge/plans/future-ideas/weekly-report-automation.md
kind: os
status: captured
```

## 52-docs_install
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os docs install --root /tmp/aos-validate/root
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
no changes
```

## 53-customer_init_example
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os customer init acme_ops --profile /Users/genome/projects/genomes_agentic_os/customer_profiles/example-customer.yml --target /tmp/aos-validate/customer
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/customer
customer: acme_ops
created:
- /private/tmp/aos-validate/customer/.agentic_root
- /private/tmp/aos-validate/customer/harness/bin
- /private/tmp/aos-validate/customer/harness/commands
- /private/tmp/aos-validate/customer/harness/skills
- /private/tmp/aos-validate/customer/harness/mcp
- /private/tmp/aos-validate/customer/harness/plugins
- /private/tmp/aos-validate/customer/harness/libraries
- /private/tmp/aos-validate/customer/harness/hooks
- /private/tmp/aos-validate/customer/harness/rules
- /private/tmp/aos-validate/customer/harness/registries
- /private/tmp/aos-validate/customer/harness/registries/capabilities.yml
- /private/tmp/aos-validate/customer/harness/registries/commands.yml
- /private/tmp/aos-validate/customer/harness/registries/skills.yml
- /private/tmp/aos-validate/customer/harness/registries/mcp-servers.yml
- /private/tmp/aos-validate/customer/harness/registries/libraries.yml
- /private/tmp/aos-validate/customer/harness/registries/hooks.yml
- /private/tmp/aos-validate/customer/harness/registries/plugins.yml
- /private/tmp/aos-validate/customer/harness/registries/rules.yml
- /private/tmp/aos-validate/customer/harness/INVENTORY.md
- /private/tmp/aos-validate/customer/harness/agentic-os.lock.json
- /private/tmp/aos-validate/customer/harness/UPDATE_POLICY.md
- /private/tmp/aos-validate/customer/harness/registries/updates.yml
- /private/tmp/aos-validate/customer/harness/security
- /private/tmp/aos-validate/customer/harness/security/ssh
- /private/tmp/aos-validate/customer/harness/logs
- /private/tmp/aos-validate/customer/harness/logs/updates
- /private/tmp/aos-validate/customer/harness/logs/backups
- /private/tmp/aos-validate/customer/harness/registries/customer-identity.json
- /private/tmp/aos-validate/customer/harness/registries/backup-policy.yml
- /private/tmp/aos-validate/customer/README.md
- /private/tmp/aos-validate/customer/ROUTER.md
- /private/tmp/aos-validate/customer/AGENTS.md
- /private/tmp/aos-validate/customer/CLAUDE.md
- /private/tmp/aos-validate/customer/CONTEXT.md
- /private/tmp/aos-validate/customer/RULES.md
- /private/tmp/aos-validate/customer/TOOLS.md
- /private/tmp/aos-validate/customer/config.toml
- /private/tmp/aos-validate/customer/PROFILE.md
- /private/tmp/aos-validate/customer/MEMORY.md
- /private/tmp/aos-validate/customer/config/codex-profile.yml
- /private/tmp/aos-validate/customer/customer.yml
- /private/tmp/aos-validate/customer/customer/README.md
- /private/tmp/aos-validate/customer/customer/handoff-checklist.md
- /private/tmp/aos-validate/customer/customer/automation-fit-matrix.md
- /private/tmp/aos-validate/customer/customer/client-automation-brief.md
- /private/tmp/aos-validate/customer/customer/update-contract.md
- /private/tmp/aos-validate/customer/harness/shared_factory/05-knowledge/templates/profile/customer-os-profile.yml
- /private/tmp/aos-validate/customer/harness/shared_factory/05-knowledge/templates/customer/client-automation-brief.md
- /private/tmp/aos-validate/customer/harness/shared_factory/05-knowledge/templates/customer/automation-fit-matrix.md
- /private/tmp/aos-validate/customer/harness/shared_factory/05-knowledge/templates/customer/customer-handoff-checklist.md
- /private/tmp/aos-validate/customer/support
- /private/tmp/aos-validate/customer/support/README.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/REFERENCES.md
- /private/tmp/aos-validate/customer/support/domain.yml
- /private/tmp/aos-validate/customer/support/config.toml
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support/00-control-plane
- /private/tmp/aos-validate/customer/support/01-inbox
- /private/tmp/aos-validate/customer/support/02-projects
- /private/tmp/aos-validate/customer/support/03-workflows
- /private/tmp/aos-validate/customer/support/04-automations
- /private/tmp/aos-validate/customer/support/05-knowledge
- /private/tmp/aos-validate/customer/support/06-runs-and-logs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures
- /private/tmp/aos-validate/customer/support/07-metrics
- /private/tmp/aos-validate/customer/support/08-archive
- /private/tmp/aos-validate/customer/support/00-control-plane/README.md
- /private/tmp/aos-validate/customer/support/00-control-plane/active-work.md
- /private/tmp/aos-validate/customer/support/00-control-plane/state-index.md
- /private/tmp/aos-validate/customer/support/00-control-plane/decisions.md
- /private/tmp/aos-validate/customer/support/00-control-plane/routing-rules.md
- /private/tmp/aos-validate/customer/support/00-control-plane/approval-rules.md
- /private/tmp/aos-validate/customer/support/01-inbox/raw-ideas.md
- /private/tmp/aos-validate/customer/support/01-inbox/triage.md
- /private/tmp/aos-validate/customer/support/02-projects/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/README.md
- /private/tmp/aos-validate/customer/support/04-automations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/engineering
- /private/tmp/aos-validate/customer/support/04-automations/engineering
- /private/tmp/aos-validate/customer/support/03-workflows/engineering/README.md
- /private/tmp/aos-validate/customer/support/04-automations/engineering/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/marketing
- /private/tmp/aos-validate/customer/support/04-automations/marketing
- /private/tmp/aos-validate/customer/support/03-workflows/marketing/README.md
- /private/tmp/aos-validate/customer/support/04-automations/marketing/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/sales
- /private/tmp/aos-validate/customer/support/04-automations/sales
- /private/tmp/aos-validate/customer/support/03-workflows/sales/README.md
- /private/tmp/aos-validate/customer/support/04-automations/sales/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support
- /private/tmp/aos-validate/customer/support/04-automations/support
- /private/tmp/aos-validate/customer/support/03-workflows/support/README.md
- /private/tmp/aos-validate/customer/support/04-automations/support/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/operations
- /private/tmp/aos-validate/customer/support/04-automations/operations
- /private/tmp/aos-validate/customer/support/03-workflows/operations/README.md
- /private/tmp/aos-validate/customer/support/04-automations/operations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/finance
- /private/tmp/aos-validate/customer/support/04-automations/finance
- /private/tmp/aos-validate/customer/support/03-workflows/finance/README.md
- /private/tmp/aos-validate/customer/support/04-automations/finance/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/learning
- /private/tmp/aos-validate/customer/support/04-automations/learning
- /private/tmp/aos-validate/customer/support/03-workflows/learning/README.md
- /private/tmp/aos-validate/customer/support/04-automations/learning/README.md
- /private/tmp/aos-validate/customer/support/05-knowledge/source-map.md
- /private/tmp/aos-validate/customer/support/05-knowledge/glossary.md
- /private/tmp/aos-validate/customer/support/05-knowledge/memory-policy.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/activity-log.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs/README.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures/README.md
- /private/tmp/aos-validate/customer/support/07-metrics/baselines.md
- /private/tmp/aos-validate/customer/support/07-metrics/scorecards.md
- /private/tmp/aos-validate/customer/support/08-archive/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/examples
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/runs
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/examples/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/runs/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/workflow.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/outcome-brief.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/alignment-questions.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/prd.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/implementation-plan.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/dispatch-handoff.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/progress.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/quick-reference.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/state-machine.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/context-pack.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/approval-rules.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/output-contract.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/runbook.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/config.toml
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/AGENTS.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/PROFILE.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/CLAUDE.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/ROUTER.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/CONTEXT.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/RULES.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/TOOLS.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/MEMORY.md
- /private/tmp/aos-validate/customer/support/03-workflows/support/intake_triage/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/logs
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/logs/README.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/automation.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/inputs.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/outputs.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/permissions.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/failure-modes.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/runbook.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/tests.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/config.toml
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/AGENTS.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/PROFILE.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/CLAUDE.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/ROUTER.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/CONTEXT.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/RULES.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/TOOLS.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/MEMORY.md
- /private/tmp/aos-validate/customer/support/04-automations/support/thread_intake/config/codex-profile.yml
updated:
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/config.toml
- /private/tmp/aos-validate/customer/support/config.toml
- /private/tmp/aos-validate/customer/support/config.toml
- /private/tmp/aos-validate/customer/support/config.toml
- /private/tmp/aos-validate/customer/support/config.toml
skipped:
- /private/tmp/aos-validate/customer/AGENTS.md
- /private/tmp/aos-validate/customer/CLAUDE.md
- /private/tmp/aos-validate/customer/ROUTER.md
- /private/tmp/aos-validate/customer/CONTEXT.md
- /private/tmp/aos-validate/customer/RULES.md
- /private/tmp/aos-validate/customer/TOOLS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support
- /private/tmp/aos-validate/customer/support/README.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/REFERENCES.md
- /private/tmp/aos-validate/customer/support/domain.yml
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support/00-control-plane
- /private/tmp/aos-validate/customer/support/01-inbox
- /private/tmp/aos-validate/customer/support/02-projects
- /private/tmp/aos-validate/customer/support/03-workflows
- /private/tmp/aos-validate/customer/support/04-automations
- /private/tmp/aos-validate/customer/support/05-knowledge
- /private/tmp/aos-validate/customer/support/06-runs-and-logs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures
- /private/tmp/aos-validate/customer/support/07-metrics
- /private/tmp/aos-validate/customer/support/08-archive
- /private/tmp/aos-validate/customer/support/00-control-plane/README.md
- /private/tmp/aos-validate/customer/support/00-control-plane/active-work.md
- /private/tmp/aos-validate/customer/support/00-control-plane/state-index.md
- /private/tmp/aos-validate/customer/support/00-control-plane/decisions.md
- /private/tmp/aos-validate/customer/support/00-control-plane/routing-rules.md
- /private/tmp/aos-validate/customer/support/00-control-plane/approval-rules.md
- /private/tmp/aos-validate/customer/support/01-inbox/raw-ideas.md
- /private/tmp/aos-validate/customer/support/01-inbox/triage.md
- /private/tmp/aos-validate/customer/support/02-projects/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/README.md
- /private/tmp/aos-validate/customer/support/04-automations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/engineering
- /private/tmp/aos-validate/customer/support/04-automations/engineering
- /private/tmp/aos-validate/customer/support/03-workflows/engineering/README.md
- /private/tmp/aos-validate/customer/support/04-automations/engineering/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/marketing
- /private/tmp/aos-validate/customer/support/04-automations/marketing
- /private/tmp/aos-validate/customer/support/03-workflows/marketing/README.md
- /private/tmp/aos-validate/customer/support/04-automations/marketing/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/sales
- /private/tmp/aos-validate/customer/support/04-automations/sales
- /private/tmp/aos-validate/customer/support/03-workflows/sales/README.md
- /private/tmp/aos-validate/customer/support/04-automations/sales/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support
- /private/tmp/aos-validate/customer/support/04-automations/support
- /private/tmp/aos-validate/customer/support/03-workflows/support/README.md
- /private/tmp/aos-validate/customer/support/04-automations/support/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/operations
- /private/tmp/aos-validate/customer/support/04-automations/operations
- /private/tmp/aos-validate/customer/support/03-workflows/operations/README.md
- /private/tmp/aos-validate/customer/support/04-automations/operations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/finance
- /private/tmp/aos-validate/customer/support/04-automations/finance
- /private/tmp/aos-validate/customer/support/03-workflows/finance/README.md
- /private/tmp/aos-validate/customer/support/04-automations/finance/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/learning
- /private/tmp/aos-validate/customer/support/04-automations/learning
- /private/tmp/aos-validate/customer/support/03-workflows/learning/README.md
- /private/tmp/aos-validate/customer/support/04-automations/learning/README.md
- /private/tmp/aos-validate/customer/support/05-knowledge/source-map.md
- /private/tmp/aos-validate/customer/support/05-knowledge/glossary.md
- /private/tmp/aos-validate/customer/support/05-knowledge/memory-policy.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/activity-log.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs/README.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures/README.md
- /private/tmp/aos-validate/customer/support/07-metrics/baselines.md
- /private/tmp/aos-validate/customer/support/07-metrics/scorecards.md
- /private/tmp/aos-validate/customer/support/08-archive/README.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support
- /private/tmp/aos-validate/customer/support/README.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/REFERENCES.md
- /private/tmp/aos-validate/customer/support/domain.yml
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
- /private/tmp/aos-validate/customer/support/00-control-plane
- /private/tmp/aos-validate/customer/support/01-inbox
- /private/tmp/aos-validate/customer/support/02-projects
- /private/tmp/aos-validate/customer/support/03-workflows
- /private/tmp/aos-validate/customer/support/04-automations
- /private/tmp/aos-validate/customer/support/05-knowledge
- /private/tmp/aos-validate/customer/support/06-runs-and-logs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures
- /private/tmp/aos-validate/customer/support/07-metrics
- /private/tmp/aos-validate/customer/support/08-archive
- /private/tmp/aos-validate/customer/support/00-control-plane/README.md
- /private/tmp/aos-validate/customer/support/00-control-plane/active-work.md
- /private/tmp/aos-validate/customer/support/00-control-plane/state-index.md
- /private/tmp/aos-validate/customer/support/00-control-plane/decisions.md
- /private/tmp/aos-validate/customer/support/00-control-plane/routing-rules.md
- /private/tmp/aos-validate/customer/support/00-control-plane/approval-rules.md
- /private/tmp/aos-validate/customer/support/01-inbox/raw-ideas.md
- /private/tmp/aos-validate/customer/support/01-inbox/triage.md
- /private/tmp/aos-validate/customer/support/02-projects/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/README.md
- /private/tmp/aos-validate/customer/support/04-automations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/engineering
- /private/tmp/aos-validate/customer/support/04-automations/engineering
- /private/tmp/aos-validate/customer/support/03-workflows/engineering/README.md
- /private/tmp/aos-validate/customer/support/04-automations/engineering/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/marketing
- /private/tmp/aos-validate/customer/support/04-automations/marketing
- /private/tmp/aos-validate/customer/support/03-workflows/marketing/README.md
- /private/tmp/aos-validate/customer/support/04-automations/marketing/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/sales
- /private/tmp/aos-validate/customer/support/04-automations/sales
- /private/tmp/aos-validate/customer/support/03-workflows/sales/README.md
- /private/tmp/aos-validate/customer/support/04-automations/sales/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/support
- /private/tmp/aos-validate/customer/support/04-automations/support
- /private/tmp/aos-validate/customer/support/03-workflows/support/README.md
- /private/tmp/aos-validate/customer/support/04-automations/support/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/operations
- /private/tmp/aos-validate/customer/support/04-automations/operations
- /private/tmp/aos-validate/customer/support/03-workflows/operations/README.md
- /private/tmp/aos-validate/customer/support/04-automations/operations/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/finance
- /private/tmp/aos-validate/customer/support/04-automations/finance
- /private/tmp/aos-validate/customer/support/03-workflows/finance/README.md
- /private/tmp/aos-validate/customer/support/04-automations/finance/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin
- /private/tmp/aos-validate/customer/support/03-workflows/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/04-automations/personal_admin/README.md
- /private/tmp/aos-validate/customer/support/03-workflows/learning
- /private/tmp/aos-validate/customer/support/04-automations/learning
- /private/tmp/aos-validate/customer/support/03-workflows/learning/README.md
- /private/tmp/aos-validate/customer/support/04-automations/learning/README.md
- /private/tmp/aos-validate/customer/support/05-knowledge/source-map.md
- /private/tmp/aos-validate/customer/support/05-knowledge/glossary.md
- /private/tmp/aos-validate/customer/support/05-knowledge/memory-policy.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/activity-log.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/runs/README.md
- /private/tmp/aos-validate/customer/support/06-runs-and-logs/failures/README.md
- /private/tmp/aos-validate/customer/support/07-metrics/baselines.md
- /private/tmp/aos-validate/customer/support/07-metrics/scorecards.md
- /private/tmp/aos-validate/customer/support/08-archive/README.md
- /private/tmp/aos-validate/customer/support/AGENTS.md
- /private/tmp/aos-validate/customer/support/PROFILE.md
- /private/tmp/aos-validate/customer/support/CLAUDE.md
- /private/tmp/aos-validate/customer/support/ROUTER.md
- /private/tmp/aos-validate/customer/support/CONTEXT.md
- /private/tmp/aos-validate/customer/support/RULES.md
- /private/tmp/aos-validate/customer/support/TOOLS.md
- /private/tmp/aos-validate/customer/support/MEMORY.md
- /private/tmp/aos-validate/customer/support/config/codex-profile.yml
```

## 54-customer_validate
```text
# CMD: /Users/genome/projects/genomes_agentic_os/.venv/bin/agentic-os customer validate --root /tmp/aos-validate/customer
# CWD: /Users/genome/projects/genomes_agentic_os
# ---
root: /private/tmp/aos-validate/customer
ok: true
core_errors: []
profile_warnings: []
```


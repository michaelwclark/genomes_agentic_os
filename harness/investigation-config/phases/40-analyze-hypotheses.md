---
schema_version: 1
id: analyze-hypotheses
kind: phase
title: Analyze competing hypotheses
priority: 40
requirements:
  causal_chain: true
  contradictions: true
  counterfactual_check: true
---

# Analyze hypotheses

Compare code behavior, deployed version, configuration, runtime evidence, and
historical context without conflating correlation with cause. For each viable
hypothesis identify supporting evidence, contradicting evidence, a falsifying
check, and remaining uncertainty. Explain why the issue appears in the stated
environment, tenant, version, or data shape.

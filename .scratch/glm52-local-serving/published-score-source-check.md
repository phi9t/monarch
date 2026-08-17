# GLM-5.2 Published-Score Source Check

Checked: 2026-08-15

Purpose: decide whether the local `published-scores.yaml` placeholders can be
replaced with primary-source GLM-5.2 conformance scores.

## Primary Source

- Hugging Face model card:
  `https://huggingface.co/zai-org/GLM-5.2/raw/main/README.md`
- The model card identifies the model as GLM-5.2 and links the Z.ai blog, Z.ai
  API guide, local serving framework recipes, and the GLM-5 technical report.
- The benchmark table reports GLM-5.2 scores for benchmarks including:
  - `AIME 2026`: `99.2`
  - `Terminal Bench 2.1 (Terminus-2)`: `81.0`
  - `Terminal Bench 2.1 (Best Reported Harness)`: `82.7`
  - `SWE-bench Pro`: `62.1`
  - `NL2Repo`: `48.9`
  - `DeepSWE`: `46.2`
  - `ProgramBench`: `63.7`

## Footnote Conditions

The model card footnotes make the published conditions part of the score:

- AIME, HMMT, and IMOAnswerBench use `temperature=1.0`, `top_p=0.95`, a maximum
  generation length of `163,840` tokens, a specific answer-format system prompt,
  and GPT-5.5 medium as the judge model.
- Terminal-Bench 2.1 (Terminus-2) uses the Terminus-2 framework with
  `parser=json`, `timeout=4h`, `temperature=1.0`, `top_p=1.0`,
  `max_new_tokens=48k`, `max_episodes=500`, and a `256K` context window.
- Terminal-Bench 2.1 (Claude Code) uses Claude Code 2.1.167 with
  `temperature=1.0`, `top_p=0.95`, and `max_new_tokens=131072`, and averages
  scores over 5 runs.

## Local Manifest Comparison

The current local benchmark manifest intentionally does not match those
published conditions:

- `terminal-bench-2` is configured for the local Harbor-backed Codex-readiness
  profile: `execution_backend=harbor_local_docker`, `temperature=0.2`,
  `top_p=0.95`, `max_output_tokens=4096`, and GLM thinking disabled. That does
  not match either published Terminal-Bench 2.1 condition.
- `aime` is configured as a local `aime` suite through
  `lm-evaluation-harness@pinned-placeholder`, `temperature=0`, `top_p=1`, and
  `max_output_tokens=4096`. That does not match the published `AIME 2026`
  identity or decoding/judging condition.
- The official model card does not publish matching primary-source scores for
  the current local `HumanEval`, `MBPP`, `GSM8K`, `RULER`, or `needle-smoke`
  manifest entries.

## Decision

Do not populate `.scratch/glm52-local-serving/benchmarks/published-scores.yaml`
from these official scores yet. They are useful source facts, but they are not
comparable to the currently pinned local benchmark profiles. Keeping the
placeholder scores makes conformance fail before inference, which preserves the
workstream rule that published conformance requires matching source, prompt,
decoding profile, benchmark revision, execution backend, metric, and tolerance.

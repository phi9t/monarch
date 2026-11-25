# GLM-5.3-Flash Deep Dive

This note summarizes Z.ai's GLM-5.3-Flash announcement and its implications for
Monarch's local serving and coding-agent verifier work. It is source-grounded in
the public announcement, Z.ai docs, the Hugging Face model card/config, and the
official serving recipes available on 2026-08-26.

## Executive Takeaways

GLM-5.3-Flash is the first natively multimodal model in the GLM-5 series. Z.ai
positions it as a lower-cost coding and agentic model that improves over
GLM-5.2 while approaching Claude Opus 4.8 on some first-party reported coding
and agentic benchmark aggregates. The main published efficiency story is a
320B-total, 18B-active MoE model with 45 text layers, hybrid sparse plus linear
attention, Manifold-Constrained Hyper-Connections, a 30T-token multimodal
pretraining corpus, and a 1M-token context window.

For Monarch's GLM serving work, the important delta from the GLM-5.2 path is
not only model quality. GLM-5.3-Flash is a forced-thinking model according to
Z.ai's current model-specific docs and API schema. The existing GLM-5.2
recommendation to disable thinking for predictable tool-call parsing should not
be carried over blindly. A Codex-compatible adapter needs to preserve and map
`reasoning_content`, tool calls, and tool results deliberately.

## Source Set

- Z.ai announcement:
  [GLM-5.3-Flash: Frontier Intelligence, Flash Cost](https://z.ai/blog/glm-5.3-flash).
- Z.ai model guide:
  [GLM-5.3-Flash](https://docs.z.ai/guides/vlm/glm-5.3-flash.md).
- Z.ai API reference:
  [Chat Completion](https://docs.z.ai/api-reference/llm/chat-completion.md).
- Z.ai capability docs:
  [Thinking Mode](https://docs.z.ai/guides/capabilities/thinking-mode.md) and
  [Function Calling](https://docs.z.ai/guides/capabilities/function-calling.md).
- Z.ai pricing: [Pricing](https://docs.z.ai/guides/overview/pricing.md).
- Weights and config:
  [zai-org/GLM-5.3-Flash on Hugging Face](https://huggingface.co/zai-org/GLM-5.3-Flash),
  especially
  [`README.md`](https://huggingface.co/zai-org/GLM-5.3-Flash/raw/main/README.md)
  and
  [`config.json`](https://huggingface.co/zai-org/GLM-5.3-Flash/raw/main/config.json).
- Serving recipes:
  [SGLang GLM-5.3-Flash](https://docs.sglang.io/cookbook/autoregressive/GLM/GLM-5.3-Flash.md),
  [vLLM recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash),
  [KTransformers tutorial][ktransformers-glm53],
  and TokenSpeed from the Hugging Face model card.

[ktransformers-glm53]: https://github.com/kvcache-ai/ktransformers/blob/main/doc/en/kt-kernel/GLM-5.3-Flash-Tutorial.md

## Model Shape

Published high-level shape:

- 320B total parameters and 18B active parameters.
- First native multimodal model in the GLM-5 series.
- 30T-token multimodal pretraining corpus.
- Hybrid sparse and linear attention, advertised as reducing long-context
  serving cost while preserving precise long-context capability.
- Manifold-Constrained Hyper-Connections, abbreviated `mHC`, for scaling
  efficiency.
- `IndexPool`, which compresses four indexer key vectors into one through
  weighted pooling for lower indexer latency and memory overhead at 1M-token
  context.

The public Hugging Face config makes the architecture concrete:

- `architectures`: `Glm5NextForConditionalGeneration`.
- `model_type`: `glm5_next`; text sub-config `glm5_next_text`.
- `max_position_embeddings`: `1048576`.
- `num_hidden_layers`: `45`.
- `hidden_size`: `4096`.
- `num_attention_heads`: `64`.
- `num_key_value_heads`: `64`.
- `mhc`: `true`.
- MoE settings include `n_routed_experts: 288`, `n_shared_experts: 1`, and
  `num_experts_per_tok: 8`.
- The layer pattern is three `linear_attention` layers followed by one
  `deepseek_sparse_attention` layer, repeated through the stack, ending with a
  final `linear_attention` layer. That yields 34 linear-attention layers and 11
  sparse-attention layers.
- Index settings include `index_topk: 2048`, `index_kpool: 4`, and
  `index_kpool_compress: true`.
- The vision config is a 24-layer encoder with `image_size: 448`,
  `patch_size: 14`, `temporal_patch_size: 2`, and output hidden size 4096.
- The published checkpoint config uses FP8 quantization metadata with
  `quant_method: fp8` and `fmt: e4m3`.

This is not a plain dense transformer target. Any Local Run or external serving
verifier should preflight framework support for GLM-5.3-Flash specifically,
including the linear-attention state pool, DSA sparse attention, FP8 handling,
multimodal processor, and tool/reasoning parsers.

## API Surface

The Z.ai model code is `glm-5.3-flash`. The documented hosted API is Chat
Completions at:

```text
POST https://api.z.ai/api/paas/v4/chat/completions
```

The model guide recommends:

- `temperature: 1`.
- `top_p: 0.95`.
- `reasoning_effort: max`.
- `thinking.type: enabled`.
- `thinking.clear_thinking: false`.
- For streaming, `stream: true` and `tool_stream: true`.

The guide says text parameters are consistent with GLM-5.3 and support a
1M-token context window. Image input is carried as content blocks under
`messages[].content[]` with `type: image_url`; multiple images use multiple
`image_url` blocks. The Chat Completion schema also covers video and file input
blocks for the multimodal request path.

The thinking-mode docs are the key compatibility constraint. They say thinking
is activated by default for the GLM-5.3, GLM-5.3-Flash, GLM-5.2, GLM-5.1,
GLM-5, and GLM-4.7 series, and they explicitly note that `GLM-5.3` and
`GLM-5.3-FLASH` use forced thinking and cannot disable it. The API schema also
says `thinking.type` can only be enabled for GLM-5.3 and GLM-5.3-FLASH, with
depth controlled by `reasoning_effort`.

Preserved Thinking is important for agent loops. When `clear_thinking=false`,
the caller must return the complete, unmodified, correctly ordered historical
`reasoning_content` in `messages`. Missing, truncated, rewritten, or reordered
thinking blocks may degrade performance or prevent Preserved Thinking from
taking effect.

Function calling uses ordinary chat-completion tool fields:

- Request `tools` describes functions.
- `tool_choice` defaults to and only supports `auto`.
- Responses include `tool_calls`, with a function `name`, JSON-string
  `arguments`, and an `id`.

## Benchmarks and Pricing

Z.ai reports these GLM-5.3-Flash scores in its announcement:

| Area | Benchmark | GLM-5.3-Flash |
| --- | --- | ---: |
| Coding | Terminal Bench 2.1 | 84.3 |
| Coding | DeepSWE v1.1 | 63.4 |
| Coding | NL2Repo | 56.3 |
| Agentic | Toolathlon Verified | 78.4 |
| Agentic | AutomationBench v1.0.6 | 48.8 |
| Agentic | Agents' Last Exam | 26.3 |
| Agentic | HLE w/ Tools | 55.3 |
| Agentic | GDPval-AA v2 | 1773 |
| Vision | OfficeQA Pro | 62.4 |
| Vision | CharXiv Reasoning w/ Tools | 89.4 |
| Vision | Chartography w/ Tools | 78 |
| Vision | BabyVision | 53.4 |
| Vision | MVBench | 77.8 |
| Vision | MMVU | 80.5 |

Two deltas matter for the existing GLM-5.2 serving effort:

- DeepSWE v1.1: GLM-5.3-Flash `63.4` vs. GLM-5.2 `46.2`.
- AutomationBench v1.0.6: GLM-5.3-Flash `48.8` vs. GLM-5.2 `26.2`.

Z.ai also reports that on its in-house Z.ai Code Bench v1.0, run on Claude Code
2.1.207, GLM-5.3-Flash at max effort nearly matches Claude Opus 4.8:
`29.0` vs. `29.5`.

Treat those benchmark claims as first-party positioning, not reproduced
evidence. The footnotes matter because the coding-agent numbers use high-budget
settings: DeepSWE is reported with mini-swe-agent, `temperature=0.95`,
`top_p=1.0`, a 6-hour timeout, and 400K context; Terminal-Bench 2.1 is reported
with Claude Code 2.1.207, `temperature=1.0`, `top_p=1`, `max_new_tokens=65536`,
and a 6-hour timeout.

The public pricing page lists GLM-5.3-Flash at discounted per-1M-token prices:

| Model | Input | Cached Input | Cached Input Storage | Output |
| --- | ---: | ---: | --- | ---: |
| GLM-5.3-Flash | $0.075 | $0.015 | Limited-time Free | $0.25 |
| GLM-5.3 | $1.40 | $0.26 | Limited-time Free | $4.40 |
| GLM-5.2 | $1.40 | $0.26 | Limited-time Free | $4.40 |

The same page shows list prices for GLM-5.3-Flash of `$0.15` input, `$0.03`
cached input, and `$0.50` output, with a 50 percent discount ending at 24:00 on
2026-09-09 UTC+8. The model guide says GLM-5.3-Flash is available to GLM Coding
Plan users with 3x the usable quota of GLM-5.3.

## Local Serving

The Hugging Face model card says GLM-5.3-Flash supports SGLang, vLLM,
TokenSpeed, and KTransformers for local deployment. The SGLang recipe is the
most detailed first-party-linked serving source found in this pass.

SGLang says its GLM-5.3-Flash recipe covers H100, H200, B200, B300, GB200, and
GB300, with MTP and multimodal serving. It recommends a GLM-5.3-Flash-capable
SGLang image:

```sh
docker pull lmsysorg/sglang:glm-5.3-flash
```

Its model introduction describes GLM-5.3-Flash as a multimodal MoE using hybrid
attention across MLA, DSA, and KDA, with mHC and a native MTP draft layer. The
recipe's low-latency path starts with adaptive MTP 5/1/6 speculative decoding;
its high-throughput path starts with speculative decoding off for sustained
batches.

Important SGLang operational details:

- Generated commands use `--model-path zai-org/GLM-5.3-Flash`.
- Recipes enable `--reasoning-parser glm45` and `--tool-call-parser glm47` by
  default.
- With the reasoning parser enabled, the OpenAI-compatible chat API places
  thinking in `message.reasoning_content` and final answer text in
  `message.content`.
- GLM-5.3-Flash maintains both a paged KV pool and a separate KDA state pool.
  The KDA pool can limit concurrency before KV memory is exhausted.
- Multimodal serving is enabled. The processor samples video at 2 FPS and caps
  video input at 240,000 visual tokens. `torchcodec` is required before sending
  video requests.
- On Blackwell, the SGLang recipe defaults to FP8 KV cache with TRT-LLM DSA; on
  H100 and H200 it defaults to BF16 KV cache with TileLang DSA.

KTransformers documents native support for 1M context and multimodality, and
says it reads the official FP8 weights directly without model conversion or
additional expert-weight quantization. It reports the FP8 model occupying about
306 GiB and recommends at least 350 GB of available system memory. Its example
commands expose an OpenAI-compatible endpoint at `/v1/chat/completions`.

## Monarch Implications

The existing GLM-5.2 local-serving guide describes this topology:

```text
Codex CLI / IDE
  -> OpenAI Responses API
  -> Responses-to-Chat adapter
  -> serving frontend
  -> GLM workers
```

That topology still applies for GLM-5.3-Flash when the backend exposes only
OpenAI-compatible Chat Completions. Z.ai documents Chat Completions and OpenAI
SDK compatibility, not OpenAI Responses API parity. A Codex-facing endpoint
still needs `POST /v1/responses` semantics unless the selected serving stack
adds that directly.

The adapter contract needs different acceptance criteria than GLM-5.2:

- Do not assume thinking can be disabled. Z.ai's model-specific docs say
  GLM-5.3-Flash can only use `thinking.type: enabled`.
- Preserve `reasoning_content` across `previous_response_id` turns if the
  backend uses Preserved Thinking with `clear_thinking=false`.
- Keep reasoning separate from visible answer text when mapping chat responses
  into Responses events.
- Exercise streaming tool calls with both `stream: true` and `tool_stream: true`.
- Replay assistant reasoning blocks, assistant tool calls, tool results, and
  visible content in the order required by the backend.
- Decide deliberately whether Codex should receive reasoning events or whether
  the adapter should retain reasoning privately for backend continuity.
- Add multimodal smoke coverage if GLM-5.3-Flash is being evaluated for browser
  or computer-use workflows, because visual input is a first-class product
  claim rather than an optional side channel.

The Local Run Ladder for a future GLM-5.3-Flash Capacity Verifier should include
these Contract Artifacts:

- Backend identity: model id, serving framework, framework version or image,
  checkpoint revision, quantization mode, visible GPU set, and command line.
- Parser behavior: whether reasoning and tool-call parsers are enabled, and
  sample raw chat chunks proving where `reasoning_content`, `content`, and
  `tool_calls` appear.
- Responses adapter transcript: request, streamed Responses events, backend
  chat requests, backend chat chunks, and final reconstructed response.
- Tool-loop result: at least one multi-step task that forces thinking around
  tool execution and validates ordered continuation with tool results.
- Multimodal result: at least one image request, and a video/file request only
  if the selected deployment profile claims support for that input type.
- Long-context result: a bounded context-window smoke that is feasible on the
  selected hardware, with the tested token count recorded rather than inferred
  from config.

## Open Questions

- The hosted API docs say GLM-5.3-Flash thinking cannot be disabled, while the
  SGLang recipe says request-level `chat_template_kwargs: {"thinking": false}`
  can disable thinking. Treat this as backend-specific until tested. For Codex
  compatibility, the stricter hosted-API behavior is the safer default.
- The benchmark table is first-party. Use it for prioritization, then require
  local Contract Artifacts before claiming Monarch serving readiness.
- The vLLM and TokenSpeed recipes were identified from first-party links, but
  this pass did not execute them. Pin the exact framework build or image before
  any verifier depends on them.
- The model card metadata says `license: mit`, but deployment still depends on
  the terms of each serving stack, hosted API plan, and any benchmark harnesses
  used for local evaluation.

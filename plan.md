# Provider Selection and DeepSeek V4 Translation Plan

## Capability

An operator submitting a translation job can explicitly choose one provider/model:

1. Groq (the existing free, multi-model fallback lane)
2. DeepSeek V4 Flash (`deepseek-v4-flash`)
3. DeepSeek V4 Pro (`deepseek-v4-pro`)

DeepSeek jobs preserve the existing translation quality contract while translating ordered groups of up to five consecutive pages per request. The provider selection, actual model, token usage, and retry count must be retained in job artifacts for audit and cost review.

## Fixed Decisions

- Do not read, log, return, or commit `DEEPSEEK_API_KEY`; load it only from `DEEPSEEK_API_KEY` in `.env`.
- DeepSeek client code lives in a new module. Do not add DeepSeek branches to `groq_client.py`.
- A requested provider is authoritative. A DeepSeek failure must not silently fall back to Groq, and a Groq failure must not incur DeepSeek cost.
- Preserve the full `VETERAN_TRANSLATOR_SYSTEM_PROMPT`, glossary, rolling context, parser contract, deterministic quality gate, and semantic review workflow for all providers.
- A DeepSeek translation group contains at most five consecutive pages. It must also obey a configurable segment and character/token budget; the 1M context window is not a reason to send an unbounded payload.
- Translate DeepSeek groups in chapter reading order. Do not run five page-groups in parallel by default because later groups need the confirmed Thai context from prior groups. OCR, image work, and upload work may remain concurrently bounded.
- Use a non-thinking/default chat mode for normal translation unless a later evaluated quality mode proves thinking is worth its additional latency/cost.
- Existing jobs and the existing Groq behavior remain backward compatible; default selection is Groq.

## Current Architecture

- `frontend/src/pages/SubmitJob.tsx` submits only `source_url`.
- `backend/src/domains/jobs/schemas.py` and `service.py` accept/store only that URL.
- `backend/src/pipeline/worker.py` translates each page through `AITranslatorEngine` with eight prior translated segments as rolling context.
- `backend/src/infrastructure/ai/groq_client.py` is an OpenAI-compatible chat client with Groq-only fallback and rate-limit handling.
- Translation artifacts already retain model name, attempt count, source, draft, final text, and QC status; this should become the source of truth for actual DeepSeek usage.

## Implementation Contract

### Provider and Model Types

Create a single typed provider selection shared by API, worker, and UI:

```text
groq
deepseek-v4-flash
deepseek-v4-pro
```

Do not let the frontend send arbitrary provider/model strings. Validate with a Pydantic enum at the API boundary. Resolve the enum to the actual API model ID only in backend code.

### New DeepSeek Client

Create `backend/src/infrastructure/ai/deepseek_client.py` with a narrow interface compatible with the translator's completion-result contract:

- Read `settings.DEEPSEEK_API_KEY`; fail fast with a safe configuration error when it is missing.
- Use the official DeepSeek OpenAI-compatible chat-completions endpoint and the selected model ID.
- Return `CompletionResult(text, model, attempts)` plus provider-specific usage metadata if available.
- Use a dedicated semaphore, timeout, exponential backoff for transient 429/5xx/network errors, and a bounded retry count.
- Never retry by changing from Flash to Pro or from DeepSeek to Groq unless a future explicit product policy permits it.
- Preserve JSON-only response parsing and do not expose provider response bodies in user-facing errors or logs.

Before implementation, verify the active official DeepSeek endpoint, model IDs, pricing, response-usage fields, and thinking-mode parameter against the account's current API documentation. The official V4 preview release currently names `deepseek-v4-flash` and `deepseek-v4-pro` and states both support 1M context, but pricing/limits must not be copied from screenshots into code without verification.

### Translator Abstraction

Refactor only enough to inject a completion client into `AITranslatorEngine`; do not duplicate prompt, parser, glossary, post-processing, or quality code by provider.

- Define a protocol/interface for `generate_chat_completion_result(messages, temperature, max_tokens)`.
- Keep `GroqClient` as one implementation and use the new `DeepSeekClient` as the other.
- Select the client once per job and retain that selection through all batch, fallback, and semantic-review calls.
- Ensure a per-segment fallback, if needed, uses the selected provider and sees the same glossary/context as the original group.

### Five-Page DeepSeek Batch Scheduler

After OCR completes for the chapter:

1. Order all `OCRSegment`s by `page_index`, then `reading_order`.
2. Partition pages into consecutive groups of at most five pages.
3. For each group, create one `TranslationBatchRequest` containing all eligible segments from those pages, the locked glossary, and the last eight confirmed translations from preceding pages.
4. Serialize output by stable `segment_id`; reject duplicate, missing, or unexpected IDs exactly as today.
5. Run existing deterministic QC and selective review before committing the group to rolling context.
6. Append approved group results to rolling context, then continue to the next group.

Dynamic split rules:

- Split a five-page group before the request if it exceeds `DEEPSEEK_MAX_BATCH_SEGMENTS` or `DEEPSEEK_MAX_BATCH_INPUT_CHARS`.
- On a payload-size or response-format failure, retry once with the same group, then split the group into smaller consecutive page groups. Do not fall back to a different provider.
- Keep the final group smaller when a chapter is not divisible by five.

Recommended initial configuration (environment-backed, not UI-editable):

```text
DEEPSEEK_BATCH_PAGES=5
DEEPSEEK_MAX_BATCH_SEGMENTS=80
DEEPSEEK_MAX_BATCH_INPUT_CHARS=120000
DEEPSEEK_TIMEOUT_SECONDS=90
DEEPSEEK_MAX_RETRIES=2
```

The exact segment/character budget must be adjusted only after measuring real OCR payloads and DeepSeek token usage; do not assume five pages are always safe.

### API and Database Changes

Add provider/model selection to a job at creation time:

- `JobSubmitReq`: add a required-with-default `translation_provider` enum defaulting to `groq`.
- `TranslationJob`: persist `translation_provider`, requested model, actual model, estimated input/output tokens, actual input/output tokens when returned, and cost-estimate fields as nullable/zero-safe values.
- Use an Alembic migration (or an explicit SQLite-compatible migration path). `create_all()` does not add columns to an existing database.
- Extend `JobStatusRes` with the requested provider/model and display-safe cost/usage fields only; never return API keys.
- Persist provider/model and token usage in translation artifacts for every batch/review request.

### Submit UI

In `SubmitJob.tsx`:

- Add an accessible radio group or segmented selector with Groq, DeepSeek V4 Flash, and DeepSeek V4 Pro.
- Default to Groq and clearly label DeepSeek as paid.
- Explain the DeepSeek batching behavior as “up to 5 consecutive pages per translation request” without promising a fixed price or fixed completion time.
- Before submit, show the chosen model and a cost warning. After backend estimation is implemented, show a non-binding estimated range and require a confirmation for Pro jobs above a configurable cap.
- Store the selection with the active job so refresh/polling displays the correct provider.
- Update status language from “AI Groq” to provider-neutral text plus the selected model.

## Quality and Cost Guardrails

- The system prompt must be identical across Groq and DeepSeek except for transport/JSON-format instructions that are proven necessary for provider compatibility.
- Never optimize DeepSeek input by removing glossary, rolling context, source text, stable IDs, or semantic-review evidence before a golden-corpus comparison shows no regression.
- Maintain a chapter-level golden corpus including Chapter 153 cases, pronouns, locked terms, ambiguous terminology, omissions, malformed source grammar, and multi-bubble continuity.
- Add a provider comparison harness that runs the same frozen OCR payload through Groq, Flash, and Pro and reports: parse success, omission/QC failures, locked-term fidelity, human preference score, input/output tokens, latency, and estimated cost.
- Start Pro as an opt-in/manual selection only. Do not automatically upgrade Flash to Pro based on a heuristic until cost and quality thresholds are approved.
- Add per-job maximum spend/token caps and fail safely before exceeding them. The UI must surface `FAILED_BUDGET_LIMIT` distinctly from provider/network failures.
- Record request IDs where DeepSeek provides them, redact Authorization data, and log only aggregate usage/cost fields.

## Test Plan

### Unit Tests

- Pydantic rejects arbitrary provider strings and defaults missing selection to Groq.
- `DeepSeekClient` sends the selected official model ID, correct authorization header, timeout, JSON request, and no Groq fallback.
- Missing DeepSeek key produces a safe configuration error without leaking configuration values.
- Usage parsing handles missing usage fields safely.
- Five-page partitioner preserves page order, keeps a final short group, and splits oversized groups without reordering IDs.
- DeepSeek group failure retries/splits within DeepSeek only.
- The shared translator receives the same full prompt, glossary, context, parser behavior, and quality review payload for Groq and DeepSeek.

### Integration Tests

- Submit each of the three provider selections; verify persisted job metadata and selected worker client.
- Verify a five-page batch carries ordered segments and rolling context only from approved prior groups.
- Verify semantic review uses the selected provider and persists actual model/attempts.
- Verify migration works against an existing SQLite database snapshot.
- Verify budget cap blocks the next paid request before an API call.

### E2E Tests

- Submit page offers all three choices, defaults to Groq, persists selection after refresh, and renders provider-neutral status.
- A DeepSeek Flash job and a Pro job show their correct selected model in final job details.
- Failure states distinguish invalid provider configuration, budget cap, and provider timeout.

## Rollout

1. Implement behind a feature flag with Groq remaining the default.
2. Run frozen golden-corpus comparisons offline/mocked first.
3. Run one manually selected Flash chapter in shadow mode; inspect artifacts and actual cost.
4. Run one manually selected Pro chapter on the same source; compare human-reviewed quality, latency, and cost.
5. Enable paid options in the UI only after the comparison report is accepted.
6. Keep no automatic provider switching in the first release.

## Non-Goals

- No automatic retranslation of existing chapters.
- No bulk 25-page single request.
- No concurrent translation of dependent page groups by default.
- No exposing DeepSeek credentials to browser/client code.
- No prompt compression or terminology/context removal as a cost-saving method.
- No changes to the currently running backend in this planning task.

## Open Questions for the Implementing Model

1. What official DeepSeek API endpoint, request fields, usage fields, rate limits, and current pricing apply to this account at implementation time?
2. Should Flash and Pro use normal mode only, or should Pro offer a separately evaluated thinking-mode option?
3. What THB/USD per-job budget cap and confirmation threshold should the UI enforce?
4. Should the provider choice be available to all submitters or only a super-admin/operator?
5. Should five pages mean exactly five source pages, or should a page-count group split earlier when OCR segmentation is unusually dense? The recommended answer is dynamic splitting by both page count and payload budget.

## Handoff

Ready for implementation by another model. Start with schema/client/batch-scheduler unit tests, then backend API/database migration, then UI. Do not begin with prompt changes. Validate DeepSeek's current official API details before writing the client.

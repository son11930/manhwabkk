from dataclasses import dataclass
from typing import Dict, Any, List
import httpx
import time
from src.config import settings

import asyncio

# Global semaphore to limit concurrent Groq API calls across the entire app (prevents 429 rate limit freezes)
_groq_semaphore = asyncio.Semaphore(3)

# Model Circuit Breaker / Cooldown registry mapping model name -> expiration timestamp (in seconds)
_exhausted_models: Dict[str, float] = {}

# Known Tokens-Per-Minute (TPM) limits per model from Groq tier table
MODEL_TPM_LIMITS: Dict[str, int] = {
    "llama-3.3-70b-versatile": 12000,
    "openai/gpt-oss-120b": 8000,
    "qwen/qwen3-32b": 6000,
    "qwen/qwen3.6-27b": 8000,
    "meta-llama/llama-4-scout-17b-16e-instruct": 30000,
    "llama-3.1-8b-instant": 6000,
    "openai/gpt-oss-20b": 8000,
    "allam-2-7b": 6000,
    "groq/compound": 70000,
    "groq/compound-mini": 70000,
}

_tpm_tracker: Dict[str, List[tuple]] = {}

def _record_tpm_usage(model: str, tokens: int) -> None:
    now = time.time()
    events = _tpm_tracker.setdefault(model, [])
    events.append((now, tokens))
    _tpm_tracker[model] = [(ts, cnt) for ts, cnt in events if now - ts < 60.0]

def _get_current_tpm(model: str) -> int:
    now = time.time()
    events = _tpm_tracker.get(model, [])
    active = [(ts, cnt) for ts, cnt in events if now - ts < 60.0]
    _tpm_tracker[model] = active
    return sum(cnt for _, cnt in active)

def _can_accommodate_tpm(model: str, estimated_tokens: int = 1600) -> bool:
    limit = MODEL_TPM_LIMITS.get(model, 10000)
    current_used = _get_current_tpm(model)
    return (current_used + estimated_tokens) <= int(limit * 0.90)


@dataclass(frozen=True)
class CompletionResult:
    """Completion text with enough provenance for translation QA artifacts."""

    text: str
    model: str
    attempts: int

class GroqClient:
    """
    HTTP client wrapper for Groq AI API (Llama-3.3-70b-versatile / Mixtral).
    """
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or settings.GROQ_MODEL
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"

    def get_fallback_models(self) -> List[str]:
        """Returns the verified Groq API model hierarchy ordered by intelligence and rate limit capacity (78,000 combined TPM)."""
        fallback_models = [
            self.model,                                   # 1. Primary model (e.g. llama-3.3-70b-versatile - 100K TPD)
            "openai/gpt-oss-120b",                        # 2. 120B model, excellent Thai - 200K TPD
            "qwen/qwen3-32b",                             # 3. Qwen 32B multilingual - 500K TPD
            "qwen/qwen3.6-27b",                           # 4. Qwen 27B multilingual - 200K TPD
            "meta-llama/llama-4-scout-17b-16e-instruct",  # 5. Llama 4 Scout 17B - 500K TPD
            "llama-3.1-8b-instant",                       # 6. Llama 3.1 8B instant - 500K TPD
            "openai/gpt-oss-20b",                         # 7. OpenAI OSS 20B - 200K TPD
            "allam-2-7b",                                 # 8. Allam 2 7B - 500K TPD
            "groq/compound",                              # 9. Groq compound router
            "groq/compound-mini",                         # 10. Groq compound mini router
        ]
        models_to_try = []
        for m in fallback_models:
            if m not in models_to_try:
                models_to_try.append(m)
        return models_to_try

    def is_all_models_exhausted(self) -> bool:
        """Checks if all models in hierarchy are currently in active rate-limit cooldown or deprecated."""
        now = time.time()
        models_to_try = self.get_fallback_models()
        for m in models_to_try:
            if m not in _exhausted_models or now >= _exhausted_models[m]:
                return False
        return True

    async def generate_chat_completion_result(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 650
    ) -> CompletionResult:
        """
        Sends chat completion request to Groq API with automatic multi-model fallback hierarchy.
        If primary model hits HTTP 429 (rate limit full) or errors out, automatically switches to backup AI models.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        attempt_count = 0
        for global_attempt in range(3):
            if self.is_all_models_exhausted():
                if global_attempt < 2:
                    print(f"[Rate Limit Patience] All AI models currently in cooldown. Waiting 10s for Groq token refill (Pass {global_attempt+1}/3)...", flush=True)
                    await asyncio.sleep(10.0)
                    now = time.time()
                    for m in list(_exhausted_models.keys()):
                        if _exhausted_models[m] - now < 30:
                            del _exhausted_models[m]
                    continue
                else:
                    print("[Circuit Breaker] All AI models exhausted after waiting 20s. Returning empty string.", flush=True)
                    return CompletionResult(text="", model="", attempts=attempt_count)
                
            models_to_try = self.get_fallback_models()

            async with _groq_semaphore:
                for model_idx, current_model in enumerate(models_to_try):
                    now = time.time()
                    if current_model in _exhausted_models:
                        if now < _exhausted_models[current_model]:
                            if model_idx == len(models_to_try) - 1 and global_attempt == 0:
                                pass # Let it drop down to patience pause
                            print(f"[Circuit Breaker] Skipping model {current_model} due to active cooldown ({int(_exhausted_models[current_model] - now)}s remaining)", flush=True)
                            continue
                        else:
                            del _exhausted_models[current_model]

                    if not _can_accommodate_tpm(current_model, estimated_tokens=2200):
                        used_tpm = _get_current_tpm(current_model)
                        limit_tpm = MODEL_TPM_LIMITS.get(current_model, 10000)
                        if model_idx == 0:
                            print(f"[TPM Tracker] Primary model {current_model} near TPM ceiling ({used_tpm}/{limit_tpm} TPM). Pausing 15s to refill primary window...", flush=True)
                            await asyncio.sleep(15.0)
                        elif model_idx < len(models_to_try) - 1:
                            print(f"[TPM Tracker] Model {current_model} near TPM ceiling ({used_tpm}/{limit_tpm} TPM). Proactively switching to next model...", flush=True)
                            continue
                        else:
                            print(f"[TPM Tracker] Model {current_model} near TPM ceiling ({used_tpm}/{limit_tpm} TPM). Pausing 6s for sliding window refill...", flush=True)
                            await asyncio.sleep(6.0)

                    payload = {
                        "model": current_model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens
                    }
                    
                    max_model_attempts = 2
                    for attempt in range(max_model_attempts):
                        try:
                            attempt_count += 1
                            async with httpx.AsyncClient(timeout=20.0) as client:
                                response = await client.post(self.base_url, headers=headers, json=payload)
                                if response.status_code == 429:
                                    retry_after_val = float(response.headers.get("Retry-After", 12.0))
                                    max_pause = 60.0 if model_idx == 0 else 15.0
                                    if retry_after_val <= max_pause and attempt < max_model_attempts - 1:
                                        print(f"[Rate Limit Pause] Pausing {retry_after_val}s to retry primary model {current_model}...", flush=True)
                                        await asyncio.sleep(retry_after_val)
                                        continue
                                    retry_after = max(retry_after_val, 15.0)
                                    _exhausted_models[current_model] = time.time() + retry_after
                                    if model_idx < len(models_to_try) - 1:
                                        next_model = models_to_try[model_idx + 1]
                                        print(f"[AI Backup Triggered] Model {current_model} hit Rate Limit (429). Cooldown set to {int(retry_after)}s -> Switching to {next_model}", flush=True)
                                    else:
                                        print(f"[AI Backup Triggered] Model {current_model} hit Rate Limit (429). Cooldown set to {int(retry_after)}s (All AI models exhausted)", flush=True)
                                    break
                                response.raise_for_status()
                                data = response.json()
                                actual_tokens = int(data.get("usage", {}).get("total_tokens", 1600))
                                _record_tpm_usage(current_model, actual_tokens)
                                return CompletionResult(
                                    text=data["choices"][0]["message"]["content"].strip(),
                                    model=current_model,
                                    attempts=attempt_count,
                                )
                        except (httpx.RequestError, httpx.HTTPStatusError) as e:
                            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in [400, 404]:
                                # Deprecated or unsupported model on Groq, put on long cooldown
                                _exhausted_models[current_model] = time.time() + 3600.0
                                print(f"[Groq Model Deprecated] Model {current_model} returned 400/404. Placing on Circuit Breaker cooldown.", flush=True)
                                break
                            if model_idx < len(models_to_try) - 1 and attempt == max_model_attempts - 1:
                                next_model = models_to_try[model_idx + 1]
                                print(f"[AI Backup Triggered] Model {current_model} error ({e}) -> Switching to {next_model}...", flush=True)
                                break
                            elif attempt < max_model_attempts - 1:
                                await asyncio.sleep(1.5)
                            else:
                                print(f"[Groq Warning] Model {current_model} failed ({e})", flush=True)
                                
            # If we reached here, all models in models_to_try were skipped or hit 429 during this pass!
            if global_attempt < 2:
                print(f"[Rate Limit Patience] All AI models hit rate limit or cooldown. Waiting 15s for Groq refill (Pass {global_attempt+1}/3) to ensure 100% translation without skipping...", flush=True)
                await asyncio.sleep(15.0)
                now = time.time()
                for m in list(_exhausted_models.keys()):
                    if _exhausted_models[m] - now < 30:
                        del _exhausted_models[m]
                        
        print("[Groq Error] All AI models failed after 3 global patience passes. Returning empty string.", flush=True)
        return CompletionResult(text="", model="", attempts=attempt_count)

    async def generate_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 650,
    ) -> str:
        """Backward-compatible text-only completion API."""
        result = await self.generate_chat_completion_result(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return result.text

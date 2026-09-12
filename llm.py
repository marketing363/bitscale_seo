"""Model-call layer (BUILD-SPEC §2, §8).

- Two tiers from config.yaml: strong / fast.
- call_node(node_id, tier, **vars): load prompt → call model → parse JSON
  (strip fences; retry once with the error appended; then raise).
- The client is injectable: tests and the `--fake` CLI flag set a ScriptedLLM
  via set_client(); a real run uses the Anthropic SDK (needs ANTHROPIC_API_KEY).
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
from pathlib import Path

import yaml

from prompts import load_prompt

_CONFIG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
_MODELS = _CONFIG["models"]
_PRICING = _CONFIG.get("pricing", {})

_CLIENT = None

# pending usage events; the graph node wrapper drains these into the runlog
_USAGE_LOG: list[dict] = []


def _cost_usd(tier: str, input_tokens: int, output_tokens: int) -> float:
    p = _PRICING.get(tier, {})
    return round(
        input_tokens * p.get("input_per_mtok", 0) / 1e6
        + output_tokens * p.get("output_per_mtok", 0) / 1e6,
        6,
    )


def record_usage(node_id: str, tier: str, usage: dict) -> None:
    _USAGE_LOG.append({
        "node": node_id,
        "model": usage.get("model"),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cost_usd": _cost_usd(tier, usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
    })


def drain_usage() -> list[dict]:
    """Return + clear pending usage events (called by the node wrapper)."""
    out = list(_USAGE_LOG)
    _USAGE_LOG.clear()
    return out


def set_client(client) -> None:
    """Inject a client (e.g. ScriptedLLM) for tests / offline runs."""
    global _CLIENT
    _CLIENT = client


def reset_client() -> None:
    global _CLIENT
    _CLIENT = None


def get_client():
    global _CLIENT
    if _CLIENT is None:
        provider = _CONFIG.get("provider", "anthropic")
        _CLIENT = {
            "azure_openai": AzureOpenAIClient,
            "claude_code": ClaudeCodeClient,
            "relay": RelayClient,
            "anthropic": AnthropicClient,
        }.get(provider, AnthropicClient)()
    return _CLIENT


class AnthropicClient:
    """Real model client. Lazy-imports the SDK so offline runs never need it."""

    def __init__(self, max_tokens: int = 4096):
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic SDK not installed. `pip install anthropic`, set "
                "ANTHROPIC_API_KEY, or run with --fake for an offline scripted run."
            ) from e
        self._client = Anthropic()  # reads ANTHROPIC_API_KEY from env
        self.max_tokens = max_tokens

    def complete(self, prompt: str, tier: str, node_id: str | None = None) -> tuple[str, dict]:
        model = _MODELS[tier]
        resp = self._client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        usage = {
            "model": model,
            "input_tokens": getattr(resp.usage, "input_tokens", 0),
            "output_tokens": getattr(resp.usage, "output_tokens", 0),
        }
        return text, usage


class AzureOpenAIClient:
    """Azure OpenAI client via the Responses API (raw HTTPS, no extra SDK dep).

    Reads from env:
      AZURE_OPENAI_ENDPOINT    full Responses URL incl. ?api-version=...
                               e.g. https://<res>.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview
      AZURE_OPENAI_API_KEY     the resource key
      AZURE_OPENAI_DEPLOYMENT  fallback deployment for both tiers (per-tier names
                               live in config.yaml -> azure_openai.deployments)

    The strong/fast tier abstraction is preserved: a tier maps to an Azure
    deployment name instead of a Claude model id.
    """

    def __init__(self, endpoint: str | None = None, api_key: str | None = None,
                 deployments: dict | None = None, max_output_tokens: int = 16000,
                 transport=None):
        import os
        cfg = _CONFIG.get("azure_openai", {})
        self.endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.deployments = {k: v for k, v in (deployments or cfg.get("deployments", {})).items() if v}
        self.fallback_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        self.max_output_tokens = max_output_tokens
        self._transport = transport
        if not self.endpoint or not self.api_key:
            raise RuntimeError(
                "Azure OpenAI provider selected (config.yaml -> provider) but "
                "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY are not set in the "
                "environment. Add them to the Claude Code environment variables, "
                "or run with --fake, or switch provider to 'anthropic'."
            )

    def _deployment(self, tier: str) -> str:
        dep = self.deployments.get(tier) or self.fallback_deployment
        if not dep:
            raise RuntimeError(
                f"No Azure deployment configured for tier '{tier}'. Set "
                "azure_openai.deployments in config.yaml or the "
                "AZURE_OPENAI_DEPLOYMENT environment variable."
            )
        return dep

    def complete(self, prompt: str, tier: str, node_id: str | None = None) -> tuple[str, dict]:
        import httpx
        deployment = self._deployment(tier)
        transport = self._transport or httpx.HTTPTransport(retries=2)
        with httpx.Client(timeout=180.0, transport=transport) as client:
            resp = client.post(
                self.endpoint,
                headers={"api-key": self.api_key, "content-type": "application/json"},
                json=({"model": deployment, "input": prompt, "max_output_tokens": self.max_output_tokens} | ({"reasoning": {"effort": "low"}} if "gpt-5" in deployment else {})),
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") and data["status"] != "completed":
            err = (data.get("error") or {}).get("message") or data.get("incomplete_details")
            raise RuntimeError(f"Azure OpenAI response not completed ({data['status']}): {err}")
        text = "".join(
            part.get("text", "")
            for item in data.get("output", []) if item.get("type") == "message"
            for part in item.get("content", []) if part.get("type") == "output_text"
        )
        usage = data.get("usage", {})
        return text, {
            "model": f"azure:{deployment}",
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }


class ClaudeCodeClient:
    """Run every model step through the local `claude` CLI (no API key).

    Uses `claude -p --output-format json`, which authenticates with your Claude
    Code login. Tools are disabled so each call is a pure JSON completion — the
    model never touches the repo. The strong/fast tiers map to --model values
    from config.yaml. Set CLAUDE_CODE_BIN to override the binary path.

    `runner` is injectable for tests: callable(args, prompt) -> (stdout, returncode).
    """

    def __init__(self, models: dict | None = None, binary: str | None = None,
                 timeout: int = 600, runner=None):
        import os
        self.models = models or _MODELS
        self.binary = binary or os.environ.get("CLAUDE_CODE_BIN", "claude")
        self.timeout = timeout
        self._runner = runner

    def complete(self, prompt: str, tier: str, node_id: str | None = None) -> tuple[str, dict]:
        import json as _json
        import shutil
        import subprocess
        model = self.models.get(tier, tier)
        args = [self.binary, "-p", "--output-format", "json", "--model", model,
                "--allowedTools", "",  # pure completion: no Bash/Edit/Write/Read
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',  # skip session MCP servers (faster startup)
                "--setting-sources", "",                      # ignore project/user settings/CLAUDE.md
                "--append-system-prompt",
                "Return ONLY the JSON object the user's schema asks for — no prose, "
                "no code fences, no tool use."]
        if self._runner is not None:
            stdout, rc, stderr = (*self._runner(args, prompt), "")[:3]
        else:
            if shutil.which(self.binary) is None:
                raise RuntimeError(
                    f"claude CLI '{self.binary}' not found. Install Claude Code and log in, "
                    "set CLAUDE_CODE_BIN, or switch config.yaml provider to anthropic/azure_openai."
                )
            proc = subprocess.run(args, input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout)
            stdout, rc, stderr = proc.stdout, proc.returncode, proc.stderr
        if rc != 0:
            raise RuntimeError(f"claude -p failed (rc={rc}): {stderr[:300] or stdout[:300]}")
        try:
            data = _json.loads(stdout)
        except _json.JSONDecodeError as e:
            raise RuntimeError(f"claude -p did not return JSON envelope: {e}: {stdout[:200]!r}") from e
        if data.get("is_error"):
            raise RuntimeError(f"claude -p returned an error: {str(data.get('result'))[:300]}")
        usage = data.get("usage", {}) or {}
        return data.get("result", ""), {
            "model": f"claude-code:{model}",
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class PendingResponse(RuntimeError):
    """Raised when the relay has written a prompt and is waiting for an answer."""

    def __init__(self, path: str, node_id: str):
        self.path, self.node_id = path, node_id
        super().__init__(
            f"relay: waiting for a response to node '{node_id}'.\n"
            f"  prompt written to : {path}\n"
            f"  write the answer to: {path.replace('.prompt.md', '.response.md')}\n"
            f"  then re-run with --resume to continue from here."
        )


class RelayClient:
    """Runs the graph with no API credentials at all.

    `claude -p` cannot authenticate from inside an existing Claude Code session -
    the parent's credentials are not visible to a spawned CLI - so ClaudeCodeClient
    401s there. This client closes that gap by turning each model step into a pair
    of files: the rendered prompt goes out, an answer is expected back, and the run
    halts cleanly in between. Whoever or whatever writes the response file is the
    model, which means an agent already holding a session can drive the pipeline
    without a key ever existing on disk.

    Responses are keyed by node id, so `--resume` replays every answered node from
    cache and only the first unanswered one stops the run again.
    """

    def __init__(self, relay_dir: str | None = None):
        self.dir = pathlib.Path(relay_dir or os.environ.get("RELAY_DIR", "relay"))
        self.dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    def _paths(self, node_id: str, prompt: str):
        # Keyed by a hash of the prompt, not by call order. A node that runs once
        # per section (c11_section_drafter) and a graph whose earlier nodes replay
        # from cache both shift the sequence number between runs, which silently
        # orphans an answer from the prompt it was written for. The hash does not
        # move, so a response always matches the prompt that produced it.
        digest = hashlib.sha1(prompt.encode()).hexdigest()[:8]
        stem = self.dir / f"{self._seq:02d}-{node_id}-{digest}"
        return stem.with_suffix(".prompt.md"), stem.with_suffix(".response.md")

    def _find_answer(self, node_id: str, prompt: str):
        """Match on the hash alone, so the sequence prefix may drift freely."""
        digest = hashlib.sha1(prompt.encode()).hexdigest()[:8]
        for candidate in self.dir.glob(f"*-{node_id}-{digest}.response.md"):
            text = candidate.read_text().strip()
            if text:
                return text
        return None

    def complete(self, prompt: str, tier: str, node_id: str | None = None) -> tuple[str, dict]:
        node_id = node_id or "unknown"
        self._seq += 1
        answered = self._find_answer(node_id, prompt)
        if answered:
            return answered, {"input_tokens": 0, "output_tokens": 0, "relayed": True}
        prompt_path, response_path = self._paths(node_id, prompt)

        prompt_path.write_text(prompt)
        raise PendingResponse(str(prompt_path), node_id)


def parse_json(text: str) -> dict:
    """Strip code fences, isolate the outermost JSON object, parse it."""
    cleaned = _FENCE.sub("", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in model output: {cleaned[:120]!r}")
    snippet = cleaned[start: end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON in model output: {e}") from e


def call_node(node_id: str, tier: str, **vars) -> dict:
    """Render the node's prompt, call the model, return parsed JSON."""
    prompt = load_prompt(node_id, **vars)
    client = get_client()
    text, usage = client.complete(prompt, tier, node_id=node_id)
    record_usage(node_id, tier, usage)
    try:
        return parse_json(text)
    except ValueError as e:
        retry_prompt = (
            prompt
            + f"\n\nYOUR PREVIOUS OUTPUT WAS NOT VALID JSON ({e}). "
            "Return ONLY the JSON object, with no surrounding prose or fences."
        )
        text2, usage2 = client.complete(retry_prompt, tier, node_id=node_id)
        record_usage(node_id, tier, usage2)
        return parse_json(text2)  # raises if still invalid

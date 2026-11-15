"""Credential-free producing configuration used for provenance and cache keys."""
from dataclasses import dataclass, field, asdict
import hashlib
import json
from .prompt import PROMPT, POLICY_PATH
from .validation import SCHEMA

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

@dataclass(frozen=True)
class Settings:
    provider: str = 'mock'
    model: str = 'gpt-4.1-mini-2025-04-14'
    endpoint: str = 'https://api.openai.com/v1/responses'
    timeout: float = 30
    max_output_tokens: int = 2048
    prompt: str = PROMPT
    schema: dict = field(default_factory=lambda: json.loads(json.dumps(SCHEMA)))
    policy: str = field(default_factory=lambda: POLICY_PATH.read_text())

    def public(self):
        return asdict(self)

    @property
    def fingerprint(self):
        return digest(json.dumps(self.public(),sort_keys=True,separators=(',',':')))

    @property
    def policy_version(self):
        return digest(self.policy)

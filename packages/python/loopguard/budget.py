"""Budget tracking and LLM pricing calculation for Loop-Guard."""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class ModelPricing:
    """Pricing in USD per 1M tokens."""
    prompt_per_1m: float
    completion_per_1m: float
    cached_prompt_per_1m: Optional[float] = None

    def calculate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0
    ) -> float:
        cost = 0.0
        # If cache pricing is defined and cached tokens > 0
        if self.cached_prompt_per_1m is not None and cached_tokens > 0:
            regular_prompt = max(0, prompt_tokens - cached_tokens)
            cost += (regular_prompt / 1_000_000.0) * self.prompt_per_1m
            cost += (cached_tokens / 1_000_000.0) * self.cached_prompt_per_1m
        else:
            cost += (prompt_tokens / 1_000_000.0) * self.prompt_per_1m

        cost += (completion_tokens / 1_000_000.0) * self.completion_per_1m
        return cost


# Standard pricing reference (as of 2025/2026 standard rates)
MODEL_CATALOG: Dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00, cached_prompt_per_1m=1.25),
    "gpt-4o-2024-08-06": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00, cached_prompt_per_1m=1.25),
    "gpt-4o-mini": ModelPricing(prompt_per_1m=0.15, completion_per_1m=0.60, cached_prompt_per_1m=0.075),
    "gpt-4-turbo": ModelPricing(prompt_per_1m=10.00, completion_per_1m=30.00),
    "gpt-3.5-turbo": ModelPricing(prompt_per_1m=0.50, completion_per_1m=1.50),
    "o1": ModelPricing(prompt_per_1m=15.00, completion_per_1m=60.00, cached_prompt_per_1m=7.50),
    "o1-mini": ModelPricing(prompt_per_1m=3.00, completion_per_1m=12.00, cached_prompt_per_1m=1.50),
    "o3-mini": ModelPricing(prompt_per_1m=1.10, completion_per_1m=4.40, cached_prompt_per_1m=0.55),
    
    # Anthropic
    "claude-3-5-sonnet-20241022": ModelPricing(prompt_per_1m=3.00, completion_per_1m=15.00, cached_prompt_per_1m=0.30),
    "claude-3-5-sonnet": ModelPricing(prompt_per_1m=3.00, completion_per_1m=15.00, cached_prompt_per_1m=0.30),
    "claude-3-7-sonnet": ModelPricing(prompt_per_1m=3.00, completion_per_1m=15.00, cached_prompt_per_1m=0.30),
    "claude-3-5-haiku": ModelPricing(prompt_per_1m=0.80, completion_per_1m=4.00, cached_prompt_per_1m=0.08),
    "claude-3-opus": ModelPricing(prompt_per_1m=15.00, completion_per_1m=75.00),
    
    # Default fallback pricing (conservative GPT-4o tier)
    "_default": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00),
}


def get_pricing_for_model(model_name: Optional[str]) -> ModelPricing:
    """Find pricing for a given model string (prefix or exact match)."""
    if not model_name:
        return MODEL_CATALOG["_default"]

    model_lower = model_name.lower()
    if model_lower in MODEL_CATALOG:
        return MODEL_CATALOG[model_lower]

    for key, pricing in MODEL_CATALOG.items():
        if key in model_lower:
            return pricing

    return MODEL_CATALOG["_default"]


@dataclass
class TokenUsageRecord:
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = "unknown"


class BudgetTracker:
    """Tracks token burn and session spend against a hard ceiling."""

    def __init__(self, max_cost_usd: float = 2.00, warning_threshold_ratio: float = 0.8):
        self.max_cost_usd = float(max_cost_usd)
        self.warning_threshold_usd = self.max_cost_usd * warning_threshold_ratio
        self.total_cost_usd: float = 0.0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_tokens: int = 0
        self.records: list[TokenUsageRecord] = []
        self.warning_emitted: bool = False

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: Optional[str] = None,
        cached_tokens: int = 0,
        explicit_cost: Optional[float] = None,
    ) -> Tuple[float, bool]:
        """
        Record token consumption and return (total_cost_usd, is_exceeded).
        """
        if explicit_cost is not None:
            cost = explicit_cost
        else:
            pricing = get_pricing_for_model(model)
            cost = pricing.calculate_cost(prompt_tokens, completion_tokens, cached_tokens)

        self.total_cost_usd += cost
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += (prompt_tokens + completion_tokens)

        self.records.append(
            TokenUsageRecord(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cached_tokens=cached_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost,
                model=model or "unknown",
            )
        )

        is_exceeded = self.total_cost_usd >= self.max_cost_usd
        return self.total_cost_usd, is_exceeded

    def should_warn(self) -> bool:
        """Returns True once when total cost reaches the warning threshold."""
        if not self.warning_emitted and self.total_cost_usd >= self.warning_threshold_usd:
            self.warning_emitted = True
            return True
        return False

    def is_exceeded(self) -> bool:
        return self.total_cost_usd >= self.max_cost_usd

    def get_summary(self) -> Dict[str, float]:
        return {
            "total_cost_usd": round(self.total_cost_usd, 5),
            "max_cost_usd": self.max_cost_usd,
            "pct_budget_used": round((self.total_cost_usd / self.max_cost_usd * 100) if self.max_cost_usd > 0 else 0, 2),
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
        }

import { ModelPricing } from "./types";

export const MODEL_CATALOG: Record<string, ModelPricing> = {
  // OpenAI
  "gpt-4o": { promptPer1M: 2.50, completionPer1M: 10.00, cachedPromptPer1M: 1.25 },
  "gpt-4o-mini": { promptPer1M: 0.15, completionPer1M: 0.60, cachedPromptPer1M: 0.075 },
  "gpt-4-turbo": { promptPer1M: 10.00, completionPer1M: 30.00 },
  "gpt-3.5-turbo": { promptPer1M: 0.50, completionPer1M: 1.50 },
  "o1": { promptPer1M: 15.00, completionPer1M: 60.00, cachedPromptPer1M: 7.50 },
  "o1-mini": { promptPer1M: 3.00, completionPer1M: 12.00, cachedPromptPer1M: 1.50 },
  "o3-mini": { promptPer1M: 1.10, completionPer1M: 4.40, cachedPromptPer1M: 0.55 },

  // Anthropic
  "claude-3-5-sonnet": { promptPer1M: 3.00, completionPer1M: 15.00, cachedPromptPer1M: 0.30 },
  "claude-3-7-sonnet": { promptPer1M: 3.00, completionPer1M: 15.00, cachedPromptPer1M: 0.30 },
  "claude-3-5-haiku": { promptPer1M: 0.80, completionPer1M: 4.00, cachedPromptPer1M: 0.08 },
  "claude-3-opus": { promptPer1M: 15.00, completionPer1M: 75.00 },

  // Default fallback
  _default: { promptPer1M: 2.50, completionPer1M: 10.00 },
};

export function getPricingForModel(modelName?: string): ModelPricing {
  if (!modelName) return MODEL_CATALOG._default;
  const lower = modelName.toLowerCase();
  if (MODEL_CATALOG[lower]) return MODEL_CATALOG[lower];

  for (const [key, pricing] of Object.entries(MODEL_CATALOG)) {
    if (lower.includes(key)) return pricing;
  }
  return MODEL_CATALOG._default;
}

export class BudgetTracker {
  maxCostUsd: number;
  totalCostUsd: number = 0;
  totalPromptTokens: number = 0;
  totalCompletionTokens: number = 0;
  totalTokens: number = 0;

  constructor(maxCostUsd: number = 2.00) {
    this.maxCostUsd = maxCostUsd;
  }

  recordUsage(params: {
    promptTokens: number;
    completionTokens: number;
    model?: string;
    cachedTokens?: number;
    explicitCost?: number;
  }): { totalCostUsd: number; isExceeded: boolean } {
    let cost = 0;
    if (params.explicitCost !== undefined) {
      cost = params.explicitCost;
    } else {
      const pricing = getPricingForModel(params.model);
      if (pricing.cachedPromptPer1M !== undefined && (params.cachedTokens || 0) > 0) {
        const regular = Math.max(0, params.promptTokens - (params.cachedTokens || 0));
        cost += (regular / 1_000_000) * pricing.promptPer1M;
        cost += ((params.cachedTokens || 0) / 1_000_000) * pricing.cachedPromptPer1M;
      } else {
        cost += (params.promptTokens / 1_000_000) * pricing.promptPer1M;
      }
      cost += (params.completionTokens / 1_000_000) * pricing.completionPer1M;
    }

    this.totalCostUsd += cost;
    this.totalPromptTokens += params.promptTokens;
    this.totalCompletionTokens += params.completionTokens;
    this.totalTokens += (params.promptTokens + params.completionTokens);

    return {
      totalCostUsd: this.totalCostUsd,
      isExceeded: this.totalCostUsd >= this.maxCostUsd,
    };
  }

  isExceeded(): boolean {
    return this.totalCostUsd >= this.maxCostUsd;
  }

  getSummary() {
    return {
      totalCostUsd: Number(this.totalCostUsd.toFixed(5)),
      maxCostUsd: this.maxCostUsd,
      pctBudgetUsed: Number(
        (this.maxCostUsd > 0 ? (this.totalCostUsd / this.maxCostUsd) * 100 : 0).toFixed(2)
      ),
      totalTokens: this.totalTokens,
      totalPromptTokens: this.totalPromptTokens,
      totalCompletionTokens: this.totalCompletionTokens,
    };
  }
}

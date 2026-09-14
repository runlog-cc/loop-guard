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

MODEL_CATALOG["gpt-4o-mini-2024-07-18"] = MODEL_CATALOG["gpt-4o-mini"];
MODEL_CATALOG["o1-mini-2024-09-12"] = MODEL_CATALOG["o1-mini"];
MODEL_CATALOG["gpt-4o-2024-08-06"] = MODEL_CATALOG["gpt-4o"];
MODEL_CATALOG["claude-3-5-sonnet-20241022"] = MODEL_CATALOG["claude-3-5-sonnet"];
export function validateNumber(value: number, integer = false): void {
  if (!Number.isFinite(value) || value < 0 || (integer && !Number.isSafeInteger(value))) throw new Error("Usage and prices must be finite nonnegative numbers; tokens must be integers");
}
export function getPricingForModel(modelName?: string): ModelPricing {
  if (!modelName) throw new Error("Unknown model: provide exact catalog pricing or explicitCost");
  const lower = modelName.toLowerCase();
  if (MODEL_CATALOG[lower]) return MODEL_CATALOG[lower];

  throw new Error("Unknown model: provide exact catalog pricing or explicitCost");
}

export class BudgetTracker {
  maxCostUsd: number;
  totalCostUsd: number = 0;
  totalPromptTokens: number = 0;
  totalCompletionTokens: number = 0;
  totalTokens: number = 0;

  constructor(maxCostUsd: number = 2.00) {
    validateNumber(maxCostUsd);
    this.maxCostUsd = maxCostUsd;
  }

  recordUsage(params: {
    promptTokens: number;
    completionTokens: number;
    model?: string;
    cachedTokens?: number;
    explicitCost?: number;
  }): { totalCostUsd: number; isExceeded: boolean } {
    for (const value of [params.promptTokens, params.completionTokens, params.cachedTokens ?? 0]) validateNumber(value, true);
    if ((params.cachedTokens ?? 0) > params.promptTokens) throw new Error("Cached tokens exceed prompt tokens");
    let cost = 0;
    if (params.explicitCost !== undefined) {
      validateNumber(params.explicitCost);
      cost = params.explicitCost;
    } else {
      const pricing = getPricingForModel(params.model);
      for (const value of [pricing.promptPer1M, pricing.completionPer1M, pricing.cachedPromptPer1M ?? 0]) validateNumber(value);
      if (pricing.cachedPromptPer1M !== undefined && (params.cachedTokens || 0) > 0) {
        const regular = Math.max(0, params.promptTokens - (params.cachedTokens || 0));
        cost += (regular / 1_000_000) * pricing.promptPer1M;
        cost += ((params.cachedTokens || 0) / 1_000_000) * pricing.cachedPromptPer1M;
      } else {
        cost += (params.promptTokens / 1_000_000) * pricing.promptPer1M;
      }
      cost += (params.completionTokens / 1_000_000) * pricing.completionPer1M;
    }

    validateNumber(this.totalCostUsd + cost);
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

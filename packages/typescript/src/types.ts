export type CircuitState = "closed" | "tripped" | "half_open";

export type TripReason =
  | "consecutive_retry"
  | "cycle_detected"
  | "budget_exceeded"
  | "max_depth_exceeded"
  | "manual_halt";

export interface TripPolicy {
  maxConsecutiveRetries?: number;
  maxDepth?: number;
  maxCostUsd?: number;
  detectCycles?: boolean;
  maxCycleLength?: number;
  minCycleRepetitions?: number;
  fallbackMode?: "exception" | "synthetic_response" | "custom";
  fallbackMessage?: string;
  customFallbackHandler?: (details: Record<string, any>) => any;
}

export interface ToolCallEvent {
  id: string;
  toolName: string;
  rawArgs: any;
  signature: string;
  timestamp: number;
  depth: number;
  isError: boolean;
  resultPreview?: string;
  costUsd?: number;
}

export interface ModelPricing {
  promptPer1M: number;
  completionPer1M: number;
  cachedPromptPer1M?: number;
}

export interface SessionTelemetry {
  sessionId: string;
  state: CircuitState;
  tripReason?: TripReason;
  tripDetails?: Record<string, any>;
  currentDepth: number;
  maxDepth: number;
  budget: {
    totalCostUsd: number;
    maxCostUsd: number;
    pctBudgetUsed: number;
    totalTokens: number;
    totalPromptTokens: number;
    totalCompletionTokens: number;
  };
  historyCount: number;
  observedRequestCount?: number;
  recentSignatures: string[];
  recentObservedSignatures?: string[];
  elapsedSeconds: number;
  history: Array<{
    id: string;
    toolName: string;
    signature: string;
    rawArgs: any;
    depth: number;
    isError: boolean;
    timestamp: number;
    resultPreview?: string;
  }>;
}

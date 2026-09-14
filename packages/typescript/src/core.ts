import { createHash } from "crypto";
import { BudgetTracker, validateNumber } from "./budget";
import {
  CircuitState,
  ToolCallEvent,
  TripPolicy,
  TripReason,
  SessionTelemetry,
} from "./types";

export class LoopGuardException extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LoopGuardException";
  }
}

export class CircuitTrippedError extends LoopGuardException {
  sessionId: string;
  reason: TripReason;
  toolName?: string;
  signature?: string;
  repetitionCount: number;
  currentDepth: number;
  costUsd: number;
  metadata: Record<string, any>;

  constructor(params: {
    message: string;
    sessionId: string;
    reason: TripReason;
    toolName?: string;
    signature?: string;
    repetitionCount?: number;
    currentDepth?: number;
    costUsd?: number;
    metadata?: Record<string, any>;
  }) {
    super(params.message);
    this.name = "CircuitTrippedError";
    this.sessionId = params.sessionId;
    this.reason = params.reason;
    this.toolName = params.toolName;
    this.signature = params.signature;
    this.repetitionCount = params.repetitionCount || 0;
    this.currentDepth = params.currentDepth || 0;
    this.costUsd = params.costUsd || 0;
    this.metadata = params.metadata || {};
  }
}

export class RepetitiveToolCallError extends CircuitTrippedError {
  constructor(params: any) {
    super(params);
    this.name = "RepetitiveToolCallError";
  }
}

export class BudgetExceededError extends CircuitTrippedError {
  constructor(params: any) {
    super(params);
    this.name = "BudgetExceededError";
  }
}

export class MaxDepthExceededError extends CircuitTrippedError {
  constructor(params: any) {
    super(params);
    this.name = "MaxDepthExceededError";
  }
}

export class SignatureHasher {
  private static normalize(obj: any): any {
    if (obj === null || obj === undefined) return obj;
    if (typeof obj !== "object") {
      if (typeof obj === "number") return Number(obj.toFixed(6));
      return obj;
    }
    if (Array.isArray(obj)) {
      return obj.map((item) => SignatureHasher.normalize(item));
    }
    const sortedKeys = Object.keys(obj).sort();
    const result: Record<string, any> = {};
    for (const key of sortedKeys) {
      result[key] = SignatureHasher.normalize(obj[key]);
    }
    return result;
  }

  static compute(toolName: string, args: any): string {
    let parsed = args;
    if (typeof args === "string") {
      try {
        parsed = JSON.parse(args);
      } catch {
        parsed = args.trim();
      }
    }
    const normalized = SignatureHasher.normalize(parsed);
    const jsonStr = JSON.stringify(normalized);
    const digest = createHash("sha256").update(jsonStr || "").digest("hex").slice(0, 16);
    return `${toolName}:${digest}`;
  }
}

export class CycleDetector {
  static detectCycle(
    signatures: string[],
    maxPeriod: number = 4,
    minReps: number = 2
  ): { pattern: string[]; repetitions: number } | null {
    const n = signatures.length;
    if (n < 4) return null;

    for (let period = 2; period <= Math.min(maxPeriod, Math.floor(n / minReps)); period++) {
      const pattern = signatures.slice(n - period);
      let reps = 1;
      let idx = n - 2 * period;

      while (idx >= 0) {
        const chunk = signatures.slice(idx, idx + period);
        let match = true;
        for (let i = 0; i < period; i++) {
          if (chunk[i] !== pattern[i]) {
            match = false;
            break;
          }
        }
        if (match) {
          reps++;
          idx -= period;
        } else {
          break;
        }
      }

      if (reps >= minReps) {
        return { pattern, repetitions: reps };
      }
    }
    return null;
  }
}

export class CircuitBreaker {
  sessionId: string;
  policy: Required<TripPolicy>;
  state: CircuitState = "closed";
  tripReason?: TripReason;
  tripDetails?: Record<string, any>;
  history: ToolCallEvent[] = [];
  signatures: string[] = [];
  observedSignatures: string[] = [];
  budget: BudgetTracker;
  currentDepth: number = 0;
  private pendingSignature?: string;
  private requestInFlight = false;
  beginRequest(): void {
    if (this.requestInFlight) throw new Error("Overlapping model requests are unsupported per guard");
    this.requestInFlight = true;
  }
  endRequest(): void { this.requestInFlight = false; }
  haltOnAccountingFailure(): void {
    if (this.state !== "tripped") this.trip("manual_halt", {error: "Response accounting or observation failed"});
  }
  startTime: number = Date.now();
  onTripCallback?: (cb: CircuitBreaker, details: Record<string, any>) => void;
  onEventCallback?: (telemetry: SessionTelemetry) => void;

  constructor(options?: {
    sessionId?: string;
    policy?: TripPolicy;
    onTrip?: (cb: CircuitBreaker, details: Record<string, any>) => void;
    onEvent?: (telemetry: SessionTelemetry) => void;
  }) {
    this.sessionId = options?.sessionId || `sess_${Math.random().toString(36).slice(2, 14)}`;
    this.policy = {
      maxConsecutiveRetries: options?.policy?.maxConsecutiveRetries ?? 3,
      maxDepth: options?.policy?.maxDepth ?? 20,
      maxCostUsd: options?.policy?.maxCostUsd ?? 2.0,
      detectCycles: options?.policy?.detectCycles ?? true,
      maxCycleLength: options?.policy?.maxCycleLength ?? 4,
      minCycleRepetitions: options?.policy?.minCycleRepetitions ?? 2,
      fallbackMode: options?.policy?.fallbackMode ?? "exception",
      fallbackMessage:
        options?.policy?.fallbackMessage ??
        "Loop-Guard Circuit Breaker Tripped: Safe execution halted.",
      customFallbackHandler: options?.policy?.customFallbackHandler ?? (() => null),
    };
    this.budget = new BudgetTracker(this.policy.maxCostUsd);
    this.onTripCallback = options?.onTrip;
    this.onEventCallback = options?.onEvent;
  }

  recordUsage(params: {
    promptTokens: number;
    completionTokens: number;
    model?: string;
    cachedTokens?: number;
    costUsd?: number;
  }): number {
    const { totalCostUsd, isExceeded } = this.budget.recordUsage({
      promptTokens: params.promptTokens,
      completionTokens: params.completionTokens,
      model: params.model,
      cachedTokens: params.cachedTokens,
      explicitCost: params.costUsd,
    });

    if (isExceeded && this.state === "closed") {
      this.trip("budget_exceeded", {
        totalCostUsd,
        maxCostUsd: this.policy.maxCostUsd,
        model: params.model,
      });
    }
    return totalCostUsd;
  }

  ensureActive(): any {
    if (this.budget.isExceeded() && this.state !== "tripped") this.trip("budget_exceeded", {});
    if (this.state === "tripped") {
      return this.handleTripped(
        this.tripReason || "manual_halt",
        "model_request",
        "",
        this.tripDetails || {}
      );
    }
    return null;
  }

  observeToolRequest(toolName: string, args: any = {}): any {
    const blocked = this.ensureActive();
    if (blocked !== null && blocked !== undefined) return blocked;

    const signature = SignatureHasher.compute(toolName, args);
    this.observedSignatures.push(signature);
    const observedRequestCount = this.observedSignatures.length;
    if (observedRequestCount > this.policy.maxDepth) {
      this.trip("max_depth_exceeded", {
        maxObservedToolRequests: this.policy.maxDepth,
        observedRequestCount,
        observation: "model_requested_tool",
      }, toolName, signature);
      return this.handleTripped(
        "max_depth_exceeded", toolName, signature, this.tripDetails || {}
      );
    }
    const simulated = this.observedSignatures;
    let consecutiveCount = 0;
    for (let i = simulated.length - 1; i >= 0; i--) {
      if (simulated[i] === signature) consecutiveCount++;
      else break;
    }
    if (consecutiveCount >= this.policy.maxConsecutiveRetries) {
      this.trip("consecutive_retry", {
        consecutiveCount,
        threshold: this.policy.maxConsecutiveRetries,
        signature,
        observation: "model_requested_tool",
      }, toolName, signature);
      return this.handleTripped(
        "consecutive_retry", toolName, signature, this.tripDetails || {}, consecutiveCount
      );
    }
    if (this.policy.detectCycles) {
      const cycle = CycleDetector.detectCycle(
        simulated, this.policy.maxCycleLength, this.policy.minCycleRepetitions
      );
      if (cycle) {
        this.trip("cycle_detected", {
          cyclePattern: cycle.pattern,
          repetitions: cycle.repetitions,
          signatures: simulated.slice(-8),
          observation: "model_requested_tool",
        }, toolName, signature);
        return this.handleTripped(
          "cycle_detected", toolName, signature, this.tripDetails || {}, cycle.repetitions
        );
      }
    }
    return null;
  }

  beforeToolCall(toolName: string, args: any = {}): any {
    if (this.pendingSignature) throw new Error("Overlapping tool calls are unsupported");
    const blocked = this.ensureActive();
    if (this.state === "tripped") return blocked;
    this.currentDepth++;
    const signature = SignatureHasher.compute(toolName, args);

    if (this.currentDepth > this.policy.maxDepth) {
      this.trip("max_depth_exceeded", {
        maxDepth: this.policy.maxDepth,
        currentDepth: this.currentDepth,
      }, toolName, signature);
      return this.handleTripped(
        "max_depth_exceeded",
        toolName,
        signature,
        this.tripDetails || {}
      );
    }

    const simulated = [...this.signatures, signature];
    let consecutiveCount = 0;
    for (let i = simulated.length - 1; i >= 0; i--) {
      if (simulated[i] === signature) {
        consecutiveCount++;
      } else {
        break;
      }
    }

    if (consecutiveCount >= this.policy.maxConsecutiveRetries) {
      this.trip("consecutive_retry", {
        consecutiveCount,
        threshold: this.policy.maxConsecutiveRetries,
        signature,
      }, toolName, signature);
      return this.handleTripped(
        "consecutive_retry",
        toolName,
        signature,
        this.tripDetails || {},
        consecutiveCount
      );
    }

    if (this.policy.detectCycles) {
      const cycle = CycleDetector.detectCycle(
        simulated,
        this.policy.maxCycleLength,
        this.policy.minCycleRepetitions
      );
      if (cycle) {
        this.trip("cycle_detected", {
          cyclePattern: cycle.pattern,
          repetitions: cycle.repetitions,
          signatures: simulated.slice(-8),
        }, toolName, signature);
        return this.handleTripped(
          "cycle_detected",
          toolName,
          signature,
          this.tripDetails || {},
          cycle.repetitions
        );
      }
    }

    this.pendingSignature = signature;
    return null;
  }

  afterToolCall(params: {
    toolName: string;
    args?: any;
    result?: any;
    isError?: boolean;
    costUsd?: number;
  }): ToolCallEvent {
    validateNumber(params.costUsd ?? 0);
    if (!this.pendingSignature || !this.pendingSignature.startsWith(params.toolName + ":")) throw new Error("Completion requires matching admitted tool call");
    let signature: string;
    if (params.args !== undefined) {
      signature = SignatureHasher.compute(params.toolName, params.args);
    } else if (this.pendingSignature) {
      signature = this.pendingSignature;
      this.pendingSignature = undefined;
    } else {
      signature = SignatureHasher.compute(params.toolName, null);
    }

    if (this.pendingSignature && signature !== this.pendingSignature) throw new Error("Completion arguments do not match pending tool call");
    this.pendingSignature = undefined;
    this.recordUsage({promptTokens: 0, completionTokens: 0, costUsd: params.costUsd ?? 0});
    this.signatures.push(signature);

    const event: ToolCallEvent = {
      id: `evt_${Math.random().toString(36).slice(2, 10)}`,
      toolName: params.toolName,
      rawArgs: params.args,
      signature,
      timestamp: Date.now(),
      depth: this.currentDepth,
      isError: params.isError || false,
      resultPreview: params.result ? String(params.result).slice(0, 200) : undefined,
      costUsd: params.costUsd || 0,
    };
    this.history.push(event);

    if (this.onEventCallback) {
      try {
        this.onEventCallback(this.toTelemetry());
      } catch {}
    }

    return event;
  }

  private trip(
    reason: TripReason,
    details: Record<string, any>,
    toolName?: string,
    signature?: string
  ) {
    this.state = "tripped";
    this.tripReason = reason;
    this.tripDetails = {
      ...details,
      reason,
      toolName,
      signature,
      depth: this.currentDepth,
      costUsd: this.budget.totalCostUsd,
    };

    if (this.onTripCallback) {
      try {
        this.onTripCallback(this, this.tripDetails);
      } catch {}
    }

    if (this.onEventCallback) {
      try {
        this.onEventCallback(this.toTelemetry());
      } catch {}
    }
  }

  private handleTripped(
    reason: TripReason,
    toolName: string,
    signature: string,
    details: Record<string, any>,
    repetitionCount: number = 0
  ): any {
    if (this.policy.fallbackMode === "synthetic_response") {
      return {
        role: "assistant",
        content: this.policy.fallbackMessage,
        loopguardStatus: {
          tripped: true,
          reason,
          sessionId: this.sessionId,
          costUsd: this.budget.totalCostUsd,
        },
      };
    } else if (this.policy.fallbackMode === "custom" && this.policy.customFallbackHandler) {
      return this.policy.customFallbackHandler(details);
    }

    const msg = `[Loop-Guard] Trip activated: ${reason}. Session ${this.sessionId} halted.`;
    if (reason === "consecutive_retry" || reason === "cycle_detected") {
      throw new RepetitiveToolCallError({
        message: msg,
        sessionId: this.sessionId,
        reason,
        toolName,
        signature,
        repetitionCount,
        currentDepth: this.currentDepth,
        costUsd: this.budget.totalCostUsd,
        metadata: details,
      });
    } else if (reason === "budget_exceeded") {
      throw new BudgetExceededError({
        message: msg,
        sessionId: this.sessionId,
        reason,
        toolName,
        signature,
        currentDepth: this.currentDepth,
        costUsd: this.budget.totalCostUsd,
        metadata: details,
      });
    } else if (reason === "max_depth_exceeded") {
      throw new MaxDepthExceededError({
        message: msg,
        sessionId: this.sessionId,
        reason,
        toolName,
        signature,
        currentDepth: this.currentDepth,
        costUsd: this.budget.totalCostUsd,
        metadata: details,
      });
    }

    throw new CircuitTrippedError({
      message: msg,
      sessionId: this.sessionId,
      reason,
      toolName,
      signature,
      currentDepth: this.currentDepth,
      costUsd: this.budget.totalCostUsd,
      metadata: details,
    });
  }

  reset(): void {
    if (this.budget.isExceeded()) throw new Error("Cannot reset exhausted budget; create a new session");
    if (this.pendingSignature || this.requestInFlight) throw new Error("Cannot reset in flight");
    this.state = "closed";
    this.tripReason = undefined;
    this.tripDetails = undefined;
    this.signatures = [];
    this.observedSignatures = [];
    this.history = [];
    this.currentDepth = 0;
  }

  toTelemetry(): SessionTelemetry {
    return {
      sessionId: this.sessionId,
      state: this.state,
      tripReason: this.tripReason,
      tripDetails: this.tripDetails,
      currentDepth: this.currentDepth,
      maxDepth: this.policy.maxDepth,
      budget: this.budget.getSummary(),
      historyCount: this.history.length,
      observedRequestCount: this.observedSignatures.length,
      recentSignatures: this.signatures.slice(-10),
      recentObservedSignatures: this.observedSignatures.slice(-10),
      elapsedSeconds: Number(((Date.now() - this.startTime) / 1000).toFixed(2)),
      history: this.history.slice(-15).map((h) => ({
        id: h.id,
        toolName: h.toolName,
        signature: h.signature,
        rawArgs: h.rawArgs,
        depth: h.depth,
        isError: h.isError,
        timestamp: h.timestamp,
        resultPreview: h.resultPreview,
      })),
    };
  }
}

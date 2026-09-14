#!/usr/bin/env python3
"""
Simulate a runaway broken multi-step agent caught in a tool retry loop.
Demonstrates Loop-Guard intercepting it in real-time, preventing token waste.
"""

import os
import sys
import time

# Ensure loopguard is importable
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "packages", "python"))

from loopguard import (
    CircuitBreaker,
    TripPolicy,
    TripReason,
    AlertDispatcher,
    RepetitiveToolCallError,
)


def mock_database_tool(sql_query: str) -> str:
    # Simulates a broken database connection where query fails every time
    return "OperationalError: connection to server on port 5432 failed: FATAL: remaining connection slots are reserved"


def run_simulated_broken_agent():
    print("\n=======================================================")
    print("🤖 Launching Multi-Step Agent with Loop-Guard Protection")
    print("=======================================================\n")

    # 1. Initialize CircuitBreaker with a 3-retry threshold and $2.00 ceiling
    policy = TripPolicy(
        max_consecutive_retries=3,
        max_depth=15,
        max_cost_usd=2.00,
        fallback_mode="synthetic_response",
        fallback_message="Loop-Guard Intervention: Database appears down. Halted after 3 retries.",
    )

    # 2. Configure alerts (mock or actual webhooks)
    alerts = AlertDispatcher()

    def on_trip_handler(cb: CircuitBreaker, details: dict):
        print("\n🚨 [ALERT] Circuit Breaker Tripped!")
        print(f"   Session ID: {cb.session_id}")
        print(f"   Reason:     {details.get('reason')}")
        print(f"   Tool:       {details.get('tool_name')}")
        print(f"   Signatures: {cb.signatures}")
        print(f"   Spend:      ${cb.budget.total_cost_usd:.4f}")

    guard = CircuitBreaker(
        session_id="agent_run_postgres_recovery",
        policy=policy,
        on_trip=on_trip_handler,
    )

    failing_sql = "SELECT id, status, balance FROM invoices WHERE status = 'pending_payment' LIMIT 50;"

    print("Agent prompt: 'Check all pending payment invoices in PostgreSQL.'")
    print("Agent begins execution loop...\n")

    for step in range(1, 6):
        print(f"--- [Step {step}] Agent attempts tool execution ---")

        # Simulate model token consumption per step
        guard.record_usage(prompt_tokens=3200, completion_tokens=120, model="gpt-4o")

        # Guard pre-execution check
        fallback = guard.before_tool_call("query_postgres", {"sql": failing_sql})
        if fallback is not None:
            print(f"🛑 [CIRCUIT OPEN] Tool call blocked by Loop-Guard!")
            print(f"   Fallback response delivered to agent:")
            print(f"   --> '{fallback.get('content')}'")
            print(f"   Observed spend: ${guard.budget.total_cost_usd:.4f} (upstream savings are not measured)")
            break

        # Simulate tool execution failure
        result = mock_database_tool(failing_sql)
        print(f"   Tool returned: {result[:65]}...")

        # Record tool result in guard
        guard.after_tool_call(
            "query_postgres",
            arguments={"sql": failing_sql},
            result=result,
            is_error=True,
        )

        time.sleep(0.4)

    print("\n✅ Simulation complete. Loop-Guard successfully prevented infinite token burn.\n")


if __name__ == "__main__":
    run_simulated_broken_agent()

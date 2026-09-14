"""Opt-in metadata-only exporter. Importing this module sends nothing.

Call make_exporter(endpoint=..., token=...) explicitly and pass its result as
CircuitBreaker(on_trip=...). Never pass a whole telemetry object to a collector.
"""
import json
import uuid
from datetime import datetime, timezone
import urllib.request
from urllib.parse import urlsplit


def make_exporter(*, endpoint: str, token: str):
    url = urlsplit(endpoint)
    if url.scheme != 'https' or not url.netloc or url.username or url.password:
        raise ValueError('An explicit HTTPS collector endpoint is required')
    if not token or '\r' in token or '\n' in token:
        raise ValueError('An explicit bearer token is required')

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(NoRedirect())

    def on_trip(guard, details):
        # Allowlist only scalar operational metadata. No session IDs, tool names,
        # arguments, prompts, outputs, signatures, or arbitrary trip details.
        reason = {'consecutive_retry':'loop_detected','cycle_detected':'loop_detected',
                  'budget_exceeded':'budget_exceeded','max_depth_exceeded':'attempt_limit',
                  'max_provider_attempts_exceeded':'attempt_limit','manual_halt':'manual_halt'}.get(guard.trip_reason.value,'accounting_unknown')
        payload = {
            'schema': 'runlog.incident.v1',
            'event_id': str(uuid.uuid4()),
            'occurred_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z'),
            'reason': reason,
            'tools': [],
            'provider_attempts': guard.provider_attempts,
            # Reference-price accounting is an estimate, not a provider receipt.
            'observed_cost_usd': None,
        }
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token,
        }, method='POST')
        with opener.open(request, timeout=5) as response:
            response.read(1024)
    return on_trip

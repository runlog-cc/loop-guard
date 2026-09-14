from types import SimpleNamespace as N
import pytest
from loopguard import CircuitBreaker, TripPolicy, wrap_openai

def client(guard, calls, cached=None):
    def create(**kwargs):
        calls.append(1)
        return N(usage=N(prompt_tokens=1, completion_tokens=1, prompt_tokens_details=N(cached_tokens=cached)), choices=[N(message=N(tool_calls=[N(function=N(name='poll', arguments='{}'))]))])
    return wrap_openai(N(chat=N(completions=N(create=create))), guard)

def test_null_fallback_never_returns_trigger_response():
    g = CircuitBreaker(policy=TripPolicy(max_consecutive_retries=1, fallback_mode='custom', custom_fallback_handler=lambda _: None))
    c = client(g, [], 0)
    assert c.chat.completions.create(model='gpt-4o') is None

def test_optional_null_cache():
    g = CircuitBreaker()
    client(g, []).chat.completions.create(model='gpt-4o')
    assert g.state.value == 'closed'

def test_attempt_limit_and_exemption():
    g = CircuitBreaker(policy=TripPolicy(max_provider_attempts=3, loop_exempt_tools=['poll']))
    calls=[]; c=client(g,calls,0)
    for _ in range(3): c.chat.completions.create(model='gpt-4o')
    with pytest.raises(Exception): c.chat.completions.create(model='gpt-4o')
    assert len(calls)==3
    assert g.provider_attempts==3
    assert g.trip_reason.value=='max_provider_attempts_exceeded'

def test_errors_count_and_unknown_usage_is_explicit():
    g=CircuitBreaker(policy=TripPolicy(max_provider_attempts=2))
    def fail(**kwargs): raise RuntimeError('provider failed')
    c=wrap_openai(N(chat=N(completions=N(create=fail))),g)
    for _ in range(2):
        with pytest.raises(RuntimeError): c.chat.completions.create(model='gpt-4o')
    with pytest.raises(Exception): c.chat.completions.create(model='gpt-4o')
    assert g.to_dict()['unaccounted_provider_attempts']==2
    assert g.provider_attempts==2

def test_exempt_tool_cannot_form_cycle_with_nonexempt_tools():
    g=CircuitBreaker(policy=TripPolicy(loop_exempt_tools=['poll'],max_consecutive_retries=10))
    for name in ['poll','status','poll','status']:
        g.observe_tool_request(name,{})
    assert g.state.value=='closed'

def test_exemption_does_not_bypass_execution_depth_or_budget():
    g=CircuitBreaker(policy=TripPolicy(loop_exempt_tools=['poll'],max_depth=2))
    for _ in range(2):
        g.before_tool_call('poll',{});g.after_tool_call('poll',{})
    with pytest.raises(Exception):g.before_tool_call('poll',{})
    g=CircuitBreaker(policy=TripPolicy(loop_exempt_tools=['poll'],max_cost_usd=1))
    g.before_tool_call('poll',{})
    g.after_tool_call('poll',{},cost_usd=1)
    with pytest.raises(Exception):g.before_tool_call('poll',{})

@pytest.mark.parametrize('limit',[0,-1,float('inf'),float('nan'),True,1.5])
def test_attempt_policy_requires_positive_finite_integer(limit):
    with pytest.raises(ValueError):CircuitBreaker(policy=TripPolicy(max_provider_attempts=limit))

def test_metadata_exporter_allowlist(monkeypatch):
    import importlib.util
    from pathlib import Path
    import json
    spec=importlib.util.spec_from_file_location('exporter',Path(__file__).parents[3]/'examples/metadata_incident_exporter.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    requests=[]
    class Reply:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b''
    class Opener:
        def open(self,request,timeout):requests.append(request);return Reply()
    monkeypatch.setattr(module.urllib.request,'build_opener',lambda *args:Opener())
    callback=module.make_exporter(endpoint='https://collector.invalid/events',token='test-only')
    assert not requests
    g=CircuitBreaker(session_id='private-session',on_trip=callback,policy=TripPolicy(max_consecutive_retries=1))
    with pytest.raises(Exception):g.before_tool_call('secret-tool',{'secret':'private'})
    payload=json.loads(requests[0].data)
    assert set(payload)=={'schema','event_id','occurred_at','reason','tools','provider_attempts','observed_cost_usd'}
    assert payload['schema']=='runlog.incident.v1'
    assert payload['observed_cost_usd'] is None
    assert payload['tools']==[]
    assert b'private' not in requests[0].data and b'secret' not in requests[0].data

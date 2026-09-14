import math
import pytest
from loopguard import CircuitBreaker
from loopguard.budget import BudgetTracker, get_pricing_for_model

def test_exact_dated_pricing():
    assert get_pricing_for_model('gpt-4o-mini-2024-07-18').prompt_per_1m == .15
    assert get_pricing_for_model('o1-mini-2024-09-12').prompt_per_1m == 3
    with pytest.raises(ValueError): get_pricing_for_model('unknown')

@pytest.mark.parametrize('value', [-1, math.nan, math.inf])
def test_invalid_usage_atomic(value):
    b = BudgetTracker()
    with pytest.raises(ValueError): b.record_usage(0,0,explicit_cost=value)
    with pytest.raises(ValueError): b.record_usage(value,0,explicit_cost=0)
    assert b.total_cost_usd == 0

def test_manual_cost_and_reset():
    g = CircuitBreaker()
    g.before_tool_call('a', {})
    g.after_tool_call('a', {}, cost_usd=3)
    assert g.budget.total_cost_usd == 3
    with pytest.raises(Exception): g.reset()
    with pytest.raises(Exception): g.ensure_active()

def test_overlap_rejected():
    g = CircuitBreaker()
    g.before_tool_call('a', {})
    with pytest.raises(RuntimeError): g.before_tool_call('b', {})
    g.after_tool_call('a', {})
    g.before_tool_call('b', {})

def test_threaded_wrapper_rejects_overlap_before_dispatch():
    from types import SimpleNamespace as NS
    from threading import Event, Thread
    from loopguard import wrap_openai
    entered, release = Event(), Event()
    calls = []
    def create(**kwargs):
        calls.append(1); entered.set(); release.wait(2)
        return NS(choices=[], usage=None)
    g = CircuitBreaker()
    c = wrap_openai(NS(chat=NS(completions=NS(create=create))), g)
    thread = Thread(target=lambda: c.chat.completions.create(model='gpt-4o'))
    thread.start(); assert entered.wait(2)
    try:
        with pytest.raises(RuntimeError): c.chat.completions.create(model='gpt-4o')
        assert len(calls) == 1
    finally:
        release.set(); thread.join()

def test_invalid_provider_usage_halts_session():
    from types import SimpleNamespace as NS
    from loopguard import wrap_openai
    calls=[]
    def create(**kwargs):
        calls.append(1)
        return NS(usage=NS(prompt_tokens=-1,completion_tokens=0), choices=[])
    g=CircuitBreaker(); c=wrap_openai(NS(chat=NS(completions=NS(create=create))),g)
    with pytest.raises(ValueError): c.chat.completions.create(model='gpt-4o')
    with pytest.raises(Exception): c.chat.completions.create(model='gpt-4o')
    assert len(calls)==1

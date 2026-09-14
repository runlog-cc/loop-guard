"""Offline complete adapter/tool loop: python examples/fake_provider.py."""
from types import SimpleNamespace as NS
from loopguard import CircuitBreaker, RepetitiveToolCallError, wrap_openai

calls = 0
def create(**kwargs):
    global calls
    calls += 1
    return NS(usage=NS(prompt_tokens=100, completion_tokens=10), choices=[NS(message=NS(
        tool_calls=[NS(function=NS(name='lookup', arguments='{"id":1}'))]))])

guard = CircuitBreaker()
client = wrap_openai(NS(chat=NS(completions=NS(create=create))), guard)
try:
    while True:
        response = client.chat.completions.create(model='gpt-4o-mini', messages=[])
        for tool in response.choices[0].message.tool_calls:
            guard.before_tool_call(tool.function.name, tool.function.arguments)
            result = {'found': False}  # Replace with actual authorized tool execution.
            guard.after_tool_call(tool.function.name, tool.function.arguments, result=result)
except RepetitiveToolCallError:
    print(f'Stopped after {calls} fake provider calls; recorded ${guard.budget.total_cost_usd:.6f}')

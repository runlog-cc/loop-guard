"""Real pinned SDK parsing over an in-process HTTP transport; no provider traffic."""
import httpx
import pytest
openai = pytest.importorskip('openai')
anthropic = pytest.importorskip('anthropic')
from loopguard import CircuitBreaker, TripPolicy, wrap_openai, wrap_anthropic

@pytest.mark.parametrize('provider', ['openai','anthropic'])
@pytest.mark.parametrize('scenario', ['normal','tool','null_cache','cache_read','error','cache_write','missing_usage'])
def test_real_sdk(provider, scenario):
    calls=[]
    def respond(request):
        calls.append(request)
        if scenario=='error': return httpx.Response(500,json={'error':{'type':'api_error','message':'controlled failure'}})
        if provider=='openai':
            message={'role':'assistant','content':'ok'}
            if scenario=='tool': message.update(content=None,tool_calls=[{'id':'call_1','type':'function','function':{'name':'poll','arguments':'{}'}}])
            body={'id':'chatcmpl-local','object':'chat.completion','created':1,'model':'gpt-4o','choices':[{'index':0,'message':message,'finish_reason':'stop'}], 'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12,'prompt_tokens_details':{'cached_tokens':None if scenario=='null_cache' else 5 if scenario=='cache_read' else 0}}}
        else:
            content=[{'type':'text','text':'ok'}] if scenario!='tool' else [{'type':'tool_use','id':'toolu_1','name':'poll','input':{}}]
            body={'id':'msg_local','type':'message','role':'assistant','model':'claude-3-5-sonnet','content':content,'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':10,'output_tokens':2,'cache_read_input_tokens':None if scenario=='null_cache' else 5 if scenario=='cache_read' else 0,'cache_creation_input_tokens':3 if scenario=='cache_write' else 0}}
        if scenario=='missing_usage': body.pop('usage')
        return httpx.Response(200,json=body)
    http=httpx.Client(transport=httpx.MockTransport(respond))
    g=CircuitBreaker(policy=TripPolicy(max_provider_attempts=2,max_consecutive_retries=1,fallback_mode='custom',custom_fallback_handler=lambda _:None))
    if provider=='openai':
        c=wrap_openai(openai.OpenAI(api_key='local-test',base_url='http://local.invalid/v1',http_client=http,max_retries=0),g)
        call=lambda:c.chat.completions.create(model='gpt-4o',messages=[{'role':'user','content':'test'}])
    else:
        c=wrap_anthropic(anthropic.Anthropic(api_key='local-test',base_url='http://local.invalid',http_client=http,max_retries=0),g)
        call=lambda:c.messages.create(model='claude-3-5-sonnet',max_tokens=10,messages=[{'role':'user','content':'test'}])
    if scenario=='error' or (provider=='anthropic' and scenario=='cache_write'):
        with pytest.raises(Exception): call()
        assert g.to_dict()['unaccounted_provider_attempts']==1
    elif scenario=='tool':
        assert call() is None
        assert call() is None
        assert len(calls)==1
    else:
        assert call() is not None
        assert call() is not None
        assert call() is None
        assert len(calls)==2
        assert g.provider_attempts==2
        assert g.to_dict()['unaccounted_provider_attempts']==(2 if scenario=='missing_usage' else 0)
    c.close()

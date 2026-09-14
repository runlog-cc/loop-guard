// Actual SDK clients and HTTP serialization over a controlled fetch transport.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const OpenAI=require('openai');
const Anthropic=require('@anthropic-ai/sdk');
const {CircuitBreaker,wrapOpenAI,wrapAnthropic}=require('../dist');
for(const provider of ['openai','anthropic']) for(const scenario of ['normal','tool','null_cache','cache_read','error','cache_write','missing_usage']) {
 test(`${provider} SDK ${scenario}`,async()=>{
  let calls=0;
  const fetch=async(url,options)=>{
   calls++;assert.match(String(url),/^http:\/\/local.invalid/);assert.equal(options.method,'POST');JSON.parse(options.body);
   if(scenario==='error')return new Response(JSON.stringify({error:{type:'api_error',message:'controlled failure'}}),{status:500,headers:{'content-type':'application/json'}});
   let body;
   if(provider==='openai')body={id:'chatcmpl-local',object:'chat.completion',created:1,model:'gpt-4o',choices:[{index:0,message:scenario==='tool'?{role:'assistant',content:null,tool_calls:[{id:'call_1',type:'function',function:{name:'poll',arguments:'{}'}}]}:{role:'assistant',content:'ok'},finish_reason:'stop'}],usage:{prompt_tokens:10,completion_tokens:2,total_tokens:12,prompt_tokens_details:{cached_tokens:scenario==='null_cache'?null:scenario==='cache_read'?5:0}}};
   else body={id:'msg_local',type:'message',role:'assistant',model:'claude-3-5-sonnet',content:scenario==='tool'?[{type:'tool_use',id:'toolu_1',name:'poll',input:{}}]:[{type:'text',text:'ok'}],stop_reason:'end_turn',stop_sequence:null,usage:{input_tokens:10,output_tokens:2,cache_read_input_tokens:scenario==='null_cache'?null:scenario==='cache_read'?5:0,cache_creation_input_tokens:scenario==='cache_write'?3:0}};
   if(scenario==='missing_usage')delete body.usage;
   return new Response(JSON.stringify(body),{status:200,headers:{'content-type':'application/json'}});
  };
  const g=new CircuitBreaker({policy:{maxProviderAttempts:2,maxConsecutiveRetries:1,fallbackMode:'custom',customFallbackHandler:()=>undefined}});
  const options={apiKey:'local-test',baseURL:'http://local.invalid',maxRetries:0,fetch};
  const c=provider==='openai'?wrapOpenAI(new OpenAI(options),g):wrapAnthropic(new Anthropic(options),g);
  const call=()=>provider==='openai'?c.chat.completions.create({model:'gpt-4o',messages:[{role:'user',content:'test'}]}):c.messages.create({model:'claude-3-5-sonnet',max_tokens:10,messages:[{role:'user',content:'test'}]});
  if(scenario==='error'||(provider==='anthropic'&&scenario==='cache_write')){await assert.rejects(call());assert.equal(g.toTelemetry().unaccountedProviderAttempts,1);}
  else if(scenario==='tool'){assert.equal(await call(),undefined);assert.equal(await call(),undefined);assert.equal(calls,1);}
  else {assert.ok(await call());assert.ok(await call());assert.equal(await call(),undefined);assert.equal(calls,2);assert.equal(g.providerAttempts,2);assert.equal(g.toTelemetry().unaccountedProviderAttempts,scenario==='missing_usage'?2:0);}
 });
}
test('poll exemptions preserve attempt and depth limits',async()=>{
 const g=new CircuitBreaker({policy:{maxProviderAttempts:4,maxDepth:3,loopExemptTools:['poll']}});
 let calls=0;const c=wrapOpenAI({chat:{completions:{create:async()=>{calls++;return {choices:[{message:{tool_calls:[{function:{name:'poll',arguments:'{}'}}]}}]};}}}},g);
 for(let i=0;i<3;i++)await c.chat.completions.create({model:'gpt-4o'});
 await assert.rejects(c.chat.completions.create({model:'gpt-4o'}));assert.equal(g.tripReason,'max_depth_exceeded');assert.equal(calls,4);
});
test('errors use attempts; reset cannot replenish them',async()=>{
 const g=new CircuitBreaker({policy:{maxProviderAttempts:2}});let calls=0;
 const c=wrapOpenAI({chat:{completions:{create:async()=>{calls++;throw Error('local failure');}}}},g);
 for(let i=0;i<3;i++)await assert.rejects(c.chat.completions.create({model:'gpt-4o'}));
 assert.equal(calls,2);assert.equal(g.tripReason,'max_provider_attempts_exceeded');g.reset();await assert.rejects(c.chat.completions.create({model:'gpt-4o'}));assert.equal(calls,2);
});
for (const realSdk of [false, true]) for (const inputTokens of [null, true, -1, 0.5, '10']) {
 test(`Anthropic rejects invalid required input before cache normalization (${realSdk ? 'real SDK' : 'stub'}: ${JSON.stringify(inputTokens)})`, async()=>{
  let calls=0;
  const body={id:'msg_local',type:'message',role:'assistant',model:'claude-3-5-sonnet',content:[{type:'text',text:'ok'}],stop_reason:'end_turn',stop_sequence:null,usage:{input_tokens:inputTokens,output_tokens:2,cache_read_input_tokens:10,cache_creation_input_tokens:0}};
  const g=new CircuitBreaker();
  const client=realSdk?new Anthropic({apiKey:'local-test',baseURL:'http://local.invalid',maxRetries:0,fetch:async()=>{calls++;return new Response(JSON.stringify(body),{status:200,headers:{'content-type':'application/json'}});}}):{messages:{create:async()=>{calls++;return body;}}};
  const c=wrapAnthropic(client,g);
  const call=()=>c.messages.create({model:'claude-3-5-sonnet',max_tokens:10,messages:[{role:'user',content:'test'}]});
  await assert.rejects(call());
  assert.equal(g.state,'tripped');assert.equal(g.tripReason,'manual_halt');
  assert.equal(g.toTelemetry().unaccountedProviderAttempts,1);assert.equal(g.budget.totalCostUsd,0);
  await assert.rejects(call());assert.equal(calls,1);
 });
}

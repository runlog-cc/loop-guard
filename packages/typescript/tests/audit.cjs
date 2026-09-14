const {test}=require('node:test');
const assert=require('node:assert/strict');
const {CircuitBreaker,wrapOpenAI,wrapAnthropic}=require('../dist');
const {BudgetTracker,getPricingForModel}=require('../dist/budget');
test('exact pricing and atomic invalid accounting',()=>{
 assert.equal(getPricingForModel('gpt-4o-mini-2024-07-18').promptPer1M,.15);
 assert.equal(getPricingForModel('o1-mini-2024-09-12').promptPer1M,3);
 assert.throws(()=>getPricingForModel('fake-gpt-4o'));
 for(const n of [-1,NaN,Infinity]) { const b=new BudgetTracker(); assert.throws(()=>b.recordUsage({promptTokens:0,completionTokens:0,explicitCost:n})); assert.throws(()=>b.recordUsage({promptTokens:n,completionTokens:0,explicitCost:0})); assert.equal(b.totalCostUsd,0); }
});
test('manual lifecycle is sequential, cost accounted, budget reset forbidden',()=>{
 const g=new CircuitBreaker();g.beforeToolCall('a',{});assert.throws(()=>g.beforeToolCall('b',{}));g.afterToolCall({toolName:'a',args:{},costUsd:3});assert.equal(g.budget.totalCostUsd,3);assert.throws(()=>g.reset());assert.throws(()=>g.ensureActive());
});
for (const provider of ['openai','anthropic']) test(provider+' rejects concurrent and tripped calls before dispatch',async()=>{
 let calls=0,finish;
 const endpoint={create:()=>{calls++;return new Promise(r=>finish=r)}};
 const g=new CircuitBreaker(); const c=provider==='openai'?wrapOpenAI({chat:{completions:endpoint}},g):wrapAnthropic({messages:endpoint},g);
 const pending=endpoint.create({model:'gpt-4o'});
 await assert.rejects(endpoint.create({model:'gpt-4o'}),/Overlapping/);assert.equal(calls,1);
 finish({});await pending;g.recordUsage({promptTokens:0,completionTokens:0,costUsd:3});await assert.rejects(endpoint.create({model:'gpt-4o'}));assert.equal(calls,1);
});
test('repeated provider tool responses trip independently of execution',async()=>{
 let calls=0;const g=new CircuitBreaker();const e={create:async()=>{calls++;return {choices:[{message:{tool_calls:[{function:{name:'same',arguments:'{}'}}]}}]}}};wrapOpenAI({chat:{completions:e}},g);
 await e.create({model:'gpt-4o'});await e.create({model:'gpt-4o'});await assert.rejects(e.create({model:'gpt-4o'}));await assert.rejects(e.create({model:'gpt-4o'}));assert.equal(calls,3);
});

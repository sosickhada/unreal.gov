import test from 'node:test';
import assert from 'node:assert/strict';
import {dispatch} from '../scripts/puter_api.mjs';
test('reserved generation invokes official SDK once and records usage',async()=>{
 let calls=0;
 const p={ai:{txt2img:async opts=>{calls++;assert.equal(opts.model,'chosen');return {src:'data:image/png;base64,AAAA'};}},auth:{getMonthlyUsage:async()=>({allowanceInfo:{remaining:9}})}};
 const r=await dispatch(p,'generate',{model:'chosen',prompt:'Korean office'},true);
 assert.equal(p.config.autoRetry,false);
 await assert.rejects(p.triggerReauth());
 assert.equal(calls,1);assert.equal(r.usage_after.remaining,9);assert.ok(r.src.startsWith('data:'));
});
test('no reservation means no generation',async()=>{
 await assert.rejects(dispatch({ai:{txt2img:()=>assert.fail()}},'generate'));
});
test('SDK authentication/generation error is never retried',async()=>{
 let calls=0;
 await assert.rejects(dispatch({ai:{txt2img:async()=>{calls++;throw Error('auth');}}},'generate',{},true));
 assert.equal(calls,1);
});
test('usage lookup failure does not regenerate an already completed image',async()=>{
 let calls=0;
 const r=await dispatch({ai:{txt2img:async()=>{calls++;return {src:'image'};}},auth:{getMonthlyUsage:async()=>{throw Error();}}},'generate',{},true);
 assert.equal(calls,1);assert.equal(r.usage_after,null);
});

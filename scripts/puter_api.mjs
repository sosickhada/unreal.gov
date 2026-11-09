// Pure dispatch is tested with an in-memory SDK double, never real credentials.
export async function dispatch(puter, action, options={}, reserved=false) {
  // SDK 2.6.5 otherwise retries 429/gate rejections internally. Its reauth
  // path is separate from autoRetry, so disable interactive replay as well.
  puter.config ??= {};
  puter.config.autoRetry=false;
  const noInteractive=async()=>{throw {code:'interactive_auth_disabled'};};
  puter.triggerReauth=noInteractive;
  if (puter.ui) for (const key of ['authenticateWithPuter','requestVerificationGate','requestUpgrade']) puter.ui[key]=noInteractive;
  if (action === 'inspect') {
    const usage=await puter.auth.getMonthlyUsage();
    return {authenticated:true,allowanceInfo:usage.allowanceInfo,models:await puter.ai.listModels()};
  }
  if (action !== 'generate' || !reserved) throw Error('not_reserved');
  // One invocation; no fallback provider call or retry after any error.
  const image=await puter.ai.txt2img(options);
  let usage_after=null;
  try {usage_after=(await puter.auth.getMonthlyUsage()).allowanceInfo;} catch {}
  return {src:image.src,usage_after};
}

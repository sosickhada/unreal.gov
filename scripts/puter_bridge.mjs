// Credentials arrive only through environment. Never print provider errors.
import { init } from '@heyputer/puter.js/src/init.cjs';
let stage = "init";
try {
  if (!process.env.PUTER_AUTH_TOKEN) throw Error();
  const puter = init(process.env.PUTER_AUTH_TOKEN);
  const action = process.argv[2];
  if (action === 'inspect') {
    stage = "usage";
    const usage = await puter.auth.getMonthlyUsage();
    stage = "models";
    const models = await puter.ai.listModels();
    await new Promise(resolve => process.stdout.write(JSON.stringify({ authenticated: true, allowanceInfo: usage.allowanceInfo, models })+'\n', resolve));
  } else {
    // No generation until free-only billing isolation and worst-case quotes are verified.
    throw Error();
  }
  process.exit(0);
} catch (error) {
  console.log(JSON.stringify({stage, code: /^[a-z_0-9-]{1,50}$/.test(error?.code) ? error.code : null, error:'Puter operation blocked or failed; details withheld'}));
  process.exit(1);
}

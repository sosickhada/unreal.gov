import { init } from '@heyputer/puter.js/src/init.cjs';
import { dispatch } from './puter_api.mjs';
try {
  if (!process.env.PUTER_AUTH_TOKEN) throw Error();
  const action=process.argv[2];
  let options={};
  if (action==='generate') {
    const chunks=[];
    for await (const chunk of process.stdin) chunks.push(chunk);
    options=JSON.parse(Buffer.concat(chunks).toString());
  }
  const result=await dispatch(init(process.env.PUTER_AUTH_TOKEN),action,options,process.env.UNREAL_PUTER_RESERVED_CALL==='1');
  await new Promise(resolve=>process.stdout.write(JSON.stringify(result)+'\n',resolve));
  process.exit(0);
} catch(error) {
  const code=/^[a-z_0-9-]{1,50}$/.test(error?.code)?error.code:null;
  await new Promise(resolve=>process.stdout.write(JSON.stringify({code,error:'Puter operation blocked or failed; details withheld'})+'\n',resolve));
  process.exit(1);
}

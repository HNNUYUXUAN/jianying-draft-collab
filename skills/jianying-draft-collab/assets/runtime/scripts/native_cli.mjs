// Use the installed vendor runtime as the parent of its installed CLI.
import { spawnSync } from 'node:child_process';
const request=JSON.parse(await Bun.file(process.argv[2]).text());
const response=spawnSync(request.executable,request.args,{
 cwd:request.cwd,encoding:'utf8',shell:false,windowsHide:true,timeout:request.timeout_ms,
 env:process.env,maxBuffer:64*1024*1024});
process.stdout.write(response.stdout||'');
process.stderr.write(response.stderr||'');
if(response.error){console.error(response.error.code||'native_spawn_failed');process.exit(1);}
process.exit(response.status??1);

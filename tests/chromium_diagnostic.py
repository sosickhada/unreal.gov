"""Bounded local-only Chromium startup probe; no DB, services or application APIs."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


def tree(pid):
    result=[]
    def visit(p):
        root=Path('/proc')/str(p)
        try:
            stat={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in (root/'status').read_text().splitlines() if ':' in line}
            result.append({'pid':p,'name':stat.get('Name'),'state':stat.get('State'),'rss':stat.get('VmRSS'),'wait':(root/'wchan').read_text().strip()})
            for ch in (root/'task'/str(p)/'children').read_text().split(): visit(int(ch))
        except (FileNotFoundError,PermissionError): pass
    visit(pid)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--shell',action='store_true');p.add_argument('--profile-dir',default='/tmp');p.add_argument('--single-process',action='store_true');args=p.parse_args()
    base=Path.home()/'.cache/ms-playwright'
    exe=base/('chromium_headless_shell-1248/chrome-headless-shell-linux64/chrome-headless-shell' if args.shell else 'chromium-1248/chrome-linux64/chrome')
    if args.shell and not exe.is_file(): exe=next((base/'chromium_headless_shell-1248').rglob('chrome-headless-shell'))
    print('executable',exe,'exists',exe.is_file(),flush=True)
    with tempfile.TemporaryDirectory(prefix='unreal-probe-',dir=args.profile_dir) as profile, tempfile.TemporaryFile() as errors:
        command=[str(exe),'--headless','--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--disable-extensions','--disable-background-networking','--no-first-run','--user-data-dir='+profile,'--dump-dom','about:blank']
        if args.single_process:command.extend(['--no-zygote','--single-process'])
        started=time.monotonic();proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors,start_new_session=True)
        try:
            try:
                out,_=proc.communicate(timeout=12)
                print('exit',proc.returncode,'seconds',round(time.monotonic()-started,2),'dom',out.decode()[:150],flush=True)
            except subprocess.TimeoutExpired:
                rows=tree(proc.pid);print('TIMEOUT',rows,flush=True)
                for row in reversed(rows):
                    try:os.kill(row['pid'],signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.wait(timeout=3)
        finally:
            errors.seek(0);print('stderr',errors.read(5000).decode(errors='replace'),flush=True)
            print('own_live_descendants',tree(proc.pid),flush=True)

if __name__=='__main__':main()

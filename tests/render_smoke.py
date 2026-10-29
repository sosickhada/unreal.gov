"""Offline real-browser acceptance test. Artifacts are retained outside the public tree."""
import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from figma_renderer import render_carousel
from PIL import Image

SAMPLE={'title':'가상 심의','slides':[{'eyebrow':'사건 접수','headline':'퇴근 앞의 질문','body':''},{'eyebrow':'가상 사건 경위','headline':'핵심 쟁점','body':'퇴근을 앞두고 질문이 도착한 가상 사건입니다.','emphasis':[]},{'eyebrow':'처분/판정안','headline':'최종 판정','body':'가상 심의 경과입니다.\n\n답변은 내일로 이월합니다.','emphasis':[]},{}]}


def identity(pid):
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        return (int(pid),fields[19]),fields[0]
    except (FileNotFoundError,PermissionError):return None,None


def descendants(pid):
    result=[]
    try:children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
    except (FileNotFoundError,PermissionError):return result
    for child in children:
        ident,state=identity(child)
        if ident:result.append(ident)
        result.extend(descendants(child))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('4','5','overflow'),default='5');parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root=args.output or Path(__file__).resolve().parents[1]/'output'/'render-smoke'/stamp
    root.mkdir(parents=True,exist_ok=True)
    events=[];observed=set();start=time.monotonic()
    memory={'peak_tree_pss_kib':0,'peak_tree_rss_kib':0};stop=threading.Event()
    def sample_memory():
        while not stop.is_set():
            pss=rss=0
            for pid in [os.getpid()]+[ident[0] for ident in descendants(os.getpid())]:
                try:
                    values={line.split(':')[0]:line.split(':')[1].split()[0] for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines() if ':' in line}
                    pss+=int(values.get('Pss',0));rss+=int(values.get('Rss',0))
                except (FileNotFoundError,PermissionError,ProcessLookupError): pass
            memory['peak_tree_pss_kib']=max(memory['peak_tree_pss_kib'],pss)
            memory['peak_tree_rss_kib']=max(memory['peak_tree_rss_kib'],rss)
            stop.wait(.1)
    monitor=threading.Thread(target=sample_memory,daemon=True);monitor.start()
    def progress(stage,details):
        observed.update(descendants(os.getpid()))
        event={'stage':stage,'seconds':round(time.monotonic()-start,3),**details,'processes':[list(p) for p in sorted(observed)]};events.append(event)
        (root/f'case-{args.case}-trace.json').write_text(json.dumps(events,ensure_ascii=False,indent=2))
        print(json.dumps(event,ensure_ascii=False),flush=True)
    sample=copy.deepcopy(SAMPLE)
    if args.case=='4':sample['slides'][2]['body']='이 가상 사건의 답변은 내일로 이월합니다.'
    if args.case=='overflow':sample['slides'][0]['headline']='퇴근 앞의 질문입니다. '*150
    paths=[];expected_error=None
    try:
        paths=render_carousel(sample,str(root/f'case-{args.case}'),progress)
        if args.case=='overflow':raise AssertionError('Overflow was silently accepted')
        assert len(paths)==int(args.case)
        for path in paths:
            with Image.open(path) as im:
                im.load();assert im.size==(1080,1350) and im.format=='PNG'
        # The fixed ending must remain byte-for-pixel identical to approved artwork.
        with Image.open(paths[-1]) as rendered,Image.open('/opt/unreal-github/figma_assets/ending_fixed.png') as approved:
            assert rendered.convert('RGB').tobytes()==approved.convert('RGB').tobytes()
    except ValueError as exc:
        if args.case!='overflow' or 'overflow' not in str(exc):raise
        expected_error=str(exc)
    finally:
        stop.set();monitor.join(timeout=2)
        deadline=time.monotonic()+2
        while any(identity(pid)[0]==ident and identity(pid)[1]!='Z' for ident in observed for pid in [ident[0]]) and time.monotonic()<deadline:
            time.sleep(.05)
        alive=[pid for pid,birth in observed if identity(pid)[0]==(pid,birth) and identity(pid)[1]!='Z']
        zombies=[pid for pid,birth in observed if identity(pid)[0]==(pid,birth) and identity(pid)[1]=='Z']
        report={'case':args.case,'seconds':round(time.monotonic()-start,3),'paths':paths,'sizes':[[1080,1350]]*len(paths),'expected_overflow_error':expected_error,'observed_processes':len(observed),'alive_processes':alive,'zombie_processes':zombies,'memory':memory,'events':events}
        (root/f'case-{args.case}-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        assert not alive and not zombies,report
    print('PASS',root/f'case-{args.case}-report.json',flush=True)

if __name__=='__main__':main()

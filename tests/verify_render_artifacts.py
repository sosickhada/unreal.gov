"""Verify retained PNGs after rendering, without starting browsers or API clients."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/opt/unreal-github/output/render-smoke/acceptance'));args=p.parse_args();root=args.root
    report={'cases':{},'live_render_processes':[]}
    for count in (4,5):
        events=json.loads((root/f'case-{count}-trace.json').read_text())
        assert any(e['stage']=='driver_closed' for e in events)
        checked=[e for e in events if e['stage']=='layout_checked']
        assert len(checked)==count and all(not e['overflow'] and not e['brokenImages'] and all(e['fonts'].values()) for e in checked)
        pages=[]
        for i in range(1,count+1):
            path=root/f'case-{count}_{i:02d}.png'
            with Image.open(path) as im:
                im.load();assert im.format=='PNG' and im.size==(1080,1350)
            pages.append({'path':str(path),'dimensions':[1080,1350],'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        with Image.open(pages[-1]['path']) as rendered,Image.open('/opt/unreal-github/figma_assets/ending_fixed.png') as approved:
            assert rendered.convert('RGB').tobytes()==approved.convert('RGB').tobytes()
        report['cases'][str(count)]={'pngs':pages,'renderer_seconds':next(e['seconds'] for e in events if e['stage']=='driver_closed'),'all_text_fits':True,'fonts_loaded':True,'ending_pixel_identical':True}
    for old in sorted((root/'baseline').glob('*.png')):
        with Image.open(old) as original,Image.open(root/old.name) as optimized:
            assert original.convert('RGBA').tobytes()==optimized.convert('RGBA').tobytes()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            name=(proc/'comm').read_text().strip()
            if not ('chrome' in name or name=='MainThread'):continue
            command=(proc/'cmdline').read_bytes()
            if b'unreal-render-' in command or b'unreal-probe-' in command:
                report['live_render_processes'].append({'pid':int(proc.name),'name':name})
        except (FileNotFoundError,PermissionError,ProcessLookupError):pass
    assert not report['live_render_processes'],report['live_render_processes']
    report['overflow_test']=json.loads((root/'case-overflow-report.json').read_text())['expected_overflow_error']
    assert report['overflow_test']
    (root/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'result':'PASS','case_4_pngs':4,'case_5_pngs':5,'dimensions':[1080,1350],'live_render_processes':report['live_render_processes'],'report':str(root/'verification.json')},ensure_ascii=False))

if __name__=='__main__':main()

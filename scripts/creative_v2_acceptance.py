"""Offline editorial comparison and optional real renderer. Never publishes or calls models."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bureau.creative_comparison import compare,markdown,FIXTURES
from bureau.config import Config
from bureau.adapters import Media


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--render',action='store_true')
    parser.add_argument('--output',default='output/creative-v2-acceptance')
    args=parser.parse_args();root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    report=compare();(root/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (root/'comparison.md').write_text(markdown(report))
    if args.render:
        project=Path(__file__).resolve().parents[1]
        draft=json.loads(FIXTURES.read_text())['cases'][0]['after']
        draft['case_number']='오프라인 회귀 시험 9001-2'
        for i,slide in enumerate(draft['slides']):
            asset=project/'data/official-shipping'/('6170455.jpg' if i in (0,2) else '5218021.jpg')
            if not asset.is_file():raise SystemExit('Renderer smoke requires existing locally licensed topic photos; nothing downloaded')
            slide['background_image']=str(asset)
        config=Config(root/'unused.db',{'RENDER_DIR':str(root),'PUBLIC_BASE_URL':'https://offline.invalid','RENDER_TIMEOUT_SECONDS':'300','RENDER_TRACE_DIR':str(root/'traces'),'PAID_AI_CALLS_ENABLED':'0'})
        media=Media(config).render(draft,9001,2);media['test_only']=True
        trace=json.loads((root/'traces/9001-v2-trace.json').read_text())
        checks=[x for x in trace if x['stage']=='layout_checked']
        report['render']={'test_only':True,'media':media,'pages':len(checks),'no_overflow':not any(x['overflow'] for x in checks),'fonts_loaded':all(all(x['fonts'].values()) for x in checks),'images_decoded':not any(x['brokenImages'] for x in checks),'story_page_count':sum(x.get('kind')=='story' for x in trace if x['stage']=='page_start'),'publication_allowed':False}
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('Offline acceptance complete: 8 editorial test cases; paid calls 0; public posts 0'+('; real five-page render' if args.render else ''))

if __name__=='__main__':main()

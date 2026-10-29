"""Isolated Chromium child; parent enforces a hard process-group deadline."""
import json
import sys
import os
import time
from pathlib import Path
from figma_renderer import render_carousel, expand_slides


def main():
    source,prefix,target=sys.argv[1:]
    draft=json.loads(Path(source).read_text())
    count=len(expand_slides(draft))
    completed=[]
    events=[];started=time.monotonic()
    def progress(stage, details):
        trace=os.getenv('UNREAL_RENDER_TRACE')
        if trace:
            events.append(dict(stage=stage,seconds=round(time.monotonic()-started,3),**details))
            Path(trace).write_text(json.dumps(events))
        if stage!='page_saved': return
        completed.append(details['page'])
        if completed!=list(range(1,count+1)): return
        # Every page has passed font/image/overflow checks and was written.
        # Commit before browser shutdown, which can hang after valid captures.
        paths=[prefix+f'_{i:02}.png' for i in completed]
        pending=Path(target+'.pending');pending.write_text(json.dumps(paths))
        pending.replace(target)
    render_carousel(draft,prefix,progress)

if __name__=='__main__':main()

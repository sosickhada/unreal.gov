"""Prepare/cache exact font subsets in an isolated process before Chromium starts."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import string
import sys
import tempfile
import inspect
from figma_renderer import validate_fonts,subset_fonts


def file_hash(path):
    result=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(262144),b''):result.update(chunk)
    return result.hexdigest()


def prepare(draft,destination):
    root=Path(__file__).resolve().parents[1]
    source=root/'figma_assets/fonts'
    names=('ROKG_R.ttf','ChosunNm-full-fixed.ttf')
    key=hashlib.sha256(json.dumps({'characters':sorted(set(json.dumps(draft,ensure_ascii=False))),
        'fonts':{n:file_hash(source/n) for n in names},'fonttools':importlib.metadata.version('fonttools'),
        # Browser teardown/CSS edits do not change font outlines or subsets.
        'subset_algorithm':inspect.getsource(subset_fonts)+inspect.getsource(validate_fonts)},sort_keys=True).encode()).hexdigest()
    cache=root/'output/render-font-cache'/key
    manifest=cache/'manifest.json'
    valid=False
    if manifest.is_file():
        try:
            saved=json.loads(manifest.read_text())
            valid=all((cache/n).is_file() and file_hash(cache/n)==saved.get(n) for n in names)
        except (OSError,ValueError): valid=False
    if not valid:
        validate_fonts(draft)
        cache.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='font-build-',dir=cache.parent) as build:
            paths=subset_fonts(draft,build)
            for n,p in paths.items():shutil.copyfile(p,cache/n)
            pending=Path(build)/'manifest.json'
            pending.write_text(json.dumps({n:file_hash(cache/n) for n in names}))
            pending.replace(manifest)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    for n in names:shutil.copyfile(cache/n,destination/n)

if __name__=='__main__':prepare(json.loads(Path(sys.argv[1]).read_text()),sys.argv[2])

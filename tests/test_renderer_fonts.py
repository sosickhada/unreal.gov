"""Subsetting must preserve the approved font's outlines and advance widths."""
from pathlib import Path
import tempfile
import unittest
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
from figma_renderer import subset_fonts

ROOT=Path('/opt/unreal-github/figma_assets/fonts')

@unittest.skipUnless((ROOT/'ChosunNm-full-fixed.ttf').is_file(),'Approved local fonts unavailable')
class FontPreservationTests(unittest.TestCase):
    def test_subset_preserves_korean_outlines_metrics_and_hinting(self):
        text='비현실문제해결부 퇴근 질문 답변 이월 가상 사건 심의 경과 처분 판정안'
        with tempfile.TemporaryDirectory() as tmp:
            paths=subset_fonts({'slides':[{'body':text}]},tmp)
            for name,path in paths.items():
                with TTFont(ROOT/name) as original,TTFont(path) as actual:
                    self.assertLess(path.stat().st_size,(ROOT/name).stat().st_size//5)
                    self.assertEqual(original['head'].unitsPerEm,actual['head'].unitsPerEm)
                    for field in ('ascent','descent','lineGap'):
                        self.assertEqual(getattr(original['hhea'],field),getattr(actual['hhea'],field))
                    oldmap=original.getBestCmap();newmap=actual.getBestCmap()
                    oldglyphs=original.getGlyphSet();newglyphs=actual.getGlyphSet()
                    for char in set(text)-{' '}:
                        code=ord(char)
                        self.assertIn(code,newmap)
                        old=oldmap[code];new=newmap[code]
                        self.assertEqual(original['hmtx'][old],actual['hmtx'][new])
                        a=DecomposingRecordingPen(oldglyphs);b=DecomposingRecordingPen(newglyphs)
                        oldglyphs[old].draw(a);newglyphs[new].draw(b)
                        self.assertEqual(a.value,b.value)
                        if 'glyf' in original and hasattr(original['glyf'][old],'program'):
                            self.assertEqual(original['glyf'][old].program.getBytecode(),actual['glyf'][new].program.getBytecode())

if __name__=='__main__':unittest.main()

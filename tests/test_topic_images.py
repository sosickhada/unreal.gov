"""Topic routing and fail-closed review tests; no provider calls."""
import json
from pathlib import Path
from unittest.mock import patch
import unittest
import test_system as system
from bureau.config import Config
from bureau.images import select_photos


class TopicImagesTest(unittest.TestCase):
    setUp=system.SystemTest.setUp
    tearDown=system.SystemTest.tearDown
    q=system.SystemTest.q
    candidates=system.SystemTest.candidates
    # Reuse the isolated DB/network guard, without inheriting the pipeline suite twice.
    def add_photo(self, name, tags):
        photo={'path':name,'sha256':name,'reviewer':'offline test','relevance_reviewed':True,
               'faces_reviewed':True,'photograph_reviewed':True,'review_required':False}
        with self.store.tx() as c:
            c.execute('INSERT INTO image_library VALUES(?,?,?,?)',(name,json.dumps(photo),tags,'test'))
        return photo

    def test_two_slots_are_automatically_routed(self):
        cid=self.candidates();rid=self.store.select(cid);self.engine.run_one()
        r=self.store.row(rid);d=json.loads(r['draft_json'])
        d['image_queries']={'content':'empty office desk','resolution_extra':'closed office door'}
        with self.store.tx() as c:c.execute('UPDATE selections SET draft_json=? WHERE id=?',(json.dumps(d),rid))
        self.add_photo('desk','empty office desk');self.add_photo('door','closed office door')
        self.engine.config=Config(self.path,{'ENABLE_EXTERNAL_CALLS':'1'})
        original=self.media.render;captured=[]
        def render(d,r,v):captured.append(d);return original(d,r,v)
        self.media.render=render
        self.store.accept_draft(rid,1)
        with patch('bureau.images.checked_photo',side_effect=lambda p:p):self.engine.run_one()
        self.assertEqual(captured[0]['slides'][1]['background_image'],'desk')
        self.assertEqual(captured[0]['slides'][2]['background_image'],'door')
        self.assertNotIn('background_image',captured[0]['slides'][0])
        self.assertEqual(self.store.row(rid)['status'],'preview_ready')
        self.assertEqual(len(self.q('SELECT * FROM image_inputs')),1)

    def test_duplicate_or_unreviewed_photo_rejected(self):
        from bureau.images import checked_photo
        with self.assertRaises(ValueError):checked_photo({'review_required':True})
        with patch('bureau.images.checked_photo',side_effect=lambda p:p):
            with self.assertRaisesRegex(ValueError,'distinct'):
                select_photos([],{}, {'content':{'sha256':'same'},'resolution_extra':{'sha256':'same'}})

    def test_unrelated_library_does_not_fill_slots(self):
        p=self.add_photo('car','car')
        rows=[{'sha256':'car','tags':'car','payload':json.dumps(p)}]
        with patch('bureau.images.checked_photo',side_effect=lambda p:p):
            self.assertEqual(select_photos(rows,{'content':'office desk'}),{})

    def test_changed_bytes_rejected(self):
        from bureau.images import checked_photo
        p=self.add_photo('changed','desk');path=Path(self.tmp.name)/'changed';path.write_bytes(b'changed')
        p['path']=str(path)
        with patch('bureau.images.inspect_image',return_value={'sha256':'different'}):
            with self.assertRaisesRegex(ValueError,'bytes changed'):checked_photo(p)

    def test_same_source_in_another_batch_reuses_selection(self):
        cid=self.candidates();rid=self.store.select(cid)
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM candidates WHERE id=?',(cid,)).fetchone()
            batch=c.execute("INSERT INTO batches(day,generation,status,created_at) SELECT day,1,'ready',created_at FROM batches LIMIT 1").lastrowid
            other=c.execute('INSERT INTO candidates(batch_id,position,title,payload,created_at) VALUES(?,?,?,?,?)',(batch,1,'다른 제목',row['payload'],'test')).lastrowid
        self.assertEqual(self.store.select(other),rid)
        self.assertEqual(len(self.q("SELECT * FROM jobs WHERE kind='draft'")),1)

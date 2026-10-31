import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from bureau.store import Store,now
from bureau.photo_review import approve

class HumanPhotoReviewTests(unittest.TestCase):
    def test_two_explicit_approvals_resume_saved_job_and_preserve_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'test.db');store.migrate()
            with store.tx() as c:
                c.execute("INSERT INTO selections(id,candidate_number,candidate_title,status,revision) VALUES(4,1,'test','draft_ready',2)")
                jid=store.enqueue(c,'render:4:2','render',{'id':4,'revision':2})
                c.execute("UPDATE jobs SET state='waiting' WHERE id=?",(jid,))
                keys=[]
                for digest in ('first','second'):
                    row=c.execute('INSERT INTO checkpoints(job_id,step,state,result,created_at) VALUES(?,?,?,?,?)',(jid,digest+'_download','succeeded',json.dumps({'path':digest,'sha256':digest,'source_url':'source','license_url':'license','license':'CC0'}),now()))
                    keys.append(row.lastrowid)
                c.execute('INSERT INTO checkpoints(job_id,step,state,created_at) VALUES(?,?,?,?)',(jid,'claude_old','uncertain',now()))
            def manual(path,*args):return {'path':path,'sha256':path,'reviewer':args[-1]}
            with patch('bureau.photo_review.license_evidence'),patch('bureau.photo_review.manual_image',side_effect=manual),patch('bureau.photo_review.checked_photo'):
                self.assertFalse(approve(store,4,2,keys[0],'content','human'))
                with self.assertRaises(ValueError):approve(store,4,2,keys[0],'resolution_extra','human')
                self.assertTrue(approve(store,4,2,keys[1],'resolution_extra','human'))
                with self.assertRaises(ValueError):approve(store,4,2,keys[1],'resolution_extra','human')
            with store.tx() as c:
                self.assertEqual(c.execute('SELECT state FROM jobs WHERE id=?',(jid,)).fetchone()[0],'queued')
                self.assertEqual(c.execute("SELECT state FROM checkpoints WHERE step='claude_old'").fetchone()[0],'uncertain')

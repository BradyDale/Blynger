import json, subprocess, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from core import Studio, new_page


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.root=self.base/'site';self.root.mkdir();(self.root/'images').mkdir()
        (self.root/'index.html').write_text(new_page('Home','<h3>Posts</h3>'))
        (self.root/'openers.html').write_text(new_page('Openers','<h3>March 2</h3><p>Thought.</p>'))
        subprocess.run(['git','init','-b','master'],cwd=self.root,capture_output=True,check=True)
        for key,value in [('user.name','Test'),('user.email','test@example.invalid')]:
            subprocess.run(['git','config',key,value],cwd=self.root,check=True)
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','commit','-qm','Initial'],cwd=self.root,check=True)
        self.remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(self.remote)],capture_output=True,check=True)
        self.studio=Studio(self.root,self.base/'private');self.studio.git('remote','add','website',str(self.remote))
        self.studio.git('push','website','master')

    def tearDown(self):self.tmp.cleanup()

    def draft(self,title,text):
        page=self.studio.create(title,staged=False)
        page['raw']=page['raw'].replace('Start writing here.',text)
        self.studio.save_draft(page,default_staged=False)
        return page['name']

    def test_only_staged_draft_is_prepared_and_success_clears_only_it(self):
        first=self.draft('First private draft','First words.')
        second=self.draft('Second private draft','Second words.')
        self.assertFalse(self.studio.publication_status()['ready'])
        self.studio.stage_draft(first,True)
        review=self.studio.prepare()
        self.assertTrue((self.root/first).is_file());self.assertFalse((self.root/second).exists())
        home=(self.root/'index.html').read_text()
        self.assertIn('First private draft',home);self.assertNotIn('Second private draft',home)
        self.studio.publish(review['signature'])
        self.assertNotIn(first,self.studio.state['drafts'])
        self.assertIn(second,self.studio.state['drafts'])
        self.assertFalse(self.studio.state['drafts'][second]['staged'])

    def test_every_prepare_save_boundary_keeps_all_private_drafts_durable(self):
        staged=self.draft('Staged writing','Publish me.')
        private=self.draft('Private writing','Keep me private.')
        self.studio.stage_draft(staged,True)
        real_save=self.studio.save_state
        durable_snapshots=[]

        def observed_save():
            real_save()
            durable_snapshots.append(json.loads(self.studio.file.read_text()))

        with patch.object(self.studio,'save_state',side_effect=observed_save):
            self.studio.prepare(review=False)
        self.assertGreaterEqual(len(durable_snapshots),2)
        for snapshot in durable_snapshots:
            self.assertIn(private,snapshot['drafts'])
            self.assertEqual(snapshot['drafts'][private]['raw'],self.studio.state['drafts'][private]['raw'])

    def test_interrupted_prepare_reopens_with_unrelated_private_draft(self):
        staged=self.draft('Staged writing','Publish me.')
        private=self.draft('Private writing','Keep me after interruption.')
        opener=self.studio.page('openers.html')
        opener['raw']=opener['raw'].replace('Thought.','PRIVATE OPENER DRAFT.')
        self.studio.save_draft(opener,default_staged=False)
        self.studio.stage_draft(staged,True)
        original_pending=list(self.studio.state['pending'])

        def interrupted(_review=True):
            self.studio.state['pending'].append('transient-generated-file')
            self.studio.save_state()
            raise RuntimeError('simulated interruption')

        with patch.object(self.studio,'_prepare_staged',side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError,'simulated interruption'):
                self.studio.prepare(review=False)
        self.assertIn(private,self.studio.state['drafts'])
        self.assertEqual(self.studio.state['pending'],original_pending)
        reopened=Studio(self.root,self.studio.data)
        self.assertIn(private,reopened.state['drafts'])
        self.assertIn('Keep me after interruption.',reopened.state['drafts'][private]['raw'])
        self.assertIn('PRIVATE OPENER DRAFT.',reopened.state['drafts']['openers.html']['raw'])
        self.assertEqual(reopened.state['pending'],original_pending)

    def test_unstage_after_review_removes_only_generated_review_files(self):
        first=self.draft('Do not leak','Private words.')
        self.studio.stage_draft(first,True);self.studio.prepare(review=False)
        self.assertTrue((self.root/first).exists())
        self.studio.stage_draft(first,False)
        self.assertFalse((self.root/first).exists())
        self.assertNotIn('Do not leak',(self.root/'index.html').read_text())
        self.assertFalse(self.studio.publication_status()['ready'])

    def test_series_dependencies_follow_stage_and_restore_when_unstaged(self):
        self.studio.create_series('Test Series','A test series.','Description.',staged=False)
        series_page='series-test-series.html'
        original=dict(self.studio.state['drafts'][series_page])
        post=self.studio.create('Installment',staged=False)
        post['series_id']='test-series';post['series_attribute']='Part I'
        self.studio.save_draft(post,default_staged=False)
        self.studio.stage_draft(post['name'],True);self.studio.prepare(review=False)
        self.assertTrue(self.studio.state['drafts'][series_page]['staged'])
        self.studio.stage_draft(post['name'],False)
        self.assertIn(series_page,self.studio.state['drafts'])
        self.assertFalse(self.studio.state['drafts'][series_page]['staged'])
        self.assertEqual(self.studio.state['drafts'][series_page]['raw'],original['raw'])
        self.assertFalse(self.studio.publication_status()['ready'])

    def test_series_dependency_does_not_publish_unstaged_series_page_edit(self):
        self.studio.create_series('Test Series','A test series.','Public description.',staged=True)
        first_review=self.studio.prepare()
        self.studio.publish(first_review['signature'])
        series_page='series-test-series.html'

        private=self.studio.page(series_page)
        private['raw']=private['raw'].replace('Public description.','PRIVATE SERIES NOTES.')
        self.studio.save_draft(private,default_staged=False)
        self.assertFalse(self.studio.state['drafts'][series_page]['staged'])

        post=self.studio.create('New installment',staged=False)
        post['series_id']='test-series';post['series_attribute']='Part I'
        self.studio.save_draft(post,default_staged=False)
        self.studio.stage_draft(post['name'],True)
        review=self.studio.prepare()

        prepared_series=(self.root/series_page).read_text()
        self.assertIn('New installment',prepared_series)
        self.assertNotIn('PRIVATE SERIES NOTES.',prepared_series)
        self.assertIn('PRIVATE SERIES NOTES.',self.studio.state['prepared_cleanup']['dependency_originals'][series_page]['raw'])

        self.studio.publish(review['signature'])
        committed=self.studio.git('show','HEAD:'+series_page)
        self.assertIn('New installment',committed)
        self.assertNotIn('PRIVATE SERIES NOTES.',committed)
        self.assertIn(series_page,self.studio.state['drafts'])
        restored=self.studio.state['drafts'][series_page]
        self.assertFalse(restored['staged'])
        self.assertFalse(restored['new'])
        self.assertIn('PRIVATE SERIES NOTES.',restored['raw'])
        self.assertIn('New installment',restored['raw'])
        self.assertEqual(restored['base'],__import__('core').digest((self.root/series_page).read_bytes()))

        reopened=Studio(self.root,self.studio.data)
        self.assertIn('PRIVATE SERIES NOTES.',reopened.state['drafts'][series_page]['raw'])
        self.assertFalse(reopened.state['drafts'][series_page]['staged'])

    def test_explicitly_staged_series_page_edit_is_published(self):
        self.studio.create_series('Test Series','A test series.','Public description.',staged=True)
        first_review=self.studio.prepare();self.studio.publish(first_review['signature'])
        series_page='series-test-series.html'
        private=self.studio.page(series_page)
        private['raw']=private['raw'].replace('Public description.','INTENTIONALLY PUBLIC NOTES.')
        self.studio.save_draft(private,default_staged=False)
        self.studio.stage_draft(series_page,True)

        post=self.studio.create('New installment',staged=False)
        post['series_id']='test-series';post['series_attribute']='Part I'
        self.studio.save_draft(post,default_staged=False);self.studio.stage_draft(post['name'],True)
        self.studio.prepare(review=False)
        self.assertIn('INTENTIONALLY PUBLIC NOTES.',(self.root/series_page).read_text())

    def test_older_drafts_migrate_to_unstaged(self):
        name=self.draft('Older draft','Still private.')
        state=json.loads(self.studio.file.read_text());state['drafts'][name].pop('staged')
        self.studio.file.write_text(json.dumps(state))
        reopened=Studio(self.root,self.studio.data)
        self.assertFalse(reopened.state['drafts'][name]['staged'])
        self.assertFalse(reopened.publication_status()['ready'])


if __name__=='__main__':unittest.main()

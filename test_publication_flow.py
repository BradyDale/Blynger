import copy, subprocess, tempfile, threading, time, types, unittest
from pathlib import Path

from app import PublicationJob, ReviewJob
from core import Studio, new_page


class BackgroundPublicationTests(unittest.TestCase):
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
        self.server=types.SimpleNamespace(studio=self.studio,lock=threading.RLock(),reader_lock=threading.RLock())
        self.job=PublicationJob(self.server)
    def tearDown(self):self.tmp.cleanup()
    def wait_for(self,state,timeout=5):
        limit=time.monotonic()+timeout
        while time.monotonic()<limit:
            status=self.job.status()
            if status['state']==state:return status
            time.sleep(.01)
        self.fail('publication did not reach '+state+': '+repr(self.job.status()))
    def delayed_network(self):
        entered=threading.Event();release=threading.Event();original=self.studio.push_publication_network
        def delayed(pending):
            entered.set();release.wait(5);return original(pending)
        self.studio.push_publication_network=delayed
        return entered,release
    def test_delayed_success_returns_promptly_and_preserves_later_draft(self):
        approved=self.studio.create('Approved post');review=self.studio.prepare();entered,release=self.delayed_network()
        started=time.monotonic();result=self.job.start(review['signature']);elapsed=time.monotonic()-started
        self.assertLess(elapsed,1);self.assertIn(result['state'],('queued','publishing'));self.assertTrue(entered.wait(2))
        later=self.studio.create('Written while publishing')
        self.studio.state['pins']['queued-while-publishing']=['3'];self.studio.save_state()
        with self.assertRaises(ValueError):self.job.start(review['signature'])
        release.set();self.wait_for('succeeded')
        self.assertIn(later['name'],self.studio.state['drafts']);self.assertNotIn(approved['name'],self.studio.state['drafts'])
        self.assertEqual(self.studio.state['pins']['queued-while-publishing'],['3'])
        hosted=subprocess.run(['git','--git-dir',str(self.remote),'show','master:'+later['name']],capture_output=True)
        self.assertNotEqual(hosted.returncode,0)
    def test_slow_initial_connection_runs_after_start_returns(self):
        self.studio.create('Slow server post');review=self.studio.prepare()
        entered=threading.Event();release=threading.Event();original=self.studio.connection
        def delayed_connection():
            entered.set();self.assertTrue(release.wait(5));return original()
        self.studio.connection=delayed_connection
        started=time.monotonic();result=self.job.start(review['signature']);elapsed=time.monotonic()-started
        self.assertLess(elapsed,1);self.assertIn(result['state'],('queued','publishing'))
        self.assertIn('pending_publication',self.studio.state);self.assertTrue(entered.wait(2))
        release.set();self.wait_for('succeeded')
        self.assertNotIn('pending_publication',self.studio.state)
    def test_unavailable_initial_connection_is_reported_as_background_failure(self):
        self.studio.create('Unavailable server post');review=self.studio.prepare()
        entered=threading.Event()
        def unavailable():
            entered.set();raise ValueError('publishing server unavailable')
        self.studio.connection=unavailable
        started=time.monotonic();result=self.job.start(review['signature']);elapsed=time.monotonic()-started
        self.assertLess(elapsed,1);self.assertIn(result['state'],('queued','publishing'))
        self.assertTrue(entered.wait(2));status=self.wait_for('uncertain')
        self.assertIn('publishing server unavailable',status['message'])
        self.assertTrue(status['retryable']);self.assertIn('pending_publication',self.studio.state)
    def test_webmention_service_wakes_after_publication_locks_are_released(self):
        class Service:
            def __init__(inner):inner.calls=[]
            def wake(inner):
                inner.calls.append((self.server.lock._is_owned(),self.server.reader_lock._is_owned()))
        service=Service();self.server.webmentions=service
        self.studio.create('Wake mentions');review=self.studio.prepare();self.job.start(review['signature'])
        self.wait_for('succeeded')
        self.assertEqual(service.calls,[(False,False)])
    def test_webmention_wake_failure_does_not_change_publication_success(self):
        class Service:
            def wake(inner):raise RuntimeError('background service unavailable')
        self.server.webmentions=Service()
        self.studio.create('Publish anyway');review=self.studio.prepare();self.job.start(review['signature'])
        status=self.wait_for('succeeded')
        self.assertIn('Webmention delivery will retry later',status['detail'])
        self.assertNotIn('pending_publication',self.studio.state)
    def test_registry_refresh_wakes_after_publication_locks_are_released(self):
        class Service:
            def __init__(inner):inner.calls=[]
            def wake(inner):
                inner.calls.append((self.server.lock._is_owned(),self.server.reader_lock._is_owned()))
        service=Service();self.server.registry_refresh=service
        self.studio.create('Refresh targets');review=self.studio.prepare();self.job.start(review['signature'])
        self.wait_for('succeeded')
        self.assertEqual(service.calls,[(False,False)])
    def test_registry_refresh_wake_failure_does_not_change_publication_success(self):
        class Service:
            def wake(inner):raise RuntimeError('registry worker unavailable')
        self.server.registry_refresh=Service()
        self.studio.create('Publish despite registry wake');review=self.studio.prepare();self.job.start(review['signature'])
        status=self.wait_for('succeeded')
        self.assertIn('Inbound target refresh will retry',status['detail'])
        self.assertNotIn('pending_publication',self.studio.state)
    def test_later_edit_survives_and_history_uses_approved_commit(self):
        approved=self.studio.create('Exact post');approved['raw']=approved['raw'].replace('Start writing here.','Approved words.');self.studio.save_draft(approved)
        review=self.studio.prepare();entered,release=self.delayed_network();self.job.start(review['signature']);self.assertTrue(entered.wait(2))
        later=self.studio.page(approved['name']);later['raw']=later['raw'].replace('Approved words.','Later unpublished words.');self.studio.save_draft(later)
        release.set();self.wait_for('succeeded')
        self.assertIn(approved['name'],self.studio.state['drafts']);self.assertIn('Later unpublished words.',self.studio.state['drafts'][approved['name']]['raw'])
        published=self.studio.state['published'][self.studio.state['ids'][approved['name']]]
        self.assertIn('Approved words.',published['content_html']);self.assertNotIn('Later unpublished words.',published['content_html'])
    def test_interrupted_job_resumes_after_restart(self):
        self.studio.create('Retry me');review=self.studio.prepare()
        original=self.studio.push_publication_network
        self.studio.push_publication_network=lambda pending:(_ for _ in ()).throw(ValueError('connection dropped'))
        self.job.start(review['signature']);self.wait_for('uncertain')
        self.assertIn('pending_publication',self.studio.state)
        restarted_job=PublicationJob(self.server);restarted=restarted_job.status()
        self.assertEqual(restarted['state'],'uncertain');self.assertTrue(restarted['retryable'])
        self.studio.push_publication_network=original;self.job=restarted_job
        restarted_job.resume();self.wait_for('succeeded')
        self.assertNotIn('pending_publication',self.studio.state)
    def test_restart_finalizes_publication_already_on_host(self):
        post=self.studio.create('Reached the host');review=self.studio.prepare()
        pending=self.studio.begin_publication(review['signature'])
        self.studio.push_publication_network(pending)
        self.assertIn('pending_publication',self.studio.state)
        self.assertIn(post['name'],self.studio.state['drafts'])
        self.job=PublicationJob(self.server)
        started=self.job.resume()
        self.assertIn(started['state'],('queued','publishing'))
        self.wait_for('succeeded')
        self.assertNotIn('pending_publication',self.studio.state)
        self.assertNotIn(post['name'],self.studio.state['drafts'])
    def test_save_after_review_is_refused_before_commit(self):
        post=self.studio.create('Reviewed post')
        post['raw']=post['raw'].replace('Start writing here.','Reviewed words.')
        self.studio.save_draft(post);review=self.studio.prepare();head=self.studio.git('rev-parse','HEAD')
        later=self.studio.page(post['name'])
        later['raw']=later['raw'].replace('Reviewed words.','Newer saved words.')
        self.studio.save_draft(later)
        with self.assertRaisesRegex(ValueError,'Review again'):
            self.studio.begin_publication(review['signature'])
        self.assertEqual(self.studio.git('rev-parse','HEAD'),head)
        self.assertNotIn('pending_publication',self.studio.state)
        self.assertIn('Newer saved words.',self.studio.state['drafts'][post['name']]['raw'])
    def test_pin_after_review_is_refused_before_commit(self):
        review=self.studio.prepare();head=self.studio.git('rev-parse','HEAD')
        self.studio.state['pins']['queued-after-review']=['1'];self.studio.save_state()
        with self.assertRaisesRegex(ValueError,'changed after this review'):
            self.studio.begin_publication(review['signature'])
        self.assertEqual(self.studio.git('rev-parse','HEAD'),head)
        self.assertEqual(self.studio.state['pins']['queued-after-review'],['1'])
    def test_finish_keeps_snapshot_work_that_was_not_in_commit(self):
        post=self.studio.create('Actually published');review=self.studio.prepare()
        pending=self.studio.begin_publication(review['signature'])
        unrelated={'raw':'private words','base':None,'new':False,'kind':'post','at':'2026-01-01T00:00:00Z','updated':'2026-01-01T00:00:00Z','generated':[],'note':'','revision':False,'fragments':None,'quotes':{}}
        self.studio.state['drafts']['unrelated.html']=copy.deepcopy(unrelated)
        self.studio.state['pins']['uncommitted-pin']=['7']
        pending['drafts']['unrelated.html']=copy.deepcopy(unrelated)
        pending['pins']['uncommitted-pin']=['7']
        self.studio.push_publication(pending)
        self.assertNotIn(post['name'],self.studio.state['drafts'])
        self.assertEqual(self.studio.state['drafts']['unrelated.html'],unrelated)
        self.assertEqual(self.studio.state['pins']['uncommitted-pin'],['7'])

    def test_success_retires_exact_approved_draft_when_page_bytes_were_already_current(self):
        post=self.studio.create('Already current');first=self.studio.prepare()
        self.studio.push_publication(self.studio.begin_publication(first['signature']))
        same=self.studio.page(post['name']);self.studio.save_draft(same)
        second=self.studio.prepare()
        self.assertIn(post['name'],self.studio.state['drafts'])
        self.studio.push_publication(self.studio.begin_publication(second['signature']))
        self.assertNotIn(post['name'],self.studio.state['drafts'])

    def test_review_job_returns_before_prepare_finishes(self):
        self.studio.create('Queued post');self.studio.git('push','website','master')
        entered=threading.Event();release=threading.Event();original=self.studio.prepare
        def delayed(review=True):
            entered.set();self.assertTrue(release.wait(5));return original(review=review)
        self.studio.prepare=delayed
        job=ReviewJob(self.server);started=time.monotonic();result=job.start()
        self.assertLess(time.monotonic()-started,1);self.assertEqual(result['state'],'running');self.assertNotIn('review',result)
        self.assertTrue(entered.wait(2));self.assertEqual(job.status()['state'],'running')
        release.set();limit=time.monotonic()+8
        while time.monotonic()<limit and job.status()['state']!='ready':time.sleep(.02)
        status=job.status();self.assertEqual(status['state'],'ready',status.get('message'))
        self.assertIn(('1.html',True),[(change['path'],change.get('new')) for change in status['review']['changes']])
        self.assertTrue((self.root/'1.html').is_file())

    def test_prepare_cannot_rewrite_files_while_approved_commit_is_in_flight(self):
        approved=self.studio.create('Approved post');review=self.studio.prepare()
        pending=self.studio.begin_publication(review['signature'])
        approved_bytes=(self.root/approved['name']).read_bytes()
        later=self.studio.create('Written during publication')
        with self.assertRaisesRegex(ValueError,'already being sent'):
            self.studio.prepare(review=False)
        self.assertEqual((self.root/approved['name']).read_bytes(),approved_bytes)
        self.assertFalse((self.root/later['name']).exists())
        self.assertEqual(self.studio.pending_publication()['commit'],pending['commit'])

    def test_second_review_is_refused_while_publication_is_in_flight(self):
        self.studio.create('Approved post');review=self.studio.prepare()
        self.studio.begin_publication(review['signature'])
        job=ReviewJob(self.server)
        with self.assertRaisesRegex(ValueError,'already being sent'):
            job.start()
        self.assertEqual(job.status()['state'],'idle')

    def test_hosted_review_refresh_is_refused_during_publication(self):
        self.studio.create('Approved post');review=self.studio.prepare()
        self.studio.begin_publication(review['signature'])
        with self.assertRaisesRegex(ValueError,'already being sent'):
            self.studio.refresh_review()


if __name__=='__main__':unittest.main()

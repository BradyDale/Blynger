import subprocess
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from core import Studio, new_page


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.root=self.base/'site'
        self.root.mkdir()
        (self.root/'images').mkdir()
        (self.root/'index.html').write_text(new_page('Home','<h3>Posts</h3>'))
        (self.root/'openers.html').write_text(new_page('Openers','<h3>Today</h3><p>Hello.</p>'))
        subprocess.run(['git','init','-b','master'],cwd=self.root,capture_output=True,check=True)
        subprocess.run(['git','config','user.name','Test'],cwd=self.root,check=True)
        subprocess.run(['git','config','user.email','test@example.invalid'],cwd=self.root,check=True)
        subprocess.run(['git','add','.'],cwd=self.root,check=True)
        subprocess.run(['git','commit','-qm','Initial'],cwd=self.root,check=True)
        self.studio=Studio(self.root,self.base/'private')

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_installment_preserves_earlier_members_byte_for_byte(self):
        import series
        first = self.studio.create('First: Test Series')
        second = self.studio.create('Second: Test Series')
        self.studio.create_series('Test Series', 'Test', 'Description.')
        self.studio.save_series_choice(first['name'], 'test-series')
        self.studio.save_series_choice(second['name'], 'test-series')
        self.studio.prepare(review=False)
        self.studio.state['drafts'].clear()
        self.studio.state['pins'].clear()
        # A legacy member can retain its old headline, absolute Series links,
        # and no boundary comments without becoming part of a new publication.
        path = self.root / first['name']
        raw = path.read_text().replace('<h1>First</h1>', '<h1>First: Test Series</h1>')
        raw = raw.replace('href="/series-', 'href="https://example.com/series-')
        raw = raw.replace(series.SUBTITLE_START, '').replace(series.SUBTITLE_END, '')
        path.write_text(raw)
        before = path.read_bytes()
        third = self.studio.create('Third')
        self.studio.save_series_choice(third['name'], 'test-series')
        self.studio.prepare(review=False)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn(first['name'], self.studio.state['drafts'])
        self.assertIn(second['name'], self.studio.state['drafts'])
        self.assertIn(third['name'], (self.root / second['name']).read_text())
        self.assertIn(third['name'], (self.root / 'series-test-series.html').read_text())

    def test_create_empty_series_and_build_static_navigation_from_explicit_members(self):
        first=self.studio.create('Day one : Test Series',body='<h2>Chapter 1</h2><p>One.</p>')
        second=self.studio.create('Day two: Test Series',body='<h2>Chapter 2</h2><p>Two.</p>')
        result=self.studio.create_series('Test Series','Test','Why I am reading this.')
        self.assertEqual(result['series'][0]['members'],[])
        self.assertEqual(result['series'][0]['page'],'series-test-series.html')
        self.studio.save_series_choice(first['name'],'test-series','Chapter 1')
        self.studio.save_series_choice(second['name'],'test-series','Chapter 2')
        first_page=self.studio.page(first['name'])
        self.assertEqual(first_page['series']['id'],'test-series')
        self.assertNotIn('blynger-series-title',first_page['body'])
        self.studio.prepare(review=False)
        first_page=self.studio.page(first['name'])
        self.assertIn('series-test-series.html',first_page['body'])
        subtitle=BeautifulSoup(first_page['body'],'html.parser').select_one('h3.blynger-series-title')
        self.assertIsNotNone(subtitle)
        self.assertEqual(subtitle.get_text(strip=True),'Test Series')
        self.assertIn('.blynger-series-title{text-align:right}',first_page['raw'])
        self.assertEqual(BeautifulSoup(first_page['body'],'html.parser').h1.get_text(strip=True),'Day one')
        homepage=BeautifulSoup(self.studio.page('index.html')['body'],'html.parser')
        self.assertEqual(homepage.find('a',href='/'+first['name']).get_text(strip=True),'Day one: Test Series')
        self.assertIn('Next Test:',first_page['body'])
        self.assertIn(second['name'],first_page['body'])
        self.assertNotIn('Next Test:',self.studio.page(second['name'])['body'])
        series_page=self.studio.page('series-test-series.html')
        soup=BeautifulSoup(series_page['body'],'html.parser')
        self.assertEqual([a.get_text() for a in soup.select('ol a')],['Day one','Day two'])
        self.assertIn('Why I am reading this.',soup.get_text())

    def test_create_series_never_guesses_members_from_matching_headlines(self):
        post=self.studio.create('One: Test Series',body='<p>Writing.</p>')
        self.studio.state['drafts'][post['name']]['fragments']={
            'version':1,
            'blocks':[{'id':'stale','html':'<p>Older writing.</p>'}],
            'dividers':[],
            'ranges':[],
        }
        result=self.studio.create_series('Test Series','Test','Description.')
        self.assertEqual(result['series'][0]['members'],[])
        self.assertIn('Test Series',self.studio.page('series-test-series.html')['body'])
        self.assertEqual(self.studio.state['series_pending'],['test-series'])

    def test_assignment_updates_attribute_and_prior_next_link_idempotently(self):
        first=self.studio.create('One: Test Series')
        second=self.studio.create('Two: Test Series')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.assign_series(first['name'],'test-series','Chapter 1')
        self.studio.assign_series(second['name'],'test-series','Chapter 2:1–2:4')
        self.studio.assign_series(second['name'],'test-series','Chapter 2:1–2:4')
        self.assertEqual(self.studio.page(first['name'])['body'].count('Next Test:'),1)
        page=self.studio.page('series-test-series.html')['body']
        self.assertIn('Chapter 2:1–2:4',page)
        self.studio.prepare(review=False)
        self.assertIn('series-test-series.html',(self.root/'sitemap.xml').read_text())
        self.assertNotIn('series-test-series.html',self.studio.state['ids'])

    def test_manual_assignment_keeps_series_suffix_on_homepage_only(self):
        self.studio.create('One: Test Series')
        plain=self.studio.create('A title without a suffix')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.assign_series(plain['name'],'test-series','Chapter 2')
        self.studio.assign_series(plain['name'],'test-series','Chapter 2')
        title=BeautifulSoup(self.studio.page(plain['name'])['body'],'html.parser').h1.get_text(strip=True)
        self.assertEqual(title,'A title without a suffix')

    def test_legacy_series_member_loses_redundant_suffix_when_another_member_is_added(self):
        legacy=self.studio.create('Legacy title: Test Series')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.state['series']['test-series']['members']=[{'name':legacy['name'],'attribute':'Old'}]
        fresh=self.studio.create('Fresh title')
        self.studio.save_series_choice(fresh['name'],'test-series','New')

        self.studio.prepare(review=False)

        self.assertEqual(BeautifulSoup(self.studio.page(legacy['name'])['body'],'html.parser').h1.get_text(strip=True),'Legacy title')
        self.assertEqual(BeautifulSoup(self.studio.page(fresh['name'])['body'],'html.parser').h1.get_text(strip=True),'Fresh title')

    def test_series_page_strips_suffix_from_legacy_saved_member_titles(self):
        raw=new_page('Test Series','<p>Introduction.</p><ol class="blynger-series-entries"><li><a href="/1.html">One: Test Series</a></li></ol>')
        updated=__import__('series').update_series_page(
            raw,
            [{'name':'1.html','title':'One: Test Series','attribute':''}],
            'Test Series',
        )
        soup=BeautifulSoup(updated,'html.parser')
        self.assertEqual(soup.select_one('ol.blynger-series-entries a').get_text(strip=True),'One')

    def test_reconcile_absorbs_one_legacy_unmanaged_series_subtitle(self):
        post=self.studio.create('A thought',body='<h3 class="blynger-series-title"><i><a href="/series-test-series.html">Test Series</a></i></h3><p>Body.</p>')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.save_series_choice(post['name'],'test-series','Chapter 1')
        self.studio.prepare(review=False)
        page=self.studio.page(post['name'])
        self.assertEqual(page['body'].count('class="blynger-series-title"'),1)
        self.assertIn('blynger-series-subtitle-start',page['raw'])

    def test_reconcile_absorbs_absolute_legacy_series_subtitles(self):
        body='<h3 class="blynger-series-title"><i><a href="https://example.com/series-test-series.html">Test Series</a></i></h3><h3 class="blynger-series-title"><i><a href="/series-test-series.html">Test Series</a></i></h3><p>Body.</p>'
        post=self.studio.create('A thought',body=body)
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.save_series_choice(post['name'],'test-series','Chapter 1')
        self.studio.prepare(review=False)
        page=self.studio.page(post['name'])
        self.assertEqual(page['body'].count('class="blynger-series-title"'),1)
        self.assertIn('blynger-series-subtitle-start',page['raw'])

    def test_removing_assignment_removes_managed_series_furniture(self):
        first=self.studio.create('One: Test Series')
        second=self.studio.create('Two: Test Series')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.assign_series(first['name'],'test-series','Chapter 1')
        self.studio.assign_series(second['name'],'test-series','Chapter 2')
        self.assertIn('Next Test:',self.studio.page(first['name'])['body'])
        self.studio.assign_series(first['name'],'')
        page=self.studio.page(first['name'])
        self.assertIsNone(page['series'])
        self.assertEqual(BeautifulSoup(page['body'],'html.parser').h1.get_text(strip=True),'One')
        self.assertNotIn('series-test-series.html',page['body'])
        self.assertNotIn('Next Test:',page['body'])

    def test_membership_update_preserves_authored_series_page_introduction(self):
        self.studio.create('One: Test Series')
        second=self.studio.create('Another post')
        self.studio.create_series('Test Series','Test','Original description.')
        series_page=self.studio.page('series-test-series.html')
        series_page['raw']=series_page['raw'].replace('Original description.','My carefully edited introduction.')
        self.studio.save_draft(series_page)
        original_base=self.studio.state['drafts']['series-test-series.html']['base']
        self.studio.assign_series(second['name'],'test-series','Chapter 2')
        updated=self.studio.page('series-test-series.html')
        self.assertIn('My carefully edited introduction.',updated['body'])
        self.assertIn(second['name'],updated['body'])
        self.assertEqual(self.studio.state['drafts']['series-test-series.html']['base'],original_base)

    def test_discard_reconciles_index_and_next_link(self):
        first=self.studio.create('One: Test Series')
        second=self.studio.create('Two: Test Series')
        third=self.studio.create('Three: Test Series')
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.assign_series(first['name'],'test-series','Chapter 1')
        self.studio.assign_series(second['name'],'test-series','Chapter 2')
        self.studio.assign_series(third['name'],'test-series','Chapter 3')
        self.studio.delete_post(second['name'])
        self.assertNotIn(second['name'],self.studio.page('series-test-series.html')['body'])
        first_body=self.studio.page(first['name'])['body']
        self.assertIn(third['name'],first_body);self.assertNotIn(second['name'],first_body)

    def test_series_choice_saves_as_metadata_until_publication_review(self):
        first=self.studio.create('First thought',body='<p>First body.</p><p>—Example Author<br>October 14, 2026</p>')
        second=self.studio.create('Second thought',body='<p>Second body.</p><p>—Example Author<br>October 14, 2026</p>')
        self.studio.create_series('Test Series','Test','Description.')

        page=self.studio.page(first['name'])
        nodes=[str(node) for node in BeautifulSoup(page['body'],'html.parser').contents if str(node).strip()]
        paragraph=next(index for index,node in enumerate(nodes) if node.startswith('<p>'))
        page['fragments']={
            'version':1,
            'blocks':[{'id':f'first-{index}','html':node} for index,node in enumerate(nodes)],
            'dividers':[f'first-{paragraph}'],
            'ranges':[{'key':'thought','start':f'first-{paragraph}','end':f'first-{paragraph+1}'}],
        }
        page['series_id']='test-series'
        page['series_attribute']='Chapter 1'
        self.studio.save_draft(page)

        second_page=self.studio.page(second['name'])
        second_page['series_id']='test-series'
        second_page['series_attribute']='Chapter 2'
        self.studio.save_draft(second_page)

        self.assertNotIn('blynger-series-title',self.studio.page(first['name'])['body'])
        self.assertEqual(self.studio.state['series_pending'],['test-series'])

        self.studio.prepare(review=False)

        prepared=self.studio.page(first['name'])
        self.assertIn('blynger-series-title',prepared['body'])
        self.assertIn('blynger-series-next',prepared['body'])
        self.assertEqual(prepared['fragments']['ranges'][0]['start'],f'first-{paragraph}')
        self.assertIsNotNone(prepared['fragments']['ranges'][0]['end'])
        self.assertEqual(self.studio.state['series_pending'],[])
        index=self.studio.page('series-test-series.html')['body']
        self.assertIn('Chapter 1',index)
        self.assertIn('Chapter 2',index)

    def test_review_repairs_saved_membership_when_pending_marker_was_lost(self):
        post=self.studio.create('A thought',body='<p>Body.</p>')
        (self.root/post['name']).write_text(self.studio.state['drafts'][post['name']]['raw'])
        self.studio.create_series('Test Series','Test','Description.')
        self.studio.save_series_choice(post['name'],'test-series','Chapter 1')
        self.studio.state['series_pending']=[]
        self.studio.state['drafts'].pop(post['name'],None)
        self.studio.save_state()

        self.assertNotIn('blynger-series-title',self.studio.page(post['name'])['body'])
        self.studio.prepare(review=False)

        repaired=self.studio.page(post['name'])
        self.assertIn('blynger-series-title',repaired['body'])
        self.assertIn('Test Series',repaired['body'])

    def test_editor_saves_series_without_a_separate_update_action(self):
        source=(Path(__file__).parent/'static/app.js').read_text()
        markup=(Path(__file__).parent/'static/index.html').read_text()
        self.assertIn("series_id: $('postSeries').value || null",source)
        self.assertIn("$('postSeries').onchange",source)
        self.assertNotIn('updateSeries',source)
        self.assertNotIn('Update series',markup)


if __name__=='__main__':
    unittest.main()

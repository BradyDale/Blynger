import json,subprocess,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
from app import generate
from core import STYLE
from tk_render import render_tk
import test_core as fixtures

URL='https://example.com/article?one=1&two=2'
PROSE='Read [the source]('+URL+').\n\nAlso see https://example.org/research.\n\n`[literal](https://example.net)`'

class TKLinkTests(unittest.TestCase):
    setUp=fixtures.StudioTests.setUp
    tearDown=fixtures.StudioTests.tearDown
    def test_links_safe_and_code_literal(self):
        soup=BeautifulSoup(render_tk(PROSE),'html.parser')
        self.assertEqual(soup.find('a',string='the source')['href'],URL)
        self.assertIsNotNone(soup.find('a',href='https://example.org/research'))
        self.assertIsNone(soup.code.find('a'))
        hostile=BeautifulSoup(render_tk('[bad](javascript:alert) <script>alert(1)</script> <img src=x onerror=alert(1)>'),'html.parser')
        self.assertIsNone(hostile.find('script'));self.assertIsNone(hostile.find('img'))
        self.assertFalse(any(a.get('href','').startswith('javascript:') for a in hostile.find_all('a')))
    def test_generated_link_survives_test_post_publication(self):
        def fake_codex(args,**kwargs):
            Path(args[args.index('-o')+1]).write_text(PROSE)
            return SimpleNamespace(returncode=0,stderr='')
        with patch('app.subprocess.run',side_effect=fake_codex):
            result=generate(self.studio,'Include a source link.','','1.html')
        self.assertEqual(BeautifulSoup(result['html'],'html.parser').find('a',string='the source')['href'],URL)
        d=self.studio.create('TK link regression test')
        d['raw']=d['raw'].replace('<p>Start writing here.</p>',result['html'])
        d['generated']=[result['provenance']];self.studio.save_draft(d)
        reopened=self.studio.page(d['name']);self.assertIn('<a href=',reopened['body'])
        remote=self.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        self.studio.git('remote','add','website',str(remote))
        review=self.studio.prepare();self.studio.publish(review['signature'],'Test TK links')
        published=self.studio.git('show','HEAD:'+d['name'])
        soup=BeautifulSoup(published,'html.parser');self.assertEqual(soup.select_one('.blyg-tk-gen a')['href'],URL)
        style=soup.find('style',id='blynger-generation-style')
        self.assertIn('border:1px dashed',style.string);self.assertIn('data:image/svg+xml',style.string)
        self.assertNotIn('[the source](',soup.article.get_text())
        iid=self.studio.state['ids'][d['name']];doc=json.loads((self.root/'blyg/items'/f'{iid}.json').read_text())
        self.assertEqual(BeautifulSoup(doc['content_html'],'html.parser').find('a',string='the source')['href'],URL)
        descriptions=[e.text for e in ET.parse(self.root/'blyg/feed.xml').findall('./channel/item/description')]
        self.assertTrue(any(BeautifulSoup(t,'html.parser').find('a',string='the source') for t in descriptions))
    def test_tk_is_rejected_outside_posts(self):
        ordinary=self.studio.create_page('Ordinary page','ordinary.html')
        for name in ('index.html','openers.html',ordinary['name']):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'only while editing a post'):
                generate(self.studio,'Write something.','Context',name)
        with self.assertRaisesRegex(ValueError,'only while editing a post'):
            generate(self.studio,'Write something.','Context',None)
    def test_existing_tk_style_is_forward_only(self):
        old='<style id="blynger-generation-style">.blyg-tk-gen{background:#eee}</style>'
        d=self.studio.page('1.html')
        d['raw']=d['raw'].replace(STYLE,old).replace('Original','<div class="blyg-tk-gen"><p>Earlier generated text.</p></div>')
        self.studio.save_draft(d);self.studio.prepare()
        published=(self.root/'1.html').read_text()
        self.assertIn(old,published);self.assertNotIn('data:image/svg+xml',published)
    def test_public_robot_discloses_without_changing_protocol_content(self):
        provenance={'sources':[{'id':'0'*25+'1'}],'model':'test-model','at':'2026-10-05T12:00:00Z'}
        d=self.studio.create('Disclosing robot');d['raw']=d['raw'].replace('<p>Start writing here.</p>','<div class="blyg-tk-gen"><p>Generated words.</p></div>');d['generated']=[provenance];d['pin_on_publish']=True;self.studio.save_draft(d)
        self.studio.prepare();page=(self.root/d['name']).read_text();soup=BeautifulSoup(page,'html.parser');iid=self.studio.state['ids'][d['name']];doc=json.loads((self.root/f'blyg/items/{iid}.json').read_text())
        self.assertEqual(json.loads(soup.article['data-generated']),[provenance]);self.assertIsNotNone(soup.find('style',id='blynger-generation-disclosure-style'));self.assertIsNotNone(soup.find('script',id='blynger-generation-disclosure-script'))
        self.assertNotIn('data-generated',doc['content_html']);self.assertNotIn('blynger-gen-badge',doc['content_html']);self.assertEqual(doc['generated'],[provenance])
        frozen=BeautifulSoup((self.root/f'blyg/f/{iid}/v1/index.html').read_text(),'html.parser');self.assertEqual(json.loads(frozen.article['data-generated']),[provenance]);self.assertIsNotNone(frozen.find('script',id='blynger-generation-disclosure-script'))
        first=page;self.studio.prepare();self.assertEqual((self.root/d['name']).read_text(),first)
    def test_disclosure_script_labels_claim_and_quoted_author(self):
        from generation_disclosure import SCRIPT
        self.assertIn('Self-reported, not verified.',SCRIPT);self.assertIn('quoted author marked this text',SCRIPT);self.assertIn("e.key==='Escape'",SCRIPT)

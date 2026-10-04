import json,re,tempfile,unittest
from pathlib import Path
from bs4 import BeautifulSoup
from PIL import Image
from metadata import enrich,sitemap
class MetadataTests(unittest.TestCase):
 def test_preserves_body_and_corrects_social_metadata(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'images').mkdir();Image.new('RGB',(400,400)).save(root/'images/self400.jpg')
   raw='<html><head><title>Wrong</title><meta property="og:url" content="http://wrong.example/"><meta name="twitter:description" content="en_US"></head><body><article><h1>Right &amp; true</h1><p>A sufficiently long opening paragraph for this test description.</p><p>—Example Author<br>March 2, 2022</p></article></body></html>'
   out=enrich(raw,'42.html',root); soup=BeautifulSoup(out,'html.parser')
   self.assertEqual(raw[raw.index('<body>'):],out[out.index('<body>'):])
   self.assertEqual(soup.find('meta',property='og:url')['content'],'https://example.com/42.html')
   self.assertEqual(soup.find('meta',property='og:type')['content'],'article')
   self.assertEqual(soup.find('meta',property='article:published_time')['content'],'2022-03-02')
   self.assertEqual(soup.find('meta',attrs={'name':'blyg:protocol-version'})['content'],__import__('version').BLYG_VERSION)
   self.assertEqual(soup.find('link',rel='blyg')['href'],'/blyg/')
   self.assertEqual(soup.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml');self.assertEqual(soup.find('link',rel='alternate',type='application/rss+xml')['title'],"Example Author's blyg")
   self.assertEqual(enrich(out,'42.html',root),out)
   data=json.loads(soup.find('script',type='application/ld+json').string);self.assertEqual(data['@type'],'BlogPosting')
 def test_new_date_retained_after_later_edit(self):
  raw='<html><head><title>Post</title></head><body><article><h1>Post</h1><p>Some words</p></article></body></html>'
  one=enrich(raw,'43.html',Path('/tmp'),published='2026-09-26T08:00:00Z')
  two=enrich(one,'43.html',Path('/tmp'),published='2027-01-01',modified='2026-09-27T08:00:00Z')
  soup=BeautifulSoup(two,'html.parser');self.assertEqual(soup.find('meta',property='article:published_time')['content'],'2026-09-26T08:00:00Z')
 def test_existing_generator_version_does_not_churn_on_app_upgrade(self):
  raw='<html><head><title>Post</title><meta name="generator" content="Blynger 0.2.0"></head><body><article><h1>Post</h1><p>Some sufficiently long words for an automatic description.</p></article></body></html>'
  updated=enrich(raw,'1.html',Path('/tmp'))
  self.assertIn('<meta name="generator" content="Blynger 0.2.0">',updated)
 def test_quote_attribution_does_not_become_description(self):
  raw='<html><head><title>Quote</title></head><body><article><h1>Quote</h1><blockquote class="blynger-citation"><p class="blynger-quote-author">by Someone · quoted from v1</p><p>A sufficiently long quotation from someone else.</p></blockquote><p>My own sufficiently long response should describe this page.</p></article></body></html>'
  soup=BeautifulSoup(enrich(raw,'47.html',Path('/tmp')),'html.parser')
  self.assertEqual(soup.find('meta',attrs={'name':'description'})['content'],'My own sufficiently long response should describe this page.')
 def test_removes_legacy_open_graph_tag_with_typographic_quotes(self):
  raw='<html><head><meta property=”og:description” content=”Obsolete description.”><title>Post</title></head><body><article><h1>Post</h1><p>A sufficiently long opening paragraph for the current description.</p></article></body></html>'
  out=enrich(raw,'1.html',Path('/tmp'))
  self.assertNotIn('property=”og:description”',out)
  self.assertEqual(BeautifulSoup(out,'html.parser').find('meta',property='og:description')['content'],'A sufficiently long opening paragraph for the current description.')
 def test_home_canonical_and_sitemap(self):
  raw='<html><head></head><body><h1>Home</h1></body></html>';s=BeautifulSoup(enrich(raw,'index.html',Path('/tmp')),'html.parser')
  self.assertEqual(s.find('link',rel='canonical')['href'],'https://example.com/')
  self.assertEqual(s.find('link',rel='blyg')['href'],'/blyg/');self.assertEqual(s.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml')
  self.assertIsNone(s.find('meta',attrs={'name':'blyg:protocol-version'}))
  self.assertIn(b'https://example.com/43.html',sitemap(['43.html','index.html']))
 def test_site_furniture_has_rss_but_not_blyg_identity_or_discovery(self):
  raw='<html><head><title>Portfolio</title><link rel="blyg" href="https://wrong.example/blyg/"></head><body><article><h1>Portfolio</h1><p>An ordinary site page.</p></article></body></html>'
  soup=BeautifulSoup(enrich(raw,'portfolio.html',Path('/tmp'),blyg_item=False,blyg_discovery=False,rss_discovery=True),'html.parser')
  self.assertIsNone(soup.find('link',rel='blyg'));self.assertIsNone(soup.find('meta',attrs={'name':'blyg:protocol-version'}));self.assertEqual(soup.find('link',rel='alternate',type='application/rss+xml')['href'],'/feed.xml')
 def test_standalone_page_has_web_metadata_without_blyg_identity(self):
  raw='<html><head><title>Archive</title></head><body><article><h1>Archive</h1><p>An ordinary archive page with enough description text.</p></article></body></html>'
  soup=BeautifulSoup(enrich(raw,'archive.html',Path('/tmp'),standalone=True),'html.parser')
  self.assertEqual(soup.find('meta',property='og:type')['content'],'website')
  self.assertEqual(json.loads(soup.find('script',type='application/ld+json').string)['@type'],'WebPage')
  self.assertIsNone(soup.find('meta',attrs={'name':'blyg:protocol-version'}));self.assertIsNone(soup.find('link',rel='blyg'))
  self.assertIsNone(soup.find('meta',property='article:published_time'))

 def test_item_json_alternate_is_managed_without_duplication(self):
  raw='<html><head><title>Post</title></head><body><article><h1>Post</h1><p>Enough words for a useful description on this post.</p></article></body></html>'
  url='https://example.com/blyg/items/00000000000000000000000000.json'
  once=enrich(raw,'1.html',Path('/tmp'),item_json=url);twice=enrich(once,'1.html',Path('/tmp'),item_json=url)
  self.assertEqual(once,twice);soup=BeautifulSoup(twice,'html.parser');self.assertEqual(len(soup.find_all('link',rel='alternate',type='application/json')),1);self.assertEqual(len(soup.find_all('link',rel='blyg')),1);self.assertEqual(len(soup.find_all('link',rel='alternate',type='application/rss+xml')),1)

 def test_quote_style_reinsertion_does_not_accumulate_metadata_whitespace(self):
  import re
  from core import QUOTE_STYLE
  raw='<html><head><style>body{color:black}</style></head><body><article><h1>A quote</h1><blockquote class="blyg-transclusion">Words</blockquote></article></body></html>'
  def render(raw):
   raw=re.sub(r'<style id="blynger-quote-style">.*?</style>','',raw,flags=re.S)
   return enrich(raw.replace('</head>',QUOTE_STYLE+'</head>',1),'46.html',Path('/tmp'))
  once=render(raw)
  for _ in range(5):
   again=render(once);self.assertEqual(again,once);once=again

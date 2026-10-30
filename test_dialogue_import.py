import unittest
from pathlib import Path
from bs4 import BeautifulSoup

from dialogue_import import render_dialogue


class DialogueImportTests(unittest.TestCase):
    def test_author_stays_ordinary_and_assistant_gets_tk_treatment(self):
        result=render_dialogue([
            {'role':'author','text':'What comes next?'},
            {'role':'assistant','text':'A useful answer with [a source](example.com/research).'},
            {'role':'assistant','text':'A second paragraph from the same speaker.'},
            {'role':'author','text':'That is interesting.'},
        ])
        soup=BeautifulSoup(result['html'],'html.parser')
        generated=soup.select('.blyg-tk-gen')
        self.assertEqual(len(generated),2)
        self.assertEqual(generated[0].find('a')['href'],'https://example.com/research')
        self.assertIn('What comes next?',soup.find('p').get_text())
        self.assertEqual(len(result['generated']),2)
        self.assertEqual(result['generated'][0]['model'],'ChatGPT import (model not stated)')
        self.assertEqual(result['turns'],4)

    def test_rich_clipboard_markup_is_sanitized_and_cannot_forge_tk(self):
        result=render_dialogue([
            {'role':'author','html':'<div class="blyg-tk-gen" data-generated="fake"><script>bad()</script><b>Brady words</b></div>'},
            {'role':'assistant','html':'<p onclick="bad()">ChatGPT words</p><iframe src="https://bad.example"></iframe>'},
        ],'GPT-6.1 Sol')
        soup=BeautifulSoup(result['html'],'html.parser')
        self.assertEqual(len(soup.select('.blyg-tk-gen')),1)
        self.assertIn('ChatGPT words',soup.select_one('.blyg-tk-gen').get_text())
        self.assertNotIn('Brady words',soup.select_one('.blyg-tk-gen').get_text())
        self.assertIsNone(soup.find('script'));self.assertIsNone(soup.find('iframe'))
        self.assertFalse(any(node.has_attr('onclick') for node in soup.find_all(True)))
        self.assertEqual(result['generated'][0]['model'],'GPT-6.1 Sol')

    def test_model_is_optional_trimmed_and_bounded(self):
        turn=[{'role':'assistant','text':'An answer.'}]
        self.assertEqual(render_dialogue(turn,'  GPT-6 Astra  ')['generated'][0]['model'],'GPT-6 Astra')
        with self.assertRaises(ValueError):render_dialogue(turn,'x'*101)
        with self.assertRaises(ValueError):render_dialogue(turn,{'not':'text'})

    def test_import_dialog_remembers_and_submits_self_reported_model(self):
        script=(Path(__file__).parent/'static/app.js').read_text()
        self.assertIn("localStorage.getItem('blynger-dialogue-model')",script)
        self.assertIn("localStorage.setItem('blynger-dialogue-model', dialogueModel)",script)
        self.assertIn("api('dialogue-import', { turns, model: dialogueModel })",script)
        self.assertIn("api('dialogue-share', { url: shareURL })",script)
        self.assertIn('Model used (self-reported)',script)

    def test_invalid_dialogue_is_rejected(self):
        for value in (None,[],[{'role':'robot','text':'No'}],[{'role':'author'}]):
            with self.subTest(value=value),self.assertRaises(ValueError):render_dialogue(value)


if __name__=='__main__':unittest.main()

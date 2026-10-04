import copy, json, os, stat, tempfile, unittest
from pathlib import Path
from bs4 import BeautifulSoup
from configuration import APP_ROOT, DEFAULT_SETTINGS, load, public_view, save, update_from_public, validate
from core import Studio

class ConfigurationTests(unittest.TestCase):
    def test_private_data_cannot_be_kept_inside_application_source(self):
        cfg=copy.deepcopy(DEFAULT_SETTINGS)
        cfg.update(site_root='/site',data_root=str(APP_ROOT/'private-data'))
        with self.assertRaisesRegex(ValueError,'outside the application folder'):
            validate(cfg)

    def test_private_text_settings_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);site=root/'site';data=root/'private';site.mkdir()
            cfg=copy.deepcopy(DEFAULT_SETTINGS);cfg.update(site_root=str(site),data_root=str(data),site_url='https://writer.example/',site_label='writer.example',author_name='A Writer',author_signature='—A Writer',blyg_title="A Writer's blyg")
            path=root/'settings.json';save(cfg,path);reloaded=load(path)
            self.assertEqual(reloaded['author_name'],'A Writer')
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
            self.assertNotIn('private key contents',path.read_text())

    def test_custom_identity_drives_new_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);site=root/'site';data=root/'private';site.mkdir();(site/'images').mkdir()
            cfg=copy.deepcopy(DEFAULT_SETTINGS);cfg.update(site_root=str(site),data_root=str(data),site_url='https://writer.example/',site_label='writer.example',author_name='A Writer',author_signature='—A Writer',blyg_title="A Writer's blyg",feed_description='Notes by A Writer',local_hostnames=['writer.example'])
            (site/'index.html').write_text('<html><head></head><body><h1>Home</h1><h2>Posts</h2></body></html>')
            (site/'openers.html').write_text('<html><head></head><body><article><h1>Openers</h1></article></body></html>')
            import subprocess
            subprocess.run(['git','init','-b','master'],cwd=site,capture_output=True,check=True)
            for key,value in [('user.name','Test'),('user.email','test@example.invalid')]:subprocess.run(['git','config',key,value],cwd=site,check=True)
            subprocess.run(['git','add','.'],cwd=site,check=True);subprocess.run(['git','commit','-qm','Initial'],cwd=site,check=True)
            studio=Studio(site,data,cfg);draft=studio.create('Configured');self.assertIn('—A Writer',draft['raw']);studio.prepare()
            manifest=json.loads((site/'blyg/blyg.json').read_text());self.assertEqual(manifest['author']['name'],'A Writer');self.assertEqual(manifest['title'],"A Writer's blyg")
            self.assertEqual(BeautifulSoup((site/draft['name']).read_text(),'html.parser').find('link',rel='canonical')['href'],'https://writer.example/'+draft['name'])

    def test_settings_screen_view_never_contains_key_material(self):
        cfg=copy.deepcopy(DEFAULT_SETTINGS);cfg.update(site_root='/site',data_root='/private')
        cfg['publishing']['ssh_key']='/keys/id_example'
        view=public_view(update_from_public(cfg,{'author_name':'Someone'}))
        self.assertEqual(view['ssh_key'],'/keys/id_example');self.assertNotIn('private_key',view)

if __name__=='__main__':unittest.main()

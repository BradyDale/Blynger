"""Four quotation modes in a disposable site, entirely offline fixtures."""
import secrets,threading,subprocess
from pathlib import Path
from test_core import StudioTests
from test_selections import seeded
from app import Handler,ThreadingHTTPServer
f=StudioTests();f.setUp();remote=f.base/'remote.git';subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
f.studio.git('remote','add','website',str(remote));f.studio.git('push','website','master');f.studio.migrate_openers();review=f.studio.prepare();f.studio.publish(review['signature']);seeded(f.studio)
class TestHandler(Handler):
    def do_GET(self):
        if self.path=='/selection-tests':return self.send(Path(__file__).with_name('test_selection_browser.html').read_text(),mime='text/html; charset=utf-8')
        super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',18766),TestHandler);server.studio=f.studio;server.token=secrets.token_urlsafe(32);server.lock=threading.RLock()
print('http://127.0.0.1:18766/selection-tests',flush=True)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close();f.tearDown()

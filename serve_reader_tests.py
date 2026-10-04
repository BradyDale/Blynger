"""Isolated UI verification with a disposable site and local bare Git remote."""
import secrets,threading
from pathlib import Path

def main():
    from test_core import StudioTests
    from app import Handler,ThreadingHTTPServer
    import subprocess
    f=StudioTests();f.setUp();remote=f.base/'remote.git'
    subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
    f.studio.git('remote','add','website',str(remote));f.studio.git('push','website','master')
    f.studio.migrate_openers();review=f.studio.prepare();f.studio.publish(review['signature'])
    class TestHandler(Handler):
        def do_GET(self):
            if self.path=='/reader-tests':return self.send(Path(__file__).with_name('test_reader_browser.html').read_text(),mime='text/html; charset=utf-8')
            super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',18766),TestHandler);server.studio=f.studio;server.token=secrets.token_urlsafe(32);server.lock=threading.RLock()
    print('Disposable reader tests: http://127.0.0.1:18766/reader-tests',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();f.tearDown()
if __name__=='__main__':main()

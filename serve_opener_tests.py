"""Disposable browser fixture; never connects to the production Git remote."""
from pathlib import Path
import argparse, secrets, threading

def main():
    from test_openers import OpenerTests
    from app import Handler, ThreadingHTTPServer
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=18766)
    parser.add_argument('--openers',type=Path,help='Optional archive HTML to copy into the disposable fixture')
    args=parser.parse_args()
    fixture=OpenerTests();fixture.setUp();fixture.seed();fixture.connect()
    if args.openers: (fixture.root/'openers.html').write_bytes(args.openers.read_bytes())
    fixture.studio.migrate_openers()
    class TestHandler(Handler):
        def do_GET(self):
            if self.path=='/opener-tests':
                return self.send(Path(__file__).with_name('test_openers_browser.html').read_text(),mime='text/html; charset=utf-8')
            super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),TestHandler)
    server.studio=fixture.studio;server.token=secrets.token_urlsafe(32);server.lock=threading.RLock();server.reader_lock=threading.RLock()
    print(f'Open http://127.0.0.1:{args.port}/opener-tests. All writes use {fixture.root}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();fixture.tearDown()

if __name__=='__main__':main()

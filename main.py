"""Small local application, with no remote service."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import secrets
import threading
import webbrowser
import urllib.request
from bot import Controller

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Idleon Gaming — local application')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    if args.port:
        try:
            with urllib.request.urlopen(url+'/api/state', timeout=.5) as response:
                existing = json.load(response)
            if existing.get('app') == 'idleon-gaming':
                print(f'Application already running: {url}', flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
    controller = Controller()
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, content_type='application/json; charset=utf-8'):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == '/':
                body = (ROOT / 'ui.html').read_text(encoding='utf-8').replace('__TOKEN__', token)
                self.send(200, body.encode('utf-8'), 'text/html; charset=utf-8')
            elif self.path == '/api/state':
                self.send(200, json.dumps(dict(app='idleon-gaming', **controller.state()),
                                          ensure_ascii=False).encode('utf-8'))
            else:
                self.send(404, b'{}')

        def do_POST(self):
            if self.headers.get('X-App-Token') != token:
                self.send(403, b'{}')
                return
            if self.path == '/api/start':
                controller.start()
            elif self.path == '/api/stop':
                controller.stop_event.set()
            elif self.path == '/api/quit':
                controller.stop_event.set()
                threading.Thread(target=server.shutdown, daemon=True).start()
            else:
                self.send(404, b'{}')
                return
            self.send(200, b'{}')

    with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'Idleon Gaming : {url}\nF8: stop the bot. Ctrl+C: close the server.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            controller.stop_event.set()
            if controller.thread:
                controller.thread.join(timeout=3)


if __name__ == '__main__':
    main()

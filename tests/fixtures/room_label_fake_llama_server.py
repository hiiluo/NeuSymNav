"""Local subprocess fixture for the llama.cpp HTTP contract; never loads a model."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys
import time


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_error(404)

    def do_POST(self):
        mode = os.environ.get('ROOM_SLM_TEST_MODE', 'valid')
        size = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(size) or b'{}')
        if self.path == '/tokenize':
            if mode == 'timeout':
                time.sleep(2)
            response = {'tokens':list(range(16))}
            self._json(200, response)
            return
        if self.path == '/v1/chat/completions':
            if mode == 'inspect_grammar' and (
                    not isinstance(body.get('grammar'), str)
                    or 'root ::=' not in body['grammar']
                    or 'response_format' in body or 'json_schema' in body
                    or body.get('cache_prompt') is not False
                    or body.get('chat_template_kwargs') != {'enable_thinking': False}):
                self.send_error(400, 'invalid grammar transport'); return
            if mode == 'grammar_unsupported':
                self.send_error(400, 'json_schema unsupported'); return
            if mode == 'oversized':
                content = '{"bad":"' + 'x' * (17*1024) + '"}'
            elif 'Objects in this room:\n' in body['messages'][0]['content']:
                content = 'bathroom||1'
            else:
                content = json.dumps({'label':'bathroom','alternatives':[],
                    'supporting_object_ids':['O(0)'],'status':'proposed',
                    'reason':'toilet anchor'})
            self._json(200, {'choices':[{'message':{'content':content},
                'finish_reason':'length' if mode == 'finish_length' else 'stop'}],
                'timings':{'cache_n':0,'prompt_n':16,'prompt_ms':2,'predicted_n':5,'predicted_ms':3},
                'usage':{'prompt_tokens':16,'completion_tokens':5,'total_tokens':21}})
            return
        self.send_error(404)

    def _json(self, code, value):
        raw = json.dumps(value).encode()
        self.send_response(code); self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)


if __name__ == '__main__':
    if os.environ.get('ROOM_SLM_TEST_MODE') == 'crash':
        raise SystemExit(17)
    port = int(sys.argv[sys.argv.index('--port') + 1])
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()

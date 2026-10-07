"""Agent Hub (lf-connect): one-command agent onboarding for any agent / app / repo.

GET  /            agent guide (markdown). With ?t=<enroll token> the commands come pre-filled.
GET  /install.sh  POSIX installer      GET /install.ps1  PowerShell installer      GET /health
POST /v1/enroll   {"name": "<agent>"}  (Authorization: Bearer <ENROLL_TOKEN>)  [?format=env]
  -> own Langfuse project in org $LANGFUSE_ORG (reused if the name exists) + fresh API key
  -> LLM-as-judge evaluators (MiniMax via LiteLLM) + rating score configs on new projects
  -> LiteLLM virtual key whose traffic is logged into that project
Secrets come from env (root-only env_file); logs carry names/ids only.
"""
import base64, hmac, json, os, re, secrets, threading, time
import http.cookiejar as cookiejar
import urllib.error, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.environ.get('PUBLIC_URL', 'https://hub.example.com')
LF = os.environ.get('LANGFUSE_URL', 'https://langfuse.example.com')
LL = os.environ.get('LITELLM_INTERNAL', 'http://litellm:4000')
LL_PUBLIC = os.environ.get('LLM_PUBLIC_URL', 'https://llm.example.com/v1')
MODEL = os.environ.get('LLM_MODEL', 'MiniMax-M3')
TOKENS = [t for t in os.environ['ENROLL_TOKEN'].split(',') if t]
ADMIN = (os.environ['PLATFORM_ADMIN_EMAIL'], os.environ['PLATFORM_ADMIN_PASSWORD'])
MASTER = os.environ['LITELLM_MASTER_KEY']
JUDGE_KEY = os.environ['JUDGE_LLM_KEY']
SAMPLING = float(os.environ.get('EVAL_SAMPLING', '0.3'))
EVAL_TEMPLATES = os.environ.get('EVAL_TEMPLATES', 'Helpfulness,Relevance,Toxicity,Hallucination').split(',')
STATIC = os.environ.get('STATIC_DIR', os.path.dirname(os.path.abspath(__file__)))
ORG = os.environ.get('LANGFUSE_ORG', 'Main')
KB_URL, SOCIAL_URL = os.environ.get('KB_URL', ''), os.environ.get('SOCIAL_URL', '')
PLANE_API_BASE, PLANE_WS = os.environ.get('PLANE_API_BASE', ''), os.environ.get('PLANE_WORKSPACE_SLUG', '')
KB_TOKEN, PLANE_TOKEN = os.environ.get('KB_TOKEN', ''), os.environ.get('PLANE_API_TOKEN', '')
MEMOS, MEMOS_ADMIN = os.environ.get('MEMOS_INTERNAL', 'http://memos:5230') + '/api/v1', os.environ.get('MEMOS_ADMIN_TOKEN', '')
LOCK = threading.Lock()
HUB_MARK = 'AI agent · managed by agent hub'  # Memos users the hub may rotate carry this description
REGISTRY = os.environ.get('REGISTRY_FILE', '/data/registry.json')  # Langfuse projects created by the hub
IN_VARS = {'input', 'query', 'question', 'user_query', 'prompt'}
OUT_VARS = {'output', 'generation', 'response', 'answer', 'completion'}


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def http(method, url, body=None, headers=None, opener=None, form=False):
    h = {'User-Agent': 'curl/8.9.1'}
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        h['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with (opener.open if opener else urllib.request.urlopen)(req, timeout=90) as f:
            raw, st = f.read(), f.status
    except urllib.error.HTTPError as e:
        raw, st = e.read(), e.code
    except Exception as e:
        return 0, str(e)
    try:
        return st, json.loads(raw)
    except Exception:
        return st, raw.decode(errors='replace')


def basic(pk, sk):
    return 'Basic ' + base64.b64encode(f'{pk}:{sk}'.encode()).decode()


class Langfuse:
    """Admin UI session (tRPC) - project/key/evaluator creation has no public API in OSS."""

    def __init__(self):
        self.op = None

    def login(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.CookieJar()))
        _, b = http('GET', LF + '/api/auth/csrf', opener=self.op)
        http('POST', LF + '/api/auth/callback/credentials',
             {'email': ADMIN[0], 'password': ADMIN[1], 'csrfToken': b.get('csrfToken'), 'json': 'true',
              'callbackUrl': LF + '/'}, opener=self.op, form=True)
        if not self.session():
            raise RuntimeError('langfuse admin login failed')

    def session(self):
        st, s = http('GET', LF + '/api/auth/session', opener=self.op)
        return (s or {}).get('user') if st == 200 and isinstance(s, dict) else None

    def trpc(self, proc, inp, query=False, retry=True):
        if self.op is None:
            self.login()
        if query:
            st, b = http('GET', LF + '/api/trpc/' + proc + '?input=' + urllib.parse.quote(json.dumps({'json': inp})),
                         opener=self.op)
        else:
            st, b = http('POST', LF + '/api/trpc/' + proc, {'json': inp}, opener=self.op)
        if st == 401 and retry:
            self.login()
            return self.trpc(proc, inp, query, False)
        if st != 200 or not isinstance(b, dict):
            raise RuntimeError(f'{proc}: {st} {str(b)[:300]}')
        return b['result']['data']['json']


LFS = Langfuse()


def org_and_project(name):
    if LFS.op is None:
        LFS.login()
    orgs = (LFS.session() or {}).get('organizations', [])
    org = next((o for o in orgs if o.get('name') == ORG), None)
    if not org:
        raise RuntimeError(f'org {ORG} not found')
    proj = next((p for p in org.get('projects', []) if p.get('name') == name), None)
    return org['id'], proj and proj['id']


def setup_evals(pid, pk, sk):
    """Judge connection + default eval model + LLM-as-judge evaluators + rating configs (new projects)."""
    done = []
    try:
        LFS.trpc('llmApiKey.create', {'projectId': pid, 'provider': 'litellm', 'adapter': 'openai',
                                      'baseURL': LL_PUBLIC, 'withDefaultModels': False,
                                      'customModels': [MODEL], 'secretKey': JUDGE_KEY})
        done.append('llm-connection')
    except RuntimeError as e:
        log('  llm connection:', str(e)[:200])
    have = {c.get('scoreName') for c in LFS.trpc('evals.jobConfigsByTarget', {'projectId': pid, 'targetObject': 'trace'}, query=True)}
    tpl = LFS.trpc('evals.allTemplates', {'projectId': pid, 'page': 0, 'limit': 200}, query=True)
    tpls = tpl.get('templates', tpl) if isinstance(tpl, dict) else tpl
    for want in EVAL_TEMPLATES:
        if want.lower() in have:
            continue
        t = max((t for t in tpls if t.get('name') == want), key=lambda t: t.get('version', 0), default=None)
        if not t:
            log('  template missing:', want)
            continue
        mapping = []
        for v in t.get('vars', []):
            col = 'input' if v in IN_VARS else 'output' if v in OUT_VARS else None
            if not col:
                mapping = None
                break
            mapping.append({'templateVariable': v, 'langfuseObject': 'trace', 'selectedColumnId': col})
        if not mapping:
            log('  template skipped (unmappable vars):', want, t.get('vars'))
            continue
        LFS.trpc('evals.createJob', {'projectId': pid, 'evalTemplateId': t['id'], 'scoreName': want.lower(),
                                     'target': 'trace', 'filter': [], 'mapping': mapping, 'sampling': SAMPLING,
                                     'delay': 30000, 'timeScope': ['NEW']})
        done.append('eval:' + want.lower())
    st, b = http('GET', LF + '/api/public/score-configs?limit=100', headers={'Authorization': basic(pk, sk)})
    existing = {c['name'] for c in (b.get('data', []) if isinstance(b, dict) else [])}
    for cfg in ({'name': 'user_rating', 'dataType': 'NUMERIC', 'minValue': 1, 'maxValue': 5,
                 'description': 'End-user rating 1-5'},
                {'name': 'thumbs', 'dataType': 'BOOLEAN', 'description': 'End-user thumbs up (1) / down (0)'},
                {'name': 'agent_self_check', 'dataType': 'NUMERIC', 'minValue': 0, 'maxValue': 1,
                 'description': 'Agent self-evaluation 0-1 (did the task succeed?)'}):
        if cfg['name'] in existing:
            continue
        st, b = http('POST', LF + '/api/public/score-configs', cfg, {'Authorization': basic(pk, sk)})
        done.append(f"score-config:{cfg['name']}:{st}")
    # last: its presence marks the project as configured (see enroll)
    for i in range(4):  # Langfuse test-calls the judge first; MiniMax occasionally misses the schema
        try:
            LFS.trpc('defaultLlmModel.upsertDefaultModel',
                     {'projectId': pid, 'provider': 'litellm', 'adapter': 'openai', 'model': MODEL,
                      'modelParams': {'temperature': 0, 'max_tokens': 4096}})
            break
        except RuntimeError as e:
            if i == 3 or 'not valid for evaluation' not in str(e):
                raise
            log('  default eval model check failed, retry', i + 1)
    done.append('default-eval-model')
    return done


def litellm_key(slug, name, pk, sk):
    meta = {'agent': slug, 'langfuse_project': name, 'created_by': 'lf-connect',
            'logging': [{'callback_name': 'langfuse', 'callback_type': 'success_and_failure',
                         'callback_vars': {'langfuse_public_key': pk, 'langfuse_secret_key': sk,
                                           'langfuse_host': LF}}]}
    H = {'Authorization': 'Bearer ' + MASTER}
    alias = 'agent-' + slug
    for _ in range(3):
        st, b = http('POST', LL + '/key/generate', {'key_alias': alias, 'metadata': meta, 'rpm_limit': 120}, H)
        if st == 200 and isinstance(b, dict) and b.get('key'):
            return b['key']
        alias = 'agent-' + slug + '-' + secrets.token_hex(2)
    raise RuntimeError(f'litellm key: {st} {str(b)[:200]}')


def registry():
    try:
        return set(json.load(open(REGISTRY, encoding='utf-8')))
    except FileNotFoundError:
        seed = {n for n in os.environ.get('REGISTRY_SEED', '').split(',') if n}
        save_registry(seed)
        for n in seed if MEMOS_ADMIN else ():  # adopt social accounts the hub created before markers existed
            A = {'Authorization': 'Bearer ' + MEMOS_ADMIN}
            st, u = http('GET', f'{MEMOS}/users/{n}', headers=A)
            if st == 200 and u.get('role') == 'USER' and HUB_MARK not in (u.get('description') or ''):
                http('PATCH', f'{MEMOS}/users/{n}?updateMask=description', {'name': 'users/' + n, 'description': HUB_MARK}, A)
        log('registry seeded:', len(seed), 'names')
        return seed


def save_registry(names):
    os.makedirs(os.path.dirname(REGISTRY), exist_ok=True)
    tmp = REGISTRY + '.tmp'
    json.dump(sorted(names), open(tmp, 'w', encoding='utf-8'))
    os.replace(tmp, REGISTRY)


def social_account(name):
    """Memos user for the agent (created or password-rotated) + a fresh personal access token."""
    A = {'Authorization': 'Bearer ' + MEMOS_ADMIN}
    pw = secrets.token_urlsafe(24)
    st, u = http('GET', f'{MEMOS}/users/{name}', headers=A)
    if st == 200:
        if not isinstance(u, dict) or u.get('role') != 'USER' or HUB_MARK not in (u.get('description') or ''):
            raise PermissionError('social account exists and is not hub-managed')
        st, b = http('PATCH', f'{MEMOS}/users/{name}?updateMask=password', {'name': 'users/' + name, 'password': pw}, A)
    else:
        st, b = http('POST', f'{MEMOS}/users?userId={name}', {'role': 'USER', 'username': name, 'displayName': name,
                                                              'description': HUB_MARK, 'password': pw, 'state': 'NORMAL'}, A)
    if st != 200:
        raise RuntimeError(f'memos user: {st} {str(b)[:200]}')
    st, b = http('POST', MEMOS + '/auth/signin', {'passwordCredentials': {'username': name, 'password': pw}})
    if st != 200:
        raise RuntimeError(f'memos signin: {st} {str(b)[:200]}')
    st, b = http('POST', f'{MEMOS}/users/{name}/personalAccessTokens', {'description': 'agent hub ' + time.strftime('%Y-%m-%d')},
                 {'Authorization': 'Bearer ' + b['accessToken']})
    if st != 200:
        raise RuntimeError(f'memos token: {st} {str(b)[:200]}')
    return b['token']


def enroll(raw_name, repair=False):
    name = re.sub(r'[^a-z0-9-]+', '-', raw_name.lower()).strip('-')[:36].strip('-')  # memos max 36
    if len(name) < 2:
        raise ValueError('name must have at least 2 letters/digits')
    with LOCK:
        org_id, pid = org_and_project(name)
        new = not pid
        known = registry()
        if not new and name not in known:
            raise PermissionError(f'name "{name}" belongs to a project the hub did not create; pick another name')
        if new:
            pid = LFS.trpc('projects.create', {'name': name, 'orgId': org_id})['id']
            save_registry(known | {name})
        k = LFS.trpc('projectApiKeys.create', {'projectId': pid, 'note': 'lf-connect ' + time.strftime('%Y-%m-%d')})
        pk, sk = k['publicKey'], k['secretKey']
        configured = not new and LFS.trpc('defaultLlmModel.fetchDefaultModel', {'projectId': pid}, query=True)
        setup = setup_evals(pid, pk, sk) if repair or not configured else ['existing project: evals unchanged']
        llm = litellm_key(name, name, pk, sk)
        try:
            social = social_account(name)
            setup.append('social-account')
        except (RuntimeError, PermissionError) as e:
            social = ''
            setup.append('social-account FAILED')
            log('  social:', str(e)[:200])
    log('enroll', name, 'new' if new else 'existing', pid, setup)
    return {'LANGFUSE_HOST': LF, 'LANGFUSE_BASE_URL': LF, 'LANGFUSE_PUBLIC_KEY': pk, 'LANGFUSE_SECRET_KEY': sk,
            'LANGFUSE_PROJECT_ID': pid, 'LANGFUSE_PROJECT_NAME': name,
            'OTEL_EXPORTER_OTLP_ENDPOINT': LF + '/api/public/otel',
            'OTEL_EXPORTER_OTLP_HEADERS': 'Authorization=' + basic(pk, sk) + ',x-langfuse-ingestion-version=4',
            'LLM_BASE_URL': LL_PUBLIC, 'LLM_API_KEY': llm, 'LLM_MODEL': MODEL,
            'AGENT_NAME': name, 'AGENT_HUB_URL': BASE,
            'KB_URL': KB_URL, 'KB_TOKEN': KB_TOKEN,
            'PLANE_API_BASE': PLANE_API_BASE, 'PLANE_WORKSPACE_SLUG': PLANE_WS, 'PLANE_API_TOKEN': PLANE_TOKEN,
            'SOCIAL_URL': SOCIAL_URL, 'SOCIAL_USER': name, 'SOCIAL_TOKEN': social}, setup


def page(name, token):
    txt = open(os.path.join(STATIC, 'lf_connect_' + name), encoding='utf-8').read()
    ok = bool(token) and any(hmac.compare_digest(token, t) for t in TOKENS)
    for k, v in {'BASE': BASE, 'LANGFUSE_URL': LF, 'LLM_URL': LL_PUBLIC.rsplit('/v1', 1)[0], 'KB_URL': KB_URL,
                 'PLANE_URL': PLANE_API_BASE.rsplit('/api', 1)[0], 'SOCIAL_URL': SOCIAL_URL}.items():
        txt = txt.replace('{{' + k + '}}', v)
    return txt.replace('{{TOKEN}}', token if ok else '<ENROLL_TOKEN>')


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype='text/plain; charset=utf-8'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        t = (urllib.parse.parse_qs(u.query).get('t') or [''])[0]
        routes = {'/': ('AGENT.md', 'text/markdown; charset=utf-8'), '/AGENT.md': ('AGENT.md', 'text/markdown; charset=utf-8'),
                  '/install.sh': ('install.sh', 'text/x-shellscript; charset=utf-8'),
                  '/install.ps1': ('install.ps1', 'text/plain; charset=utf-8')}
        if u.path == '/health':
            return self.send(200, 'ok')
        if u.path not in routes:
            return self.send(404, 'not found')
        f, ct = routes[u.path]
        self.send(200, page(f, t), ct)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != '/v1/enroll':
            return self.send(404, 'not found')
        tok = self.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        if not tok or not any(hmac.compare_digest(tok, t) for t in TOKENS):
            return self.send(401, 'invalid enroll token')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            q = urllib.parse.parse_qs(u.query)
            env, setup = enroll(str(body.get('name', '')), repair=bool(body.get('repair')))
        except ValueError as e:
            return self.send(400, str(e))
        except PermissionError as e:
            return self.send(409, str(e))
        except Exception as e:
            log('enroll FAILED', str(e)[:300])
            return self.send(502, 'enroll failed: ' + str(e)[:200])
        if (q.get('format') or [''])[0] == 'env':
            out = ['# Langfuse + LLM gateway (lf-connect ' + time.strftime('%Y-%m-%d') + '; setup: ' + ', '.join(setup) + ')']
            out += [f'{k}={v}' for k, v in env.items()]
            return self.send(200, '\n'.join(out) + '\n')
        self.send(200, json.dumps({'env': env, 'setup': setup}), 'application/json')

    def log_message(self, fmt, *a):  # no query strings (may hold the token) in logs
        log(self.command, self.path.split('?')[0], a[1] if len(a) > 1 else '')


if __name__ == '__main__':
    log('lf-connect on :8080')
    ThreadingHTTPServer(('0.0.0.0', 8080), H).serve_forever()

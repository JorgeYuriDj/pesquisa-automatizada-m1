"""Primitivas do juiz dos blocos (controle/blocos.py e controle/fichas.py), congeladas junto com ele.

Cópia fiel das funções de controle/gate.py e controle/handoff.py que o juiz usa. Existem aqui para
que gate.py e handoff.py, que o próprio plano manda mudar (B03-01, B03-02), possam evoluir sem
mexer no juiz e sem exigir um clique do dono a cada commit. Este arquivo fica no congelado.
"""
import hashlib
import json
import base64
import math
import os
from pathlib import Path
import re


class Blocked(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def filehash(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        d = {}
        for k, v in items:
            require(k not in d, 'duplicate_json_key')
            d[k] = v
        return d

    def finite(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite_json')
        return result
    return json.loads(data, object_pairs_hook=pairs, parse_float=finite, parse_constant=lambda x: (_ for _ in ()).throw(Blocked('nonfinite_json')))


# Higiene de nomes: componente ou extensão reservada (mesma expressão de controle/handoff.py).
RESTRICTED = re.compile(r'(^|/|[^a-z])(?:cofre|reservados?|gabaritos?|respostas[ _.-]*reservadas?|answer[ _.-]*keys?)|\.(pkl|pdf|pem|key)(\.|$)', re.I)


# Frozen hygiene checks for outgoing review bytes; not a custody/identity proof.
REVIEW_SECRETS = {
    'google_oauth': re.compile(r'(?<![A-Za-z0-9_-])(?:ya29\.|1//)[A-Za-z0-9_./=-]{20,}'),
    'refresh_token': re.compile(r'(?<![A-Za-z0-9_-])rt_[A-Za-z0-9_-]{20,}'),
    'api_key': re.compile(r"""(?i)(?<![a-z0-9_])["']?api[_-]?key["']?\s*[:=]\s*["']?[A-Za-z0-9_./+=-]{16,}"""),
    'github_token': re.compile(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}'),
    'openai_key': re.compile(r'(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}'),
    'private_key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'google_key': re.compile(r'AIza[0-9A-Za-z_-]{30,}'),
    'aws_key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'slack_token': re.compile(r'xox[abprs]-[A-Za-z0-9-]{10,}'),
    'bearer': re.compile(r'(?i)bearer\s+[A-Za-z0-9._-]{30,}'),
    'password': re.compile(r"""(?i)(?=(?P<key>"(?:password|senha)"|'(?:password|senha)'|(?:password|senha))\s*(?P<operator>[:=])\s*(?P<value>"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|\S+))"""),
}


# Recognize compact token structure without assuming canonical header whitespace.
JWT_HEADER = re.compile(r'(?=(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{4,})\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*)')
def contains_jwt(text):
    for match in JWT_HEADER.finditer(text):
        header=match.group(1)
        if len(header)>16384:
            return True
        try:
            raw=base64.urlsafe_b64decode(header+'='*((-len(header))%4))
            value=json.loads(raw.decode('utf-8'))
        except RecursionError:
            if raw.lstrip().startswith(b'{'):return True
            continue
        except (ValueError,UnicodeError):
            continue
        if type(value) is dict and type(value.get('alg')) is str and value['alg']:
            return True
    return False


def scan_review_secrets(text):
    found = {name for name, pattern in REVIEW_SECRETS.items()
             if name != 'password' and pattern.search(text)}
    if contains_jwt(text):found.add('jwt')
    for match in REVIEW_SECRETS['password'].finditer(text):
        value = match.group('value')
        # A quoted JSON key uses a JSON value boundary. A null/boolean or
        # short number must not absorb a subsequent numeric field. Malformed
        # JSON falls back to the conservative assignment scanner.
        if match.group('key').startswith('"') and match.group('operator') == ':':
            tail=text[match.start('value'):]
            try:
                decoded,end=json.JSONDecoder().raw_decode(tail)
                rest=tail[end:].lstrip()
                if not rest or rest[0] in ',}':
                    if decoded is None or isinstance(decoded,(bool,list,dict)):
                        continue
                    value=str(decoded)
            except ValueError:
                pass
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            if value[0] == '"':
                try:
                    value = json.loads(value)
                except ValueError:
                    value = value[1:-1]
            else:
                value = value[1:-1]
        if len(value) >= 8 and re.search(r'[0-9!@#$%^&*]', value):
            found.add('password')
    return sorted(found)


def git_env():
    """Git nunca pergunta nada: falha rápido em vez de pendurar."""
    return safe_environment()


def write_once(obj, path):
    """Nunca sobrescreve: um registro por arquivo, bytes canônicos, fsync do arquivo e do diretório."""
    path = Path(path)
    with path.open('xb') as f:
        f.write(canonical(obj) + b'\n'); f.flush(); os.fsync(f.fileno())
    d = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(d)
    finally:
        os.close(d)
    return digest(obj)


# Fronteira CL-B04-17: candidato ainda nao promovido.
import stat
import subprocess
from pathlib import Path
MAX_CONFIG=65536
CORE={'core.repositoryformatversion','core.filemode','core.bare','core.logallrefupdates','core.ignorecase','core.precomposeunicode'}
BASE_KEYS=CORE|{'user.name','user.email','remote.origin.url','remote.origin.fetch','commit.gpgsign'}
def need(ok,reason):
 if not ok:raise Blocked(reason)
def protected_path(path,directory=False):
 p=Path(path)
 need(p.is_absolute() and '..' not in p.parts,'protected_path_absolute')
 for ancestor in p.parents:
  info=ancestor.lstat()
  need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and (not info.st_mode&0o022 or bool(info.st_mode&stat.S_ISVTX)),'untrusted_ancestor')
 info=p.lstat()
 need((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) and info.st_uid==0 and not info.st_mode&0o022,'unprotected_object')
 if not directory:need(info.st_nlink==1,'linked_object')
 return info
def safe_environment():
 return {'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_SYSTEM':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_SSH_COMMAND':'/usr/bin/ssh -oBatchMode=yes','GIT_PAGER':'/bin/cat'}
def identity(info):return (info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_gid,info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)

# Git used by the installed validator. Configuration is data, never a command source.
GIT_OPTIONS = {
    'status': {'--porcelain', '-uall'},
    'show': {'-s', '--format=%ct'},
    'log': {'-1', '--name-only', '--diff-filter=A', '--diff-filter=D',
            '--format=', '--format=%H', '--format=%ae', '--format=%ct',
            '--format=%ae%n%ce', '--format=%H%x00%ae%x00%P'},
    'diff': {'--name-only', '--no-ext-diff', '--no-textconv', '--no-renames',
             '--no-color', '--full-index', '--binary', '--text', '-z'},
    'diff-tree': {'-m', '-r', '--no-commit-id', '--name-only'},
    'cat-file': {'-e'},
    'rev-parse': {'--abbrev-ref', '--path-format=absolute', '--git-common-dir'},
    'ls-files': {'-z'},
    'ls-tree': {'--name-only'},
    'merge-base': {'--is-ancestor'},
}
def git_arguments(args):
    """Only grammars used by the frozen judge; no caller-supplied program options."""
    need(args and all(type(x) is str and '\0' not in x and '\r' not in x
                      and '\n' not in x and len(x) <= 8192 for x in args),
         'git_argument_type')
    verb, rest = args[0], list(args[1:])
    if verb in GIT_OPTIONS:
        readonly_git_arguments(verb, rest)
        return list(args)
    if verb == 'config':
        need(rest in (['user.email'], ['user.name']), 'git_config_operation')
    elif verb == 'remote':
        need(rest == ['get-url', 'origin'], 'git_remote_operation')
    elif verb == 'branch':
        need(len(rest) == 5 and rest[:2] == ['-r', '--contains'] and
             re.fullmatch(r'[0-9a-f]{40}', rest[2]) and
             rest[3:] == ['--list', 'origin/claude/*'], 'git_branch_operation')
    elif verb == 'rev-list':
        need(len(rest) == 4 and rest[:3] == ['--parents', '-n', '1'] and
             re.fullmatch(r'[0-9a-f]{40}', rest[3]), 'git_revision_operation')
    elif verb in ('ls-remote', 'fetch'):
        need(len(rest) == 2 and rest[0] == 'origin' and
             re.fullmatch(r'refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*', rest[1]) and
             '..' not in rest[1], 'git_transport_operation')
    elif verb == 'push':
        need(rest == ['-q'], 'git_transport_operation')
        return ['push', '-q', 'origin', 'HEAD']
    elif verb == 'add':
        need(rest and rest[0] == '--' and len(rest) > 1 and
             all(not p.startswith(('-', '/', ':')) and '..' not in Path(p).parts for p in rest[1:]),
             'git_add_operation')
    elif verb == 'commit':
        need(len(rest) >= 3 and rest[:2] == ['-q', '-m'] and
             (len(rest) == 3 or (rest[3] == '--' and all(
              not p.startswith(('-', '/', ':')) and '..' not in Path(p).parts for p in rest[4:]))),
             'git_commit_operation')
        return ['commit', '--no-gpg-sign', *rest]
    elif verb == 'worktree':
        if rest == ['prune']:
            pass
        elif len(rest) == 5 and rest[:3] == ['add', '--detach', '--quiet']:
            need(Path(rest[3]).is_absolute() and not Path(rest[3]).exists() and
                 re.fullmatch(r'(?:[0-9a-f]{40}|HEAD)', rest[4]), 'git_worktree_operation')
            protected_path(Path(rest[3]).parent, True)
        elif len(rest) == 3 and rest[:2] == ['remove', '--force']:
            protected_path(rest[2], True)
        else:
            raise Blocked('git_worktree_operation')
    else:
        raise Blocked('git_command_not_allowed')
    return list(args)

def git_directory(root):
    root = Path(root)
    protected_path(root, True)
    link = root / '.git'
    info = link.lstat()
    if stat.S_ISDIR(info.st_mode):
        protected_path(link, True)
        common = link
    else:
        raw = protected_bytes(link, 4096).decode('utf-8')
        need(raw.startswith('gitdir: ') and raw.endswith('\n'), 'git_worktree_link')
        link = Path(raw[8:].strip())
        protected_path(link, True)
        common_raw = protected_bytes(link/'commondir', 4096).decode('utf-8').strip()
        need(common_raw == '../..', 'git_worktree_common')
        common = link.parent.parent
        protected_path(common, True)
    return link, common

def protected_bytes(path, limit):
    path = Path(path)
    before = protected_path(path)
    need(before.st_size <= limit, 'protected_file_size')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        need(identity(before) == identity(os.fstat(fd)), 'protected_file_changed')
        chunks, size = [], 0
        while size <= limit:
            data = os.read(fd, min(65536, limit + 1 - size))
            if not data:
                break
            chunks.append(data); size += len(data)
        need(size == before.st_size and
             identity(before) == identity(os.fstat(fd)) == identity(path.lstat()),
             'protected_file_changed')
        return b''.join(chunks)
    finally:
        os.close(fd)

# Installed bootstrap supplies this from a root-only deployment file. A checkout cannot.
VALIDATOR_TRANSPORT = None
def configure_validator_transport(config):
    global VALIDATOR_TRANSPORT
    need(VALIDATOR_TRANSPORT is None, 'transport_already_configured')
    need(type(config) is dict and set(config) == {'remote', 'key', 'known_hosts'}, 'transport_fields')
    need(config['remote'] == 'git@github.com:JorgeYuriDj/pesquisa-automatizada.git', 'transport_destination')
    for name in ('key', 'known_hosts'):
        need(re.fullmatch(r'/[A-Za-z0-9_./-]+', config[name]) and '..' not in Path(config[name]).parts,
             'transport_path')
        protected_path(config[name])
    VALIDATOR_TRANSPORT = dict(config)

def inspect_git_configuration(root):
    _, common = git_directory(root)
    config = common/'config'
    raw = protected_bytes(config, MAX_CONFIG)
    # stdin is the exact verified configuration. Git may not open include targets.
    value = subprocess.run(['/usr/bin/git','config','--null','--no-includes','--file','-','--list'],
                           input=raw, capture_output=True, env=safe_environment(), timeout=5)
    need(value.returncode == 0 and not value.stderr and len(value.stdout) <= MAX_CONFIG, 'git_config_parse')
    pairs = []
    for record in value.stdout.split(b'\0'):
        if record:
            key, separator, data = record.partition(b'\n')
            need(separator, 'git_config_parse')
            pairs.append((key.decode('ascii').lower(), data.decode('utf-8')))
    keys = [key for key, _ in pairs]
    need(len(set(keys)) == len(keys), 'git_config_duplicate')
    need(all(key in BASE_KEYS or re.fullmatch(r'branch\.[a-z0-9._/-]+\.(?:remote|merge)', key)
             for key in keys), 'git_config_key_not_allowed')
    values = dict(pairs)
    need(values.get('commit.gpgsign', 'false') == 'false', 'git_signing_program_not_allowed')
    need(values.get('core.repositoryformatversion') == '0' and
         values.get('core.bare', 'false') == 'false', 'git_repository_format')
    remote = values.get('remote.origin.url')
    if remote is not None:
        if VALIDATOR_TRANSPORT:
            need(remote == VALIDATOR_TRANSPORT['remote'], 'git_remote_not_pinned')
        else:
            local = remote.startswith('/') and '..' not in Path(remote).parts and re.fullmatch(r'/[A-Za-z0-9_./-]+', remote)
            metadata_only = re.fullmatch(r'(?:https://github[.]com/|git@github[.]com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:[.]git)?', remote)
            need(local or metadata_only, 'git_remote_not_pinned')
        need(values.get('remote.origin.fetch') == '+refs/heads/*:refs/remotes/origin/*',
             'git_fetch_not_pinned')
    for key, data in pairs:
        if key.endswith('.remote'):
            need(data == 'origin', 'git_branch_remote')
        elif key.startswith('branch.') and key.endswith('.merge'):
            need(re.fullmatch(r'refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]*', data)
                 and '..' not in data, 'git_branch_merge')
    return values

def guarded_git(root, *args, text=False, timeout=120):
    argv = git_arguments(args)  # Reject command overrides before reading a candidate URL.
    config = inspect_git_configuration(root)
    env = safe_environment()
    if argv[0] in ('ls-remote', 'fetch', 'push') and not VALIDATOR_TRANSPORT:
        remote = config.get('remote.origin.url', '')
        need(remote.startswith('/'), 'git_transport_not_pinned')
        try:
            protected_path(remote, True)
        except FileNotFoundError as exc:
            raise Blocked('git_remote_unavailable') from exc
    if VALIDATOR_TRANSPORT:
        t = VALIDATOR_TRANSPORT
        for key in ('key', 'known_hosts'):
            protected_path(t[key])
        env['GIT_SSH_COMMAND'] = (
            '/usr/bin/ssh -F /dev/null -oBatchMode=yes -oIdentitiesOnly=yes '
            '-oStrictHostKeyChecking=yes -oUserKnownHostsFile=' + t['known_hosts'] +
            ' -i ' + t['key'])
    extra = ['--no-ext-diff', '--no-textconv'] if argv[0] in ('diff','show','log','diff-tree') else []
    return subprocess.run(
        ['/usr/bin/git','-c','core.fsmonitor=','-c','core.hooksPath=/dev/null',
         '-c','core.pager=/bin/cat','-c','protocol.ext.allow=never',
         '-c','protocol.file.allow=always','-c','maintenance.auto=false',
         '-c','gc.auto=0','-c','core.quotePath=false','-c','diff.algorithm=myers',
         '-c','diff.indentHeuristic=false','-C',str(root),argv[0],*extra,*argv[1:]],
        stdin=subprocess.DEVNULL,capture_output=True,text=text,env=env,timeout=timeout)

def installed_sources(installed,expected):
 installed=Path(installed);protected_path(installed,True)
 need(set(expected)=={'blocos.py','fichas.py','juiz_base.py','run_tests.py','revisao_juiz.py'},'installed_inventory')
 need({p.name for p in installed.iterdir()}==set(expected),'installed_inventory_extra_or_missing')
 sources={}
 for name,wanted in expected.items():
  need(re.fullmatch(r'[0-9a-f]{64}',wanted),'installed_hash_format')
  p=installed/name;before=protected_path(p)
  need(before.st_size<=2*1024*1024,'installed_size')
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
  try:
   need(identity(before)==identity(os.fstat(fd)),'installed_changed')
   raw=b''
   while len(raw)<=2*1024*1024:
    chunk=os.read(fd,65536)
    if not chunk:break
    raw+=chunk
   need(len(raw)==before.st_size and identity(before)==identity(os.fstat(fd))==identity(p.lstat()),'installed_changed')
   need(hashlib.sha256(raw).hexdigest()==wanted,'installed_hash_mismatch')
  finally:os.close(fd)
  sources[name]=raw
 need({p.name for p in installed.iterdir()}==set(expected),'installed_inventory_extra_or_missing')
 return sources


def installed_hashes(installed,expected):
 installed_sources(installed,expected)
 return True


def verify_openpgp(root, commit, keyring):
    need(re.fullmatch(r'[0-9a-f]{40}', commit), 'signature_commit')
    protected_path(keyring, True)
    inspect_git_configuration(root)
    env = safe_environment()
    env['GNUPGHOME'] = str(keyring)
    return subprocess.run(
        ['/usr/bin/git', '-C', str(root), '-c', 'core.fsmonitor=',
         '-c', 'core.hooksPath=/dev/null', '-c', 'gpg.format=openpgp',
         '-c', 'gpg.program=/usr/bin/gpg', 'verify-commit', '--raw', commit],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env, timeout=60)

def verify_ssh_commit(root, commit, public_key, principal):
    """Verify one immutable commit with one pinned SSH signer, no inherited programs."""
    import base64
    import tempfile
    need(re.fullmatch(r'[0-9a-f]{40}', commit), 'ssh_signature_commit')
    need(re.fullmatch(r'[A-Za-z0-9._+@-]{3,160}', principal), 'ssh_signature_principal')
    need(type(public_key) is str and
         re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]+={0,2}', public_key), 'ssh_signature_key')
    try:
        key = base64.b64decode(public_key.split()[1], validate=True)
    except ValueError as exc:
        raise Blocked('ssh_signature_key') from exc
    need(len(key) == 51 and key[:19] == b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20',
         'ssh_signature_key')
    inspect_git_configuration(root)
    with tempfile.TemporaryDirectory(prefix='sc-allowed-signers-', dir='/run') as directory:
        home = Path(directory)
        home.chmod(0o700)
        protected_path(home, True)
        allowed = home/'allowed_signers'
        allowed.write_text(principal+' namespaces="git" '+public_key+'\n', encoding='ascii')
        allowed.chmod(0o600)
        protected_path(allowed)
        return subprocess.run(
            ['/usr/bin/git','-C',str(root),'-c','core.fsmonitor=','-c','core.hooksPath=/dev/null',
             '-c','gpg.format=ssh','-c','gpg.ssh.program=/usr/bin/ssh-keygen',
             '-c','gpg.ssh.allowedSignersFile='+str(allowed),'-c','gpg.ssh.revocationFile=/dev/null',
             '-c','gpg.minTrustLevel=fully','verify-commit','--raw',commit],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,env=safe_environment(),timeout=60)


def git_fixture_mutation(root, *args):
    allowed = (('commit','-q','--allow-empty','-m','negativo: commit local'),
               ('commit','-q','-m','negativo: remove'),
               ('commit','-q','-m','negativo: recria'))
    if args not in allowed:
        need((len(args) == 5 and args[:4] == ('rm','-q','--cached','--')) or
             (len(args) == 3 and args[:2] == ('add','--')), 'fixture_git_operation')
        need(not args[-1].startswith(('/', '-', ':')) and '..' not in Path(args[-1]).parts,
             'fixture_git_path')
    inspect_git_configuration(root)
    return subprocess.run(
        ['/usr/bin/git', '-C', str(root), '-c', 'core.fsmonitor=', '-c',
         'core.hooksPath=/dev/null', '-c', 'user.name=negativo', '-c',
         'user.email=negativo@local', '-c', 'commit.gpgsign=false', *args],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, env=safe_environment(), timeout=120)


def revision_argument(value, ranges=False):
    single = r'(?:HEAD|[0-9a-f]{40})(?:\^|\^\{commit\})?'
    return type(value) is str and bool(re.fullmatch(
        single + (r'(?:\.\.' + single + r')?' if ranges else ''), value))

def relative_git_path(value):
    return (type(value) is str and bool(value) and not value.startswith(('/', '-', ':')) and
            '\\' not in value and ':' not in value and
            '..' not in value.split('/') and '.' not in value.split('/') and '\0' not in value)

def readonly_git_arguments(verb, rest):
    """Validate positional arguments too: diff must never infer --no-index."""
    if verb == 'status':
        need(rest in ([], ['--porcelain'], ['--porcelain','-uall']), 'git_status_operation')
    elif verb == 'rev-parse':
        need(rest == ['--path-format=absolute','--git-common-dir'] or
             rest == ['--abbrev-ref','HEAD'] or
             (len(rest) == 1 and revision_argument(rest[0])), 'git_revparse_operation')
    elif verb == 'cat-file':
        need(len(rest) == 2 and rest[0] == '-e' and revision_argument(rest[1]), 'git_object_operation')
    elif verb == 'merge-base':
        need(len(rest) == 3 and rest[0] == '--is-ancestor' and
             all(revision_argument(x) for x in rest[1:]), 'git_ancestry_operation')
    elif verb == 'show':
        if len(rest) == 1:
            commit, sep, path = rest[0].partition(':')
            need(sep and revision_argument(commit) and relative_git_path(path), 'git_show_operation')
        else:
            need(len(rest) == 3 and rest[:2] == ['-s','--format=%ct'] and
                 revision_argument(rest[2]), 'git_show_operation')
    elif verb == 'ls-files':
        if '--' in rest:
            i = rest.index('--'); opts, paths = rest[:i], rest[i+1:]
            need(opts in ([], ['-z']) and paths and all(relative_git_path(x) for x in paths),
                 'git_files_operation')
        else:
            need(rest in ([], ['-z']), 'git_files_operation')
    elif verb == 'ls-tree':
        need(len(rest) == 3 and rest[0] == '--name-only' and revision_argument(rest[1]) and
             relative_git_path(rest[2]), 'git_tree_operation')
    else: # log, diff, diff-tree: fixed options, followed by revisions, then optional -- paths.
        before, paths = rest, []
        if '--' in rest:
            i = rest.index('--'); before, paths = rest[:i], rest[i+1:]
            need(paths and all(relative_git_path(x) for x in paths), 'git_path_operation')
        positional = [x for x in before if not x.startswith('-')]
        need(all(x in GIT_OPTIONS[verb] for x in before if x.startswith('-')), 'git_option_not_allowed')
        expected = (0,1) if verb == 'log' else ((2,) if verb == 'diff' else (1,))
        # Only the closed-block working-tree probe may use a single revision.
        if (verb == 'diff' and before == ['--name-only','HEAD'] and len(paths)==1
                and re.fullmatch(r'blocos/B[0-9]{2}',paths[0])):
            expected = (1,)
        need(len(positional) in expected and
             all(revision_argument(x, ranges=verb == 'log') for x in positional),
             'git_revision_operation')


def probe_write_denials(prefix, directories, files, cwd, env):
    """Try harmless opens/creations under the executor, never overwrite a protected file."""
    need(directories and len(set(directories + files)) == len(directories + files), 'probe_inventory')
    for path in directories:
        protected_path(path, True)
    for path in files:
        protected_path(path)
    program = r"""
import errno,json,os,sys,uuid
targets=json.loads(sys.argv[1]);denied=[];unexpected=[]
for kind, path in targets:
    fd=None;created=None;directory=None
    try:
        if kind=='directory':
            directory=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            created='.sc-write-probe-'+uuid.uuid4().hex
            fd=os.open(created,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        else:
            fd=os.open(path,os.O_WRONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        unexpected.append(path)
    except OSError as exc:
        if exc.errno in (errno.EACCES,errno.EPERM,errno.EROFS):denied.append(path)
        else:unexpected.append(path)
    finally:
        if fd is not None:
            os.close(fd)
            if created is not None:os.unlink(created,dir_fd=directory)
        if directory is not None:os.close(directory)
print(json.dumps({'uid':os.geteuid(),'denied':denied,'unexpected':unexpected}))
"""
    targets = [('directory', p) for p in directories] + [('file', p) for p in files]
    result = subprocess.run([*prefix,'/usr/bin/python3','-I','-B','-c',program,json.dumps(targets)],
                            cwd=cwd,env=env,capture_output=True,timeout=10,stdin=subprocess.DEVNULL)
    need(result.returncode == 0 and not result.stderr, 'write_probe_failed')
    data = strict_json(result.stdout)
    need(data.get('uid', 0) > 0 and data.get('unexpected') == [] and
         data.get('denied') == directories + files, 'executor_can_write_authority')
    return data

"""Prototipo do leitor sem privilegios; testes somente com canarios sinteticos."""
import base64,select,shutil,signal,tempfile,time
from pathlib import Path
UID=1800000002
MAX_FILE=8*1024*1024
MAX_TOTAL=32*1024*1024
ALLOWED=re.compile(r'(?:artifacts/(?:runner\.(?:stdout|stderr)|(?:inner-metadata|metadata|exit|error)\.json)|worker/\.sc-suite-result\.json|history/(?:approval-000023\.json|run-[0-9a-f]{32}/(?:attempt\.json|(?:0[1-9]|1[0-2])\.(?:json|log))))\Z')
Refused=Blocked
def need(value,reason):
 if not value:raise Refused(reason)
def ident(s):return (s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
def owned_directory(fd,uid):
 s=os.fstat(fd);need(stat.S_ISDIR(s.st_mode) and s.st_uid==uid and not s.st_mode&0o022,'unsafe_directory')
def collect(root,paths,uid,hook=None):
 need(os.geteuid()==uid and uid!=0,'collector_must_be_unprivileged')
 need(type(paths) is list and 0<len(paths)<=128 and len(set(paths))==len(paths),'path_inventory')
 need(all(type(p) is str and ALLOWED.fullmatch(p) for p in paths),'unexpected_path')
 flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
 rootfd=os.open(root,flags);total=0;files=[]
 try:
  owned_directory(rootfd,uid)
  for rel in paths:
   fds=[os.dup(rootfd)];guards=[]
   try:
    segments=rel.split('/')
    for part in segments[:-1]:
     before=os.stat(part,dir_fd=fds[-1],follow_symlinks=False)
     need(stat.S_ISDIR(before.st_mode),'directory_type')
     if hook:hook('before_directory',rel,part)
     newfd=os.open(part,flags,dir_fd=fds[-1]);fds.append(newfd);owned_directory(newfd,uid)
     need(ident(before)==ident(os.fstat(newfd)),'directory_changed')
     guards.append((fds[-2],part,before))
    leaf=segments[-1];before=os.stat(leaf,dir_fd=fds[-1],follow_symlinks=False)
    need(stat.S_ISREG(before.st_mode) and before.st_uid==uid and before.st_nlink==1,'file_type_owner_or_links')
    need(0<=before.st_size<=MAX_FILE and total+before.st_size<=MAX_TOTAL,'size_limit')
    if hook:hook('before_file',rel,leaf)
    fd=os.open(leaf,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fds[-1])
    try:
     need(ident(before)==ident(os.fstat(fd)),'file_changed_before_read')
     chunks=[];count=0
     while True:
      data=os.read(fd,min(65536,MAX_FILE+1-count))
      if not data:break
      chunks.append(data);count+=len(data);need(count<=MAX_FILE and total+count<=MAX_TOTAL,'size_limit')
     if hook:hook('after_read',rel,leaf)
     need(ident(before)==ident(os.fstat(fd))==ident(os.stat(leaf,dir_fd=fds[-1],follow_symlinks=False)),'file_changed_after_read')
     for directory,name,info in guards:need(ident(info)==ident(os.stat(name,dir_fd=directory,follow_symlinks=False)),'directory_changed_after_read')
     raw=b''.join(chunks);need(len(raw)==before.st_size,'short_or_growing_file');total+=len(raw)
     files.append({'path':rel,'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode('ascii')})
    finally:os.close(fd)
   finally:
    for fd in reversed(fds):os.close(fd)
  return {'schema':'sc-unprivileged-collector-prototype/1','uid':os.geteuid(),'files':files,'total_bytes':total}
 finally:os.close(rootfd)
def call_unprivileged(root,paths,hook=None):
 readfd,writefd=os.pipe();pid=os.fork()
 if pid==0:
  try:
   os.close(readfd);os.setsid();os.setgroups([]);os.setgid(UID);os.setuid(UID)
   os.environ.clear();os.environ.update({'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent'})
   import ctypes
   libc=ctypes.CDLL(None,use_errno=True);need(libc.prctl(38,1,0,0,0)==0,'no_new_privs')
   need(writefd>2,'output_pipe_descriptor')
   nullfd=os.open('/dev/null',os.O_RDWR|os.O_NOFOLLOW)
   for target in (0,1,2):os.dup2(nullfd,target)
   if nullfd>2:os.close(nullfd)
   for rawfd in os.listdir('/proc/self/fd'):
    fd=int(rawfd)
    if fd not in (0,1,2,writefd):
     try:os.close(fd)
     except OSError as exc:
      if exc.errno!=9:raise
   nullstat=os.stat('/dev/null')
   for fd in (0,1,2):
    info=os.fstat(fd);need(stat.S_ISCHR(info.st_mode) and info.st_rdev==nullstat.st_rdev,'stdio_not_null')

   try:value={'ok':True,'result':collect(root,paths,UID,hook)}
   except (Refused,OSError) as exc:value={'ok':False,'error':type(exc).__name__+(':'+str(exc) if isinstance(exc,Refused) else '')}
   raw=json.dumps(value,separators=(',',':')).encode()
   while raw:raw=raw[os.write(writefd,raw):]
   os._exit(0)
  except BaseException:os._exit(2)
 os.close(writefd);chunks=[];size=0;deadline=time.monotonic()+10
 try:
  while True:
   need(time.monotonic()<deadline,'collector_timeout')
   if not select.select([readfd],[],[],.1)[0]:continue
   chunk=os.read(readfd,65536)
   if not chunk:break
   size+=len(chunk);need(size<=MAX_TOTAL*2,'collector_output_limit');chunks.append(chunk)
  _,status=os.waitpid(pid,0);need(os.waitstatus_to_exitcode(status)==0,'collector_failed')
  value=json.loads(b''.join(chunks))
  if value.get('ok'):
   result=value['result'];need(result['uid']==UID and len(result['files'])==len(paths),'output_identity')
   need([row['path'] for row in result['files']]==paths,'output_paths')
   total=0
   for row in result['files']:
    need(type(row['size']) is int and 0<=row['size']<=MAX_FILE,'output_size')
    raw=base64.b64decode(row['base64'],validate=True);total+=len(raw)
    need(len(raw)==row['size'] and hashlib.sha256(raw).hexdigest()==row['sha256'],'output_bytes')
   need(total==result['total_bytes'] and total<=MAX_TOTAL,'output_total')
  return value
 finally:
  os.close(readfd)
  try:
   got,_=os.waitpid(pid,os.WNOHANG)
   if not got:os.killpg(pid,signal.SIGKILL);os.waitpid(pid,0)
  except ChildProcessError:pass



def isolated_test_namespace():
    """Recognize the reserved, credentialless test namespace, never an environment flag."""
    try:
        rows = [tuple(map(int,line.split())) for line in Path('/proc/self/uid_map').read_text().splitlines()]
        return (rows == [(0,1800000002,1),(12345,1800000000,1),(65534,1800000001,1)]
                and os.geteuid() == 0 and Path('/').stat().st_uid == 0
                and not Path('/.oldroot').exists()
                and __import__('socket').if_nameindex() == [(1,'lo')]
                and all(not Path(p).exists() for p in (
                    '/root/.ssh','/root/.codex','/var/lib/sc-pesquisa-executor',
                    '/var/lib/claude-console-research','/var/lib/claude-mobile',
                    '/var/lib/antigravity-mobile')))
    except (OSError, ValueError):
        return False

def isolated_command(root, argv, timeout, network=False):
    return isolated_execution(root,argv,timeout,network)

def isolated_suite(root,suite,timeout,installation):
    need(type(suite) is str and re.fullmatch(r'(?:controle|infra/google_cloud)/test_[a-z0-9_]+[.]py',suite),
         'isolated_suite_path')
    need(type(installation) is dict,'isolated_suite_installation')
    installed_hashes(installation['installed'],installation['files'])
    return isolated_execution(root,['python3','controle/run_tests.py'],timeout,False,suite,installation)

def isolated_execution(root, argv, timeout, network=False, suite=None, installation=None):
    """Run a tracked command with no host credential identity or host filesystem view.

    The parent never executes repository code. A root-only caller snapshots regular files,
    creates a fresh user/mount/PID/network namespace, then receives bounded bytes from the
    unprivileged collector. An already isolated test runner needs no second host UID map.
    """
    import ctypes, fcntl, grp, pwd, shutil, signal, select, socket, tempfile, time
    root = Path(root)
    need(type(argv) is list and len(argv) >= 2 and argv[0] in ('python3','git') and
         all(type(a) is str and '\0' not in a for a in argv), 'isolated_argv')
    need(type(timeout) is int and 1 <= timeout <= 600, 'isolated_timeout')
    need(network is False, 'candidate_network_forbidden')
    if argv[0] == 'python3':
        need(relative_git_path(argv[1]), 'isolated_script_path')
        command = ['/usr/bin/python3','-I','-B',str(root/argv[1]),*argv[2:]]
    else:
        isolated_git_arguments(argv[1:])
        command = ['/usr/bin/git','-c','core.fsmonitor=','-c','core.hooksPath=/dev/null',*argv[1:]]
    if suite is None and isolated_test_namespace():
        with tempfile.TemporaryDirectory(prefix='sc-command-home-') as home:
            env = safe_environment(); env['HOME'] = home
            try:
                result = subprocess.run(['/usr/bin/setpriv','--no-new-privs','--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all','--',*command],cwd=root,stdin=subprocess.DEVNULL,
                                        capture_output=True,env=env,timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise Blocked('comando_tempo_esgotado') from exc
            need(len(result.stdout) <= MAX_FILE and len(result.stderr) <= MAX_FILE, 'command_output_limit')
            return result.returncode, result.stdout
    need(os.geteuid() == 0 and __import__('platform').machine() == 'x86_64', 'isolated_host_unsupported')
    inspect_git_configuration(root)
    for uid in (UID,1800000000,1800000001):
        for lookup in (pwd.getpwuid,grp.getgrgid):
            try:
                lookup(uid)
            except KeyError:
                pass
            else:
                raise Blocked('isolated_uid_allocated')
        for name in ('/etc/subuid','/etc/subgid'):
            for line in (Path(name).read_text().splitlines() if Path(name).exists() else []):
                _,start,count = line.split(':')
                need(not int(start) <= uid < int(start)+int(count), 'isolated_uid_delegated')
    protected_path('/run',True)
    lockdir=Path('/run/sc-pesquisa-isolated');lockdir.mkdir(mode=0o700,exist_ok=True);protected_path(lockdir,True)
    lock=os.open(lockdir/'sc-pesquisa-isolated-command.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    info=os.fstat(lock)
    need(stat.S_ISREG(info.st_mode) and info.st_uid==0 and info.st_nlink==1 and not info.st_mode&0o077,'isolated_lock')
    fcntl.flock(lock,fcntl.LOCK_EX)
    trial=None;pid=None;ready_r=None;go_w=None
    try:
        names=guarded_git(root,'ls-files','-z').stdout.decode('utf-8').split('\0')
        need(names[-1]=='' and 0<len(names)<=20001,'isolated_inventory')
        snapshot=[];total=0
        for name in names[:-1]:
            need(relative_git_path(name) and '.git' not in Path(name).parts,'isolated_path')
            source=root/name
            try:
                info=protected_path(source);raw=protected_bytes(source,8*1024*1024)
                total+=len(raw);need(total<=128*1024*1024,'isolated_snapshot_limit')
                snapshot.append((name,raw,info.st_mode&0o111))
            except FileNotFoundError:
                snapshot.append((name,None,0))
        trial=Path(tempfile.mkdtemp(prefix='sc-isolated-command-',dir='/tmp'));trial.chmod(0o755)
        worker=trial/'worker';rootfs=trial/'rootfs';artifacts=trial/'artifacts'
        rootfs.mkdir();artifacts.mkdir(mode=0o700)
        frozen=trial/'frozen'
        if suite is not None:
            need(all(name!='.sc-suite-result.json' for name,_,_ in snapshot),'isolated_result_collision')
            frozen.mkdir(mode=0o755)
            for name,wanted in installation['files'].items():
                raw=protected_bytes(Path(installation['installed'])/name,2*1024*1024)
                need(filehash(raw)==wanted,'isolated_installed_judge_changed')
                (frozen/name).write_bytes(raw)
            extras=root/'controle/suites_extras.json'
            if extras.exists() or extras.is_symlink():
                (frozen/'suites_extras.json').write_bytes(protected_bytes(extras,1024*1024))
        env=safe_environment()
        git_prefix=['/usr/bin/git','-c','core.fsmonitor=','-c','core.hooksPath=/dev/null','-c','maintenance.auto=false','-c','gc.auto=0']
        subprocess.run([*git_prefix,'clone','--no-local','--no-hardlinks','--no-checkout','-q',str(root),str(worker)],
                       check=True,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=60)
        source_head=guarded_git(root,'rev-parse','HEAD').stdout.decode().strip()
        subprocess.run([*git_prefix,'-C',str(worker),'update-ref','--no-deref','HEAD',source_head],
                       check=True,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
        source_git,_=git_directory(root)
        (worker/'.git/index').write_bytes(protected_bytes(source_git/'index',32*1024*1024))
        # This offline copy must never masquerade as an observed live GitHub remote.
        subprocess.run([*git_prefix,'-C',str(worker),'remote','remove','origin'],
                       check=True,env=env,stdin=subprocess.DEVNULL,capture_output=True,timeout=10)
        rootfd=os.open(worker,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            for name,raw,executable in snapshot:
                if raw is not None:snapshot_write(rootfd,name,raw,executable)
        finally:os.close(rootfd)
        snapshot.clear()
        for folder in (worker,rootfs,artifacts,*([frozen] if suite is not None else [])):
            for parent,dirs,files in os.walk(folder,followlinks=False):
                os.chown(parent,UID,UID)
                for name in dirs+files:os.chown(Path(parent)/name,UID,UID,follow_symlinks=False)
        os.chown(trial,UID,UID)
        if argv[0]=='python3':command[3]='/workspace/'+argv[1]
        if suite is not None:
            command=['/usr/bin/python3','-I','-B','/judge/run_tests.py',
                     '--worker',suite,'--root','/workspace','--result','/workspace/.sc-suite-result.json']
        inner=r"""
import ctypes,os,resource,socket,sys
from pathlib import Path
newroot,seconds,mode=sys.argv[1],int(sys.argv[2]),sys.argv[3];command=sys.argv[4:]
libc=ctypes.CDLL(None,use_errno=True)
import subprocess
subprocess.run(['/usr/bin/mount','--bind','/proc',str(Path(newroot)/'proc')],check=True)
os.chdir(newroot)
if libc.syscall(155,b'.',b'.oldroot')!=0:raise OSError(ctypes.get_errno(),'pivot_root')
os.chdir('/')
if libc.umount2(b'/.oldroot',2)!=0:raise OSError(ctypes.get_errno(),'detach_oldroot')
os.rmdir('/.oldroot');os.chdir('/workspace')
if socket.if_nameindex()!=[(1,'lo')]:raise RuntimeError('network_not_private')
resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024*1024,8*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU,(seconds+1,seconds+2))
env={'PATH':'/usr/bin:/bin','HOME':'/home/runner','LANG':'C.UTF-8','LC_ALL':'C.UTF-8','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_SYSTEM':'/dev/null','GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_PAGER':'/bin/cat'}
# A suite needs synthetic internal UIDs; all are mapped to unprivileged host identities.
# Ordinary ficha commands still receive no capabilities.
options=['--no-new-privs'] if mode=='suite' else ['--no-new-privs','--bounding-set=-all','--inh-caps=-all','--ambient-caps=-all']
os.execve('/usr/bin/setpriv',['/usr/bin/setpriv',*options,'--',*command],env)
"""
        ready_r,ready_w=os.pipe();go_r,go_w=os.pipe();pid=os.fork()
        if pid==0:
            stage='close_descriptors'
            try:
                os.close(ready_r);os.close(go_w);os.close(lock)
                stage='session';os.setsid()
                stage='clear_parent_groups';os.setgroups([])
                libc=ctypes.CDLL(None,use_errno=True)
                # Fixed judge setup only: create the namespace before switching
                # to its unprivileged outside identity. Parent UID0 is never mapped.
                stage='unshare_user'
                if libc.unshare(0x10000000)!=0:raise OSError(ctypes.get_errno(),'unshare_user')
                need(libc.prctl(4,1,0,0,0)==0,'namespace_dumpable')
                os.write(ready_w,b'R')
                need(os.read(go_r,1)==b'G','mapping_handshake')
                stage='set_namespace_gid';os.setresgid(0,0,0)
                stage='set_namespace_uid';os.setresuid(0,0,0)
                stage='clear_namespace_groups';os.setgroups([])
                need(libc.prctl(38,1,0,0,0)==0,'namespace_no_new_privs')
                stage='parent_identity_gate'
                os.write(ready_w,b'D');os.close(ready_w)
                need(os.read(go_r,1)==b'X','identity_handshake');os.close(go_r)
                stage='worker_cwd';os.chdir(worker)
                os.environ.clear();os.environ.update({'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(artifacts)})
                stage='unshare_mount'
                if libc.unshare(0x00020000)!=0:raise OSError(ctypes.get_errno(),'unshare_mount')
                def mount(args):
                    subprocess.run(['/usr/bin/mount',*args],check=True,stdin=subprocess.DEVNULL,
                                   capture_output=True,env=os.environ.copy(),timeout=10)
                stage='private_rootfs'
                mount(['--make-rprivate','/']);mount(['--bind',str(rootfs),str(rootfs)])
                for name in ('usr','etc','proc','tmp','run','root','home/runner','dev','dev/shm','var','sys','workspace','.oldroot'):
                    (rootfs/name).mkdir(parents=True,exist_ok=True)
                (rootfs/'tmp').chmod(0o1777);(rootfs/'dev/shm').chmod(0o1777)
                def bind(source,target,readonly=False):
                    mount(['--rbind' if Path(source).is_dir() else '--bind',str(source),str(target)])
                    if readonly:mount(['-o','remount,bind,ro,nosuid',str(target)])
                for name in ('usr/bin','usr/sbin','usr/lib','usr/lib64','usr/share'):
                    source=Path('/')/name
                    if source.is_dir():
                        (rootfs/name).mkdir(parents=True,exist_ok=True);bind(source,rootfs/name,True)
                for name in ('bin','sbin','lib','lib64'):
                    source=Path('/')/name
                    if source.is_symlink():(rootfs/name).symlink_to(os.readlink(source))
                    elif source.is_dir():(rootfs/name).mkdir();bind(source,rootfs/name,True)
                for name in ('passwd','group','nsswitch.conf','os-release'):
                    source=Path('/etc')/name
                    if source.is_file():shutil.copyfile(source,rootfs/'etc'/name)
                for name in ('null','zero','random','urandom'):
                    (rootfs/'dev'/name).touch();bind('/dev/'+name,rootfs/'dev'/name)
                for name,target in [('fd','/proc/self/fd'),('stdin','/proc/self/fd/0'),('stdout','/proc/self/fd/1'),('stderr','/proc/self/fd/2')]:
                    (rootfs/'dev'/name).symlink_to(target)
                private_setpriv=artifacts/'setpriv';shutil.copyfile('/usr/bin/setpriv',private_setpriv);private_setpriv.chmod(0o755)
                bind(private_setpriv,rootfs/'usr/bin/setpriv',True);bind(worker,rootfs/'workspace')
                if suite is not None:
                    (rootfs/'judge').mkdir();bind(frozen,rootfs/'judge',True)
                stage='execute_nested_namespace'
                with (artifacts/'runner.stdout').open('wb') as out,(artifacts/'runner.stderr').open('wb') as err:
                    try:
                        result=subprocess.run(['/usr/bin/unshare','--mount','--mount-proc','--net','--ipc','--uts','--pid','--fork','--kill-child',
                                               '/usr/bin/python3','-I','-B','-c',inner,str(rootfs),str(timeout),'suite' if suite is not None else 'command',*command],
                                              cwd=rootfs,env=os.environ.copy(),stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                              close_fds=True,timeout=timeout)
                        code=result.returncode
                    except subprocess.TimeoutExpired:
                        code=124
                # Artifacts are outside the child's root and are never mounted into it.
                (artifacts/'exit.json').write_text(json.dumps({'returncode':code})+'\n')
                os._exit(0)
            except BaseException as exc:
                try:(artifacts/'error.json').write_text(json.dumps({'type':type(exc).__name__,'message':('stage='+stage+'; '+str(exc)+' '+(exc.stderr.decode('utf-8','replace') if isinstance(exc,subprocess.CalledProcessError) and isinstance(exc.stderr,bytes) else ''))[:768]})+'\n')
                except BaseException:pass
                os._exit(2)
        os.close(ready_w);os.close(go_r)
        need(select.select([ready_r],[],[],10)[0] and os.read(ready_r,1)==b'R','isolated_namespace_handshake')
        mapping='0 1800000002 1\n12345 1800000000 1\n65534 1800000001 1\n'
        Path('/proc/%d/uid_map'%pid).write_text(mapping);Path('/proc/%d/gid_map'%pid).write_text(mapping)
        os.write(go_w,b'G')
        need(select.select([ready_r],[],[],10)[0] and os.read(ready_r,1)==b'D',
             'isolated_identity_handshake')
        observed=dict(line.split(':',1) for line in Path('/proc/%d/status'%pid).read_text().splitlines() if ':' in line)
        need(observed.get('Uid','').split()==[str(UID)]*4
             and observed.get('Gid','').split()==[str(UID)]*4
             and observed.get('Groups','').split()==[]
             and observed.get('NoNewPrivs','').strip()=='1','isolated_outside_identity')
        os.write(go_w,b'X');os.close(go_w);go_w=None
        deadline=time.monotonic()+timeout+35
        while True:
            done,status=os.waitpid(pid,os.WNOHANG)
            if done:break
            need(time.monotonic()<deadline,'isolated_command_timeout')
            time.sleep(.05)
        pid=None
        if os.waitstatus_to_exitcode(status)!=0:
            detail=call_unprivileged(str(trial),['artifacts/error.json'])
            reason='isolated_command_setup_failed'
            if detail.get('ok'):
                data=strict_json(base64.b64decode(detail['result']['files'][0]['base64'],validate=True))
                reason+=':'+data['type']+':'+data['message']
            raise Blocked(reason)
        collected=call_unprivileged(str(trial),['artifacts/runner.stdout','artifacts/runner.stderr','artifacts/exit.json'])
        need(collected['ok'],'isolated_collection_failed')
        values={row['path']:base64.b64decode(row['base64'],validate=True) for row in collected['result']['files']}
        code=strict_json(values['artifacts/exit.json'])['returncode']
        need(type(code) is int and -255<=code<=255,'isolated_exit_code')
        if suite is not None:
            report=call_unprivileged(str(trial),['worker/.sc-suite-result.json'])
            raw=base64.b64decode(report['result']['files'][0]['base64'],validate=True) if report.get('ok') else None
            return code,values['artifacts/runner.stdout'],values['artifacts/runner.stderr'],raw
        need(code!=124,'comando_tempo_esgotado')
        return code,values['artifacts/runner.stdout']
    finally:
        if pid is not None:
            try:os.killpg(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            try:os.waitpid(pid,0)
            except ChildProcessError:pass
        if ready_r is not None:os.close(ready_r)
        if go_w is not None:os.close(go_w)
        if trial is not None:
            need(trial.parent==Path('/tmp') and trial.name.startswith('sc-isolated-command-'),'isolated_cleanup_path')
            need(shutil.rmtree.avoids_symlink_attacks,'isolated_cleanup_unsupported')
            shutil.rmtree(trial)
        os.close(lock)


def snapshot_write(rootfd, relative, raw, executable):
    """Create only relative regular files; a pre-existing link never receives a mkdir."""
    need(relative_git_path(relative) and '.git' not in Path(relative).parts,'isolated_path')
    fd=os.dup(rootfd)
    try:
        for component in Path(relative).parts[:-1]:
            try:
                new=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            except FileNotFoundError:
                os.mkdir(component,0o700,dir_fd=fd)
                new=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            os.close(fd);fd=new
            info=os.fstat(fd)
            need(stat.S_ISDIR(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'snapshot_parent')
        leaf=os.open(Path(relative).name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,
                     0o700 if executable else 0o600,dir_fd=fd)
        with os.fdopen(leaf,'wb') as stream:
            stream.write(raw)
    finally:os.close(fd)


def isolated_git_arguments(args):
    """Additional file comparisons allowed only after the credentialless boundary."""
    if (len(args)==5 and list(args[:3])==['diff','--no-index','--numstat'] and
            all(relative_git_path(p) for p in args[3:])):
        return list(args)
    if (len(args)==5 and list(args[:4])==['status','--porcelain','--untracked-files=all','--']
            and relative_git_path(args[4])):
        return list(args)
    if (len(args)==5 and list(args[:2])==['log','--diff-filter=DM'] and
            re.fullmatch(r'--format=tformat:[A-Z_]+',args[2]) and args[3]=='--' and
            relative_git_path(args[4])):
        return list(args)
    return git_arguments(args)


INSTALLATION_FILES = frozenset(('blocos.py','fichas.py','juiz_base.py','run_tests.py','revisao_juiz.py'))

def validator_installation(path, expected_sha256=None):
    """Deployment authority is outside the worktree and writable only by its custodian."""
    raw = protected_bytes(path, 32768)
    if expected_sha256 is not None:
        need(re.fullmatch(r'[0-9a-f]{64}',expected_sha256) and filehash(raw)==expected_sha256,
             'installation_manifest_changed')
    data = strict_json(raw)
    need(type(data) is dict and set(data)=={
        'schema','repository','installed','state','source_commit','frozen_after','frozen_sha256','previous_closure','files','transport','native_host_id'},
        'installation_fields')
    need(data['schema']=='sc-validator-installation/1' and
         type(data['source_commit']) is str and re.fullmatch(r'[0-9a-f]{40}',data['source_commit']) and
         type(data['frozen_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',data['frozen_sha256']) and
         type(data['frozen_after']) is str and re.fullmatch(r'B[0-9]{2}',data['frozen_after']),
         'installation_schema')
    need(type(data['native_host_id']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}',data['native_host_id']),
         'installation_native_host')
    closure=data['previous_closure']
    need(type(closure) is dict and set(closure)=={'commit','sha256'} and
         type(closure['commit']) is str and re.fullmatch(r'[0-9a-f]{40}',closure['commit']) and
         type(closure['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',closure['sha256']),
         'installation_previous_closure')
    for name in ('repository','installed','state'):
        need(type(data[name]) is str,'installation_path_type')
        protected_path(data[name],True)
    repository,installed,state=(Path(data[x]) for x in ('repository','installed','state'))
    need(repository.stat().st_mode&0o077==0 and state.stat().st_mode&0o077==0,
         'installation_private_directory')
    need(repository!=installed and repository not in installed.parents and
         installed not in repository.parents, 'installed_judge_in_checkout')
    need(type(data['files']) is dict and set(data['files'])==INSTALLATION_FILES, 'installation_inventory')
    installed_hashes(installed,data['files'])
    need(type(data['transport']) is dict and set(data['transport'])=={'remote','key','known_hosts'},
         'installation_transport')
    return data

def installed_entrypoint(data, current_file, loaded_files):
    """Imports must resolve to the protected installation, never the candidate checkout."""
    installed = Path(data['installed'])
    need(Path(current_file).absolute().parent == installed, 'judge_not_running_from_installation')
    for name,path in loaded_files.items():
        need(name in INSTALLATION_FILES and Path(path).absolute()==installed/name,
             'judge_import_outside_installation')
        need(filehash(protected_bytes(path,2*1024*1024))==data['files'][name],
             'judge_import_hash_changed')
    return Path(data['repository'])


MOBILE_CONFIRMATION_PREFIX = 'docs/decisoes/confirmacoes/'

def launcher_qualification(dt, read_versioned, verify_owner=None, expected_host=None):
    """Check bound evidence; recording a JSON claim alone is not a native demonstration."""
    need(type(dt) is dict and dt.get('estado')=='ativo_qualificado','launcher_not_qualified')
    lanc=dt.get('lancador');q=dt.get('qualificacao')
    need(type(lanc) is dict and type(q) is dict and set(q)=={
        'schema','lancador_sha256','sonda','rota_movel','observador'},'launcher_qualification_schema')
    need(q['schema'] in ('sc-lancador-qualificacao/1','sc-lancador-qualificacao/2') and q['lancador_sha256']==digest(lanc),
         'launcher_qualification_subject')
    need(type(expected_host) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}',expected_host) and
         lanc.get('native_host_id')==expected_host,'launcher_host_not_bound')
    identity=lanc.get('executor')
    need(type(identity) is dict and set(identity)=={'uid','gid','home','setpriv_sha256'} and
         type(identity['uid']) is int and identity['uid']>0 and
         type(identity['gid']) is int and identity['gid']>0 and
         type(identity['home']) is str and Path(identity['home']).is_absolute() and
         type(identity['setpriv_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',identity['setpriv_sha256']),
         'launcher_qualification_identity')
    def evidence(ref):
        need(type(ref) is dict and set(ref)=={'path','sha256'} and relative_git_path(ref['path']) and
             not RESTRICTED.search(ref['path']) and type(ref['sha256']) is str and
             re.fullmatch(r'[0-9a-f]{64}',ref['sha256']),'launcher_evidence_reference')
        raw=read_versioned(ref['path'])
        need(type(raw) is bytes and len(raw)<=8*1024*1024 and filehash(raw)==ref['sha256'],
             'launcher_evidence_hash')
        return raw
    proofs={}
    for name in ('sonda','rota_movel','observador'):
        data=strict_json(evidence(q[name]))
        need(type(data) is dict and data.get('schema')=='sc-lancador-'+name.replace('_','-')+'/1' and
             data.get('lancador_sha256')==q['lancador_sha256'] and
             canonical(data.get('executor'))==canonical(identity) and
             type(data.get('host_id')) is str and bool(data['host_id']),
             'launcher_evidence_subject:'+name)
        evidence(data.get('evidencia_bruta'))
        proofs[name]=data
    probe,mobile,observer=(proofs[name] for name in ('sonda','rota_movel','observador'))
    need(probe.get('metodo')=='sonda_real' and probe.get('credenciais_negadas') is True and
         probe.get('escritas_negadas') is True,'launcher_probe_not_demonstrated')
    notebook_only=q['schema']=='sc-lancador-qualificacao/2'
    if notebook_only:
        need(mobile.get('celular_demonstrado') is False and mobile.get('celular_pendencia')=={
            'estado':'bloqueado_dono','ordem':'8','bloqueia_fechamento':False,
            'causa':'Sessao VPS nao aparece no celular; dono adiou a demonstracao.',
            'desbloqueio':'Dono abre e responde na sessao nativa pelo celular.'},'launcher_mobile_deferral_invalid')
    need(mobile.get('metodo')=='codex_remote_nativo' and mobile.get('notebook_demonstrado') is True and
         (notebook_only or mobile.get('celular_demonstrado') is True) and
         type(mobile.get('sessao_nativa')) is str and
         re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_:/.-]{0,199}',mobile['sessao_nativa']),
         'launcher_mobile_not_demonstrated')
    need(observer.get('metodo')=='observacao_nativa_turno' and observer.get('qualificado') is True and
         observer.get('sessao_nativa')==mobile['sessao_nativa'] and
         type(observer.get('turn_id')) is str and bool(observer['turn_id']) and
         observer.get('estado_turno') in ('completed','idle'),
         'launcher_observer_not_demonstrated')
    need(probe['host_id']==mobile['host_id']==observer['host_id']==expected_host,'launcher_evidence_host_diverges')
    confirmation=mobile.get('confirmacao_dono')
    need(type(confirmation) is dict and type(confirmation.get('path')) is str and
         confirmation['path'].startswith(MOBILE_CONFIRMATION_PREFIX) and confirmation['path'].endswith('.md'),
         'launcher_mobile_owner_reference')
    if notebook_only:
        # The GitHub signature binds the eventual joint ratification bytes. Pinning
        # that file's hash here would create a cycle with the frozen plan hash.
        need(set(confirmation)=={'path'} and relative_git_path(confirmation['path']),
             'launcher_mobile_owner_reference')
        owner_raw=read_versioned(confirmation['path'])
        need(type(owner_raw) is bytes and 0<len(owner_raw)<=8*1024*1024,'launcher_evidence_hash')
    else:
        owner_raw=evidence(confirmation)
    terms=['CONFIRMO ACESSO NOTEBOOK' if notebook_only else 'CONFIRMO ACESSO DESKTOP E CELULAR',
           'LANCADOR '+q['lancador_sha256'], 'HOST '+expected_host,
           'SESSAO '+mobile['sessao_nativa']]
    if notebook_only:terms.append('CELULAR BLOQUEADO_DONO ORDEM 8')
    text=owner_raw.decode('utf-8','strict')
    need(all(term in text.splitlines() for term in terms),'launcher_mobile_owner_subject')
    need(callable(verify_owner),'launcher_mobile_owner_verifier_missing')
    verify_owner(confirmation['path'],terms)
    update=dt.get('atualizacao_b04',{})
    need(type(update) is dict,'launcher_legacy_flags_schema')
    flags=update.get('contencao_cl08_cl11')
    if flags is not None:
        need(type(flags) is dict,'launcher_legacy_flags_schema')
        need(flags.get('modo_real_bloqueado') is False and
             ((notebook_only and flags.get('prova_movel_real') is False and flags.get('prova_notebook_real') is True) or
              (not notebook_only and flags.get('prova_movel_real') is True)) and
             flags.get('observador_nativo_qualificado') is True,'launcher_legacy_flags_blocked')
    return proofs

def installed_bootstrap(argv=None):
    """Direct-source entrypoint; no local import or cached bytecode before hashes."""
    import argparse
    import sys
    import types
    need(sys.flags.isolated and sys.dont_write_bytecode,'installed_bootstrap_python_flags')
    parser=argparse.ArgumentParser(description='Verified installed judge bootstrap')
    parser.add_argument('--instalacao',required=True)
    parser.add_argument('--entrypoint',required=True,choices=('blocos','run_tests'))
    parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args(argv)
    deployment=validator_installation(args.instalacao)
    installed=Path(deployment['installed'])
    need(Path(__file__).absolute()==installed/'juiz_base.py','bootstrap_outside_installation')
    sources=installed_sources(installed,deployment['files'])
    # Executed directly by Python, this module never comes from __pycache__.
    # Every other local module executes the same bytes checked above.
    sys.modules['juiz_base']=sys.modules[__name__]
    modules={}
    for name in ('fichas','revisao_juiz','run_tests','blocos'):
        module=types.ModuleType(name)
        module.__file__=str(installed/(name+'.py'))
        module.__package__=''
        sys.modules[name]=module
        exec(compile(sources[name+'.py'],module.__file__,'exec',dont_inherit=True),module.__dict__)
        modules[name]=module
    tail=args.arguments
    if tail and tail[0]=='--':tail=tail[1:]
    sys.argv=[str(installed/(args.entrypoint+'.py')),'--instalacao',args.instalacao,*tail]
    return modules[args.entrypoint].main()


if __name__=='__main__':
    try:
        raise SystemExit(installed_bootstrap())
    except (Blocked,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'ok':False,'erro':str(exc)},ensure_ascii=False))
        raise SystemExit(1)

"""Plano CPU fechado; importar/construir nao executa nem autoriza unidade alguma.

O supervisor confiavel confere ato, hashes/posse, frente unica e gates antes
 de consumir argv. A observacao abaixo e de uma unidade, nao aceite operacional.
"""
import hashlib
import json
import re
from pathlib import Path
import os

ROOT = '/var/lib/sc-pesquisa/runtime-cpu/qualificacao'
RUNTIME = '/var/lib/sc-pesquisa/runtime-cpu/llama-b11960/llama-b11960'
MODEL = '/var/lib/sc-pesquisa/modelos/Qwen3.5-9B-Q4_K_M.gguf'
MODEL_SHA256 = 'cd76ec205963b3b33350093e6904d9de16c4e666fd104e1f632d25c7f15f2a13'
ARCHIVE_SHA256 = '31cc3a6bc638ac6c48dc4b1b74888f1eaadf3d14227c1e5f67daf9a49541d97a'
BASE = 'e7c5b0314d0620c013db6fd90241835a86bbb931'
PROBE_PREFIX = 'SC_CPU_PRE_EXEC_1 '
# This code is data until the separately authorized trusted supervisor starts it.
# It stops BEFORE exec; a missing/incorrect release byte never starts a binary.
PRE_EXEC = r"""import errno,json,os,socket,sys
spec=json.loads(sys.argv[1])
status=dict(line.split(':',1) for line in open('/proc/self/status') if ':' in line)
report={'schema':'sc-cpu-pre-exec/1','unit':spec['unit'],'operation':spec['operation'],
 'pid':os.getpid(),'uid':[int(x) for x in status['Uid'].split()],
 'gid':[int(x) for x in status['Gid'].split()], 'groups':os.getgroups(),
 'nnp':int(status['NoNewPrivs']), 'threads':int(status['Threads']),
 'caps':{k:status[k].strip() for k in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')},
 'cgroup':open('/proc/self/cgroup').read(), 'files':{},'negative':None}
for path in spec['files']:
 with open(path,'rb') as f: f.read(1)
 report['files'][path]={'readable':True,'readonly':bool(os.statvfs(path).f_flag & os.ST_RDONLY)}
if spec['operation']=='qualificacao':
 negative={}
 try:
  s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
 except OSError as e: negative['network_errno']=e.errno
 else: s.close();negative['network_errno']=None
 try:
  fd=os.open('/prova/prova.txt',os.O_WRONLY)
 except OSError as e: negative['write_errno']=e.errno
 else: os.close(fd);negative['write_errno']=None
 report['negative']=negative
print('SC_CPU_PRE_EXEC_1 '+json.dumps(report,sort_keys=True,separators=(',',':')),file=sys.stderr,flush=True)
if sys.stdin.buffer.read(1)!=b'R': raise SystemExit(125)
if spec['operation']!='qualificacao':
 os.execv(spec['exec'][0],spec['exec'])
"""


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True).encode()).hexdigest()


def plan(operation, nonce, identities, *, attempt=None, remaining_s=None):
    """Return argv and exact expectations. identities are claims, NOT approvals.

    Closed CPU3x3 and M1 two-turn operations, plus historical preparation.
    No caller paths, arbitrary flags, retry or launching on import.
    """
    cpu_generation = type(operation) is str and re.fullmatch(r'completion_T[123]_r[123]', operation) is not None
    m1_operation = operation in ('tokenize_m1_t1','tokenize_m1_t2','completion_m1_t1','completion_m1_t2')
    legacy = operation in ('qualificacao','completion_help','completion_version','tokenize_help',
                          'tokenize_version','tokenize_T1','tokenize_T2','tokenize_T3')
    need(type(operation) is str and (legacy or cpu_generation or m1_operation), 'operation')
    need(type(nonce) is str and re.fullmatch('[0-9a-f]{32}', nonce), 'nonce')
    tokenizing = operation in ('tokenize_T1','tokenize_T2','tokenize_T3','tokenize_m1_t1','tokenize_m1_t2')
    generating = cpu_generation or operation in ('completion_m1_t1','completion_m1_t2')
    qualifying = operation == 'qualificacao'
    if m1_operation:
        need(type(attempt) is str and re.fullmatch('[0-9a-f]{32}',attempt), 'attempt')
    else:
        need(attempt is None, 'unexpected_attempt')
    if cpu_generation or m1_operation:
        ceiling = 1800 if m1_operation else 900
        need(type(remaining_s) is int and 1 <= remaining_s <= ceiling, 'remaining_seconds')
        runtime_seconds = min(120, remaining_s) if tokenizing else remaining_s
    else:
        need(remaining_s is None, 'unexpected_deadline')
        runtime_seconds = 120 if tokenizing else 30
    expected_keys = {'fixture'} if qualifying else ({'executable','prompt'} if tokenizing or generating else {'executable'})
    need(type(identities) is dict and set(identities) == expected_keys, 'identities')
    need(all(type(v) is str and re.fullmatch('[0-9a-f]{64}',v) for v in identities.values()), 'sha256')
    unit = 'sc-cpu-prep-'+nonce+'.service'
    # No host /run, home, project, /var/lib, devices or sockets are bound.
    binds = [('/usr/bin/env','/usr/bin/env'),('/usr/bin/python3.10','/usr/bin/python3.10'),
             ('/usr/lib/python3.10','/usr/lib/python3.10'),
             ('/usr/lib/x86_64-linux-gnu','/usr/lib/x86_64-linux-gnu'),
             ('/usr/lib/x86_64-linux-gnu','/lib/x86_64-linux-gnu'),
             ('/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2','/lib64/ld-linux-x86-64.so.2')]
    files = {}
    command = []
    if qualifying:
        binds.append((ROOT+'/prova.txt','/prova/prova.txt'))
        files['/prova/prova.txt'] = identities['fixture']
    else:
        binary = 'llama-completion' if operation.startswith('completion_') else 'llama-tokenize'
        binds.append((RUNTIME,'/runtime'))
        files['/runtime/'+binary] = identities['executable']
        command = ['/runtime/'+binary]
        if tokenizing or generating:
            task = operation[-2:] if tokenizing else operation.split('_')[1]
            if m1_operation:
                prompt_source = M1_ROOT+'/estado-corrida/tentativa-'+attempt+'/turno-'+operation[-1]+'/'+('efetivo.txt' if tokenizing else 'transporte.txt')
            else:
                prompt_source = CPU_PROMPTS+('/prompts-efetivos/' if tokenizing else '/prompts-transporte/')+task+'.txt'
            binds += [(MODEL,'/model/model.gguf'),(prompt_source,'/prompt/prompt.txt')]
            files.update({'/model/model.gguf':MODEL_SHA256,'/prompt/prompt.txt':identities['prompt']})
            if tokenizing:
                command += ['--model','/model/model.gguf','--file','/prompt/prompt.txt','--ids','--no-escape']
            else:
                from . import frontend_cpu as f
                dt=f.e.strict_json((Path(__file__).resolve().parents[1]/f.e.DT_PATH).read_bytes())
                profile=f.profile_ok(dt)
                command=f.closed_arguments(profile,command[0],'/model/model.gguf','/prompt/prompt.txt',
                                           int(operation[-1]) if m1_operation else None)
        else:
            command += ['--help' if operation.endswith('_help') else '--version']
    properties = {
        'Type':'exec','User':'991','Group':'991','SupplementaryGroups':'',
        'RootDirectory':ROOT+'/rootfs','MountAPIVFS':'yes',
        'ProtectSystem':'strict','ProtectHome':'yes','PrivateTmp':'yes','PrivateDevices':'yes',
        'ProtectProc':'invisible','ProcSubset':'pid','NoNewPrivileges':'yes',
        'CapabilityBoundingSet':'','AmbientCapabilities':'','PrivateNetwork':'yes',
        'IPAddressDeny':'any','RestrictAddressFamilies':'AF_UNIX',
        'RestrictNamespaces':'yes','RestrictSUIDSGID':'yes','LockPersonality':'yes',
        'ProtectKernelTunables':'yes','ProtectKernelModules':'yes','ProtectKernelLogs':'yes',
        'ProtectControlGroups':'yes','CPUQuota':'300%','MemoryHigh':'7G','MemoryMax':'8G',
        'MemorySwapMax':'0','Nice':'10','TasksMax':'6','TasksAccounting':'yes',
        'RuntimeMaxSec':str(runtime_seconds),
        'TimeoutStopSec':'5','KillMode':'control-group','Restart':'no',
        'WorkingDirectory':'/','UMask':'0077',
        'BindReadOnlyPaths':' '.join(source+':'+target for source,target in binds),
        'UnsetEnvironment':'LD_PRELOAD LD_LIBRARY_PATH PYTHONPATH PYTHONHOME BASH_ENV ENV',
    }
    spec = {'unit':unit,'operation':operation,'files':files,'exec':command}
    argv = ['/usr/bin/systemd-run','--quiet','--wait','--pipe','--no-ask-password','--unit='+unit]
    argv += ['--property='+k+'='+v for k,v in properties.items()]
    argv += ['--','/usr/bin/env','-i','PATH=/usr/bin:/bin','LANG=C.UTF-8','LC_ALL=C.UTF-8',
             'OMP_THREAD_LIMIT=3','/usr/bin/python3.10','-I','-S','-B','-c',PRE_EXEC,
             json.dumps(spec,sort_keys=True,separators=(',',':'))]
    result = {'schema':'sc-cpu-plan/1','operation':operation,'unit':unit,'argv':argv,
              'properties':properties,'binds':[list(x) for x in binds],'files':files,'runtime_archive_sha256':ARCHIVE_SHA256,
              'base_cpu':BASE,'pre_exec_sha256':hashlib.sha256(PRE_EXEC.encode()).hexdigest()}
    if cpu_generation or m1_operation:
        result.update(attempt=attempt, remaining_s=remaining_s)
    result['sha256'] = digest(result)
    return result


def strict_json(raw):
    need(type(raw) is bytes and 0<len(raw)<=65536, 'report_bytes')
    def unique(pairs):
        value = {}
        for key, val in pairs:
            need(key not in value, 'duplicate_key')
            value[key] = val
        return value
    def invalid(value):
        raise ValueError('json_constant')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def check_pre_exec(p, report_raw, observed):
    """Check one held process. Never returns authorization or operational GO.

    observed is collected independently by the trusted supervisor WHILE held:
    systemctl show, cgroup pids.max/current, source hashes/RO bind manifest.
    Their collection/authority cannot be established from a dict or exit zero.
    """
    need(type(p) is dict and 'sha256' in p, 'plan')
    need(p['sha256']==digest({k:v for k,v in p.items() if k!='sha256'}), 'plan_changed')
    # Rebuild the only allowed argv; a self-consistent caller forgery is rejected.
    op=p['operation']; ids = ({'fixture':p['files'].get('/prova/prova.txt')} if op=='qualificacao'
         else {'executable':p['files'].get('/runtime/llama-completion' if op.startswith('completion_') else '/runtime/llama-tokenize')})
    if '/prompt/prompt.txt' in p['files']: ids['prompt']=p['files']['/prompt/prompt.txt']
    need(p==plan(op,p['unit'][12:-8],ids,attempt=p.get('attempt'),remaining_s=p.get('remaining_s')), 'plan_noncanonical')
    report = strict_json(report_raw)
    keys={'schema','unit','operation','pid','uid','gid','groups','nnp','threads','caps','cgroup','files','negative'}
    need(type(report) is dict and set(report)==keys,'report_schema')
    need(report['schema']=='sc-cpu-pre-exec/1' and report['unit']==p['unit'] and report['operation']==op,'report_binding')
    for name in ('uid','gid'):
        need(type(report[name]) is list and len(report[name])==4 and
             all(type(x) is int and x==991 for x in report[name]), 'identity')
    need(report['groups'] in ([],[991]) and all(type(x) is int for x in report['groups']), 'groups')
    need(type(report['nnp']) is int and report['nnp']==1,'nnp')
    need(type(report['threads']) is int and 1<=report['threads']<=6,'threads')
    need(report['caps']==dict.fromkeys(('CapInh','CapPrm','CapEff','CapBnd','CapAmb'),'0000000000000000'),'caps')
    need(type(report['pid']) is int and report['pid']>1,'pid')
    need(report['files']=={path:{'readable':True,'readonly':True} for path in p['files']},'files')
    for facts in report['files'].values():
        need(all(type(v) is bool for v in facts.values()),'file_types')
    if op=='qualificacao':
        negative=report['negative']
        need(type(negative) is dict and set(negative)=={'network_errno','write_errno'},'negative')
        # AF_INET construction must actually be denied, without DNS or endpoint.
        need(type(negative['network_errno']) is int and negative['network_errno'] in (1,13,97),'network')
        need(type(negative['write_errno']) is int and negative['write_errno'] in (1,13,30),'write')
    else: need(report['negative'] is None,'unexpected_probe')
    need(type(observed) is dict and set(observed)=={'show','pids_max','pids_current','source_hashes','readonly_binds'},'observation')
    need(observed['source_hashes']==p['files'],'source_hashes')
    need(observed['readonly_binds']==[list(x) for x in p['binds']],'binds')
    need(type(observed['pids_max']) is int and observed['pids_max']==6,'pids_max')
    need(type(observed['pids_current']) is int and 1<=observed['pids_current']<=6,'pids_current')
    show=observed['show']
    expected={'Id':p['unit'],'MainPID':str(report['pid']),'ActiveState':'active',
              'User':'991','Group':'991','NoNewPrivileges':'yes','PrivateNetwork':'yes',
              'ProtectSystem':'strict','ProtectHome':'yes','RootDirectory':ROOT+'/rootfs',
              'TasksMax':'6','MemoryHigh':str(7*1024**3),'MemoryMax':str(8*1024**3),
              'MemorySwapMax':'0','CPUQuotaPerSecUSec':'3s','Nice':'10',
              'CapabilityBoundingSet':'','AmbientCapabilities':'',
              'Type':'exec','Restart':'no','KillMode':'control-group','PrivateDevices':'yes',
              'PrivateTmp':'yes','RestrictNamespaces':'yes','SupplementaryGroups':'',
              'WorkingDirectory':'/','UMask':'0077',
              'ProtectProc':'invisible','ProcSubset':'pid','MountAPIVFS':'yes',
              'ProtectKernelTunables':'yes','ProtectKernelModules':'yes','ProtectKernelLogs':'yes',
              'ProtectControlGroups':'yes','RestrictSUIDSGID':'yes','LockPersonality':'yes',
              'RestrictAddressFamilies':'AF_UNIX','TasksAccounting':'yes',
              'RuntimeMaxUSec':systemd_span(int(p['properties']['RuntimeMaxSec'])),
              'TimeoutStopUSec':'5s'}
    need(type(show) is dict and all(show.get(k)==v for k,v in expected.items()),'unit_properties')
    denied=show.get('IPAddressDeny')
    need(type(denied) is str and (denied=='any' or
         set(denied.split())=={'0.0.0.0/0','::/0'}), 'ip_address_deny')
    cg=show.get('ControlGroup')
    need(type(cg) is str and cg=='/system.slice/'+p['unit'],'unit_cgroup')
    need(report['cgroup']=='0::'+cg+'\n','process_cgroup')
    return {'schema':'sc-cpu-pre-exec-checked/1','plan_sha256':p['sha256'],'unit':p['unit'],
            'pid':report['pid'],'scope':'held_process_only','operational_go':False}


CPU_PROMPTS = ROOT+'/cpu-m1-04'
M1_ROOT = '/var/lib/sc-pesquisa/runtime-cpu/m1-r'
AUX_EXE = '/usr/local/lib/sc-pesquisa/codex-code-mode-host'
AUX_SHA256 = '657f4e902726e05867c937b583049d5997e057f8cd0ab40450633c9c9ef8d630'
APP_EXE = '/usr/local/lib/sc-pesquisa/codex'


def systemd_span(seconds):
    minutes, seconds = divmod(seconds, 60)
    return ' '.join(x for x in ((str(minutes)+'min') if minutes else '',
                               (str(seconds)+'s') if seconds or not minutes else '') if x)


def classify_residents(rows, current_unit=None):
    """Pure check of native observations. An idle UI alone is never sufficient."""
    need(type(rows) is list, 'residents')
    need(current_unit is None or type(current_unit) is str and re.fullmatch(r'sc-(?:cpu-prep|m1-python)-[0-9a-f]{32}\.service',current_unit), 'current_unit')
    by_pid = {}
    for row in rows:
        need(type(row) is dict and set(row)=={'pid','ppid','exe','exe_sha256','argv','cgroup','children'}, 'resident_schema')
        need(type(row['pid']) is int and row['pid']>1 and row['pid'] not in by_pid, 'resident_pid')
        need(type(row['ppid']) is int and type(row['children']) is list and
             all(type(x) is int for x in row['children']), 'resident_children')
        by_pid[row['pid']]=row
    kinds={}
    for pid,row in by_pid.items():
        exe,args,cg=row['exe'],row['argv'],row['cgroup']
        if current_unit and cg=='0::/system.slice/'+current_unit+'\n':
            kind='current_authorized_unit'
        elif exe=='/usr/lib/systemd/systemd' and ('--user' in args or '(sd-pam)' in args):
            kind='systemd_user'
        elif exe=='/usr/sbin/sshd':
            kind='sshd_session'
        elif exe==APP_EXE and 'app-server' in args:
            need(re.fullmatch(r'0::/user.slice/user-991.slice/session-[0-9]+\.scope\n',cg) is not None,'app_scope')
            kind='codex_app_server'
        elif exe==AUX_EXE:
            need(row['exe_sha256']==AUX_SHA256 and not row['children'],'aux_hash_or_children')
            parent=by_pid.get(row['ppid'])
            need(parent is not None and parent['exe']==APP_EXE and 'app-server' in parent['argv']
                 and parent['cgroup']==cg and pid in parent['children'], 'aux_parent_scope')
            kind='codex_auxiliary'
        else:
            raise ValueError('uid991_unclassified')
        kinds[pid]=kind
    for pid,kind in kinds.items():
        if kind=='codex_app_server':
            # Check children from every parent thread and reverse PPid relation.
            reported=set(by_pid[pid]['children'])
            actual={child for child,row in by_pid.items() if row['ppid']==pid}
            need(reported==actual and all(kinds.get(child)=='codex_auxiliary' for child in actual),'active_native_children')
    return [dict(by_pid[pid],classification=kinds[pid]) for pid in sorted(by_pid)]


def residents(current_unit=None):
    rows=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            uid=p.stat().st_uid
        except (FileNotFoundError, ProcessLookupError):
            continue
        if uid!=991:continue
        try:
            st=dict(x.split(':',1) for x in (p/'status').read_text().splitlines() if ':' in x)
            need(st['Uid'].split()==['991']*4 and st['Gid'].split()==['991']*4,'resident_identity')
            exe=str((p/'exe').resolve(strict=True))
            start=(p/'stat').read_text().rsplit(')',1)[1].split()[19]
            tids=sorted(x.name for x in (p/'task').iterdir())
            children=set()
            for task in (p/'task').iterdir():
                children.update(int(x) for x in (task/'children').read_text().split())
            args=[x.decode('utf-8','strict') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
            comm=(p/'comm').read_text().strip()
            cg=(p/'cgroup').read_text()
            if comm=='(sd-pam)':args.append('(sd-pam)')
            need((p/'stat').read_text().rsplit(')',1)[1].split()[19]==start and sorted(x.name for x in (p/'task').iterdir())==tids,'resident_changed_during_observation')
            again=dict(x.split(':',1) for x in (p/'status').read_text().splitlines() if ':' in x)
            args_again=[x.decode('utf-8','strict') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
            if (p/'comm').read_text().strip()=='(sd-pam)':args_again.append('(sd-pam)')
            children_again=set()
            for task in (p/'task').iterdir():
                children_again.update(int(x) for x in (task/'children').read_text().split())
            need(str((p/'exe').resolve(strict=True))==exe and args_again==args and again['PPid']==st['PPid']
                 and again['Uid']==st['Uid'] and again['Gid']==st['Gid'] and (p/'cgroup').read_text()==cg
                 and children_again==children,'resident_changed_during_observation')
            rows.append({'pid':int(p.name),'ppid':int(st['PPid']),'exe':exe,
                         'exe_sha256':hashlib.sha256((p/'exe').read_bytes()).hexdigest() if exe==AUX_EXE else None,
                         'argv':args,'cgroup':cg,'children':sorted(children)})
        except (FileNotFoundError, ProcessLookupError):
            raise ValueError('resident_changed_during_observation')
    return classify_residents(rows,current_unit)

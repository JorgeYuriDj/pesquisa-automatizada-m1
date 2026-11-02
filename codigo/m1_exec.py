"""Closed, inactive M1 Python adapter. Real invocation requires signed final act.

The model supplies JSON/code only; it never supplies a receipt, path or command.
No functions run on import. Qualification itself is not implemented/repeated here.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time
from . import cpu_launcher as cpu
from . import m1

ROOT='/var/lib/sc-pesquisa/runtime-cpu/m1-r'
ACT='docs/decisoes/confirmacoes/B05-CPU-M1-04.md'
MANIFEST='docs/decisoes/B05-CPU-M1-04-manifesto.json'
FREEZE='0abf77a2d59e1aa56c6d2853b82d5a7c37044a9f5d742b349870d542f42dc5bb'
KEYS='85ca0fe4f7b4c52298ac01443b5bb574977222ea'
PRELUDE=r"""import hashlib,json,os,sys
p='/codigo.py'
s=dict(x.split(':',1) for x in open('/proc/self/status') if ':' in x)
v={'pid':os.getpid(),'uid':s['Uid'].split(),'gid':s['Gid'].split(),
'nnp':s['NoNewPrivs'].strip(),'caps':{k:s[k].strip() for k in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')},
'code_sha256':hashlib.sha256(open(p,'rb').read()).hexdigest(),
'ro':bool(os.statvfs(p).f_flag & os.ST_RDONLY),'cgroup':open('/proc/self/cgroup').read()}
print('SC_M1_HELD_1 '+json.dumps(v,sort_keys=True),file=sys.stderr,flush=True)
if sys.stdin.buffer.read(1)!=b'R':raise SystemExit(125)
os.execv('/usr/bin/python3',['/usr/bin/python3','-I','-S','/codigo.py'])
"""

def owned(path):
    p=Path(path)
    m1.e.require(not p.is_symlink(),'m1_source_link')
    for part in (p,*p.parents):
        st=part.stat()
        m1.e.require(st.st_uid==0 and not st.st_mode&0o022,'m1_source_owner')
    return p

def plano(attempt,code_sha):
    m1.e.require(type(attempt) is str and m1.re.fullmatch('[0-9a-f]{32}',attempt),'m1_attempt')
    m1.e.require(type(code_sha) is str and m1.re.fullmatch('[0-9a-f]{64}',code_sha),'m1_code_hash')
    baseline=cpu.plan('qualificacao',attempt,{'fixture':code_sha})
    props=dict(baseline['properties'])
    unit='sc-m1-python-'+attempt+'.service'
    binds=[pair[:] for pair in baseline['binds'][:-1]]
    binds[1]=['/usr/bin/python3.10','/usr/bin/python3']
    binds.append([ROOT+'/'+attempt+'/codigo.py','/codigo.py'])
    props.update(RootDirectory=ROOT+'/'+attempt+'/rootfs',WorkingDirectory='/',RuntimeMaxSec='10',
                 BindReadOnlyPaths=' '.join(s+':'+t for s,t in binds))
    argv=['/usr/bin/systemd-run','--quiet','--wait','--pipe','--no-ask-password','--unit='+unit]
    argv+=['--property='+k+'='+v for k,v in props.items()]
    argv+=['--','/usr/bin/env','-i','PATH=/usr/bin:/bin','LANG=C.UTF-8','LC_ALL=C.UTF-8',
           'OMP_THREAD_LIMIT=3','/usr/bin/python3','-I','-S','-B','-c',PRELUDE]
    return {'unit':unit,'argv':argv,'properties':props,'binds':binds,'code_sha256':code_sha,
            'calculation_argv':['/usr/bin/python3','-I','-S','/codigo.py']}

def lote_confiavel(root):
    frozen=owned(Path(root)/'docs/evidencias/bloco5-2026-10-31/m1-congelamento.json').read_bytes()
    if m1.h(frozen)!=FREEZE:raise m1.Incidente('m1_freeze_changed')
    freeze=m1.e.strict_json(frozen)
    mapping={'escopo.md':('escopo',freeze['escopo_sha256']),
             'contrato.md':('contrato',freeze['contrato_sha256']),
             'exemplo_certo.md':('exemplo_certo',freeze['exemplos']['certo_sha256']),
             'exemplo_a_recusar.md':('exemplo_a_recusar',freeze['exemplos']['a_recusar_sha256']),
             'constantes.json':('constantes',freeze['constantes']['sha256'])}
    files={};hashes={}
    for name,(key,pin) in mapping.items():
        rel='docs/evidencias/bloco5-2026-10-31/m1/'+name
        m1.e.require(freeze['arquivos'][key]==rel,'m1_frozen_path')
        files[name]=owned(Path(root)/rel).read_bytes();hashes[name]=pin
    return {'inputs':m1.lote(files,hashes),'files':files,'hashes':hashes}

def estado_ativo(marker,attempt):
    marker=owned(marker)
    expected=Path(ROOT)/'estado-corrida'/('tentativa-'+attempt)
    m1.e.require(marker==expected and marker.is_dir(),'m1_canonical_attempt')
    state=m1.e.strict_json(owned(marker.parent/'estado.json').read_bytes())
    m1.e.require(state['active']==attempt and attempt in state['used'] and state['terminal'] is None and state['seal'] is None,'m1_attempt_ativa')
    if state['freeze']!=FREEZE or state['boot_id']!=m1.boot_id():raise m1.Incidente('m1_lote_ou_boot_alterado')
    now=time.monotonic_ns()
    m1.e.require(now>=state['last_ns']>=state['start_ns'],'m1_clock_regressao')
    m1.e.require(now-state['start_ns']<=1_790_000_000_000,'m1_tempo_insuficiente')
    return state


def cpu_aprovada(root,ref):
    # Freeze inputs before the act; verify future raw results, never a pass flag.
    m1.e.require(type(ref) is dict and set(ref)=={'criterio_sha256','dt_sha256','resultado_path'},'m1_cpu_ref')
    m1.e.require(ref['resultado_path']=='docs/evidencias/bloco5-2026-10-31/qualificacao2-cpu-resultado.json','m1_cpu_result_path')
    criterion=owned(Path(root)/'docs/decisoes/DT-B05-CRITERIO-CPU-02.json').read_bytes()
    dt_raw=owned(Path(root)/m1.e.DT_PATH).read_bytes()
    m1.e.require(m1.h(criterion)==ref['criterio_sha256'] and m1.h(dt_raw)==ref['dt_sha256'],'m1_cpu_input_hash')
    result=owned(Path(root)/ref['resultado_path']).read_bytes()
    log=owned(Path(root)/'docs/evidencias/bloco5-2026-10-31/qualificacao2-cpu-log.jsonl').read_bytes()
    m1.e.require(m1.e.conferir_teste_cpu(criterion,result,log,m1.e.strict_json(dt_raw),qualification=2)=='APROVADO','m1_cpu_not_approved')
    return {'result_sha256':m1.h(result),'log_sha256':m1.h(log)}


def autoridade(root,current_unit=None):
    """One authority path shared with the model collector, preserving native checks."""
    from . import cpu_exec
    trusted=cpu_exec.authority(root,'m1_python',current_unit)
    return dict(lote_confiavel(root),manifest=trusted['manifest'],residents=trusted['residents'])


def observar(plan,raw):
    """Independent held-process observation; every source binding is checked."""
    value=m1.e.strict_json(raw)
    m1.e.require(type(value) is dict and set(value)=={'pid','uid','gid','nnp','caps','code_sha256','ro','cgroup'},'m1_prelude_schema')
    m1.e.require(type(value['pid']) is int and value['pid']>1 and value['uid']==['991']*4 and value['gid']==['991']*4,'m1_identity')
    m1.e.require(value['nnp']=='1' and value['ro'] is True and value['code_sha256']==plan['code_sha256'],'m1_prelude')
    m1.e.require(value['caps']==dict.fromkeys(('CapInh','CapPrm','CapEff','CapBnd','CapAmb'),'0000000000000000'),'m1_caps')
    show=subprocess.run(['systemctl','show','--all',plan['unit']],capture_output=True,text=True,check=True,timeout=2).stdout
    observed=dict(line.split('=',1) for line in show.splitlines() if '=' in line)
    expected={k:v for k,v in plan['properties'].items() if k not in ('CPUQuota','MemoryHigh','MemoryMax','RuntimeMaxSec','TimeoutStopSec','BindReadOnlyPaths','UnsetEnvironment')}
    expected.update(Id=plan['unit'],MainPID=str(value['pid']),ActiveState='active',
                    CPUQuotaPerSecUSec='3s',MemoryHigh=str(7*1024**3),MemoryMax=str(8*1024**3),RuntimeMaxUSec='10s',TimeoutStopUSec='5s')
    denied=expected.pop('IPAddressDeny')
    m1.e.require(all(observed.get(k)==v for k,v in expected.items()),'m1_native_properties')
    m1.e.require(observed.get('IPAddressDeny')=='any' or set(observed.get('IPAddressDeny','').split())=={'0.0.0.0/0','::/0'},'m1_ip_deny')
    cg='/system.slice/'+plan['unit'];m1.e.require(observed.get('ControlGroup')==cg and value['cgroup']=='0::'+cg+'\n','m1_cgroup')
    proc=Path('/proc')/str(value['pid'])
    status=dict(x.split(':',1) for x in (proc/'status').read_text().splitlines() if ':' in x)
    m1.e.require(status['Uid'].split()==value['uid'] and status['Gid'].split()==value['gid'] and status['PPid'].strip()=='1','m1_native_identity')
    for ns in ('mnt','net'):m1.e.require(os.readlink(proc/'ns'/ns)!=os.readlink('/proc/self/ns/'+ns),'m1_namespace')
    cgpath=Path('/sys/fs/cgroup'+cg)
    m1.e.require((cgpath/'pids.max').read_text().strip()=='6' and 1<=int((cgpath/'pids.current').read_text())<=6,'m1_pids')
    environment=(proc/'environ').read_bytes().rstrip(b'\0').split(b'\0')
    m1.e.require(set(environment)=={b'PATH=/usr/bin:/bin',b'LANG=C.UTF-8',b'LC_ALL=C.UTF-8',b'OMP_THREAD_LIMIT=3'},'m1_environment')
    mountinfo=(proc/'mountinfo').read_text()
    for source,target in plan['binds']:
        src=owned(source).stat();dst=(proc/'root'/target.lstrip('/')).stat()
        m1.e.require((src.st_dev,src.st_ino)==(dst.st_dev,dst.st_ino),'m1_bind_identity')
        entries=[line.split() for line in mountinfo.splitlines() if line.split()[4]==target]
        m1.e.require(entries and 'ro' in entries[-1][5].split(','),'m1_bind_readonly')
    return {'show':show,'mountinfo':mountinfo,'prelude':value}

def capturar(root,attempt,first_raw,inputs,marker,remaining_seconds):
    """One real Python execution, blocked until final signed manifest exists.

    Reserve execucao before launch; any uncertain capture is terminal, never retry.
    Only admitted code is staged. Runtime files and receipts remain on the VPS.
    """
    code=m1.codigo_admissivel(first_raw,inputs)  # no effect before AST admission
    before=autoridade(root)
    if inputs!=before['inputs']:raise m1.Incidente('m1_inputs_nao_congelados')
    from . import cpu_exec
    cpu_exec.require_generation(root,attempt,1,first_raw)
    estado_ativo(marker,attempt)
    m1.e.require(type(remaining_seconds) in (int,float) and remaining_seconds>=10,'m1_time_remaining')
    marker=owned(marker)
    m1.e.require(marker.name=='tentativa-'+attempt,'m1_attempt_directory')
    evidence=marker/'execucao';evidence.mkdir(mode=0o700,exist_ok=False)
    source=Path(ROOT)/attempt;source.mkdir(mode=0o755,exist_ok=False)
    (source/'rootfs').mkdir(mode=0o755,exist_ok=False)
    path=source/'codigo.py'
    with path.open('xb') as f:f.write(code);f.flush();os.fsync(f.fileno())
    path.chmod(0o644)
    plan=plano(attempt,m1.h(code))
    (evidence/'processos-antes.json').write_text(json.dumps(before['residents'],sort_keys=True)+'\n')
    (evidence/'turno1.json').write_bytes(first_raw);(evidence/'plan.json').write_text(json.dumps(plan,sort_keys=True)+'\n')
    start=time.monotonic_ns();proc=None;out=b'';err=b'';pre=b'';timed=False;complete=False;rc=None;failure=None;released=False;obs=None
    try:
        proc=subprocess.Popen(plan['argv'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                              env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'},bufsize=0)
        selector=selectors.DefaultSelector();selector.register(proc.stderr,selectors.EVENT_READ)
        until=time.monotonic()+3
        while b'\n' not in pre and time.monotonic()<until:
            if not selector.select(max(0,until-time.monotonic())):break
            chunk=os.read(proc.stderr.fileno(),65536)
            if not chunk:break
            pre+=chunk;m1.e.require(len(pre)<=65536,'m1_prelude_limit')
        selector.close();line,sep,err=pre.partition(b'\n')
        m1.e.require(sep==b'\n' and line.startswith(b'SC_M1_HELD_1 '),'m1_prelude_missing')
        pre=line+sep;obs=observar(plan,line[len(b'SC_M1_HELD_1 '):])
        (evidence/'observed.json').write_text(json.dumps(obs,sort_keys=True)+'\n')
        autoridade(root,plan['unit'])  # repeat gates before release, not another execution
        estado_ativo(marker,attempt)
        proc.stdin.write(b'R');proc.stdin.flush();released=True
    except BaseException as ex:failure=type(ex).__name__+':'+str(ex)
    finally:
        prefix=err
        if proc:
            try:proc.stdin.close()
            except BaseException as ex:failure=(failure or '')+';stdin:'+str(ex)
            proc.stdin=None
            try:
                out,rest=proc.communicate(timeout=max(.1,10-(time.monotonic_ns()-start)/1e9))
                err=prefix+rest;rc=proc.returncode;complete=True
            except subprocess.TimeoutExpired as ex:
                timed=True;out=ex.output or b'';err=prefix+(ex.stderr or b'')
                try:subprocess.run(['systemctl','stop',plan['unit']],capture_output=True,timeout=6,check=True)
                except BaseException as stop:failure=(failure or '')+';stop:'+str(stop)
                try:
                    out,rest=proc.communicate(timeout=2);err=prefix+rest;rc=proc.returncode;complete=True
                except BaseException as late:failure=(failure or '')+';capture:'+str(late)
            except BaseException as ex:failure=(failure or '')+';communicate:'+str(ex)
        duration=time.monotonic_ns()-start
        try:
            post=subprocess.run(['systemctl','show','--all',plan['unit'],'--property=ActiveState,MainPID'],capture_output=True,text=True,timeout=2,check=True).stdout
            (evidence/'post.stdout').write_text(post)
            states=dict(x.split('=',1) for x in post.splitlines() if '=' in x)
            complete=complete and states.get('MainPID')=='0' and states.get('ActiveState') in ('inactive','failed')
        except BaseException as ex:complete=False;failure=(failure or '')+';post:'+str(ex)
        if len(out)>65536 or len(err)>65536:failure=(failure or '')+';capture_limit';complete=False
        for name,data in [('stdout.bin',out),('stderr.bin',err),('prelude.stderr',pre)]: (evidence/name).write_bytes(data)
        receipt={'schema':'sc-m1-exec-capture/1','attempt':attempt,'code_sha256':m1.h(code),'stdout_sha256':m1.h(out),'stderr_sha256':m1.h(err),
                 'argv':plan['calculation_argv'],'returncode':rc,'timeout':timed,'complete':bool(complete and released and failure is None),'duration_ns':duration}
        (evidence/'recibo.json').write_text(json.dumps(receipt,sort_keys=True)+'\n')
        (evidence/'coletor.json').write_text(json.dumps({'released':released,'failure':failure,'start_ns':start,'end_ns':start+duration,'unit':plan['unit']},sort_keys=True)+'\n')
    if not receipt['complete']:raise m1.Incidente('m1_execucao_ou_captura_incerta')
    if timed or rc!=0:raise RuntimeError('m1_erro_execucao')
    m1.conferir_fluxos(attempt,first_raw,out,err,receipt)
    return out,err,receipt

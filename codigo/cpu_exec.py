"""Trusted CPU/M1 collector. No launch on import; signed manifest and review gates precede every unit."""
import os,sys,json,pathlib,hashlib,subprocess,datetime,stat,uuid,selectors,time
from . import cpu_launcher as m
from . import frontend_cpu as f
from . import executor_modelo as e
from . import m1
from . import m1_exec
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")
def digest(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def js(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def call(args):return subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=8,check=True).stdout
def owned(p):
 p=pathlib.Path(p).resolve(strict=True)
 for x in (p,*p.parents):
  s=x.stat();assert s.st_uid==0 and not s.st_mode&0o022,('source_not_protected',str(x),s.st_uid,oct(s.st_mode))
 return {'path':str(p),'uid':p.stat().st_uid,'gid':p.stat().st_gid,'mode':oct(stat.S_IMODE(p.stat().st_mode)),'inode':p.stat().st_ino,'device':p.stat().st_dev}
def residents(unit=None):
 return m.residents(unit)
def preflight(root,operation,current_unit=None):
 return authority(root,operation,current_unit)
def prepare_source_manifest(plan):
 manifest=[]
 seen=set()
 for source,target in plan['binds']:
  data=owned(source);data['target']=target
  if pathlib.Path(source).is_dir():
   n=0;h=hashlib.sha256()
   for root,dirs,files in os.walk(source,followlinks=False):
    for name in sorted(dirs+files):
     child=pathlib.Path(root)/name
     if str(child) in seen:continue
     seen.add(str(child));info=owned(child)
     h.update(json.dumps(info,sort_keys=True).encode());n+=1
   data.update({'entries_checked':n,'metadata_digest':h.hexdigest()})
  else:data['sha256']=digest(source)
  manifest.append(data)
 return manifest
def execute(root, operation, attempt=None):
 """Exactly one closed operation. Existing evidence forbids retries."""
 global R
 R=pathlib.Path(root)
 import sys
 sys.path.insert(0,'/usr/local/lib/sc-pesquisa/juiz')
 import blocos as b
 with b.repo_lock(R):
  before=preflight(R,operation)
  out,deadline,remaining=reserve(R,operation,attempt)
  if '_m1_' in operation:
   if operation.startswith('completion'):check_m1(R,attempt,int(operation[-1]))
   else:check_m1_render(R,attempt,int(operation[-1]))
  else:check_cpu_prompt(R,before,operation)
  ids=identities(operation,attempt)
  plan=m.plan(operation,uuid.uuid4().hex,ids,attempt=attempt,remaining_s=remaining)
  js(out/'plan.json',plan)
  js(out/'processos-antes.json',before['residents'])
  js(out/'fontes.json',prepare_source_manifest(plan))
  js(out/'inicio.json',{'utc':now(),'operation':operation,'unit':plan['unit'],'ptrace_scope':int(pathlib.Path('/proc/sys/kernel/yama/ptrace_scope').read_text()),'supervisor_sha256':digest(__file__),'unica_tentativa':True,'deadline_ns':deadline})
  op=operation
  started=time.monotonic();proc=None;first=b'';remaining=b'';stdout=b'';released=False;checked=None;error=None;exitcode=None;post={}
  try:
   if deadline is not None:e.require(time.monotonic_ns()<deadline,'deadline_before_launch')
   proc=subprocess.Popen(plan['argv'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','LC_ALL':'C.UTF-8'},bufsize=0)
   sel=selectors.DefaultSelector();sel.register(proc.stderr,selectors.EVENT_READ)
   until=started+20
   while b'\n' not in first and time.monotonic()<until:
    ready=sel.select(max(0,until-time.monotonic()))
    if not ready:break
    piece=os.read(proc.stderr.fileno(),65536)
    if not piece:break
    first+=piece
    assert len(first)<=65536,'first_report_too_long'
   sel.close()
   assert b'\n' in first,'prelude_missing_or_timeout'
   line,remaining=first.split(b'\n',1);first=line+b'\n'
   assert line.startswith(m.PROBE_PREFIX.encode()),'unexpected_stderr_before_prelude'
   raw=line[len(m.PROBE_PREFIX):]
   report=m.strict_json(raw);pid=report['pid'];pp=pathlib.Path('/proc')/str(pid)
   show_raw=call(['systemctl','show','--all',plan['unit']])
   (out/'systemctl-held.stdout').write_text(show_raw)
   show=dict(x.split('=',1) for x in show_raw.splitlines() if '=' in x)
   direct_status=(pp/'status').read_text();(out/'proc-status-held.txt').write_text(direct_status)
   status=dict(x.split(':',1) for x in direct_status.splitlines() if ':' in x)
   for key,field in [('Uid','uid'),('Gid','gid')]:assert [int(x) for x in status[key].split()]==report[field]
   assert int(status['PPid'])==1
   environment=(pp/'environ').read_bytes().split(b'\0')
   for value in (b'OMP_THREAD_LIMIT=3',):
    e.require(environment.count(value)==1,'held_environment')
   assert (pp/'cgroup').read_text()==report['cgroup']
   namespaces={key:os.readlink(pp/'ns'/key) for key in ['mnt','net','pid','user']}
   assert namespaces['mnt']!=os.readlink('/proc/self/ns/mnt')
   assert namespaces['net']!=os.readlink('/proc/self/ns/net')
   js(out/'namespaces.json',namespaces)
   mounts=(pp/'mountinfo').read_text();(out/'mountinfo-held.txt').write_text(mounts)
   readonly=[];sources={};actual_binds=[]
   parsed=[]
   for ln in mounts.splitlines():
    fields=ln.split();parsed.append((fields[4],fields[5].split(','),ln))
   for source,target in plan['binds']:
    source_stat=pathlib.Path(source).stat();dest_stat=(pp/'root'/target.lstrip('/')).stat()
    assert (source_stat.st_dev,source_stat.st_ino)==(dest_stat.st_dev,dest_stat.st_ino),('bind_identity',source,target)
    matching=[x for x in parsed if x[0]==target]
    assert matching and 'ro' in matching[-1][1],('bind_not_readonly',target)
    readonly.append([source,target]);actual_binds.append({'source':source,'target':target,'device':dest_stat.st_dev,'inode':dest_stat.st_ino,'mountinfo':matching[-1][2]})
   js(out/'binds-observados.json',actual_binds)
   for target in plan['files']:
    matches=sorted([(s,t) for s,t in plan['binds'] if target==t or target.startswith(t+'/')],key=lambda v:len(v[1]))
    assert matches
    source,t=matches[-1];physical=pathlib.Path(source+target[len(t):]);owned(physical)
    sources[target]=digest(physical)
   cg=pathlib.Path('/sys/fs/cgroup'+show['ControlGroup'])
   observed={'show':show,'pids_max':int((cg/'pids.max').read_text()),'pids_current':int((cg/'pids.current').read_text()),'source_hashes':sources,'readonly_binds':readonly}
   js(out/'observed.json',observed)
   checked=m.check_pre_exec(plan,raw,observed);js(out/'checked.json',checked)
   preflight(R,operation,plan['unit'])
   if deadline is not None: e.require(time.monotonic_ns()<deadline,'deadline_before_release')
   transport=json.loads((R/'.git/sc-auth/admin-transport.json').read_text())
   fresh_env=dict(os.environ,GIT_SSH_COMMAND=transport['ssh_command'],GIT_TERMINAL_PROMPT='0')
   fresh_remote=subprocess.check_output(['git','-C',str(R),'ls-remote','origin','refs/heads/main'],env=fresh_env,text=True,timeout=8).split()[0]
   assert fresh_remote==call(['git','-C',str(R),'rev-parse','HEAD']).strip(),'remote_changed_before_release'
   assert not (R/'PARE').exists() and not (R/'blocos/PARE').exists()
   proc.stdin.write(b'R');proc.stdin.flush();released=True
  except BaseException as ex:error=type(ex).__name__+': '+str(ex)
  finally:
   if proc is not None:
    manual_rest=remaining
    if proc.stdin is not None:
     proc.stdin.close();proc.stdin=None
    try:
     stdout,err=proc.communicate(timeout=max(.001, min(int(plan['properties']['RuntimeMaxSec'])-(time.monotonic()-started), (deadline-time.monotonic_ns())/1e9 if deadline is not None else 120)))
     remaining=manual_rest+err;exitcode=proc.returncode
    except subprocess.TimeoutExpired as ex:
     stdout=ex.output or b'';remaining=manual_rest+(ex.stderr or b'')
     error=(error+'; ' if error else '')+'supervisor_timeout'
     try:
      stopped=subprocess.run(['systemctl','stop',plan['unit']],capture_output=True,timeout=10)
      js(out/'stop-result.json',{'returncode':stopped.returncode,'stdout':stopped.stdout.decode(errors='replace'),'stderr':stopped.stderr.decode(errors='replace')})
     except BaseException as stop_error:
      error+='; stop_unconfirmed: '+str(stop_error)
     try:
      stdout,err=proc.communicate(timeout=10);remaining=manual_rest+err;exitcode=proc.returncode
     except subprocess.TimeoutExpired as late:
      stdout=late.output or stdout
      if late.stderr is not None:remaining=manual_rest+late.stderr
      error+='; process_still_unconfirmed'
     except BaseException as late:
      error+='; capture_failed: '+str(late)
    except BaseException as ex:
     error=(error+'; ' if error else '')+'capture_failed: '+str(ex)
    try:
     postcp=subprocess.run(['systemctl','show',plan['unit'],'--property=ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,MainPID'],capture_output=True,text=True,timeout=8)
     post={'returncode':postcp.returncode,'stdout':postcp.stdout,'stderr':postcp.stderr}
    except BaseException as ex:
     error=(error+'; ' if error else '')+'post_state_unavailable: '+str(ex)
     post={'unavailable':str(ex)}
   (out/'prelude.stderr').write_bytes(first);(out/'stderr-restante.bin').write_bytes(remaining);(out/'stdout.bin').write_bytes(stdout)
   js(out/'unit-after.json',post)
   try:after=residents();js(out/'processos-depois.json',after)
   except BaseException as ex:error=(error+'; ' if error else '')+'post_processes: '+str(ex)
   state_after=dict(x.split('=',1) for x in post.get('stdout','').splitlines() if '=' in x)
   if state_after.get('ActiveState') not in ('inactive','failed') or state_after.get('MainPID')!='0':
    error=(error+'; ' if error else '')+'termination_not_confirmed'
   if deadline is not None and time.monotonic_ns()>deadline: error=(error+'; ' if error else '')+'deadline_exceeded'
   limit=f.MAX_STDERR if operation.startswith('tokenize') else e.MAX_SAIDA
   if len(stdout)>limit or len(remaining)>f.MAX_STDERR:error=(error+'; ' if error else '')+'capture_limit'
   success=bool(checked and released and exitcode==0 and error is None)
   result={'utc':now(),'operation':op,'unit':plan['unit'],'success':success,'error':error,'released_R':released,'exit_code':exitcode,'duration_seconds':time.monotonic()-started,'runtime_operational_go':False,'repeat_allowed':False}
   js(out/'resultado.json',result);print(json.dumps(result),flush=True)
  e.require(success,'native_capture_failed')
  return {'path':str(out),'plan':plan,'stdout':stdout,'stderr':remaining,'returncode':exitcode,'result':result}


CRITERIO_PATH='docs/decisoes/DT-B05-CRITERIO-CPU-02.json'
LOG_PATH='docs/evidencias/bloco5-2026-10-31/qualificacao2-cpu-log.jsonl'
RESULT_PATH='docs/evidencias/bloco5-2026-10-31/qualificacao2-cpu-resultado.json'
MANIFEST='docs/decisoes/B05-CPU-M1-07-manifesto.json'
PREPARATION_MANIFEST='docs/decisoes/B05-CPU-M1-04-manifesto.json'
PREPARATION_MANIFEST_SHA='d87d110c78b538fdf1aeee5d1b069104047c0e4d660d237ab030af15a39f5a67'
ACT='docs/decisoes/confirmacoes/B05-CPU-M1-07.md'
EVIDENCE='docs/evidencias/bloco5-2026-10-31/cpu-m1-04-preparacao'
PREPARED=EVIDENCE+'/dt-preparada.json'
PREP_REVIEW='coord/outbox/claude/sc-b05-cpu-m1-04-preparacao-revisao.json'
CODE_REVIEW='coord/outbox/claude/sc-b05-cpu-m1-07-consolidado-revisao.json'
CPU_STATE=pathlib.Path(m.ROOT)/'cpu-rodada-qualificacao2'
ORDER=tuple('completion_T%d_r%d'%(task,rep) for task in (1,2,3) for rep in (1,2,3))
SOURCE_NAMES=('controle/cpu_exec.py','controle/cpu_launcher.py','controle/m1_exec.py',
              'controle/m1.py','controle/frontend_cpu.py','controle/executor_modelo.py',
              'controle/harness.py')
CLAUDE_KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKy87HxSEheG8vEPhSs9u2KZCtVErAQfpmprtUJCZ2w7'
PIN_NAMES=('ARTEFATO_SHA256','EXECUTOR_NOME','EXECUTOR_VERSAO','EXECUTOR_SHA256','PREPARACAO_CPU_SHA256')


def protected(path):
 m1_exec.owned(path)
 return pathlib.Path(path)


def raw(root,rel):
 return protected(pathlib.Path(root)/rel).read_bytes()


def signed_review(root,kind):
 """A local pointer identifies a commit; only the pinned native signature grants trust."""
 review_path=PREP_REVIEW if kind=='preparation' else CODE_REVIEW
 pointer_path=EVIDENCE+'/aprovacao-claude.json' if kind=='preparation' else 'docs/evidencias/bloco5-2026-10-31/cpu-m1-07-codigo-aprovado.json'
 pointer=e.strict_json(raw(root,pointer_path));e.exact(pointer,['commit'])
 e.require(type(pointer['commit']) is str and m.re.fullmatch('[0-9a-f]{40}',pointer['commit']),'review_commit')
 return authenticated_review(root,pointer['commit'],review_path)


def authenticated_review(root,commit,review_path):
 sys.path.insert(0,'/usr/local/lib/sc-pesquisa/juiz')
 import juiz_base
 e.require(pathlib.Path(juiz_base.__file__).resolve()==pathlib.Path('/usr/local/lib/sc-pesquisa/juiz/juiz_base.py'),'native_verifier')
 result=juiz_base.verify_ssh_commit(root,commit,CLAUDE_KEY,'noreply@anthropic.com')
 e.require(result.returncode==0,'claude_signature')
 approved=subprocess.check_output(['/usr/bin/git','-C',str(root),'show',commit+':'+review_path],timeout=8)
 e.require(approved==raw(root,review_path),'claude_review_bytes')
 review=e.strict_json(approved)
 e.require(review.get('veredito')=='aprovado','claude_not_approved')
 return review


def bind_preparation(base,prepared,link,manifest,manifest_sha,criterion):
 e.exact(link,['manifesto_sha256','base_dt_sha256','criterio_sha256','prepared_dt_sha256','preparacao_cpu_sha256'])
 e.require(link['manifesto_sha256']==manifest_sha and link['base_dt_sha256']==manifest['base_dt']['sha256']
           and link['criterio_sha256']==manifest['criterion']['sha256'],'preparation_review_binding')
 import copy
 expected=copy.deepcopy(base)
 ex=prepared['executor'];identity=manifest['identities']
 for field in ('preparacao_cpu','preparacao_cpu_sha256'):expected['executor'][field]=ex[field]
 for field in ('nome','versao','sha256'):
  e.require(ex[field]==identity['executor'][field],'prepared_executor')
  expected['executor'][field]=identity['executor'][field]
 e.require(e.canonical(expected)==e.canonical(prepared),'prepared_unapproved_delta')
 e.require(ex['preparacao_cpu_sha256']==link['preparacao_cpu_sha256'],'preparation_review_pin')
 values=(identity['model_sha256'],identity['executor']['nome'],identity['executor']['versao'],
         identity['executor']['sha256'],link['preparacao_cpu_sha256'])
 old=tuple(getattr(e,name) for name in PIN_NAMES)
 e.require(old==(None,)*5 or old==values,'pins_already_bound_differently')
 try:
  for name,value in zip(PIN_NAMES,values):setattr(e,name,value)
  e.conferir_dt(prepared)
  f.preparation_ok(prepared,criterion)
 except BaseException:
  for name,value in zip(PIN_NAMES,old):setattr(e,name,value)
  raise
 return prepared


def previous_execution(root,manifest):
 """Reuse exact reviewed CPU04 evidence; no new preparation or qualification."""
 previous=manifest['previous_execution']
 e.exact(previous,['manifest04','qualification2','incident04','incident05','incident06'])
 e.require(previous['manifest04']=={'path':PREPARATION_MANIFEST,'sha256':PREPARATION_MANIFEST_SHA},'previous_manifest_pin')
 old_raw=raw(root,PREPARATION_MANIFEST)
 e.require(e.digest(old_raw)==PREPARATION_MANIFEST_SHA,'previous_manifest_hash')
 old=e.strict_json(old_raw)
 for key in old:
  if key not in ('schema','sources','future_bindings'):
   e.require(manifest[key]==old[key],'previous_unchanged_'+key)
 expected=dict(old['future_bindings'],code_review=CODE_REVIEW)
 e.require(manifest['future_bindings']==expected,'previous_future_bindings')
 q=previous['qualification2'];e.exact(q,['review_commit','review_path','result_sha256','log_sha256'])
 e.require(q['review_commit']=='fd852f1f83fa4a996af0e7fed38b9aee90bfc0e1' and
           q['review_path']=='coord/outbox/claude/sc-b05-cpu-m1-04-qualificacao2-revisao.json','previous_q2_review')
 review=authenticated_review(root,q['review_commit'],q['review_path'])
 e.require(review.get('review_target')=='a18576fdc36438c8eeb8b0b590cd0d1a20cb567e','previous_q2_target')
 for path,pin in ((RESULT_PATH,q['result_sha256']),(LOG_PATH,q['log_sha256'])):
  approved=subprocess.check_output(['/usr/bin/git','-C',str(root),'show',review['review_target']+':'+path],timeout=8)
  e.require(e.digest(approved)==pin and raw(root,path)==approved,'previous_q2_bytes')
 incident=previous['incident04'];e.exact(incident,['receipt_path','receipt_sha256','state_path','state_sha256','attempt','first_response_sha256'])
 e.require(incident['receipt_path']=='docs/evidencias/bloco5-2026-10-31/cpu-m1-04-m1/recibo.json' and
           incident['receipt_sha256']=='e31692633a150fabc3caed5dfa10b439cbae812295b3ea00ff80631a48dfeb14' and
           incident['state_path']=='/var/lib/sc-pesquisa/runtime-cpu/m1/estado-corrida/estado.json','previous_incident_pin')
 receipt_raw=raw(root,incident['receipt_path'])
 e.require(e.digest(receipt_raw)==incident['receipt_sha256'],'previous_incident_receipt')
 receipt=e.strict_json(receipt_raw);state_raw=raw(root,incident['state_path'])
 e.require(e.digest(state_raw)==incident['state_sha256']==receipt['state_sha256'],'previous_incident_state')
 state=e.strict_json(state_raw)
 e.require(state['terminal']=='incidente' and state['active'] is None and state['seal'] is None and
           state['used']==[incident['attempt']]==[receipt['attempt_id']],'previous_incident_consumed')
 index_raw=raw(root,'docs/evidencias/bloco5-2026-10-31/cpu-m1-04-m1/indice-opaco.json')
 e.require(e.digest(index_raw)==receipt['inventory_sha256'],'previous_inventory')
 path='runtime/estado-corrida/tentativa-'+incident['attempt']+'/execucao/turno1.json'
 matching=[v for v in e.strict_json(index_raw)['files'] if v['path']==path]
 e.require(len(matching)==1 and matching[0]['sha256']==incident['first_response_sha256'],'previous_first_response')
 incident05=previous['incident05'];e.exact(incident05,['receipt_path','receipt_sha256','state_path','state_sha256','attempt'])
 e.require(incident05['receipt_path']=='docs/evidencias/bloco5-2026-10-31/cpu-m1-05-m1/recibo.json' and
           incident05['receipt_sha256']=='33d3beec4029509c79e652fbd830f873089c3aa0173b79e5f8301bdc5f83d20f' and
           incident05['state_path']=='/var/lib/sc-pesquisa/runtime-cpu/m1-05/estado-corrida/estado.json','previous_incident05_pin')
 receipt05_raw=raw(root,incident05['receipt_path'])
 e.require(e.digest(receipt05_raw)==incident05['receipt_sha256'],'previous_incident05_receipt')
 receipt05=e.strict_json(receipt05_raw);state05_raw=raw(root,incident05['state_path'])
 e.require(e.digest(state05_raw)==incident05['state_sha256']==receipt05['state_sha256'],'previous_incident05_state')
 state05=e.strict_json(state05_raw)
 e.require(state05['terminal']=='incidente' and state05['active'] is None and state05['seal'] is None and
           state05['used']==[incident05['attempt']]==[receipt05['attempt']] and receipt05['seal_exists'] is False,'previous_incident05_consumed')
 e.require(all(type(receipt05[k]) is int and receipt05[k]==0 for k in
               ('tokenizations','generations','python_executions','systemd_units_created','refusals','execution_error_counter')) and
           all(type(state05[k]) is int and state05[k]==0 for k in ('recusadas','erros')),'previous_incident05_zero_operations')
 incident06=previous['incident06'];e.exact(incident06,['receipt_path','receipt_sha256','state_path','state_sha256','used'])
 e.require(incident06['receipt_path']=='docs/evidencias/bloco5-2026-10-31/cpu-m1-06-m1/recibo.json' and
           incident06['receipt_sha256']=='14a749df2647ff3e96a59edf4b0f886b9ec5703efe8a6b248317900809b3ab77' and
           incident06['state_path']=='/var/lib/sc-pesquisa/runtime-cpu/m1-06/estado-corrida/estado.json','previous_incident06_pin')
 receipt06_raw=raw(root,incident06['receipt_path'])
 e.require(e.digest(receipt06_raw)==incident06['receipt_sha256'],'previous_incident06_receipt')
 receipt06=e.strict_json(receipt06_raw);state06_raw=raw(root,incident06['state_path'])
 e.require(e.digest(state06_raw)==incident06['state_sha256']==receipt06['state_sha256'],'previous_incident06_state')
 state06=e.strict_json(state06_raw)
 e.require(state06['terminal']=='incidente' and state06['active'] is None and state06['seal'] is None and
           state06['used']==incident06['used']==receipt06['used'] and receipt06['seal_exists'] is False,'previous_incident06_consumed')
 e.require(type(state06['recusadas']) is int and state06['recusadas']==receipt06['refusals']==2 and
           type(state06['erros']) is int and state06['erros']==receipt06['execution_error_counter']==0,'previous_incident06_counters')
 return old


def authority(root,operation,current_unit=None):
 e.require(operation in ('m1_python','tokenize_m1_t1','tokenize_m1_t2','completion_m1_t1','completion_m1_t2'),'act07_m1_only')
 e.require(os.geteuid()==0,'supervisor_root')
 root=protected(root)
 manifest_raw=raw(root,MANIFEST);manifest=e.strict_json(manifest_raw)
 e.exact(manifest,['schema','sources','base_dt','criterion','profile_sha256','freeze_sha256','contract_sha256',
                   'qualification','identities','future_bindings','primary_result','previous_execution'])
 e.require(manifest['schema']=='sc-cpu-m1-execution-manifest/5','manifest_schema')
 e.require(set(manifest['sources'])==set(SOURCE_NAMES),'manifest_sources')
 for name,pin in manifest['sources'].items():
  path=protected(root/name)
  e.require(e.digest(path.read_bytes())==pin,'source_pin')
  module=sys.modules.get('controle.'+path.stem)
  e.require(module is not None and pathlib.Path(module.__file__).resolve()==path.resolve(),'loaded_source')
 for key,expected_path in [('base_dt',e.DT_PATH),('criterion',CRITERIO_PATH)]:
  e.exact(manifest[key],['path','sha256'])
  e.require(manifest[key]['path']==expected_path and e.digest(raw(root,expected_path))==manifest[key]['sha256'],'manifest_input')
 primary_rejected(root,manifest['primary_result'])
 base=e.strict_json(raw(root,e.DT_PATH));criterion=e.strict_json(raw(root,CRITERIO_PATH))
 e.require(manifest['profile_sha256']==e.PERFIL_CPU_SHA256==e.digest(e.canonical(base['executor']['perfil_proposto'])),'manifest_profile')
 e.require(manifest['freeze_sha256']==m1_exec.FREEZE and manifest['contract_sha256']=='17929806202c7a4ceb2bb752996eeffac7af9e001943938d4422a01f5216af63','manifest_scientific_inputs')
 e.require(manifest['future_bindings']=={'prepared_dt':PREPARED,'preparation_review':PREP_REVIEW,
             'code_review':CODE_REVIEW,'cpu_result':RESULT_PATH,'cpu_log':LOG_PATH},'future_paths')
 q=manifest['qualification'];e.exact(q,['path','sha256'])
 e.require(q['path']=='docs/evidencias/bloco5-2026-10-31/cpu-download-03-preparacao/qualificacao/resultado.json','qualification_path')
 qr=raw(root,q['path']);e.require(e.digest(qr)==q['sha256'],'qualification_hash')
 qv=e.strict_json(qr)
 e.require(qv.get('success') is True and qv.get('released_R') is True and qv.get('operation')=='qualificacao'
           and type(qv.get('exit_code')) is int and qv['exit_code']==0 and qv.get('error') is None,'qualification_failed')
 sys.path.insert(0,'/usr/local/lib/sc-pesquisa/juiz')
 import blocos
 e.require(pathlib.Path(blocos.__file__).resolve()==pathlib.Path('/usr/local/lib/sc-pesquisa/juiz/blocos.py'),'installed_judge')
 blocos.confirmacao_dono_ok(root,ACT,['B05-CPU-M1-07','m1_manifesto_sha256: '+e.digest(manifest_raw),'10 segundos'],chaves_commit=m1_exec.KEYS)
 code_review=signed_review(root,'code')
 e.require(code_review.get('manifesto_sha256')==e.digest(manifest_raw),'code_review_manifest')
 for path in ('PARE','blocos/PARE'):e.require(not (root/path).exists(),'PARE')
 e.require(digest(root/'blocos/AVISO_DONO.md')=='64cbe0bb9e3e6448b01f746b0a8105fbbeaf161257c0b962a0fe920330236799','AVISO_changed')
 e.require(int(pathlib.Path('/proc/sys/kernel/yama/ptrace_scope').read_text())>=1,'ptrace_scope')
 for unit in ('sc-blocos-encadeador.timer','sc-blocos-encadeador.service'):
  e.require(call(['systemctl','show',unit,'--property=ActiveState','--value']).strip()=='inactive','native_encoder_active')
 seen=residents(current_unit)
 identity=manifest['identities']
 e.exact(identity,['model_sha256','tokenizer_sha256','executor','template_sha256','runtime_files','runtime_links'])
 e.require(identity['model_sha256']==m.MODEL_SHA256 and identity['template_sha256']==f.TEMPLATE_SHA256,'model_template_pin')
 e.require(identity['tokenizer_sha256']=='712076edf65a35a84188df933912d9e735758fa7bdffb9796287adfadf4263a3'
           and identity['executor']=={'nome':'llama-completion','versao':'b11960','sha256':'7119bef261611b26f326f7c4da4dc3fdeb7bb28e2faf1ec392bda7b21215ef52'},'runtime_identity')
 # The snapshot is root-owned and never mounted writable. Each held unit also rehashes its executable/model/prompt.
 e.require(type(identity['runtime_files']) is dict and identity['runtime_files'],'runtime_files')
 e.require(len(identity['runtime_files'])==51 and type(identity['runtime_links']) is dict and len(identity['runtime_links'])==10,'runtime_inventory')
 e.require(set(p.name for p in pathlib.Path(m.RUNTIME).iterdir())==set(identity['runtime_files'])|set(identity['runtime_links']),'runtime_inventory_changed')
 for rel,target in identity['runtime_links'].items():
  e.require(type(rel) is str and type(target) is str and '/' not in rel+target and rel not in ('.','..') and target not in ('.','..'),'runtime_link_path')
  path=pathlib.Path(m.RUNTIME)/rel
  e.require(path.is_symlink() and os.readlink(path)==target and path.resolve().parent==pathlib.Path(m.RUNTIME),'runtime_link_changed')
 for rel,pin in identity['runtime_files'].items():
  e.require(type(rel) is str and '/' not in rel and rel not in ('.','..'),'runtime_file_path')
  e.require(digest(protected(pathlib.Path(m.RUNTIME)/rel))==pin,'runtime_dependency')
 transport=json.loads(raw(root,'.git/sc-auth/admin-transport.json'))
 env=dict(os.environ,GIT_SSH_COMMAND=transport['ssh_command'],GIT_TERMINAL_PROMPT='0')
 remote=subprocess.check_output(['git','-C',str(root),'ls-remote','origin','refs/heads/main'],env=env,text=True,timeout=8).split()[0]
 local=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,timeout=8).strip()
 e.require(remote==local,'main_changed')
 result={'manifest':manifest,'base_dt':base,'criterion':criterion,'residents':seen}
 if operation not in ('prepare','tokenize_T1','tokenize_T2','tokenize_T3'):
  approval=signed_review(root,'preparation');link=approval.get('vinculo_preparacao')
  prepared_raw=raw(root,PREPARED)
  e.require(type(link) is dict and e.digest(prepared_raw)==link.get('prepared_dt_sha256'),'prepared_dt_review_hash')
  prepared=e.strict_json(prepared_raw)
  old_manifest=previous_execution(root,manifest)
  result['dt']=bind_preparation(base,prepared,link,old_manifest,PREPARATION_MANIFEST_SHA,criterion)
  result['approval']=link
  if operation=='m1_python' or '_m1_' in operation:cpu_approved(root,result)
 return result


def cpu_approved(root,trusted):
 criterion=raw(root,CRITERIO_PATH);dt=trusted['dt']
 result=raw(root,RESULT_PATH)
 log=raw(root,LOG_PATH)
 e.require(e.conferir_teste_cpu(criterion,result,log,dt,qualification=2)=='APROVADO','cpu_not_approved')
 state=e.strict_json(protected(CPU_STATE/'estado.json').read_bytes())
 e.require(state['finished'] is True and state['next']==9 and state['boot_id']==m1.boot_id(),'cpu_state')
 for row,operation in zip(log.splitlines(),ORDER):
  record=e.strict_json(row);folder=CPU_STATE/operation
  plan,stdout,stderr=native_read(folder,operation)
  e.require(record['invocacao']['argv']==e.strict_json(plan['argv'][-1].encode())['exec'],'cpu_native_argv')
  e.require(plan_ids(plan)==identities(operation,None),'cpu_native_identities')
  e.require(f.unblob(record['invocacao']['captura']['stdout'],e.MAX_SAIDA)==stdout
       and f.unblob(record['invocacao']['captura']['stderr'],f.MAX_STDERR)==stderr,'cpu_native_streams')
 return {'result_sha256':e.digest(result),'log_sha256':e.digest(log)}


def remaining(deadline,now_ns,ceiling):
 e.require(type(deadline) is int and type(now_ns) is int,'clock_type')
 seconds=(deadline-now_ns)//1_000_000_000
 e.require(1<=seconds<=ceiling,'deadline')
 return seconds


def reserve(root,operation,attempt):
 deadline=None;seconds=None
 if operation in ('tokenize_T1','tokenize_T2','tokenize_T3'):
  e.require(attempt is None,'attempt')
  out=pathlib.Path(root)/EVIDENCE/operation
 elif operation in ORDER:
  state=e.strict_json(protected(CPU_STATE/'estado.json').read_bytes())
  e.require(state['boot_id']==m1.boot_id() and not state['finished'] and state['next']<9
            and ORDER[state['next']]==operation,'cpu_operation_order')
  e.require(time.monotonic_ns()>=state['last_ns']>=state['start_ns'],'cpu_clock')
  deadline=state['start_ns']+900_000_000_000
  seconds=remaining(deadline,time.monotonic_ns(),900)
  out=CPU_STATE/operation
  e.require(not out.exists(),'cpu_operation_consumed')
  state['next']+=1;state['last_ns']=time.monotonic_ns()
  js(CPU_STATE/'estado.json',state)  # consumed before any launch; uncertain operations never replay
 else:
  e.require(operation in ('tokenize_m1_t1','tokenize_m1_t2','completion_m1_t1','completion_m1_t2'),'closed_operation')
  e.require(type(attempt) is str and m.re.fullmatch('[0-9a-f]{32}',attempt),'attempt')
  marker=pathlib.Path(m.M1_ROOT)/'estado-corrida'/('tentativa-'+attempt)
  state=m1_exec.estado_ativo(marker,attempt)
  deadline=state['start_ns']+1_800_000_000_000
  seconds=remaining(deadline,time.monotonic_ns(),1800)
  out=marker/('turno-'+operation[-1])/operation
 out.mkdir(mode=0o700,exist_ok=False)
 return out,deadline,seconds


def identities(operation,attempt):
 if '_m1_' in operation:
  folder=pathlib.Path(m.M1_ROOT)/'estado-corrida'/('tentativa-'+attempt)/('turno-'+operation[-1])
  prompt=folder/('efetivo.txt' if operation.startswith('tokenize') else 'transporte.txt')
 else:
  task=operation[-2:] if operation.startswith('tokenize') else operation.split('_')[1]
  prompt=pathlib.Path(m.CPU_PROMPTS)/('prompts-efetivos' if operation.startswith('tokenize') else 'prompts-transporte')/(task+'.txt')
 executable=pathlib.Path(m.RUNTIME)/('llama-tokenize' if operation.startswith('tokenize') else 'llama-completion')
 expected='712076edf65a35a84188df933912d9e735758fa7bdffb9796287adfadf4263a3' if operation.startswith('tokenize') else '7119bef261611b26f326f7c4da4dc3fdeb7bb28e2faf1ec392bda7b21215ef52'
 e.require(digest(protected(executable))==expected,'executable_changed')
 return {'executable':expected,
         'prompt':digest(protected(prompt))}


APPROVED_CPU_RENDERS = {'T1': {'efetivo': 'efdfe32e4ff27646e3b6686fb320a0df4de7eb771eb1e397c8170500d4cebd89', 'arquivo': 'fd31415fb06af99b27995599773eca9733ae48d5c120b8d207f3c67add592b7a'}, 'T2': {'efetivo': '4ea53c97a0e7e8b668c0220aeedf5db1040eeb557b96de370b17302f79ac42bc', 'arquivo': '58c58238bc1f07d22a8ca50bc2c276c69c4f1106b3d9206597a72b162ab96a6c'}, 'T3': {'efetivo': '840204a864e77377245a55b8107be6db8a81756443fde2142fac21ae90422f06', 'arquivo': '09d864a212cd2ddc2e5618cece0d18784b9bf590b771634eb690a86889aa6c89'}}


def approved_cpu_renders(dt):
 prompts=dt["executor"]["preparacao_cpu"]["prompts"]
 e.require(set(prompts)==set(APPROVED_CPU_RENDERS),"approved_render_tasks")
 for task,pins in APPROVED_CPU_RENDERS.items():
  for field,pin in pins.items():
   e.require(e.digest(f.unblob(prompts[task][field],f.MAX_PROMPT+1))==pin,"approved_render_hash")


def prepare_cpu(root):
 """Three deterministic renders and three offline tokenizations; never generation."""
 trusted=authority(root,'prepare');folder=pathlib.Path(root)/EVIDENCE
 folder.mkdir(mode=0o700,exist_ok=False)
 js(folder/'inicio.json',{'utc':now(),'manifesto_sha256':digest(pathlib.Path(root)/MANIFEST)})
 dt=f.prepare(trusted['base_dt'],trusted['criterion'],pathlib.Path(m.MODEL))
 identity=trusted['manifest']['identities']
 for key in ('nome','versao','sha256'):dt['executor'][key]=identity['executor'][key]
 approved_cpu_renders(dt)
 pathlib.Path(m.CPU_PROMPTS).mkdir(mode=0o755,exist_ok=False)
 for suffix,field in (('efetivos','efetivo'),('transporte','arquivo')):
  target=pathlib.Path(m.CPU_PROMPTS)/('prompts-'+suffix);target.mkdir(mode=0o755,exist_ok=False)
  for task,prompt in dt['executor']['preparacao_cpu']['prompts'].items():
   path=target/(task+'.txt');path.write_bytes(f.unblob(prompt[field],f.MAX_PROMPT+1));path.chmod(0o644)
 js(folder/'dt-renderizada.json',dt)
 ids={}
 for task in ('T1','T2','T3'):
  result=execute(root,'tokenize_'+task);ids[task]=result['stdout']
 bound=f.bind_tokenizations(dt,pathlib.Path(m.MODEL),ids,identity['tokenizer_sha256'])
 js(pathlib.Path(root)/PREPARED,bound)
 js(folder/'resultado.json',{'utc':now(),'inferences':0,'prepared_dt_sha256':digest(pathlib.Path(root)/PREPARED),
    'preparacao_cpu_sha256':bound['executor']['preparacao_cpu_sha256'],'operational_go':False})
 return bound


def check_cpu_prompt(root,trusted,operation):
 task=operation[-2:] if operation.startswith('tokenize') else operation.split('_')[1]
 if operation.startswith('tokenize'):
  draft=e.strict_json(raw(root,EVIDENCE+'/dt-renderizada.json'))
  prompt=draft['executor']['preparacao_cpu']['prompts'][task]
 else:prompt=trusted['dt']['executor']['preparacao_cpu']['prompts'][task]
 field='efetivo' if operation.startswith('tokenize') else 'arquivo'
 suffix='efetivos' if operation.startswith('tokenize') else 'transporte'
 e.require(protected(pathlib.Path(m.CPU_PROMPTS)/('prompts-'+suffix)/(task+'.txt')).read_bytes()==f.unblob(prompt[field],f.MAX_PROMPT+1),'cpu_prompt_changed')


def run_cpu(root):
 """One round. A partial or uncertain run remains consumed and never becomes APROVADO."""
 import base64
 trusted=authority(root,ORDER[0]);dt=trusted['dt'];criterion=trusted['criterion']
 CPU_STATE.mkdir(mode=0o700,exist_ok=False)
 state={'boot_id':m1.boot_id(),'start_ns':time.monotonic_ns(),'last_ns':time.monotonic_ns(),'next':0,'finished':False}
 js(CPU_STATE/'estado.json',state)
 started=now();rows=[];cr=raw(root,CRITERIO_PATH)
 try:
  for op in ORDER:
   task=op.split('_')[1];rep=int(op[-1]);call_start=time.monotonic()
   native=execute(root,op)
   invocation=f.invocation_record(dt,task,'/runtime/llama-completion','/model/model.gguf','/prompt/prompt.txt',
                                 native['stdout'],native['stderr'],native['returncode'])
   output,boundary=f.verify_invocation(invocation,dt,task)
   expected=next(x['aceite']['resposta_exata'] for x in criterion['criterio']['tarefas'] if x['id']==task)
   try:
    parsed=e.conferir_saida(output);accepted=bool(boundary and parsed['tarefa']==task and parsed['resposta']==expected)
   except (ValueError,UnicodeError):accepted=False
   row={'schema':'sc-teste-cpu-chamada/2','criterio_sha256':e.digest(cr),'artefato_sha256':e.ARTEFATO_SHA256,
        'executor_sha256':e.EXECUTOR_SHA256,'tarefa':task,'repeticao':rep,'saida_base64':base64.b64encode(output).decode(),
        'saida_sha256':e.digest(output),'aceita':accepted,'duracao_s':time.monotonic()-call_start,
        'parametros_geracao':criterion['criterio']['parametros_geracao'],'invocacao':invocation}
   rows.append(row)
   with (CPU_STATE/'chamadas.jsonl').open('ab') as stream:
    stream.write(e.canonical(row)+b'\n');stream.flush();os.fsync(stream.fileno())
  ended=now();remaining(state['start_ns']+900_000_000_000,time.monotonic_ns(),900)
  log=b''.join(e.canonical(row)+b'\n' for row in rows)
  rate=sum(row['aceita'] for row in rows)/9
  result={'schema':'sc-teste-cpu/2','item':'B05-02','criterio':{'path':CRITERIO_PATH,'sha256':e.digest(cr)},
          'log':{'path':LOG_PATH,'sha256':e.digest(log)},'artefato_sha256':e.ARTEFATO_SHA256,
          'executor':trusted['manifest']['identities']['executor'],
          'maquina':{'cpu':next(x.split(':',1)[1].strip() for x in pathlib.Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')),
                     'ram_total_bytes':int(pathlib.Path('/proc/meminfo').read_text().splitlines()[0].split()[1])*1024,'dispositivo':'cpu','rede':False},
          'iniciado_em_utc':started,'terminado_em_utc':ended,'tarefas':[{'id':task,'repeticoes':[
           {key:row[key] for key in ('repeticao','saida_sha256','aceita','duracao_s')} for row in rows if row['tarefa']==task]} for task in ('T1','T2','T3')],
          'repeticoes_por_tarefa':3,'uma_rodada_sem_alegacao_estatistica':True,'limiar':criterion['criterio']['limiar'],
          'valor_observado':rate,'veredito':'APROVADO' if rate>=criterion['criterio']['limiar']['valor'] else 'REPROVADO',
          'perfil_sha256':e.PERFIL_CPU_SHA256,'preparacao_sha256':e.PREPARACAO_CPU_SHA256}
  e.conferir_teste_cpu(cr,e.canonical(result),log,dt,qualification=2)
  for rel,data in ((LOG_PATH,log),(RESULT_PATH,e.canonical(result)+b'\n')):
   with (pathlib.Path(root)/rel).open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
  state=e.strict_json((CPU_STATE/'estado.json').read_bytes());state['finished']=True;js(CPU_STATE/'estado.json',state)
  return result
 except BaseException as exc:
  js(CPU_STATE/'falha.json',{'utc':now(),'error':type(exc).__name__+':'+str(exc),'completed_calls':len(rows),'retry_allowed':False})
  raise


def m1_folder(attempt,turn):
 e.require(type(attempt) is str and m.re.fullmatch('[0-9a-f]{32}',attempt),'attempt')
 e.require(type(turn) is int and turn in (1,2),'turn')
 return pathlib.Path(m.M1_ROOT)/'estado-corrida'/('tentativa-'+attempt)/('turno-'+str(turn))


def m1_messages(root,attempt,turn):
 lot=m1_exec.lote_confiavel(root);initial=m1.entrada_turno1(lot['files'],lot['hashes'])
 if turn==1:return [{'role':'user','content':initial}]
 first=derived_m1(root,attempt,1)
 capture=m1_folder(attempt,1).parent/'execucao'
 out=protected(capture/'stdout.bin').read_bytes();err=protected(capture/'stderr.bin').read_bytes()
 receipt=e.strict_json(protected(capture/'recibo.json').read_bytes())
 e.require(protected(capture/'turno1.json').read_bytes()==first,'m1_first_capture')
 return m1.mensagens_turno2(initial,first,out,err,receipt,attempt)


def m1_render(root,attempt,turn):
 messages=m1_messages(root,attempt,turn)
 template,_=f.template_local(pathlib.Path(m.MODEL),m.MODEL_SHA256,f.EOS_POLICY)
 rendered=f.render(template,messages)
 return messages,template,rendered


def check_m1_render(root,attempt,turn):
 folder=m1_folder(attempt,turn);messages,template,rendered=m1_render(root,attempt,turn)
 e.require(protected(folder/'efetivo.txt').read_bytes()==rendered and
           protected(folder/'transporte.txt').read_bytes()==rendered+b'\n','m1_render_binding')
 return messages,template,rendered


def native_read(folder,operation,attempt=None):
 plan=e.strict_json(protected(folder/'plan.json').read_bytes())
 expected=m.plan(operation,plan['unit'].removeprefix('sc-cpu-prep-').removesuffix('.service'),
                 plan_ids(plan),attempt=attempt,remaining_s=plan.get('remaining_s'))
 e.require(plan==expected,'native_plan_changed')
 result=e.strict_json(protected(folder/'resultado.json').read_bytes())
 checked=e.strict_json(protected(folder/'checked.json').read_bytes())
 e.require(result['success'] is True and result['released_R'] is True and result['exit_code']==0 and result['error'] is None
           and result['operation']==operation and result['unit']==plan['unit']
           and checked['plan_sha256']==plan['sha256'],'native_capture_binding')
 return plan,protected(folder/'stdout.bin').read_bytes(),protected(folder/'stderr-restante.bin').read_bytes()


def m1_binding(root,attempt,turn):
 folder=m1_folder(attempt,turn)
 messages,template,rendered=check_m1_render(root,attempt,turn)
 plan,ids,stderr=native_read(folder/('tokenize_m1_t'+str(turn)),'tokenize_m1_t'+str(turn),attempt)
 e.require(plan_ids(plan)==identities('tokenize_m1_t'+str(turn),attempt),'tokenizer_identity')
 meta=f.gguf_metadata(pathlib.Path(m.MODEL),m.MODEL_SHA256)
 proof=f.tokenization_bytes_ok(ids,meta,rendered)
 prepared=m1.preparar_turno(turn,template,messages,ids)
 e.require(proof['P']==prepared['P'] and prepared['P']>1,'m1_token_count')
 return {'schema':'sc-m1-tokenizer-binding/1','attempt':attempt,'turn':turn,
         'manifesto_sha256':digest(pathlib.Path(root)/MANIFEST),'profile_sha256':e.PERFIL_CPU_SHA256,
         'history_sha256':prepared['history_sha256'],'prompt_sha256':e.digest(rendered),
         'transport_sha256':e.digest(rendered+b'\n'),'tokenizer_plan_sha256':plan['sha256'],
         'ids_sha256':e.digest(ids),'stderr_sha256':e.digest(stderr),'model_sha256':m.MODEL_SHA256,
         'tokenizer_sha256':plan_ids(plan)['executable'],'P':proof['P'],'proof':proof,
         'n_ctx':8192,'max_tokens':512 if turn==1 else 2048}


def prepare_m1(root,attempt,turn):
 authority(root,'tokenize_m1_t'+str(turn))
 folder=m1_folder(attempt,turn);m1_exec.estado_ativo(folder.parent,attempt)
 messages,template,rendered=m1_render(root,attempt,turn)
 folder.mkdir(mode=0o755,exist_ok=False)
 for name,data in [('efetivo.txt',rendered),('transporte.txt',rendered+b'\n')]:
  path=folder/name;path.write_bytes(data);path.chmod(0o644)
 execute(root,'tokenize_m1_t'+str(turn),attempt)
 binding=m1_binding(root,attempt,turn);js(folder/'vinculo.json',binding)
 return binding


def check_m1(root,attempt,turn):
 recorded=e.strict_json(protected(m1_folder(attempt,turn)/'vinculo.json').read_bytes())
 expected=m1_binding(root,attempt,turn)
 e.require(recorded==expected,'m1_tokenizer_binding_changed')
 return expected


def derived_m1(root,attempt,turn):
 binding=check_m1(root,attempt,turn)
 op='completion_m1_t'+str(turn)
 plan,stdout,stderr=native_read(m1_folder(attempt,turn)/op,op,attempt)
 e.require(plan_ids(plan)==identities(op,attempt),'completion_identity')
 cap=f.capture(stdout,stderr,0,binding['P'],binding['max_tokens'],8192)
 e.require(cap['fronteira_valida'],'m1_generation_boundary')
 return f.unblob(cap['saida'],e.MAX_SAIDA)


def require_generation(root,attempt,turn,supplied):
 e.require(type(supplied) is bytes and supplied==derived_m1(root,attempt,turn),'m1_generation_origin')


def run_m1(root):
 """One persistent run. Model refusals follow the existing counters; infrastructure never retries."""
 sys.path.insert(0,'/usr/local/lib/sc-pesquisa/juiz')
 import blocos as b
 # Acquire before any run state is created; execute acquires its own lock later.
 with b.repo_lock(root):
  trusted=m1_exec.autoridade(root)
  pathlib.Path(m.M1_ROOT).mkdir(mode=0o755,exist_ok=True)
  protected(m.M1_ROOT)
  session=m1.Sessao(pathlib.Path(m.M1_ROOT)/'estado-corrida',m1_exec.FREEZE,time.monotonic_ns,root)
  session.iniciar()
 while True:
  attempt=uuid.uuid4().hex;marker=session.admitir(attempt,m1_exec.FREEZE)
  try:
   prepare_m1(root,attempt,1);execute(root,'completion_m1_t1',attempt)
   first=derived_m1(root,attempt,1)
   previous_hash=trusted['manifest']['previous_execution']['incident04']['first_response_sha256']
   js(marker/'comparacao-hash-turno1.json',{'schema':'sc-m1-hash-informativo/1',
       'representation':'decoded_json_bytes_without_eog_suffix','previous_sha256':previous_hash,
       'current_sha256':e.digest(first),'equal':e.digest(first)==previous_hash,'blocks_acceptance':False})
   try:m1.codigo_admissivel(first,trusted['inputs'])
   except m1.Incidente:raise
   except (ValueError,UnicodeError):
    state=session.falhar(attempt,'recusa')
    if state['terminal'] is not None:return state
    continue
   try:m1_exec.capturar(root,attempt,first,trusted['inputs'],marker,10)
   except RuntimeError as exc:
    if str(exc)!='m1_erro_execucao':raise
    state=session.falhar(attempt,'erro_execucao')
    if state['terminal'] is not None:return state
    continue
   prepare_m1(root,attempt,2);execute(root,'completion_m1_t2',attempt)
   final=derived_m1(root,attempt,2)
   capture=marker/'execucao'
   out=protected(capture/'stdout.bin').read_bytes();err=protected(capture/'stderr.bin').read_bytes()
   receipt=e.strict_json(protected(capture/'recibo.json').read_bytes())
   try:m1.verificar(final,trusted['inputs'],attempt,first,out,err,receipt)
   except m1.Incidente:raise
   except (ValueError,UnicodeError):
    state=session.falhar(attempt,'recusa')
    if state['terminal'] is not None:return state
    continue
   return session.aceitar(attempt,final,trusted['inputs'],first,out,err,receipt,m1_exec.FREEZE)
  except BaseException as exc:
   session.falhar(attempt,'pare' if (pathlib.Path(root)/'PARE').exists() or (pathlib.Path(root)/'blocos/PARE').exists() else 'incidente')
   js(marker/'incidente.json',{'utc':now(),'error':type(exc).__name__+':'+str(exc),'retry_allowed':False})
   raise


def plan_ids(plan):
 binary='/runtime/llama-tokenize' if plan['operation'].startswith('tokenize') else '/runtime/llama-completion'
 return {'executable':plan['files'][binary],'prompt':plan['files']['/prompt/prompt.txt']}


CPU03_ARCHIVE='docs/evidencias/bloco5-2026-10-31/cpu-m1-03-rodada'
CPU03_INDEX_SHA='79adb5f8e5c5017b7d85267d078e49ba8b15a03c3d4b25143e8e7f66991f4c70'
CPU03_INPUTS={
 'docs/decisoes/B05-CPU-M1-03-manifesto.json':'1a991fb36e80eedb2d66c4b326c5b470a5210d6f2c55ea951fa6f04c443d3bbe',
 'docs/decisoes/DT-B05-EXECUTOR-01.json':'f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441',
 'docs/decisoes/DT-B05-CRITERIO-CPU-01.json':'5d53ae937e4e7ca197fecd0fc756ff5bbd64e17fa3db8373086abaaf2791a9d1',
 'docs/evidencias/bloco5-2026-10-31/cpu-m1-03-preparacao/dt-preparada.json':'d652bab4251dce76ae452ac9a70aec9fa180a182ea38468727dd1cb547f781a4'}
CPU03_RESULT='docs/evidencias/bloco5-2026-10-31/teste-cpu-resultado.json'
CPU03_RECEIPT='docs/evidencias/bloco5-2026-10-31/cpu-m1-04-candidata/finalizacao03.json'


def primary_rejected(root,primary):
 e.exact(primary,['archive_index_sha256','documents'])
 e.require(primary['archive_index_sha256']==CPU03_INDEX_SHA and
           set(primary['documents'])=={e.LOG_PATH,CPU03_RESULT,CPU03_RECEIPT},'primary_paths')
 documents={rel:raw(root,rel) for rel in primary['documents']}
 for rel,data in documents.items():e.require(e.digest(data)==primary['documents'][rel],'primary_hash')
 result=e.strict_json(documents[CPU03_RESULT])
 e.require(result['veredito']=='REPROVADO' and result['valor_observado']==6/9 and
           result['limiar']['valor']==1.0 and result['log']=={'path':e.LOG_PATH,'sha256':e.digest(documents[e.LOG_PATH])},'primary_rejected')



def cpu03_documents(root,machine_record):
 """Read-only documentary derivation of the consumed round. Never launch or write.

 The original signed archive and inputs remain immutable. The caller may stage
 these candidate documents for review; promoting them needs the new signed act.
 """
 import copy,base64
 root=pathlib.Path(root)
 index_raw=raw(root,CPU03_ARCHIVE+'/indice-arquivos.json')
 e.require(e.digest(index_raw)==CPU03_INDEX_SHA,'cpu03_index')
 index=e.strict_json(index_raw);archive={}
 for entry in index['files']:
  rel=entry['path']
  e.require(type(rel) is str and rel.startswith(CPU03_ARCHIVE+'/')
            and '..' not in pathlib.PurePosixPath(rel).parts and rel not in archive,'cpu03_path')
  data=raw(root,rel)
  e.require(len(data)==entry['bytes'] and e.digest(data)==entry['sha256'],'cpu03_archive')
  archive[rel]=data
 e.require(len(archive)==index['files_count']==161,'cpu03_inventory')
 inputs={}
 for rel,pin in CPU03_INPUTS.items():
  data=raw(root,rel);e.require(e.digest(data)==pin,'cpu03_input');inputs[rel]=data
 def old(rel):return e.strict_json(archive[CPU03_ARCHIVE+'/'+rel])
 state=old('nativo/estado.json');failure=old('nativo/falha.json')
 e.require(state['next']==9 and state['finished'] is False and failure['completed_calls']==9
           and failure['error']=='ValueError:horario_sem_utc' and failure['retry_allowed'] is False,'cpu03_consumed')
 e.exact(machine_record,['maquina','capturado_em_utc','boot_id','origem'])
 e.utc(machine_record['capturado_em_utc'])
 e.require(machine_record['boot_id']==state['boot_id']
           and machine_record['origem']=='leitura na finalizacao documental; nao observacao durante a rodada','cpu03_machine_origin')
 start=old('invocacao/invocacao.json')['utc_start'];end=old('invocacao/resultado.json')['utc_end']
 def utc_z(value):
  e.require(type(value) is str and value.endswith('+00:00'),'cpu03_utc_source')
  value=value[:-6]+'Z';e.utc(value);return value
 started,ended=utc_z(start),utc_z(end)
 e.require(e.utc(machine_record['capturado_em_utc'])>=e.utc(ended),'cpu03_machine_time')
 manifest=e.strict_json(inputs['docs/decisoes/B05-CPU-M1-03-manifesto.json'])
 prepared=e.strict_json(inputs['docs/evidencias/bloco5-2026-10-31/cpu-m1-03-preparacao/dt-preparada.json'])
 cr=inputs[e.CRITERIO_PATH];criterion=e.strict_json(cr)
 link={'manifesto_sha256':CPU03_INPUTS['docs/decisoes/B05-CPU-M1-03-manifesto.json'],
       'base_dt_sha256':CPU03_INPUTS[e.DT_PATH],'criterio_sha256':CPU03_INPUTS[e.CRITERIO_PATH],
       'prepared_dt_sha256':CPU03_INPUTS['docs/evidencias/bloco5-2026-10-31/cpu-m1-03-preparacao/dt-preparada.json'],
       'preparacao_cpu_sha256':'cdcb1065030dda2c14ccc0223b6f0605c3a0271f53045190a1bba58eca986bee'}
 original=archive[CPU03_ARCHIVE+'/nativo/chamadas.jsonl']
 lines=original.splitlines();e.require(len(lines)==9,'cpu03_calls')
 pins=tuple(getattr(e,name) for name in PIN_NAMES)
 try:
  for name in PIN_NAMES:setattr(e,name,None)
  dt=bind_preparation(e.strict_json(inputs[e.DT_PATH]),prepared,link,manifest,link['manifesto_sha256'],criterion)
  rows=[]
  for line,op in zip(lines,ORDER):
   record=e.strict_json(line);task=op.split('_')[1];rep=int(op[-1]);folder='nativo/'+op+'/'
   e.require(e.canonical(record)==line and record['tarefa']==task and record['repeticao']==rep
             and record['aceita'] is False,'cpu03_row')
   plan=old(folder+'plan.json');native=old(folder+'resultado.json');checked=old(folder+'checked.json')
   e.require(plan['sha256']==m.digest({k:v for k,v in plan.items() if k!='sha256'})
             and checked['plan_sha256']==plan['sha256'],'cpu03_plan')
   e.require(native['operation']==op and native['unit']==plan['unit'] and native['success'] is True
             and native['released_R'] is True and native['exit_code']==0 and native['error'] is None,'cpu03_native')
   stdout=archive[CPU03_ARCHIVE+'/'+folder+'stdout.bin']
   stderr=archive[CPU03_ARCHIVE+'/'+folder+'stderr-restante.bin']
   inv=record['invocacao'];cap=inv['captura']
   e.require(f.unblob(cap['stdout'],e.MAX_SAIDA)==stdout and f.unblob(cap['stderr'],f.MAX_STDERR)==stderr
             and cap['returncode']==0 and inv['argv']==e.strict_json(plan['argv'][-1].encode())['exec'],'cpu03_streams')
   argv=inv['argv'];new=f.invocation_record(dt,task,argv[0],argv[2],argv[4],stdout,stderr,0)
   e.require({k:v for k,v in inv.items() if k!='captura'}==
             {k:v for k,v in new.items() if k!='captura'},'cpu03_invocation')
   output,boundary=f.verify_invocation(new,dt,task)
   expected=next(t['aceite']['resposta_exata'] for t in criterion['criterio']['tarefas'] if t['id']==task)
   try:
    parsed=e.conferir_saida(output);accepted=bool(boundary and parsed['tarefa']==task and parsed['resposta']==expected)
   except (ValueError,UnicodeError):accepted=False
   row=copy.deepcopy(record);row.update(invocacao=new,saida_base64=base64.b64encode(output).decode(),
                                      saida_sha256=e.digest(output),aceita=accepted)
   rows.append(row)
  log=b''.join(e.canonical(row)+b'\n' for row in rows);rate=sum(row['aceita'] for row in rows)/9
  e.require(rate==6/9 and criterion['criterio']['limiar']['valor']==1.0,'cpu03_primary_rejected')
  result={'schema':'sc-teste-cpu/2','item':'B05-02','criterio':{'path':e.CRITERIO_PATH,'sha256':e.digest(cr)},
          'log':{'path':e.LOG_PATH,'sha256':e.digest(log)},'artefato_sha256':e.ARTEFATO_SHA256,
          'executor':manifest['identities']['executor'],'maquina':copy.deepcopy(machine_record['maquina']),
          'iniciado_em_utc':started,'terminado_em_utc':ended,
          'tarefas':[{'id':task,'repeticoes':[{k:row[k] for k in ('repeticao','saida_sha256','aceita','duracao_s')}
                    for row in rows if row['tarefa']==task]} for task in ('T1','T2','T3')],
          'repeticoes_por_tarefa':3,'uma_rodada_sem_alegacao_estatistica':True,'limiar':criterion['criterio']['limiar'],
          'valor_observado':rate,'veredito':'REPROVADO','perfil_sha256':e.PERFIL_CPU_SHA256,
          'preparacao_sha256':e.PREPARACAO_CPU_SHA256}
  result_raw=e.canonical(result)+b'\n'
  e.require(e.conferir_teste_cpu(cr,result_raw,log,dt,qualification=1)=='REPROVADO','cpu03_verdict')
  receipt={'schema':'sc-cpu03-finalizacao-documental/1','primary_result':'REPROVADO','accepted':6,'total':9,
           'original_accepted':0,'original_calls_sha256':e.digest(original),'archive_index_sha256':CPU03_INDEX_SHA,
           'log_sha256':e.digest(log),'result_sha256':e.digest(result_raw),'machine_record':copy.deepcopy(machine_record),
           'time_origin':{'kind':'intervalo externo preservado; horarios internos nao gravados',
             'start':{'path':CPU03_ARCHIVE+'/invocacao/invocacao.json','field':'utc_start','original':start},
             'end':{'path':CPU03_ARCHIVE+'/invocacao/resultado.json','field':'utc_end','original':end},
             'normalization':'somente +00:00 para Z; mesmos instantes'},
           'inferences':0,'retry_allowed':False,'original_state_modified':False,'M1_authorized':False}
  return {e.LOG_PATH:log,CPU03_RESULT:result_raw,
          CPU03_RECEIPT:e.canonical(receipt)+b'\n'}
 finally:
  for name,value in zip(PIN_NAMES,pins):setattr(e,name,value)

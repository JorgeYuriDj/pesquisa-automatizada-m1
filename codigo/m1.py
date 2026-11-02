"""M1/V6: closed contract, independent capture binding and persistent limits.

Pure checks do not grant operational authority. The Python adapter requires the
future signed act, qualified route and CPU acceptance; imports have no effects.
"""
import hashlib
import math
import re
from . import executor_modelo as e
from . import frontend_cpu as f


def turno1(raw):
    e.require(type(raw) is bytes and 0<len(raw)<=32768,'m1_turno1_bytes')
    value=e.strict_json(raw)
    e.require(type(value) is dict and set(value)=={'schema','codigo'},'m1_turno1_keys')
    e.require(value['schema']=='sc-m1-turno1/1' and type(value['codigo']) is str,'m1_turno1_schema')
    code=value['codigo'].encode('utf-8')
    e.require(0<len(code)<=16384 and b'\0' not in code,'m1_codigo_bytes')
    return code  # Parsed, NOT admissible or authorized for execution.


def contexto(turn, prompt_tokens):
    e.require(type(turn) is int and turn in (1,2),'m1_turno')
    f.prompt_budget(prompt_tokens,512 if turn==1 else 2048,8192)


def conferir_fluxos(attempt, first_raw, stdout, stderr, receipt):
    """Bind already collected streams; does NOT run/re-run code to compare."""
    e.require(type(attempt) is str and re.fullmatch('[0-9a-f]{32}',attempt),'m1_attempt')
    code=turno1(first_raw)
    e.require(type(stdout) is bytes and type(stderr) is bytes and
              len(stdout)<=65536 and len(stderr)<=65536,'m1_fluxos_limite')
    fields={'schema','attempt','code_sha256','stdout_sha256','stderr_sha256',
            'argv','returncode','timeout','complete','duration_ns'}
    e.require(type(receipt) is dict and set(receipt)==fields,'m1_recibo_schema')
    e.require(receipt['schema']=='sc-m1-exec-capture/1' and receipt['attempt']==attempt,'m1_recibo_vinculo')
    for key,data in [('code_sha256',code),('stdout_sha256',stdout),('stderr_sha256',stderr)]:
        e.require(receipt[key]==hashlib.sha256(data).hexdigest(),'m1_fluxo_alterado')
    e.require(receipt['argv']==['/usr/bin/python3','-I','-S','/codigo.py'],'m1_python_argv')
    e.require(type(receipt['returncode']) is int and receipt['returncode']==0 and
              receipt['timeout'] is False and receipt['complete'] is True,'m1_execucao_incompleta')
    e.require(type(receipt['duration_ns']) is int and 0<=receipt['duration_ns']<=10_000_000_000,'m1_execucao_tempo')
    stdout.decode('utf-8','strict');stderr.decode('utf-8','strict')
    return {'scope':'stream_consistency_only','operational_go':False,'attempt':attempt}


TURNO2_INSTRUCAO = 'Saida registrada pelo harness (stdout integral) abaixo. Agora entregue somente o objeto JSON final no esquema exato de contrato.md, sem cercas e sem texto fora do objeto. Use os nomes e a estrutura da ficha abaixo. Os campos vazios sao apenas marcadores: preencha cada campo com o tipo e o conteudo exigidos pelo contrato, sem acrescentar chaves.\n{\n  "etapa": "",\n  "grandeza": "",\n  "formula": "",\n  "entradas": {\n    "E_in": {\n      "valor": "",\n      "unidade": "",\n      "procedencia": ""\n    },\n    "Y": {\n      "valor": "",\n      "unidade": "",\n      "procedencia": ""\n    }\n  },\n  "saida": {\n    "valor": "",\n    "valor_3_algarismos": "",\n    "unidade": ""\n  },\n  "calculo": {\n    "ferramenta": "",\n    "codigo": "",\n    "saida_bruta": ""\n  },\n  "interpretacao": ""\n}'


def mensagens_turno2(initial, first_raw, stdout, stderr, receipt, attempt):
    e.require(type(initial) is str and 0<len(initial.encode('utf-8'))<=65536,'m1_entrada')
    conferir_fluxos(attempt,first_raw,stdout,stderr,receipt)
    # Preserve original admitted JSON and captured stdout; no tips or repair.
    return [{'role':'user','content':initial},
            {'role':'assistant','content':first_raw.decode('utf-8','strict')},
            {'role':'user','content':TURNO2_INSTRUCAO+'\n\n'+stdout.decode('utf-8','strict')}]


def v6_consistente(attempt, first_raw, stdout, stderr, receipt, final):
    checked=conferir_fluxos(attempt,first_raw,stdout,stderr,receipt)
    e.require(type(final) is dict and type(final.get('calculo')) is dict and
              type(final.get('saida')) is dict,'m1_v6_estrutura')
    calc=final['calculo'];output=final['saida'];value=output.get('valor')
    e.require(type(value) in (int,float) and math.isfinite(value),'m1_v6_valor')
    # A copy error cannot hide a number without captured provenance.
    if stdout.split(b'\n',1)[0] != repr(value).encode('utf-8'):raise Incidente('m1_v6_valor_sem_procedencia')
    e.require(type(calc.get('codigo')) is str and calc['codigo'].encode('utf-8')==turno1(first_raw),'m1_v6_codigo')
    e.require(type(calc.get('saida_bruta')) is str and calc['saida_bruta'].encode('utf-8')==stdout,'m1_v6_stdout')
    e.require(type(output.get('valor_3_algarismos')) is str and
              output['valor_3_algarismos']==format(value,'.3g'),'m1_v6_format')
    e.require(stdout==(repr(value)+'\n'+output['valor_3_algarismos']+'\n').encode('utf-8'),'m1_v6_linhas')
    return checked  # Independent origin, V1-V5/V7 and operational gates still required.


def estado_inicial(start_ns):
    e.require(type(start_ns) is int and start_ns>=0,'m1_clock')
    return dict(start_ns=start_ns,last_ns=start_ns,recusadas=0,erros=0,terminal=None)


def registrar_falha(state,event,now_ns):
    e.require(type(state) is dict and set(state)=={'start_ns','last_ns','recusadas','erros','terminal'},'m1_estado')
    e.require(all(type(state[k]) is int and state[k]>=0 for k in ('start_ns','last_ns','recusadas','erros')),'m1_estado_contadores')
    e.require(type(now_ns) is int and now_ns>=state['last_ns']>=state['start_ns'],'m1_clock_regressao')
    e.require(state['terminal'] is None,'m1_ja_encerrada')
    e.require(event in ('recusa','erro_execucao','incidente','pare'),'m1_evento')
    new=dict(state,last_ns=now_ns)
    if event in ('incidente','pare'):new['terminal']=event
    elif now_ns-state['start_ns']>=1_800_000_000_000:new['terminal']='prazo'
    else:
        key='recusadas' if event=='recusa' else 'erros';new[key]+=1
        if new['recusadas']>=3 or new['erros']>=3:new['terminal']='limite'
    return new

import ast
import json
import os
from pathlib import Path

FILES=('escopo.md','contrato.md','exemplo_certo.md','exemplo_a_recusar.md','constantes.json')
FRASES={
    1:'Q_sci > 1: a energia de fusão liberada (Y) superou a energia do laser (E_in).',
    -1:'Q_sci < 1: a energia de fusão liberada (Y) foi menor que a energia do laser (E_in).',
    0:'Q_sci = 1: a energia de fusão liberada (Y) igualou a energia do laser (E_in).',
}

class Incidente(ValueError):
    """An integrity/access/provenance incident ends the run, without retry."""

def h(raw):return hashlib.sha256(raw).hexdigest()

def carregar_entradas(escopo):
    e.require(type(escopo) is bytes,'m1_escopo_bytes')
    text=escopo.decode('utf-8','strict')
    pattern=r'- \x60(?P<name>E_in|Y)\x60 = \x60(?P<value>[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)\x60 J,[^\n]*\n  Procedência: \x60(?P<origin>[^\x60\n]+)\x60'
    found=list(re.finditer(pattern,text));e.require(len(found)==2,'m1_entradas_formato')
    result={}
    for item in found:
        name=item['name'];value=float(item['value'])
        e.require(name not in result and math.isfinite(value) and value>0,'m1_entrada_positiva')
        result[name]={'valor':value,'unidade':'J','procedencia':item['origin']}
    e.require(set(result)=={'E_in','Y'},'m1_entradas')
    return result

def lote(raw_files,expected_hashes):
    e.require(type(raw_files) is dict and set(raw_files)==set(FILES),'m1_cinco_arquivos')
    e.require(type(expected_hashes) is dict and set(expected_hashes)==set(FILES),'m1_hashes_lote')
    for name in FILES:
        raw=raw_files[name]
        e.require(type(raw) is bytes and 0<len(raw)<=65536,'m1_arquivo')
        if h(raw)!=expected_hashes[name]:raise Incidente('m1_lote_alterado')
        raw.decode('utf-8','strict')
    constants=e.strict_json(raw_files['constantes.json'])
    e.require(type(constants) is dict and set(constants)=={'autor','constantes'} and constants['constantes']==[],'m1_constantes')
    return carregar_entradas(raw_files['escopo.md'])

def codigo_admissivel(raw,inputs):
    """Closed AST recognizer; preserves bytes, never evaluates generated code."""
    code=turno1(raw)
    try:tree=ast.parse(code.decode('utf-8','strict'),mode='exec')
    except (SyntaxError,ValueError) as ex:raise ValueError('m1_codigo_sintaxe') from ex
    for node in ast.walk(tree):
        if (isinstance(node,(ast.Import,ast.ImportFrom)) or
            isinstance(node,ast.Attribute) and '__' in node.attr or
            isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and
            node.func.id in ('open','exec','eval','compile','__import__','getattr','globals','locals','vars','input','breakpoint')):
            raise Incidente('m1_acesso_proibido')
    # Ordinary attributes/calls remain outside the closed AST, but are recusals.
    # Scan every node for incidents first, including nested dunder attributes.
    if len(tree.body)!=5:raise ValueError('m1_codigo_fora_contrato')
    seen=set()
    for node in tree.body[:2]:
        if not (isinstance(node,ast.Assign) and len(node.targets)==1 and
                isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('E_in','Y') and
                isinstance(node.value,ast.Constant) and type(node.value.value) in (int,float)):
            raise ValueError('m1_entrada_codigo')
        name=node.targets[0].id
        try:value=float(node.value.value)
        except (ValueError,OverflowError):raise Incidente('m1_literal_nao_finito') from None
        if name in seen or not math.isfinite(value) or value!=float(inputs[name]['valor']):
            raise Incidente('m1_numero_sem_procedencia')
        seen.add(name)
    expected=ast.parse('q = Y / E_in\nprint(repr(q))\nprint(format(q, ".3g"))\n')
    if [ast.dump(x,include_attributes=False) for x in tree.body[2:]] != [
            ast.dump(x,include_attributes=False) for x in expected.body]:
        raise ValueError('m1_operacao_fora_contrato')
    return code

def verificar(raw_final,inputs,attempt,first_raw,stdout,stderr,receipt):
    """V1-V7 only; independent capture origin belongs to the outer collector."""
    code=codigo_admissivel(first_raw,inputs)
    e.require(type(raw_final) is bytes and 0<len(raw_final)<=65536,'V1_bytes')
    v=e.strict_json(raw_final)
    def exact(obj,keys):e.require(type(obj) is dict and set(obj)==set(keys),'V1_chaves')
    def number(value):return type(value) in (int,float) and math.isfinite(value)
    exact(v,('etapa','grandeza','formula','entradas','saida','calculo','interpretacao'))
    exact(v['entradas'],('E_in','Y'));exact(v['saida'],('valor','valor_3_algarismos','unidade'))
    exact(v['calculo'],('ferramenta','codigo','saida_bruta'))
    for name in ('E_in','Y'):
        exact(v['entradas'][name],('valor','unidade','procedencia'))
        e.require(number(v['entradas'][name]['valor']) and
                  type(v['entradas'][name]['unidade']) is str and
                  type(v['entradas'][name]['procedencia']) is str,'V1_entrada_tipos')
    e.require(number(v['saida']['valor']),'V1_valor')
    texts=[v[k] for k in ('etapa','grandeza','formula','interpretacao')]
    texts+=[v['saida'][k] for k in ('valor_3_algarismos','unidade')]
    texts+=list(v['calculo'].values())
    e.require(all(type(value) is str for value in texts),'V1_texto')
    e.require((v['etapa'],v['grandeza'],v['formula'],v['calculo']['ferramenta'])==
              ('M1-QSCI-N230729','Q_sci','Q_sci = Y / E_in','python'),'V2_identidade')
    e.require(all(v['entradas'][n]['unidade']=='J' for n in ('E_in','Y')) and
              v['saida']['unidade']=='adimensional','V2_unidades')
    for name in ('E_in','Y'):
        if float(v['entradas'][name]['valor'])!=float(inputs[name]['valor']) or v['entradas'][name]['procedencia']!=inputs[name]['procedencia']:
            raise Incidente('V3_entrada_alterada')
    v6_consistente(attempt,first_raw,stdout,stderr,receipt,v)
    expected=float(inputs['Y']['valor'])/float(inputs['E_in']['valor'])
    e.require(math.isfinite(expected) and expected>0 and abs(v['saida']['valor']-expected)<=1e-9*expected,'V4')
    e.require(v['saida']['valor_3_algarismos']==format(v['saida']['valor'],'.3g'),'V5')
    value=v['saida']['valor'];relation=(value>1)-(value<1)
    e.require(v['interpretacao']==FRASES[relation],'V7')
    return {'schema':'sc-m1-verificado/1','criterios':['V1','V2','V3','V4','V5','V6','V7'],
            'output_sha256':h(raw_final),'code_sha256':h(code),'stdout_sha256':h(stdout),
            'scope':'verified_against_supplied_capture','operational_go':False}

def entrada_turno1(raw_files,expected_hashes):
    lote(raw_files,expected_hashes)
    parts=['Entregue somente {"schema":"sc-m1-turno1/1","codigo":"..."} com o bloco Python permitido no contrato. Use exatamente cinco instruções: E_in e Y atribuídos aos literais do escopo (em qualquer ordem); q = Y / E_in; print(repr(q)); print(format(q, \".3g\")). Comentários e espaços são permitidos. Não execute conta de cabeça.']
    for name in FILES:parts.append('ARQUIVO '+name+'\n'+raw_files[name].decode('utf-8','strict'))
    return '\n\n'.join(parts)

def preparar_turno(turn,template,messages,ids_stdout):
    e.require(type(messages) is list and messages and
              all(type(x) is dict and set(x)=={'role','content'} and x['role'] in ('user','assistant') and type(x['content']) is str for x in messages),'m1_messages')
    rendered=f.render(template,messages)
    ids=e.strict_json(ids_stdout)
    e.require(type(ids) is list and ids and all(type(x) is int and x>=0 for x in ids),'m1_token_ids')
    contexto(turn,len(ids))
    return {'schema':'sc-m1-prompt/1','turn':turn,'history_sha256':h(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode()),
            'prompt_sha256':h(rendered),'prompt':rendered,'ids':ids,'P':len(ids),'n_ctx':8192,
            'max_tokens':512 if turn==1 else 2048,'scope':'requires_independent_tokenizer_binding'}


import fcntl
import functools

def exclusivo(fn):
    @functools.wraps(fn)
    def wrapped(self,*args,**kwargs):
        fd=os.open(self.path/'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            return fn(self,*args,**kwargs)
        finally:os.close(fd)
    return wrapped

def boot_id():return Path('/proc/sys/kernel/random/boot_id').read_text().strip()

class Sessao:
    """Persistent single run; unfinished attempts block automatic resumption.

    Trusted coordinator owns this directory; model/code never mount it.
    This state machine grants no authority to start model or Python units.
    """
    def __init__(self,path,freeze_hash,clock,authority_root=None):
        self.path=Path(path);self.freeze_hash=freeze_hash;self.clock=clock;self.authority_root=authority_root
    def _save(self,v):
        temp=self.path/'estado.tmp'
        with temp.open('x',encoding='utf-8') as stream:
            json.dump(v,stream,ensure_ascii=False,sort_keys=True);stream.write('\n')
            stream.flush();os.fsync(stream.fileno())
        os.replace(temp,self.path/'estado.json')
        fd=os.open(self.path,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
    def iniciar(self):
        e.require(re.fullmatch('[0-9a-f]{64}',self.freeze_hash) is not None,'m1_freeze')
        self.path.mkdir(mode=0o700,parents=False,exist_ok=False)
        v=estado_inicial(self.clock());v.update(freeze=self.freeze_hash,active=None,used=[],seal=None,boot_id=boot_id())
        self._save(v);return v
    def _load(self,current_freeze,pare):
        v=e.strict_json((self.path/'estado.json').read_bytes())
        if v['boot_id']!=boot_id():
            v['terminal']='incidente_reinicio';self._save(v);raise Incidente(v['terminal'])
        if pare or current_freeze!=v['freeze']:
            v['terminal']='pare' if pare else 'incidente_lote';self._save(v);raise Incidente(v['terminal'])
        e.require(v['terminal'] is None and v['seal'] is None,'m1_terminal')
        instant=self.clock();e.require(instant>=v['last_ns'],'m1_clock_regressao')
        if instant-v['start_ns']>=1_800_000_000_000:
            v['last_ns']=instant;v['terminal']='prazo';self._save(v);raise ValueError('m1_prazo')
        v['last_ns']=instant;return v
    @exclusivo
    def admitir(self,attempt,current_freeze,pare=False):
        v=self._load(current_freeze,pare)
        e.require(re.fullmatch('[0-9a-f]{32}',attempt) is not None,'m1_attempt')
        e.require(v['active'] is None and attempt not in v['used'],'m1_consumida_ou_incompleta')
        marker=self.path/('tentativa-'+attempt);marker.mkdir(mode=0o700,exist_ok=False)
        v['used'].append(attempt);v['active']=attempt;self._save(v);return marker
    @exclusivo
    def falhar(self,attempt,event):
        v=e.strict_json((self.path/'estado.json').read_bytes())
        e.require(v['active']==attempt,'m1_attempt_ativa')
        base={k:v[k] for k in ('start_ns','last_ns','recusadas','erros','terminal')}
        base=registrar_falha(base,event,self.clock());v.update(base);v['active']=None
        v['ultima_causa']=event;self._save(v);return v
    @exclusivo
    def aceitar(self,attempt,raw_final,inputs,first_raw,stdout,stderr,receipt,current_freeze,pare=False):
        v=self._load(current_freeze,pare);e.require(v['active']==attempt,'m1_attempt_ativa')
        from . import m1_exec
        e.require(self.authority_root is not None,'m1_authority_missing')
        e.require(self.path.resolve()==(Path(m1_exec.ROOT)/'estado-corrida').resolve(),'m1_canonical_session')
        trusted=m1_exec.autoridade(self.authority_root)
        if current_freeze!=m1_exec.FREEZE or inputs!=trusted['inputs']:raise Incidente('m1_lote_nao_vinculado')
        from . import cpu_exec
        cpu_exec.require_generation(self.authority_root,attempt,1,first_raw)
        cpu_exec.require_generation(self.authority_root,attempt,2,raw_final)
        marker=self.path/('tentativa-'+attempt)
        capture=marker/'execucao'
        # Only the outer collector writes this directory; never mounted in child.
        for name,data in [('turno1.json',first_raw),('stdout.bin',stdout),('stderr.bin',stderr)]:
            e.require((capture/name).read_bytes()==data,'m1_captura_independente')
        recorded=e.strict_json((capture/'recibo.json').read_bytes())
        e.require(recorded==receipt,'m1_recibo_independente')
        checked=verificar(raw_final,inputs,attempt,first_raw,stdout,stderr,receipt)
        raw_receipt=json.dumps(receipt,sort_keys=True,separators=(',',':')).encode()
        for name,data in [('saida.json',raw_final),('turno1.json',first_raw),('stdout.bin',stdout),('stderr.bin',stderr),('recibo.json',raw_receipt)]:
            with (marker/name).open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        seal={'schema':'sc-m1-selo/1','attempt':attempt,'freeze':v['freeze'],'verification':checked,'receipt_sha256':h(raw_receipt)}
        self._load(current_freeze,pare)  # deadline must still hold immediately before sealing
        with (self.path/'selo.json').open('x',encoding='utf-8') as stream:
            json.dump(seal,stream,ensure_ascii=False,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        v.update(seal=h((self.path/'selo.json').read_bytes()),terminal='aceita',active=None);self._save(v)
        return seal

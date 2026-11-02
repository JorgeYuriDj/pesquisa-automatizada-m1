"""Fichas de aceite: o critério de cada item do plano escrito como verificações que o código executa.

Ordem do dono de 30/10: regra determinística é regra em código. Cada item do plano tem uma ficha
JSON em blocos/fichas/<ITEM>.json com entrada e saída esperadas. Quem decide se o item foi
cumprido é este módulo, não a sessão que fez o trabalho. Uma frase de aceite sem ficha não fecha.

Esquema da ficha (sc-ficha/1):
  {
    "schema": "sc-ficha/1",
    "item": "B04-02",
    "criterio_sha256": "<sha256 do texto do aceite no plano; muda o texto, muda a ficha>",
    "tipo": "maquina" | "dono" | "julgamento",
    "verificacoes": [ {"id": "V1", "tipo": <tipo>, ...campos...}, ... ],
    "negativos":    [ {"id": "N1", "alvo": "V1", "mutacao": {"tipo": <mutacao>, ...}}, ... ]
  }

Tipos de item:
  maquina     só verificações mecânicas; nenhuma confirmação de pessoa;
  dono        exige pelo menos uma `confirmacao_dono`: um arquivo criado pelo dono no site do
              GitHub, cujo commit o GitHub assina (chave em blocos/CHAVES_CONFIRMACAO.json);
              nenhuma sessão de agente consegue produzir essa assinatura;
  julgamento  exige pelo menos uma `parecer_contem`: os dois revisores externos escrevem no
              parecer do bloco a linha pedida (por exemplo "JULGAMENTO B08-01: aprovado").

Tipos de verificação (lista fechada; qualquer outro campo é erro):
  arquivo          {path, contem?: [str], nao_contem?: [str], min_bytes?: int}
                   arquivo versionado existe e contém/não contém os trechos literais.
  json             {path, campos?: {"a.b.0": valor}, existem?: ["a.b"], minimos?: {"a.n": num},
                    tipos?: {"a.b": "int|float|str|bool|list|dict"}}
                   JSON estrito versionado com os valores exatos pedidos.
  comando          {argv: ["python3", "controle/x.py", ...] | ["git", <subcomando leitura>, ...],
                    codigo?: 0, stdout_contem?: [str], stdout_nao_contem?: [str], timeout?: <=600,
                    repeticoes?: 1..3, saidas_identicas?: bool, rede?: false}
                   roda um script versionado do repositório, sem rede (unshare), ambiente mínimo.
  recibo_testes    {suite: "controle/test_x.py", min_executados?: int, testes?: ["modulo.Classe.test_y"]}
                   o último recibo APROVADO da cadeia de testes, gerado sobre o código atual,
                   tem a suíte com zero falhas e os testes nomeados com status passed.
  remoto           {antes_de?: "AAAA-MM-DDTHH:MM:SSZ"}
                   HEAD igual ao ramo no origin; se antes_de, o commit é anterior a esse instante.
  ordem_git        {antes: path, depois: path}
                   o commit que criou `antes` é ancestral do commit que criou `depois`.
  confirmacao_dono {path: "docs/decisoes/confirmacoes/<nome>.md", contem?: [str]}
                   arquivo criado num único commit, assinado pela chave do GitHub (site), com autor
                   do dono, que só acrescenta esse arquivo e cujo conteúdo traz os trechos pedidos.
  parecer_contem   {linha: str, revisores?: ["claude", "antigravity"]}
                   o parecer de cada revisor, citado por hash no recibo de revisão do bloco, contém a linha.

Negativos: cada verificação precisa de pelo menos um negativo. O negativo aplica uma mutação numa
cópia temporária do repositório e exige que a verificação alvo FALHE. Uma ficha que aprova mesmo
depois da mutação é uma ficha furada e não vale. Mutações (lista fechada):
  apagar {path} | alterar_byte {path} | truncar {path} | substituir {path, de, para} |
  json_definir {path, campo, valor} | commit_vazio {} | recommitar {path}

Uso:
  python3 -I -B controle/fichas.py validar [--negativos] [--bloco B03]   estrutura, cobertura, hashes
  python3 -I -B controle/fichas.py conferir B04-02 [--bloco B04]         roda as verificações
  python3 -I -B controle/fichas.py negativos B04-02 [--bloco B04]        roda os negativos
  python3 -I -B controle/fichas.py confirmacao docs/decisoes/confirmacoes/x.md
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.append(str(Path(__file__).resolve().parent))
from juiz_base import canonical, protected_bytes, isolated_command, guarded_git, verify_openpgp, git_fixture_mutation, Blocked, require, digest, filehash, strict_json, RESTRICTED, git_env   # noqa: E402

DIR = 'blocos/fichas'
SCHEMA = 'sc-ficha/1'
CHAVES = 'blocos/CHAVES_CONFIRMACAO.json'
CONFIRMACOES = 'docs/decisoes/confirmacoes'
PLANO = 'blocos/PLANO.json'
TIPOS = ('maquina', 'dono', 'julgamento')
TIPOS_VERIFICACAO = ('arquivo', 'json', 'comando', 'recibo_testes', 'remoto', 'ordem_git', 'confirmacao_dono', 'parecer_contem', 'qualificacao_lancador')
CAMPOS = {
    'qualificacao_lancador': ({'dt','instalacao'},set()),
    'arquivo': ({'path'}, {'contem', 'nao_contem', 'min_bytes'}),
    'json': ({'path'}, {'campos', 'existem', 'minimos', 'tipos'}),
    'comando': ({'argv'}, {'codigo', 'stdout_contem', 'stdout_nao_contem', 'timeout', 'repeticoes', 'saidas_identicas', 'rede'}),
    'recibo_testes': ({'suite'}, {'min_executados', 'testes'}),
    'remoto': (set(), {'antes_de'}),
    'ordem_git': ({'antes', 'depois'}, set()),
    'confirmacao_dono': ({'path'}, {'contem'}),
    'parecer_contem': ({'linha'}, {'revisores'}),
}
MUTACOES = {
    'apagar': {'path'}, 'alterar_byte': {'path'}, 'truncar': {'path'}, 'substituir': {'path', 'de', 'para'},
    'json_definir': {'path', 'campo', 'valor'}, 'commit_vazio': set(), 'recommitar': {'path'},
}
REVISORES = ('claude', 'antigravity')
COMANDOS_GIT = ('rev-parse', 'log', 'diff', 'status', 'show', 'ls-files', 'ls-remote', 'verify-commit', 'cat-file', 'merge-base', 'diff-tree')
TIPOS_JSON = {'int': int, 'float': (int, float), 'str': str, 'bool': bool, 'list': list, 'dict': dict}
ID_ITEM = re.compile(r'B\d{2}-\d{2}')
ID_BLOCO = re.compile(r'B\d{2}')
ID_CHECK = re.compile(r'[VN]\d{1,2}')
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
INSTANTE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
EMAIL = re.compile(r'[^@\s]+@[^@\s]+')
MAX_TIMEOUT = 600
MAX_LEITURA = 8 * 1024 * 1024
_ISOLAMENTO = {}


# ---------------------------------------------------------------- utilidades

def git(root, *args, check=True):
    p = guarded_git(root, *args, text=True, timeout=120)
    if check and p.returncode != 0:
        nome = next((a for a in args if not a.startswith('-') and '=' not in a), args[0])
        raise Blocked('git_failed:%s:%s' % (nome, p.stderr.strip().splitlines()[-1][:80] if p.stderr.strip() else ''))
    return p


def rastreados(root):
    return set(git(root, 'ls-files', '-z').stdout.split('\0'))


def caminho_ok(path):
    require(isinstance(path, str) and path and not path.startswith('/') and '..' not in path.split('/')
            and '/'.join(Path(path).parts) == path, 'caminho_invalido:' + str(path))
    require(not RESTRICTED.search(path), 'material_restrito:' + path)
    return path


def ler(root, rel, rastreado=None):
    """Bytes de um arquivo versionado, pequeno e sem truque de caminho."""
    caminho_ok(rel)
    require(rel in (rastreados(root) if rastreado is None else rastreado), 'nao_versionado:' + rel)
    p = Path(root) / rel
    require(p.is_file() and not p.is_symlink(), 'ausente:' + rel)
    require(p.stat().st_size <= MAX_LEITURA, 'arquivo_grande:' + rel)
    return protected_bytes(p,MAX_LEITURA)


def texto(dados):
    return dados.decode('utf-8', errors='replace')


def valor_em(obj, campo):
    atual = obj
    for parte in campo.split('.'):
        if isinstance(atual, list):
            require(parte.isdigit() and int(parte) < len(atual), 'campo_ausente:' + campo)
            atual = atual[int(parte)]
        else:
            require(isinstance(atual, dict) and parte in atual, 'campo_ausente:' + campo)
            atual = atual[parte]
    return atual


def lista_de_textos(valor, motivo):
    require(isinstance(valor, list) and all(isinstance(x, str) and x for x in valor), motivo)
    return valor


def instante(valor):
    require(isinstance(valor, str) and INSTANTE.fullmatch(valor), 'instante_invalido:' + str(valor))
    import calendar
    return calendar.timegm(time.strptime(valor, '%Y-%m-%dT%H:%M:%SZ'))


# ---------------------------------------------------------------- esquema

def validar_verificacao(v):
    require(isinstance(v, dict) and isinstance(v.get('id'), str) and ID_CHECK.fullmatch(v['id']) and v['id'][0] == 'V', 'verificacao_id')
    t = v.get('tipo')
    require(t in TIPOS_VERIFICACAO, 'verificacao_tipo:%s' % v['id'])
    obrig, opc = CAMPOS[t]
    chaves = set(v) - {'id', 'tipo'}
    require(obrig <= chaves <= obrig | opc, 'verificacao_campos:%s' % v['id'])
    for k in ('path', 'antes', 'depois', 'dt', 'instalacao'):
        if k in v:
            caminho_ok(v[k])
    for k in ('contem', 'nao_contem', 'stdout_contem', 'stdout_nao_contem', 'existem', 'testes'):
        if k in v:
            lista_de_textos(v[k], 'verificacao_lista:%s:%s' % (v['id'], k))
    if t == 'arquivo' and 'min_bytes' in v:
        require(type(v['min_bytes']) is int and v['min_bytes'] >= 1, 'verificacao_min_bytes:' + v['id'])
    if t == 'json':
        for k in ('campos', 'minimos', 'tipos'):
            if k in v:
                require(isinstance(v[k], dict) and v[k] and all(isinstance(c, str) and c for c in v[k]), 'verificacao_json:%s:%s' % (v['id'], k))
        if 'minimos' in v:
            require(all(type(x) in (int, float) and type(x) is not bool for x in v['minimos'].values()), 'verificacao_minimos:' + v['id'])
        if 'tipos' in v:
            require(all(x in TIPOS_JSON for x in v['tipos'].values()), 'verificacao_tipos:' + v['id'])
        require(any(k in v for k in ('campos', 'existem', 'minimos', 'tipos')), 'verificacao_json_vazia:' + v['id'])
    if t == 'comando':
        argv = v['argv']
        lista_de_textos(argv, 'comando_argv:' + v['id'])
        require(len(argv) >= 2 and argv[0] in ('python3', 'git'), 'comando_programa:' + v['id'])
        if argv[0] == 'python3':
            caminho_ok(argv[1])
            require(argv[1].endswith('.py') and argv[1].split('/')[0] in ('controle', 'infra'), 'comando_script:' + v['id'])
        else:
            require(argv[1] in COMANDOS_GIT, 'comando_git:' + v['id'])
        require(type(v.get('codigo', 0)) is int, 'comando_codigo:' + v['id'])
        require(type(v.get('timeout', 120)) is int and 1 <= v.get('timeout', 120) <= MAX_TIMEOUT, 'comando_timeout:' + v['id'])
        require(type(v.get('repeticoes', 1)) is int and 1 <= v.get('repeticoes', 1) <= 3, 'comando_repeticoes:' + v['id'])
        require(type(v.get('saidas_identicas', False)) is bool and type(v.get('rede', False)) is bool, 'comando_flags:' + v['id'])
        require(not v.get('saidas_identicas') or v.get('repeticoes', 1) >= 2, 'comando_identicas_sem_repeticao:' + v['id'])
    if t == 'recibo_testes':
        caminho_ok(v['suite'])
        require(type(v.get('min_executados', 1)) is int and v.get('min_executados', 1) >= 1, 'recibo_min:' + v['id'])
    if t == 'remoto' and 'antes_de' in v:
        instante(v['antes_de'])
    if t == 'confirmacao_dono':
        require(v['path'].startswith(CONFIRMACOES + '/') and v['path'].endswith('.md'), 'confirmacao_caminho:' + v['id'])
    if t == 'parecer_contem':
        require(isinstance(v['linha'], str) and len(v['linha'].strip()) >= 8, 'parecer_linha:' + v['id'])
        revisores = v.get('revisores', list(REVISORES))
        require(isinstance(revisores, list) and revisores and all(r in REVISORES for r in revisores) and len(set(revisores)) == len(revisores), 'parecer_revisores:' + v['id'])
    return v


def validar_negativo(n, alvos):
    require(isinstance(n, dict) and set(n) == {'id', 'alvo', 'mutacao'} and isinstance(n.get('id'), str)
            and ID_CHECK.fullmatch(n['id']) and n['id'][0] == 'N', 'negativo_id')
    require(n['alvo'] in alvos, 'negativo_alvo:' + n['id'])
    m = n['mutacao']
    require(isinstance(m, dict) and m.get('tipo') in MUTACOES and set(m) - {'tipo'} == MUTACOES[m['tipo']], 'negativo_mutacao:' + n['id'])
    if 'path' in m:
        caminho_ok(m['path'])
    for k in ('de', 'para', 'campo'):
        if k in m:
            require(isinstance(m[k], str) and m[k] != '' if k != 'para' else isinstance(m[k], str), 'negativo_mutacao:' + n['id'])
    return n


def validar_ficha(ficha, aceite=None, item=None):
    require(isinstance(ficha, dict) and set(ficha) == {'schema', 'item', 'criterio_sha256', 'tipo', 'verificacoes', 'negativos'}
            and ficha['schema'] == SCHEMA, 'ficha_schema')
    require(isinstance(ficha['item'], str) and ID_ITEM.fullmatch(ficha['item']), 'ficha_item')
    require(item is None or ficha['item'] == item, 'ficha_item_diverge_do_nome')
    require(isinstance(ficha['criterio_sha256'], str) and HEX64.fullmatch(ficha['criterio_sha256']), 'ficha_criterio')
    require(aceite is None or ficha['criterio_sha256'] == digest(aceite), 'ficha_criterio_diverge_do_plano:' + ficha['item'])
    require(ficha['tipo'] in TIPOS, 'ficha_tipo')
    vs, ns = ficha['verificacoes'], ficha['negativos']
    require(isinstance(vs, list) and vs and isinstance(ns, list), 'ficha_sem_verificacao')
    ids = [validar_verificacao(v)['id'] for v in vs]
    require(len(set(ids)) == len(ids), 'verificacao_id_repetido')
    nids = [validar_negativo(n, set(ids))['id'] for n in ns]
    require(len(set(nids)) == len(nids), 'negativo_id_repetido')
    sem_negativo = [i for i in ids if i not in {n['alvo'] for n in ns}]
    require(not sem_negativo, 'verificacao_sem_negativo:' + ','.join(sem_negativo))
    tipos = {v['tipo'] for v in vs}
    if ficha['tipo'] == 'maquina':
        require(not tipos & {'confirmacao_dono', 'parecer_contem'}, 'ficha_maquina_com_pessoa')
    elif ficha['tipo'] == 'dono':
        require('confirmacao_dono' in tipos, 'ficha_dono_sem_confirmacao')
    else:
        require('parecer_contem' in tipos, 'ficha_julgamento_sem_parecer')
    return ficha


def caminho_ficha(item):
    return '%s/%s.json' % (DIR, item)


def carregar(root, item, aceite=None):
    require(isinstance(item, str) and ID_ITEM.fullmatch(item), 'ficha_item')
    rel = caminho_ficha(item)
    p = Path(root) / rel
    require(p.is_file() and not p.is_symlink(), 'ficha_ausente:' + item)
    return validar_ficha(strict_json(p.read_bytes()), aceite, item)


def hash_ficha(root, item):
    p = Path(root) / caminho_ficha(item)
    return filehash(p.read_bytes()) if p.is_file() else None


# ---------------------------------------------------------------- verificações

def v_arquivo(root, v, ctx):
    dados = ler(root, v['path'], ctx['rastreados'])
    require(len(dados) >= v.get('min_bytes', 1), 'arquivo_vazio:' + v['path'])
    t = texto(dados)
    for trecho in v.get('contem', []):
        require(trecho in t, 'arquivo_nao_contem:%s:%s' % (v['path'], trecho[:40]))
    for trecho in v.get('nao_contem', []):
        require(trecho not in t, 'arquivo_contem_proibido:%s:%s' % (v['path'], trecho[:40]))


def v_json(root, v, ctx):
    obj = strict_json(ler(root, v['path'], ctx['rastreados']))
    for campo, esperado in v.get('campos', {}).items():
        atual = valor_em(obj, campo)
        require(atual == esperado and type(atual) is type(esperado) if isinstance(esperado, bool) or isinstance(atual, bool) else atual == esperado,
                'json_campo_diverge:%s:%s' % (v['path'], campo))
    for campo in v.get('existem', []):
        valor_em(obj, campo)
    for campo, minimo in v.get('minimos', {}).items():
        atual = valor_em(obj, campo)
        require(type(atual) in (int, float) and type(atual) is not bool and atual >= minimo, 'json_abaixo_do_minimo:%s:%s' % (v['path'], campo))
    for campo, nome in v.get('tipos', {}).items():
        atual = valor_em(obj, campo)
        require(isinstance(atual, TIPOS_JSON[nome]) and not (nome in ('int', 'float') and isinstance(atual, bool)), 'json_tipo_errado:%s:%s' % (v['path'], campo))


def isolamento():
    """Prefixo que corta a rede do comando. Sem isolamento disponível, a verificação não roda."""
    if 'prefixo' not in _ISOLAMENTO:
        prefixo = None
        if shutil.which('unshare'):
            for cand in (['unshare', '-n'], ['unshare', '-rn']):
                try:
                    if subprocess.run(cand + ['true'], capture_output=True, timeout=20).returncode == 0:
                        prefixo = cand
                        break
                except (OSError, subprocess.SubprocessError):
                    pass
        _ISOLAMENTO['prefixo'] = prefixo
    return _ISOLAMENTO['prefixo']


def rodar(root, argv, timeout, rede):
    """Comandos do candidato sempre sem rede e fora da identidade privilegiada do host."""
    return isolated_command(root, argv, timeout, rede)


def v_comando(root, v, ctx):
    if v['argv'][0] == 'python3':
        require(v['argv'][1] in ctx['rastreados'], 'script_nao_versionado:' + v['argv'][1])
    saidas = []
    for _ in range(v.get('repeticoes', 1)):
        codigo, saida = rodar(root, v['argv'], v.get('timeout', 120), v.get('rede', False))
        require(codigo == v.get('codigo', 0), 'comando_codigo_diverge:%d' % codigo)
        saidas.append(saida)
    t = texto(saidas[-1])
    for trecho in v.get('stdout_contem', []):
        require(trecho in t, 'comando_saida_nao_contem:' + trecho[:40])
    for trecho in v.get('stdout_nao_contem', []):
        require(trecho not in t, 'comando_saida_contem_proibido:' + trecho[:40])
    if v.get('saidas_identicas'):
        require(len(set(saidas)) == 1, 'comando_saidas_diferentes')


def v_recibo_testes(root, v, ctx):
    import run_tests
    try:
        ultimo = run_tests.load_history(Path(root) / run_tests.HISTORY)
        atual = run_tests.snapshot(Path(root), completo=True)
    except run_tests.Rejected as exc:
        raise Blocked('historico_testes_invalido:' + str(exc)) from exc
    require(ultimo is not None and ultimo['status'] == 'APROVADO', 'recibo_testes_ausente_ou_reprovado')
    require(ultimo['files'] == atual, 'codigo_mudou_depois_dos_testes')
    linha = next((r for r in ultimo['suites'] if r.get('suite') == v['suite']), None)
    require(linha is not None, 'suite_fora_do_recibo:' + v['suite'])
    res = linha['result']
    require(linha.get('returncode') == 0 and res['failures'] == 0 and res['errors'] == 0 and not res.get('skipped'), 'suite_com_falha:' + v['suite'])
    require(res['executed'] >= v.get('min_executados', 1), 'suite_abaixo_do_minimo:%s:%d' % (v['suite'], res['executed']))
    estados = {o['id']: o['status'] for o in res['outcomes']}
    for tid in v.get('testes', []):
        require(estados.get(tid) == 'passed', 'teste_nao_passou:' + tid)


def v_remoto(root, v, ctx):
    if ctx.get('historico'):
        return   # cópia de um fechamento passado não tem ramo vivo; a conferência ao vivo foi feita ao fechar
    branch = ctx.get('ramo') or git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    head = git(root, 'rev-parse', 'HEAD').stdout.strip()
    require(branch != 'HEAD', 'sem_ramo')
    remoto = git(root, 'ls-remote', 'origin', 'refs/heads/' + branch, check=False).stdout.split()
    require(remoto and remoto[0] == head, 'head_diferente_do_remoto')
    if 'antes_de' in v:
        quando = int(git(root, 'log', '-1', '--format=%ct', 'HEAD').stdout.strip())
        require(quando <= instante(v['antes_de']), 'commit_depois_do_prazo')


def commit_de_criacao(root, rel):
    adds = git(root, 'log', '--diff-filter=A', '--format=%H', '--', rel).stdout.split()
    require(len(adds) == 1, 'arquivo_sem_criacao_unica:' + rel)
    return adds[0]


def v_ordem_git(root, v, ctx):
    for rel in (v['antes'], v['depois']):
        require(rel in ctx['rastreados'], 'nao_versionado:' + rel)
    a, d = commit_de_criacao(root, v['antes']), commit_de_criacao(root, v['depois'])
    require(a != d and git(root, 'merge-base', '--is-ancestor', a, d, check=False).returncode == 0, 'ordem_git_invertida')


def ler_em(root, commit, rel):
    """Bytes de um arquivo como estava num commit (o estado confiado, não a árvore atual)."""
    caminho_ok(rel)
    p = guarded_git(root, 'show', '%s:%s' % (commit, rel), timeout=60)
    require(p.returncode == 0, 'ausente_no_commit:%s:%s' % (str(commit)[:12], rel))
    return p.stdout


def chaves(root, commit=None):
    """Chaves de confirmação em vigor. Com `commit`, lê o arquivo como estava nesse commit: a
    confirmação de uma mudança é conferida com as chaves de ANTES da mudança, nunca com as que a
    própria mudança traz (senão quem troca a chave assina a própria troca)."""
    c = strict_json(ler_em(root, commit, CHAVES) if commit else ler(root, CHAVES))
    require(isinstance(c, dict) and set(c) == {'schema', 'chave_publica', 'impressoes', 'autores', 'committer'}
            and c['schema'] == 'sc-chaves-confirmacao/1', 'chaves_schema')
    caminho_ok(c['chave_publica'])
    require(isinstance(c['impressoes'], list) and c['impressoes'] and all(isinstance(x, str) and HEX40.fullmatch(x.lower()) for x in c['impressoes']), 'chaves_impressoes')
    require(isinstance(c['autores'], list) and c['autores'] and all(isinstance(x, str) and EMAIL.fullmatch(x) for x in c['autores']), 'chaves_autores')
    require(isinstance(c['committer'], str) and EMAIL.fullmatch(c['committer']), 'chaves_committer')
    return c


def assinatura(root, commit, chave_publica):
    """Impressão digital (40 hex) da assinatura OpenPGP válida do commit, ou None."""
    require(shutil.which('gpg') is not None, 'gpg_ausente')
    with tempfile.TemporaryDirectory(prefix='sc-gnupg-') as home:
        os.chmod(home, 0o700)
        env = {**git_env(), 'GNUPGHOME': home}
        imp = subprocess.run(['gpg', '--batch', '--quiet', '--import'], input=chave_publica, capture_output=True, timeout=60, env=env)
        require(imp.returncode == 0, 'chave_publica_invalida')
        p = verify_openpgp(root, commit, home)
        if p.returncode != 0:
            return None
        for linha in p.stderr.splitlines():
            partes = linha.split()
            if len(partes) >= 3 and partes[0] == '[GNUPG:]' and partes[1] == 'VALIDSIG':
                return partes[2].upper()
    return None


def v_confirmacao_dono(root, v, ctx):
    rel = v['path']
    require(rel.startswith(CONFIRMACOES + '/'), 'confirmacao_caminho:' + rel)
    dados = ler(root, rel, ctx['rastreados'])
    em = ctx.get('chaves_commit')
    c = chaves(root, em)
    publica = ler_em(root, em, c['chave_publica']) if em else ler(root, c['chave_publica'], ctx['rastreados'])
    commit = commit_de_criacao(root, rel)
    pais = git(root, 'rev-list', '--parents', '-n', '1', commit).stdout.split()
    require(len(pais) == 2, 'confirmacao_commit_com_varios_pais')
    tocados = git(root, 'diff-tree', '--no-commit-id', '--name-only', '-r', commit).stdout.split()
    require(tocados == [rel], 'confirmacao_commit_toca_outros_arquivos')
    autor, committer = git(root, 'log', '-1', '--format=%ae%n%ce', commit).stdout.split('\n')[:2]
    require(autor in c['autores'], 'confirmacao_autor:' + autor)
    require(committer == c['committer'], 'confirmacao_committer:' + committer)
    no_commit = guarded_git(root, 'show', '%s:%s' % (commit, rel), timeout=60)
    require(no_commit.returncode == 0 and no_commit.stdout == dados, 'confirmacao_alterada_depois_do_commit')
    fp = assinatura(root, commit, publica)
    require(fp is not None and fp in {x.upper() for x in c['impressoes']}, 'confirmacao_sem_assinatura_do_github')
    t = texto(dados)
    for trecho in v.get('contem', []):
        require(trecho in t, 'confirmacao_nao_contem:' + trecho[:40])


def v_parecer_contem(root, v, ctx):
    bloco = ctx.get('bloco')
    require(isinstance(bloco, str) and ID_BLOCO.fullmatch(bloco), 'parecer_sem_bloco')
    for revisor in v.get('revisores', list(REVISORES)):
        rel = 'blocos/%s/revisoes/%s.json' % (bloco, revisor)
        r = strict_json(ler(root, rel, ctx['rastreados']))
        parecer = r.get('parecer') if isinstance(r, dict) else None
        require(isinstance(parecer, dict) and set(parecer) == {'path', 'sha256'}, 'parecer_ausente:' + revisor)
        dados = ler(root, parecer['path'], ctx['rastreados'])
        require(filehash(dados) == parecer['sha256'], 'parecer_mudou:' + revisor)
        require(v['linha'] in texto(dados), 'parecer_sem_linha:%s:%s' % (revisor, v['linha'][:40]))


def v_qualificacao_lancador(root,v,ctx):
    from juiz_base import launcher_qualification
    loader=lambda path:ler(root,path,ctx['rastreados'])
    dt=strict_json(loader(v['dt']))
    def verify_owner(path,terms):
        v_confirmacao_dono(root,{'path':path,'contem':terms},ctx)
    proofs=launcher_qualification(dt,loader,verify_owner,dt['lancador'].get('native_host_id'))
    installation=strict_json(loader(v['instalacao']))
    require(valor_em(installation,'native_host_id')==dt['lancador']['native_host_id'],'installed_native_host_diverges')
    identity=valor_em(installation,'lancador.executor')
    require(canonical(identity)==canonical(dt['lancador']['executor']),'installed_executor_diverges')
    require(valor_em(installation,'lancador.binario_sha256')==dt['lancador']['binario_sha256'],
            'installed_binary_diverges')
    require(valor_em(installation,'isolamento.prova_path')==dt['qualificacao']['sonda']['path'] and
            valor_em(installation,'isolamento.prova_sha256')==dt['qualificacao']['sonda']['sha256'],
            'installed_probe_diverges')
    require(valor_em(installation,'acesso.notebook.demonstrado') is True,'installed_notebook_not_demonstrated')
    if dt['qualificacao']['schema']=='sc-lancador-qualificacao/2':
        require(valor_em(installation,'acesso.celular.demonstrado') is False and
                valor_em(installation,'acesso.celular.pendencia')==proofs['rota_movel']['celular_pendencia'],
                'installed_mobile_deferral_diverges')
    else:
        require(valor_em(installation,'acesso.celular.demonstrado') is True,'installed_mobile_not_demonstrated')


VERIFICADORES = {'qualificacao_lancador':v_qualificacao_lancador,'arquivo': v_arquivo, 'json': v_json, 'comando': v_comando, 'recibo_testes': v_recibo_testes, 'remoto': v_remoto,
                 'ordem_git': v_ordem_git, 'confirmacao_dono': v_confirmacao_dono, 'parecer_contem': v_parecer_contem}


def contexto(root, bloco=None, chaves_commit=None, historico=False):
    return {'rastreados': rastreados(root), 'bloco': bloco, 'chaves_commit': chaves_commit, 'historico': historico,
            'ramo': git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()}


def executar(root, v, ctx):
    try:
        VERIFICADORES[v['tipo']](root, v, ctx)
        return None
    except Blocked as e:
        return str(e)
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, subprocess.SubprocessError) as e:
        return '%s:%s' % (type(e).__name__, e)


def conferir_ficha(root, ficha, bloco=None, chaves_commit=None, historico=False):
    """Lista de falhas das verificações positivas (vazia = item cumprido). historico=True confere a
    cópia de um fechamento passado: a verificação `remoto` não se aplica (não há ramo vivo)."""
    ctx = contexto(root, bloco or ficha['item'][:3], chaves_commit, historico)
    erros = []
    for v in ficha['verificacoes']:
        e = executar(root, v, ctx)
        if e is not None:
            erros.append('%s:%s' % (v['id'], e))
    return erros


def conferir(root, item, bloco=None, aceite=None, chaves_commit=None):
    return conferir_ficha(root, carregar(root, item, aceite), bloco, chaves_commit)


# ---------------------------------------------------------------- negativos

@contextmanager
def copia(root):
    tmp = Path(tempfile.mkdtemp(prefix='sc-ficha-'))
    alvo = tmp / 'arvore'
    try:
        git(root, 'worktree', 'add', '--detach', '--quiet', str(alvo), 'HEAD')
        yield alvo
    finally:
        git(root, 'worktree', 'remove', '--force', str(alvo), check=False)
        git(root, 'worktree', 'prune', check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def git_negativo(copia_root, *args):
    p = git_fixture_mutation(copia_root, *args)
    require(p.returncode == 0, 'git_fixture_failed')
    return p


def aplicar_mutacao(copia_root, m):
    p = Path(copia_root) / m['path'] if 'path' in m else None
    if m['tipo'] == 'apagar':
        require(p.is_file(), 'mutacao_alvo_ausente:' + m['path'])
        p.unlink()
    elif m['tipo'] == 'alterar_byte':
        dados = p.read_bytes()
        p.write_bytes((dados[:-1] + bytes([dados[-1] ^ 0x01])) if dados else b'x')
    elif m['tipo'] == 'truncar':
        require(p.is_file(), 'mutacao_alvo_ausente:' + m['path'])
        p.write_bytes(b'')
    elif m['tipo'] == 'substituir':
        t = texto(p.read_bytes())
        require(m['de'] in t, 'mutacao_trecho_ausente:' + m['de'][:40])
        p.write_bytes(t.replace(m['de'], m['para']).encode('utf-8'))
    elif m['tipo'] == 'json_definir':
        obj = strict_json(p.read_bytes())
        partes = m['campo'].split('.')
        atual = obj
        for parte in partes[:-1]:
            atual = atual[int(parte)] if isinstance(atual, list) else atual[parte]
        if isinstance(atual, list):
            atual[int(partes[-1])] = m['valor']
        else:
            atual[partes[-1]] = m['valor']
        p.write_bytes(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True).encode('utf-8') + b'\n')
    elif m['tipo'] == 'commit_vazio':
        git_negativo(copia_root, 'commit', '-q', '--allow-empty', '-m', 'negativo: commit local')
    elif m['tipo'] == 'recommitar':
        # A cópia está limpa em HEAD: cada commit leva só o que foi preparado aqui.
        git_negativo(copia_root, 'rm', '-q', '--cached', '--', m['path'])
        git_negativo(copia_root, 'commit', '-q', '-m', 'negativo: remove')
        git_negativo(copia_root, 'add', '--', m['path'])
        git_negativo(copia_root, 'commit', '-q', '-m', 'negativo: recria')


def negativos_ficha(root, ficha, bloco=None, chaves_commit=None):
    """Lista de negativos que NÃO fizeram a verificação alvo falhar (vazia = ficha falsificável).
    Exige árvore limpa: a cópia é feita de HEAD, e a verificação alvo precisa passar na cópia antes
    da mutação, senão o negativo 'falharia' por outro motivo e não provaria nada."""
    require(not git(root, 'status', '--porcelain', '-uall').stdout.strip(), 'arvore_suja_para_negativos')
    base = contexto(root, bloco or ficha['item'][:3], chaves_commit)
    furos = []
    alvos = {v['id']: v for v in ficha['verificacoes']}
    for n in ficha['negativos']:
        with copia(root) as c:
            ctx = dict(base, rastreados=rastreados(c))
            antes = executar(c, alvos[n['alvo']], ctx)
            if antes is not None:
                furos.append('%s:alvo_nao_passa_na_copia:%s' % (n['id'], antes))
                continue
            try:
                aplicar_mutacao(c, n['mutacao'])
            except (Blocked, OSError, ValueError, KeyError, IndexError) as e:
                furos.append('%s:mutacao_falhou:%s' % (n['id'], e))
                continue
            ctx = dict(base, rastreados=rastreados(c))
            if executar(c, alvos[n['alvo']], ctx) is None:
                furos.append('%s:nao_falhou' % n['id'])
    return furos


def negativos(root, item, bloco=None, aceite=None, chaves_commit=None):
    return negativos_ficha(root, carregar(root, item, aceite), bloco, chaves_commit)


# ---------------------------------------------------------------- validação do conjunto

def itens_do_plano(root):
    plano = strict_json(ler(root, PLANO))
    saida = {}
    for b in plano['blocos']:
        for i in b['itens']:
            saida[i['id']] = {'bloco': b['id'], 'aceite': i['aceite']}
    return saida


def exigidos(root, itens):
    """Itens que precisam de ficha: todos os de blocos não fechados e os não concluídos dos fechados."""
    out = []
    for item, info in itens.items():
        d = Path(root) / 'blocos' / info['bloco']
        if not (d / 'verificado.json').is_file():
            out.append(item)
            continue
        f = strict_json((d / 'fechamento.json').read_bytes()) if (d / 'fechamento.json').is_file() else {'itens': {}}
        if f['itens'].get(item, {}).get('estado') != 'concluido':
            out.append(item)
    return sorted(out)


def validar(root, com_negativos=False, bloco=None):
    root = Path(root)
    itens = itens_do_plano(root)
    arquivos = sorted(p.name[:-5] for p in (root / DIR).glob('B*.json')) if (root / DIR).is_dir() else []
    relatorio = {'ok': True, 'faltam': [], 'fichas': {}}
    for item in exigidos(root, itens):
        if bloco and itens[item]['bloco'] != bloco:
            continue
        if item not in arquivos:
            relatorio['faltam'].append(item)
            relatorio['ok'] = False
    for item in arquivos:
        if bloco and itens.get(item, {}).get('bloco') != bloco:
            continue
        linha = {'tipo': None, 'estrutura': None, 'positivos': None, 'negativos': None}
        relatorio['fichas'][item] = linha
        try:
            require(item in itens, 'ficha_de_item_fora_do_plano:' + item)
            ficha = carregar(root, item, itens[item]['aceite'])
        except (Blocked, ValueError, KeyError, TypeError) as e:
            linha['estrutura'] = str(e)
            relatorio['ok'] = False
            continue
        linha['tipo'] = ficha['tipo']
        linha['estrutura'] = 'ok'
        linha['positivos'] = conferir_ficha(root, ficha, itens[item]['bloco'])
        if com_negativos and not linha['positivos']:
            try:
                linha['negativos'] = negativos_ficha(root, ficha, itens[item]['bloco'])
            except Blocked as e:
                linha['negativos'] = [str(e)]
            if linha['negativos']:
                relatorio['ok'] = False
    return relatorio


def main(argv=None):
    p = argparse.ArgumentParser(description='Fichas de aceite: critérios executáveis dos itens do plano.')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('validar'); s.add_argument('--negativos', action='store_true'); s.add_argument('--bloco')
    s = sub.add_parser('conferir'); s.add_argument('item'); s.add_argument('--bloco'); s.add_argument('--chaves-em')
    s = sub.add_parser('negativos'); s.add_argument('item'); s.add_argument('--bloco'); s.add_argument('--chaves-em')
    s = sub.add_parser('confirmacao'); s.add_argument('path'); s.add_argument('--chaves-em')
    args = p.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if args.cmd == 'validar':
            res = validar(root, args.negativos, args.bloco)
            ok = res['ok']
        elif args.cmd == 'conferir':
            res = {'item': args.item, 'falhas': conferir(root, args.item, args.bloco, chaves_commit=args.chaves_em)}
            ok = not res['falhas']
        elif args.cmd == 'negativos':
            res = {'item': args.item, 'furos': negativos(root, args.item, args.bloco, chaves_commit=args.chaves_em)}
            ok = not res['furos']
        else:
            ctx = contexto(root, chaves_commit=args.chaves_em)
            e = executar(root, {'id': 'V1', 'tipo': 'confirmacao_dono', 'path': args.path}, ctx)
            res = {'path': args.path, 'falha': e}
            ok = e is None
    except Blocked as e:
        print(json.dumps({'ok': False, 'erro': str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': ok, 'resultado': res}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

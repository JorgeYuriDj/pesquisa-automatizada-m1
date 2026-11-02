"""Blocos de trabalho sem pendência herdada em silêncio, revisão externa obrigatória e encadeamento.

Regra (ordens do dono de 29/10): um bloco só fecha quando TODO item do seu manifesto termina em
`concluido`, com evidência versionada que confere por hash, recibo de testes aprovado sobre o código
atual, revisão do Claude e do Antigravity sobre o trabalho do bloco, árvore limpa e HEAD igual ao
remoto. Os únicos outros estados aceitos são `bloqueado_dono` (ação exata que só o dono faz) e
`bloqueado_externo` (causa e desbloqueio), sempre com evidência. `pendente`, `parcial`, `adiado` ou
qualquer outro estado impedem o fechamento. Item bloqueado entra no topo do bloco seguinte, no
máximo duas vezes (MAX_HERANCA); se continuar bloqueado depois disso, o bloco não fecha e o dono é avisado.

Garantias por código (versão de regras 2, a partir do B03):
- o manifesto é recalculado a partir do plano e do fechamento do bloco anterior no commit de
  abertura; manifesto escrito à mão, item herdado omitido ou PARE/AVISO ignorados não passam;
- o plano dos blocos ainda não abertos congela no fechamento do bloco anterior; mudança exige
  entrada em blocos/PLANO_ALTERACOES.json com a ordem do dono;
- bloco fechado é conferido pelo estado do commit de fechamento, com as regras daquele momento;
  testes e código novos não "desfecham" blocos antigos;
- aviso ao dono é enviado ao GitHub e só sai com registro de resolução em blocos/avisos/;
- cada bloco exige blocos/<ID>/revisoes/{claude,antigravity}.json cobrindo, sem lacuna, o trabalho
  desde a revisão anterior; todo achado dos revisores aparece no fechamento.

Versão de regras 3 (ordens do dono de 30/10: regra determinística é regra em código):
- cada item tem uma ficha executável em blocos/fichas/<ITEM>.json (controle/fichas.py). Um item só
  é `concluido` se a ficha passa e seus negativos derrubam a ficha; a ficha não muda durante o bloco;
- o congelamento cobre plano, fichas, chaves de confirmação e identidades. Qualquer mudança exige
  confirmação do dono: arquivo criado por ele no site do GitHub, cujo commit o GitHub assina
  (docs/decisoes/confirmacoes/), citando o hash da nova versão. Agente nenhum produz essa assinatura;
- o executor propõe mudanças com `propor` (blocos/propostas/); a proposta só vale depois da
  confirmação do dono e do registro em PLANO_ALTERACOES.json;
- revisor indisponível não dispensa a revisão: só uma confirmação do dono dispensa; recibo do
  Claude pela nuvem precisa estar num ramo origin/claude/*;
- cada sessão de bloco assina com identidade própria (blocos/IDENTIDADES.json): abrir exige
  identidade de agente; commit do dono dentro do bloco só pode criar confirmações;
- o celular acompanha, não trava: o lançador é item do plano com ficha, não condição de abertura.

Arquivos (todos versionados no repositório):
  blocos/PLANO.json               fila de blocos planejados, com prazo_utc opcional por bloco
  blocos/PLANO_ALTERACOES.json    mudanças do plano depois de congelado, cada uma com ordem do dono
  blocos/fichas/<ITEM>.json       critério executável de cada item (ver controle/fichas.py)
  blocos/CHAVES_CONFIRMACAO.json  chave pública e autores aceitos nas confirmações do dono
  blocos/IDENTIDADES.json         e-mails de commit do dono e de cada agente
  blocos/propostas/*.json         propostas de mudança do plano feitas pelo executor
  blocos/<ID>/manifesto.json      escopo do bloco, gravado uma vez na abertura
  blocos/<ID>/revisoes/           pedido-<commit>.json, claude.json, antigravity.json e pareceres
  blocos/<ID>/fechamento.json     estado final de cada item, escrito pela sessão do bloco
  blocos/<ID>/verificado.json     gravado uma vez por `fechar` quando todas as regras passam
  blocos/PARE                     se existir, nada novo é aberto nem lançado
  blocos/AVISO_DONO.md            motivo da parada, em português simples
  blocos/avisos/<sha256>.json     resolução de cada aviso apagado
  docs/decisoes/confirmacoes/     confirmações do dono (commits assinados pelo site do GitHub)

Uso na VPS:
  python3 -I -B controle/blocos.py estado
  python3 -I -B controle/blocos.py abrir
  python3 -I -B controle/blocos.py propor B04-02 "motivo da mudança"
  python3 -I -B controle/blocos.py ratificar "motivo"   (mudança do congelado: link para o dono confirmar)
  python3 -I -B controle/blocos.py pedir-revisao B03
  python3 -I -B controle/blocos.py fechar B03
  python3 -I -B controle/blocos.py conferir          (conferência da integração contínua)
  python3 -I -B controle/blocos.py encadear --config <arquivo>

Modos do encadeador: inativo (não lança), ensaio (sessão postiça, só com remoto local) e real
(argv da DT do lançador escolhido pelo dono, DT e binário conferidos por hash a cada lançamento).
No modo real, a CLI permanece como supervisor até o fim da unidade transitória, sem
manter locks do repositório durante a execução. A unidade usa prazo próprio e encerra
todo o cgroup. O próximo passo exige recibo durável; morte do supervisor sem recibo
bloqueia retomada. O serviço do timer precisa permitir essa duração (até 6h + margens).
Instalar o timer em modo real é o item B02-05, com ficha.
"""
import argparse
import ast
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

# Reject even formerly accepted argparse abbreviations before local imports.
# Disabling abbreviation at parse time alone would be too late for this boundary.
if __name__=='__main__' and any(arg.startswith('--') and len(arg.split('=',1)[0])>2
        and '--instalacao'.startswith(arg.split('=',1)[0]) for arg in sys.argv[1:]):
    raise SystemExit('installed_bootstrap_required: use juiz_base.py --instalacao ... --entrypoint blocos -- ...')
sys.path.append(str(Path(__file__).resolve().parent))
from juiz_base import validator_installation, installed_entrypoint, configure_validator_transport, probe_write_denials, protected_path, guarded_git, verify_openpgp, git_fixture_mutation, Blocked, require, canonical, digest, filehash, strict_json, RESTRICTED, write_once, git_env   # noqa: E402
import fichas as fx   # noqa: E402
import juiz_base as jb   # noqa: E402

DIR = 'blocos'
RUNTIME_INSTALLATION = None
RUNTIME_CONTROL_PATHS = ()
REAL_PENDING = {}
# Reviewed source pins; deployment still requires the installed-judge gate.
CODEX_AUXILIARES = {
    'b8a11fedf24b2dfb59a70c9e52b030f9a508dcd49cd2dd0d41956f4c785156b8':
        '657f4e902726e05867c937b583049d5997e057f8cd0ab40450633c9c9ef8d630',
}
BWRAP_PATH = '/usr/bin/bwrap'
BWRAP_SHA256 = 'bf6cf3d4456665f5d80c14eb79a76e0ce87b39a0883e614a161658b4ec33492c'
# Closed migration set: only these two preserved B05 failures can be reconciled.
# A new incident requires new review; no recurring retry allowance is introduced.
RECONCILIACAO_B05_LOGS = {
    'sc-bloco-b05-ac201e67f599b6164900d804cbf64b3b.service':
        '012887112f386b3985097dff0adf0085363b4bf1e088da277870650219d933d0',
    'sc-bloco-b05-784861066790615ae857455a37498cc7.service':
        '7da15226918390d97423ddbdab2fb9abb9166ecd7757be9c1bbf387194373df5',
}
SESSION_UNIT = re.compile(r'sc-bloco-b[0-9]{2}-[0-9a-f]{32}\.service\Z')
PROTECTED_REVIEW_ROOTS = ('/var/lib/claude-passage-control', '/var/lib/antigravity-passage-control')
IDENTIDADES = 'blocos/IDENTIDADES.json'
PROPOSTAS = 'blocos/propostas'
CONFIRMACOES = fx.CONFIRMACOES
ID = re.compile(r'B\d{2}')
ITEM = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,40}')
HEX40 = re.compile(r'[0-9a-f]{40}')
HEX64 = re.compile(r'[0-9a-f]{64}')
PRAZO = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')
ESTADOS = ('concluido', 'bloqueado_dono', 'bloqueado_externo')
REGRAS = 4                 # versão gravada em verificado.json; blocos antigos (sem campo) = 1
MAX_HERANCA = {1: 2, 2: 2, 3: 2}   # por versão de regras; ordem do dono de 29/10: no máximo duas vezes
MAX_HERANCA[4] = MAX_HERANCA[3]    # regras 4: mesmo limite
SCHEMA_DO_BLOCO = {3: 'sc-bloco/2', 4: 'sc-bloco/3'}   # o manifesto fixa a versão de regras do bloco
REGRAS_DO_SCHEMA = {'sc-bloco/1': 2, 'sc-bloco/2': 3, 'sc-bloco/3': 4}
MAX_ITENS = 8              # itens planejados por bloco: cabe numa sessão
MAX_TENTATIVAS = 2         # sessões lançadas para o mesmo bloco antes de parar e avisar
MAX_LANCAMENTOS_DIA = 8
MAX_EVIDENCIA = 8 * 1024 * 1024
DISCO_MINIMO = 10 * 10**9  # bytes livres para lançar uma sessão
MEMORIA_MINIMA = 1536 * 2**20
RECIBO = re.compile(r'docs/evidencias/testes/approval-(\d{6})\.json')
REVISORES = ('claude', 'antigravity')
CANAIS = {'claude': ('nuvem', 'vps-cli'), 'antigravity': ('vps-cli',)}
AUTOR_NUVEM = 'noreply@anthropic.com'
CLAUDE_PUBLIC_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKy87HxSEheG8vEPhSs9u2KZCtVErAQfpmprtUJCZ2w7'
SESSAO_NUVEM = re.compile(r'https://claude\.ai/code/session_[A-Za-z0-9]{8,}')
VEREDITOS = ('sem_achados', 'com_achados', 'indisponivel')
GRAVIDADES = ('alta', 'media', 'baixa')

# One pre-versioning receipt remains valid only as its exact historical bytes.
# Extending this migration exception is an owner-reserved foundation change.
LEGACY_VERIFIED_RECORDS = {
    'B02': {'head':'fd6e4d0b2f8c356ff722979e9f0a9fee265ecbbc',
            'sha256':'6961a5f694fe4b307df7975d8c97ddc06bd549761464eb67950258b38e215635'}
}

REVIEWER_RATIFICATION_POLICY = {
    'schema':'sc-ratificacao-revisor/1',
    'fundamentos':('cegamento','dinheiro-teto-gpu-go','chaves-identidades',
                   'duas-revisoes','limite-heranca','regra-aprovacao'),
    'paths':('blocos/CHAVES_CONFIRMACAO.json','blocos/IDENTIDADES.json',
             'controle/chaves/','controle/juiz_base.py',
             'controle/release_lot.py','infra/google_cloud/',
             'docs/AVALIACAO_CEGA.md','docs/GUIA_CUSTODIA.md',
             'blocos/fichas/B02-05.json','blocos/fichas/B03-01.json','blocos/fichas/B06-03.json',
             'blocos/fichas/B07-01.json','docs/decisoes/DT-B03-LANCADOR-01.json',
             'docs/decisoes/GO_NOGO_2026-10-31.json'),
    'plan_blocks':('B06','B07'),
    'plan_items':('B02-05','B03-01'),
    'symbols':('REVIEWER_RATIFICATION_POLICY','REGRAS','MAX_HERANCA','REVISORES',
               'CLAUDE_PUBLIC_KEY','AUTOR_NUVEM','SCHEMA_DO_BLOCO','REGRAS_DO_SCHEMA',
               'LEGACY_VERIFIED_RECORDS','verified_record_rules',
               'confirmacao_dono_ok','cloud_review_signature','alteracao_registrada',
               'reviewer_policy_at','foundation_nodes','foundation_plan','reviewer_ratification','ratification_statement',
               'herdados_de','revisao_ok','revisoes_ok','installation_authority',
               'termo_ajuste_ordem8','ficha_efetiva_ordem8','EMENDAS_FICHA'),
}



def git(root, *args, check=True):
    p = guarded_git(root, *args, text=True, timeout=120)
    require(p.returncode == 0 or not check, 'git_failed:' + args[0])
    return p


def load(path):
    return strict_json(Path(path).read_bytes())


def show(root, commit, rel):
    """Conteúdo de um arquivo num commit, ou None se ele não existia."""
    p = guarded_git(root, 'show', '%s:%s' % (commit, rel), timeout=60)
    return p.stdout if p.returncode == 0 else None


def pedido_canonico_imutavel(root, rel, raw):
    """The request identity is the single, unchanged Git creation at this path."""
    require(show(root, 'HEAD', rel) == raw, 'canonical_request_unversioned_or_changed')
    origin = fx.commit_de_criacao(root, rel)
    require(show(root, origin, rel) == raw, 'canonical_request_origin_changed')
    require(not git(root, 'log', '--format=%H', origin + '..HEAD', '--', rel).stdout.strip(),
            'canonical_request_history_changed')
    return origin


def show_json(root, commit, rel):
    raw = show(root, commit, rel)
    require(raw is not None, 'ausente_no_commit:%s:%s' % (commit[:12], rel))
    return strict_json(raw)


def ancestral(root, a, b):
    return git(root, 'merge-base', '--is-ancestor', a, b, check=False).returncode == 0


def rel_ok(path):
    require(isinstance(path, str) and path and not path.startswith('/') and '..' not in path.split('/')
            and '/'.join(Path(path).parts) == path, 'caminho_invalido:' + str(path))
    require(not RESTRICTED.search(path), 'material_restrito:' + path)


def text_ok(value, minimum, reason):
    require(isinstance(value, str) and len(value.strip()) >= minimum, reason)


def agora(now=None):
    return time.time() if now is None else now


def iso(now=None):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))


def rastreados_de(root):
    return set(git(root, 'ls-files', '-z').stdout.split('\0'))


# ---------------------------------------------------------------- plano e manifesto

def validar_itens(itens, planejados=True):
    require(isinstance(itens, list) and itens, 'itens_vazios')
    ids = [i.get('id') for i in itens]
    require(all(isinstance(x, str) and ITEM.fullmatch(x) for x in ids) and len(set(ids)) == len(ids), 'itens_ids_invalidos')
    for i in itens:
        text_ok(i.get('titulo'), 3, 'item_sem_titulo:' + i['id'])
        text_ok(i.get('aceite'), 10, 'item_sem_criterio_de_aceite:' + i['id'])
    if planejados:
        require(len(itens) <= MAX_ITENS, 'bloco_grande_demais_divida_no_plano')


def validar_plano(plano):
    require(isinstance(plano, dict) and set(plano) == {'schema', 'blocos'} and plano['schema'] == 'sc-plano/1', 'plano_schema')
    ids = [b.get('id') for b in plano['blocos']]
    require(all(isinstance(x, str) and ID.fullmatch(x) for x in ids) and ids == sorted(set(ids)), 'plano_ids')
    for b in plano['blocos']:
        require({'id', 'titulo', 'itens'} <= set(b) <= {'id', 'titulo', 'itens', 'prazo_utc'}, 'plano_bloco_schema:' + b['id'])
        require('prazo_utc' not in b or (isinstance(b['prazo_utc'], str) and PRAZO.fullmatch(b['prazo_utc'])), 'plano_prazo:' + b['id'])
        text_ok(b['titulo'], 3, 'plano_bloco_sem_titulo:' + b['id'])
        validar_itens(b['itens'])
        require(all(set(i) == {'id', 'titulo', 'aceite'} for i in b['itens']), 'plano_item_schema:' + b['id'])
        # Todo item do plano tem ficha: o id precisa ter a forma que a ficha reconhece (Bnn-nn do próprio bloco).
        require(all(fx.ID_ITEM.fullmatch(i['id']) and i['id'].startswith(b['id'] + '-') for i in b['itens']), 'plano_item_id:' + b['id'])
    return plano


def load_plano(root):
    return validar_plano(load(Path(root) / DIR / 'PLANO.json'))


def blocos_abertos(root):
    d = Path(root) / DIR
    return sorted(p.name for p in d.iterdir() if p.is_dir() and ID.fullmatch(p.name) and (p / 'manifesto.json').is_file()) if d.is_dir() else []


def blocos_no_commit(root, commit):
    names = git(root, 'ls-tree', '--name-only', commit, DIR + '/', check=False).stdout.split()
    return sorted(n.split('/')[-1] for n in names
                  if ID.fullmatch(n.split('/')[-1]) and show(root, commit, '%s/manifesto.json' % n) is not None)


def validar_manifesto(m, bid):
    """sc-bloco/1: regras 1 e 2. sc-bloco/2 (regras 3): cada item traz ficha_sha256 (None só para
    achados herdados, que não têm ficha)."""
    require(isinstance(m, dict) and set(m) == {'schema', 'id', 'titulo', 'anterior', 'origin_commit', 'aberto_em', 'itens'}
            and m['schema'] in REGRAS_DO_SCHEMA and m['id'] == bid, 'manifesto_schema')
    validar_itens(m['itens'], planejados=False)
    com_ficha = REGRAS_DO_SCHEMA[m['schema']] >= 3
    for i in m['itens']:
        require(set(i) == {'id', 'titulo', 'aceite', 'herdado_de', 'herdado_vezes'} | ({'ficha_sha256'} if com_ficha else set()), 'manifesto_item_schema:' + i['id'])
        require(type(i['herdado_vezes']) is int and 0 <= i['herdado_vezes'] <= max(MAX_HERANCA.values()), 'heranca_invalida:' + i['id'])
        require((i['herdado_de'] is None) == (i['herdado_vezes'] == 0), 'heranca_inconsistente:' + i['id'])
        if com_ficha:
            require(i['ficha_sha256'] is None or (isinstance(i['ficha_sha256'], str) and HEX64.fullmatch(i['ficha_sha256'])), 'manifesto_ficha:' + i['id'])
            require((i['ficha_sha256'] is None) == (fx.ID_ITEM.fullmatch(i['id']) is None), 'manifesto_ficha_obrigatoria:' + i['id'])
    require(sum(1 for i in m['itens'] if i['herdado_de'] is None) <= MAX_ITENS, 'bloco_grande_demais')
    return m


def identidades(root, commit='HEAD'):
    raw = show(root, commit, IDENTIDADES)
    require(raw is not None, 'identidades_ausentes')
    ident = strict_json(raw)
    require(isinstance(ident, dict) and set(ident) == {'schema', 'dono', 'agentes'} and ident['schema'] == 'sc-identidades/1'
            and isinstance(ident['dono'], dict) and isinstance(ident['dono'].get('emails'), list) and ident['dono']['emails']
            and isinstance(ident['agentes'], dict) and ident['agentes'], 'identidades_schema')
    emails_dono = set(ident['dono']['emails'])
    emails_agentes = {}
    for nome, a in ident['agentes'].items():
        require(isinstance(a, dict) and isinstance(a.get('emails'), list) and a['emails'], 'identidades_schema')
        for e in a['emails']:
            require(isinstance(e, str) and '@' in e and e not in emails_dono and e not in emails_agentes, 'identidades_email_repetido:' + str(e))
            emails_agentes[e] = nome
    return {'dono': emails_dono, 'agentes': emails_agentes}


def identidade_de_agente_ok(root):
    """Quem abre um bloco assina como agente, nunca com o e-mail do dono."""
    ident = identidades(root)
    email = git(root, 'config', 'user.email', check=False).stdout.strip()
    require(email in ident['agentes'], 'identidade_de_agente_nao_configurada:' + (email or 'vazio'))
    return ident['agentes'][email]


def base_confianca(root, commit='HEAD'):
    """Último estado confirmado: o commit de fechamento do último bloco verificado no commit dado.
    Chaves e confirmações são conferidas como estavam ali, não como estão agora."""
    fechados = [bid for bid in blocos_no_commit(root, commit) if show(root, commit, '%s/%s/verificado.json' % (DIR, bid)) is not None]
    if not fechados:
        return None
    return strict_json(show(root, commit, '%s/%s/verificado.json' % (DIR, fechados[-1])))['head']


def chaves_em_vigor(root, commit='HEAD'):
    """Commit cujas chaves de confirmação valem: a base de confiança, se já tinha chaves; senão a
    árvore atual (primeira confirmação, que inaugura a confiança)."""
    base = base_confianca(root, commit)
    return base if base and show(root, base, fx.CHAVES) is not None else None


def autores_ok(root, m):
    """Dentro do bloco, o e-mail do dono só aparece em commit assinado pelo site do GitHub que cria
    confirmações ou altera somente blocos/PARE (ou num merge feito por ele no site); e-mail fora do registro não passa. O e-mail
    sozinho não prova nada: a assinatura prova."""
    ident = identidades(root)
    em = chaves_em_vigor(root)
    c = fx.chaves(root, em)
    publica = fx.ler_em(root, em, c['chave_publica']) if em else fx.ler(root, c['chave_publica'])
    aceitas = {x.upper() for x in c['impressoes']}
    linhas = git(root, 'log', '--format=%H%x00%ae%x00%P', m['origin_commit'] + '..HEAD').stdout.split('\n')
    for linha in linhas:
        if not linha.strip():
            continue
        commit, email, pais = linha.split('\0')
        if email in ident['agentes']:
            continue
        require(email in ident['dono'], 'autor_desconhecido:' + email)
        fp = fx.assinatura(root, commit, publica)
        require(fp is not None and fp in aceitas, 'commit_do_dono_sem_assinatura_do_github:' + commit[:12])
        if len(pais.split()) > 1:
            continue   # merge feito pelo dono no site do GitHub
        tocados = git(root, 'diff-tree', '-m', '-r', '--no-commit-id', '--name-only', commit).stdout.split()
        require(tocados and (all(t.startswith(CONFIRMACOES + '/') for t in tocados) or tocados==[DIR+'/PARE']), 'commit_do_dono_fora_das_confirmacoes:' + commit[:12])


def load_manifesto(root, bid):
    return validar_manifesto(load(Path(root) / DIR / bid / 'manifesto.json'), bid)


def herdados_de(manifesto_anterior, fechamento_anterior, anterior, max_heranca):
    """Itens que o bloco seguinte recebe no topo: os não concluídos do anterior e seus achados
    não concluídos. Função única para abrir e para conferir manifestos (sem divergência)."""
    vezes = {i['id']: i['herdado_vezes'] for i in manifesto_anterior['itens']}
    herdados = []
    for item_id, registro in sorted(fechamento_anterior['itens'].items()):
        if registro['estado'] != 'concluido':
            n = vezes.get(item_id, 0) + 1
            require(n <= max_heranca, 'heranca_esgotada:' + item_id)
            origem = next(i for i in manifesto_anterior['itens'] if i['id'] == item_id)
            herdados.append({'id': item_id, 'titulo': origem['titulo'], 'aceite': origem['aceite'], 'herdado_de': anterior, 'herdado_vezes': n})
    for a in fechamento_anterior.get('achados', []):
        if a['estado'] != 'concluido':
            herdados.append({'id': a['id'], 'titulo': 'Achado: ' + a['descricao'][:80], 'aceite': 'Corrigido com evidência e teste, ou decisão registrada.',
                             'herdado_de': anterior, 'herdado_vezes': 1})
    return herdados


def futuro(plano, anterior):
    return [b for b in plano['blocos'] if anterior is None or b['id'] > anterior]


def confirmacao_dono_ok(root, rel, contem, chaves_commit=None):
    """Confirmação do dono: arquivo em docs/decisoes/confirmacoes/ criado pelo site do GitHub, com
    a assinatura do GitHub conferida contra as chaves em vigor (blocos/CHAVES_CONFIRMACAO.json no
    commit `chaves_commit`, o último estado confirmado) e os trechos exigidos."""
    rel_ok(rel)
    erro = fx.executar(root, {'id': 'V1', 'tipo': 'confirmacao_dono', 'path': rel, 'contem': list(contem)},
                       fx.contexto(root, chaves_commit=chaves_commit))
    require(erro is None, 'confirmacao_do_dono_invalida:%s:%s' % (rel, erro))



def reviewer_policy_at(root, commit):
    """Read only literals from the already trusted baseline; never import old code."""
    raw=show(root,commit,'controle/blocos.py')
    require(raw is not None,'ratificacao_revisor_sem_bootstrap')
    try:
        tree=ast.parse(raw)
        def literal(name):
            nodes=[n for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
                   and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
            require(len(nodes)==1,'ratificacao_revisor_sem_bootstrap')
            return ast.literal_eval(nodes[0].value)
        policy=literal('REVIEWER_RATIFICATION_POLICY')
        signer=literal('CLAUDE_PUBLIC_KEY')
        principal=literal('AUTOR_NUVEM')
    except (ValueError,TypeError,SyntaxError,RecursionError) as exc:
        raise Blocked('ratificacao_revisor_sem_bootstrap') from exc
    require(policy==REVIEWER_RATIFICATION_POLICY and signer==CLAUDE_PUBLIC_KEY
            and principal==AUTOR_NUVEM,'ratificacao_revisor_politica_diverge')
    return policy


def foundation_plan(raw, policy):
    """Owner-reserved plan data, including absence and execution order."""
    require(raw is not None,'ratificacao_revisor_plano_ausente')
    plan=strict_json(raw)
    require(type(plan) is dict and set(plan)=={'schema','blocos'}
            and plan['schema']=='sc-plano/1' and type(plan['blocos']) is list,
            'ratificacao_revisor_plano_invalido')
    blocks={};items={}
    for position,block in enumerate(plan['blocos']):
        require(type(block) is dict and type(block.get('id')) is str
                and block['id'] not in blocks and type(block.get('itens')) is list,
                'ratificacao_revisor_plano_invalido')
        bid=block['id'];blocks[bid]={'position':position,'value':block}
        for item_position,item in enumerate(block['itens']):
            require(type(item) is dict and type(item.get('id')) is str
                    and item['id'] not in items,'ratificacao_revisor_plano_invalido')
            items[item['id']]={'block':bid,'position':item_position,'value':item}
    return {'blocks':{bid:blocks.get(bid) for bid in policy['plan_blocks']},
            'items':{iid:items.get(iid) for iid in policy['plan_items']}}


def foundation_nodes(raw, names):
    """Direct changes to the approval and inheritance rules require the owner."""
    require(raw is not None,'ratificacao_revisor_fundamento_ausente')
    try:
        tree=ast.parse(raw)
        selected=[]
        for node in tree.body:
            children=list(ast.walk(node))
            declares={x.name for x in children if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
            declares.update(x.id for x in children if isinstance(x,ast.Name) and isinstance(x.ctx,ast.Store))
            declares.update(x.asname or x.name.split('.')[0] for x in children if isinstance(x,ast.alias))
            # Direct top-level mutation/calls involving a protected binding also count.
            # Dynamic reflection still needs independent signed semantic review.
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                declares.update(x.id for x in children if isinstance(x,ast.Name))
            if declares & set(names):
                selected.append(ast.dump(node,include_attributes=False))
        return selected
    except (ValueError,TypeError,SyntaxError,RecursionError) as exc:
        raise Blocked('ratificacao_revisor_fundamento_invalido') from exc



def ratification_statement(report, wanted, foundations):
    """One terminal normative block, outside Markdown fences and blockquotes."""
    try:
        lines=report.decode('utf-8').splitlines()
    except UnicodeError as exc:
        raise Blocked('ratificacao_revisor_texto_invalido') from exc
    while lines and not lines[-1].strip():
        lines.pop()
    begin,end='SC_RATIFICATION_BEGIN','SC_RATIFICATION_END'
    require(lines.count(begin)==1 and lines.count(end)==1,'ratificacao_revisor_bloco_unico')
    start=lines.index(begin)
    require(start==0 or not lines[start-1].strip(),'ratificacao_revisor_bloco_sem_separador')
    require(lines[-1]==end and lines.index(end)>start,'ratificacao_revisor_bloco_terminal')
    prefix=lines[:start]
    require(not any(re.search(r'\b(?:RATIFICO|PRESERVADO)\b',line,re.I) for line in prefix),
            'ratificacao_revisor_declaracao_conflitante')
    fence=None
    for line in prefix:
        match=re.match(r' {0,3}(['+chr(96)+r']{3,}|~{3,})(.*)$',line)
        if match:
            chars,tail=match.groups()
            if fence is None:
                fence=(chars[0],len(chars))
            elif chars[0]==fence[0] and len(chars)>=fence[1] and not tail.strip():
                fence=None
    require(fence is None,'ratificacao_revisor_bloco_citado')
    require('RATIFICO '+wanted in lines[start+1:-1],'ratificacao_revisor_hash_ausente')
    for foundation in foundations:
        require('PRESERVADO '+foundation+' '+wanted in lines[start+1:-1],
                'ratificacao_revisor_fundamento_sem_atestado:'+foundation)
    expected=['RATIFICO '+wanted]+['PRESERVADO '+name+' '+wanted for name in foundations]
    require(lines[start+1:-1]==expected,'ratificacao_revisor_bloco_invalido')
    return True


def reviewer_ratification(root, commit, before, after, ref, base_head):
    """A signed reviewer may ratify routine changes only after the owner's bootstrap.

    Direct protected changes are refused deterministically. Semantic/indirect
    preservation also requires an explicit signed reviewer attestation; this is
    delegated review, not a claim that syntax proves unchanged behavior.
    """
    require(type(base_head) is str and HEX40.fullmatch(base_head) is not None
            and ancestral(root,base_head,commit),'ratificacao_revisor_sem_base')
    policy=reviewer_policy_at(root,base_head)
    require(type(ref) is dict and set(ref)=={'path','sha256','commit_assinado','apos_bloco'},
            'ratificacao_revisor_schema')
    rel=ref['path'];rel_ok(rel)
    require(re.fullmatch(r'blocos/B\d{2}/revisoes/claude\.json',rel) is not None
            and type(ref['sha256']) is str and HEX64.fullmatch(ref['sha256']) is not None
            and type(ref['commit_assinado']) is str and HEX40.fullmatch(ref['commit_assinado']) is not None
            and type(ref['apos_bloco']) is str and ID.fullmatch(ref['apos_bloco']) is not None,
            'ratificacao_revisor_schema')
    raw=show(root,commit,rel)
    require(raw is not None and filehash(raw)==ref['sha256'],'ratificacao_revisor_recibo')
    review=strict_json(raw)
    require(type(review) is dict and review.get('schema')=='sc-revisao-externa/1'
            and review.get('bloco')==rel.split('/')[1]
            and type(review.get('sessao')) is str and SESSAO_NUVEM.fullmatch(review['sessao']) is not None
            and review.get('veredito')=='sem_achados' and review.get('achados')==[],
            'ratificacao_revisor_sem_aprovacao')
    proof=cloud_review_signature(root,rel,review,commit)
    require(proof['commit']==ref['commit_assinado'],'ratificacao_revisor_commit_diverge')
    target=review['commit_revisado']
    require(ancestral(root,base_head,review['base_revisada'])
            and ancestral(root,review['base_revisada'],base_head)
            and ancestral(root,base_head,target),'ratificacao_revisor_base_diverge')
    require(congelado(root,base_head,ref['apos_bloco'])==before
            and congelado(root,target,ref['apos_bloco'])==after
            and congelado(root,commit,ref['apos_bloco'])==after,'ratificacao_revisor_congelado_diverge')
    require(before.get('chaves')==after.get('chaves') and before.get('identidades')==after.get('identidades'),
            'ratificacao_revisor_fundamentos_exigem_dono')
    paths=git(root,'diff','--name-only',base_head,commit).stdout.splitlines()
    require(not any(path==guard or guard.endswith('/') and path.startswith(guard)
                    for path in paths for guard in policy['paths']),
            'ratificacao_revisor_fundamentos_exigem_dono')
    require(foundation_plan(show(root,base_head,'%s/PLANO.json' % DIR),policy)==
            foundation_plan(show(root,target,'%s/PLANO.json' % DIR),policy)==
            foundation_plan(show(root,commit,'%s/PLANO.json' % DIR),policy),
            'ratificacao_revisor_fundamentos_exigem_dono')
    require(foundation_nodes(show(root,base_head,'controle/blocos.py'),policy['symbols'])==
            foundation_nodes(show(root,target,'controle/blocos.py'),policy['symbols']),
            'ratificacao_revisor_regra_exige_dono')
    ratification_statement(proof['parecer'],digest(after),policy['fundamentos'])
    return True


def alteracao_registrada(root, commit, antes, depois, regras=REGRAS, base_head=None):
    """O congelado mudou: só passa com entrada em PLANO_ALTERACOES.json que nomeie exatamente o
    antes e o depois por hash e cite a ordem do dono. Regras 3: a ordem é uma confirmação do dono
    assinada pelo site do GitHub, conferida com as chaves de ANTES da mudança (base_head), e que
    cita o hash do depois; regras 2: arquivo citado por hash."""
    raw = show(root, commit, '%s/PLANO_ALTERACOES.json' % DIR)
    require(raw is not None, 'plano_alterado_sem_registro')
    alteracoes = strict_json(raw)
    require(isinstance(alteracoes, dict) and alteracoes.get('schema') == 'sc-plano-alteracoes/1'
            and isinstance(alteracoes.get('alteracoes'), list), 'plano_alteracoes_schema')
    de, para = digest(antes), digest(depois)
    for a in alteracoes['alteracoes']:
        if isinstance(a, dict) and a.get('de_sha256') == de and a.get('para_sha256') == para:
            common={'de_sha256','para_sha256','motivo'}
            require(set(a) in (common|{'ordem_dono'},common|{'ordem_revisor'}),
                    'plano_alteracao_schema')
            text_ok(a['motivo'], 20, 'plano_alteracao_sem_motivo')
            if 'ordem_revisor' in a:
                require(regras>=4,'ratificacao_revisor_regras')
                return reviewer_ratification(root,commit,antes,depois,a['ordem_revisor'],base_head)
            ref = a['ordem_dono']
            if regras >= 3:
                require(isinstance(ref, dict) and set(ref) == {'path'}, 'plano_alteracao_ordem')
                em = base_head if base_head and show(root, base_head, fx.CHAVES) is not None else None
                confirmacao_dono_ok(root, ref['path'], [para], em)
                return True
            require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'plano_alteracao_ordem')
            rel_ok(ref['path'])
            conteudo = show(root, commit, ref['path'])
            require(conteudo is not None and filehash(conteudo) == ref['sha256'], 'plano_alteracao_ordem_nao_confere')
            return True
    raise Blocked('plano_alterado_sem_registro')


# Regras 3 congelavam também gate.py e handoff.py, que o próprio plano manda mudar (B03-01, B03-02).
# Regras 4 congelam só o juiz; as primitivas dele estão em juiz_base.py. Cada bloco usa a versão
# de regras com que foi aberto (SCHEMA_DO_BLOCO), para que conferir o passado não mude de sentido.
MOTOR_V3 = ('controle/blocos.py', 'controle/fichas.py', 'controle/run_tests.py', 'controle/gate.py', 'controle/handoff.py',
            '.github/workflows/conferencia.yml')
MOTOR = ('controle/blocos.py', 'controle/fichas.py', 'controle/juiz_base.py', 'controle/revisao_juiz.py', 'controle/run_tests.py',
         '.github/workflows/conferencia.yml')
MOTOR_POR_REGRAS = {3: MOTOR_V3, 4: MOTOR}
MOTOR_V4_ORIGINAL = ('controle/blocos.py', 'controle/fichas.py', 'controle/juiz_base.py', 'controle/run_tests.py',
                     '.github/workflows/conferencia.yml')


def motor_da_abertura(root, commit, regras):
    """Inventário literal do juiz na abertura; nunca executa código histórico.
    Só a rederivação usa esta seleção. O gate do estado corrente sempre inclui o juiz atual."""
    atual = MOTOR_POR_REGRAS[max(3, regras)]
    if regras < 4:
        return atual
    source = show(root, commit, 'controle/blocos.py')
    if source is None:
        return atual  # repositório sem motor histórico nunca ganha um inventário reduzido
    try:
        tree = ast.parse(source)
        declarations = [n for n in tree.body if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'MOTOR' for t in n.targets)]
        # Count direct bindings whose target is stored as a string by the AST,
        # as well as ordinary Name targets. No historical code is evaluated.
        assignments = []
        for node in ast.walk(tree):
            if isinstance(node, ast.alias):
                require(node.name != '*', 'motor_da_abertura_desconhecido')
                bound = (node.asname or node.name.split('.')[0]) == 'MOTOR'
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                   ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                bound = node.name == 'MOTOR'
            elif isinstance(node, ast.MatchMapping):
                bound = node.rest == 'MOTOR'
            elif isinstance(node, ast.arg):
                bound = node.arg == 'MOTOR'
            else:
                bound = (isinstance(node, ast.Name) and node.id == 'MOTOR'
                         and isinstance(node.ctx, (ast.Store, ast.Del)))
            if bound:assignments.append(node)
        require(len(declarations) == 1 and len(declarations[0].targets) == 1
                and len(assignments) == 1, 'motor_da_abertura_desconhecido')
        motor = ast.literal_eval(declarations[0].value)
    except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
        raise Blocked('motor_da_abertura_desconhecido') from exc
    require(type(motor) is tuple and len(MOTOR_V4_ORIGINAL) <= len(motor) <= 64
            and all(type(path) is str and len(path) <= 240 and re.fullmatch(
                r'(?:controle/(?:[A-Za-z_][A-Za-z0-9_-]*/)*[A-Za-z_][A-Za-z0-9_-]*\.py'
                r'|\.github/workflows/[A-Za-z_][A-Za-z0-9_.-]*\.ya?ml)', path)
                    for path in motor), 'motor_da_abertura_desconhecido')
    require(len(set(motor)) == len(motor) and set(MOTOR_V4_ORIGINAL).issubset(motor),
            'motor_da_abertura_desconhecido')
    # Added modules must exist in that immutable opening tree. The original
    # core retains its historical absent-file hashes where applicable.
    require(all(show(root,commit,path) is not None for path in motor
                if path not in MOTOR_V4_ORIGINAL), 'motor_da_abertura_arquivo_ausente')
    return motor


def congelado(root, commit, anterior, plano=None, regras=REGRAS, motor=None):
    """O que fica congelado entre fechamentos (regras 3): blocos futuros do plano, TODAS as fichas,
    as chaves de confirmação, as identidades e o próprio motor das regras (MOTOR, por hash). Mudar
    qualquer um exige confirmação do dono: o executor não reescreve o juiz em silêncio."""
    plano = plano if plano is not None else validar_plano(show_json(root, commit, '%s/PLANO.json' % DIR))
    nomes = git(root, 'ls-tree', '--name-only', commit, fx.DIR + '/', check=False).stdout.split()
    fichas = {n.split('/')[-1][:-5]: strict_json(show(root, commit, n)) for n in sorted(nomes) if n.endswith('.json')}
    extras = {}
    for chave, rel in (('chaves', fx.CHAVES), ('identidades', IDENTIDADES)):
        raw = show(root, commit, rel)
        extras[chave] = strict_json(raw) if raw is not None else None
    motor_hashes = {}
    for rel in (MOTOR_POR_REGRAS[max(3, regras)] if motor is None else motor):
        raw = show(root, commit, rel)
        motor_hashes[rel] = filehash(raw) if raw is not None else None
    return {'blocos': futuro(plano, anterior), 'fichas': fichas, 'chaves': extras['chaves'], 'identidades': extras['identidades'], 'motor': motor_hashes}


def plano_congelado_ok(root, anterior, plano, commit, regras=REGRAS, motor=None):
    """O congelado é o mesmo do commit de fechamento do anterior, ou a mudança está registrada.
    Sem anterior não há base de congelamento."""
    if anterior is None:
        return
    vraw = show(root, commit, '%s/%s/verificado.json' % (DIR, anterior))
    require(vraw is not None, 'anterior_nao_verificado:' + anterior)
    base_head = strict_json(vraw)['head']
    if regras >= 3:
        antes, depois = congelado(root, base_head, anterior, regras=regras, motor=motor), congelado(root, commit, anterior, plano, regras, motor)
    else:
        base = validar_plano(show_json(root, base_head, '%s/PLANO.json' % DIR))
        antes, depois = futuro(base, anterior), futuro(plano, anterior)
    if antes != depois:
        alteracao_registrada(root, commit, antes, depois, regras, base_head)


def avisos_resolvidos_ok(root, commit='HEAD', regras=REGRAS):
    """Todo AVISO_DONO.md já apagado tem resolução em blocos/avisos/<sha256>.json com motivo e
    evidência. Apagar o aviso sem resolver não reabre a cadeia. Regras 3: o aviso é dirigido ao
    dono, então a resolução traz uma confirmação dele citando o hash do aviso."""
    apagados = git(root, 'log', '--diff-filter=D', '--format=%H', commit, '--', '%s/AVISO_DONO.md' % DIR).stdout.split()
    for c in apagados:
        conteudo = show(root, c + '^', '%s/AVISO_DONO.md' % DIR)
        if conteudo is None:
            continue
        h = filehash(conteudo)
        raw = show(root, commit, '%s/avisos/%s.json' % (DIR, h))
        require(raw is not None, 'aviso_apagado_sem_resolucao:' + h[:12])
        r = strict_json(raw)
        require(set(r) == {'schema', 'aviso_sha256', 'motivo', 'evidencias'} and r['schema'] == 'sc-aviso-resolvido/1'
                and r['aviso_sha256'] == h, 'aviso_resolucao_schema:' + h[:12])
        text_ok(r['motivo'], 20, 'aviso_resolucao_sem_motivo:' + h[:12])
        require(isinstance(r['evidencias'], list) and r['evidencias'], 'aviso_resolucao_sem_evidencia:' + h[:12])
        for ref in r['evidencias']:
            require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'evidencia_schema')
            rel_ok(ref['path'])
            conteudo_ev = show(root, commit, ref['path'])
            require(conteudo_ev is not None and filehash(conteudo_ev) == ref['sha256'], 'aviso_resolucao_evidencia:' + ref['path'])
        if regras >= 3:
            confirmacoes = [ref['path'] for ref in r['evidencias'] if ref['path'].startswith(CONFIRMACOES + '/')]
            require(confirmacoes, 'aviso_resolvido_sem_confirmacao_do_dono:' + h[:12])
            confirmacao_dono_ok(root, confirmacoes[0], ['AVISO ' + h], chaves_em_vigor(root, commit))


def ficha_no_commit(root, commit, item):
    """Hash da ficha do item no commit, validada contra o aceite do item. Achado herdado não tem ficha."""
    if fx.ID_ITEM.fullmatch(item['id']) is None:
        return None
    raw = show(root, commit, fx.caminho_ficha(item['id']))
    require(raw is not None, 'ficha_ausente:' + item['id'])
    try:
        fx.validar_ficha(strict_json(raw), item['aceite'], item['id'])
    except (Blocked, ValueError, TypeError, KeyError) as exc:
        raise Blocked('ficha_invalida:%s:%s' % (item['id'], exc)) from exc
    return filehash(raw)


def derivar_manifesto(root, commit, bid=None, regras=REGRAS, motor=None):
    """O manifesto que `abrir` gravaria no commit dado. Usado para abrir e para conferir."""
    require(show(root, commit, '%s/PARE' % DIR) is None, 'parado_pelo_dono')
    require(show(root, commit, '%s/AVISO_DONO.md' % DIR) is None, 'aviso_ao_dono_pendente')
    avisos_resolvidos_ok(root, commit, regras)
    abertos = [x for x in blocos_no_commit(root, commit) if bid is None or x < bid]
    anterior = abertos[-1] if abertos else None
    herdados = []
    if anterior:
        vraw = show(root, commit, '%s/%s/verificado.json' % (DIR, anterior))
        require(vraw is not None, 'anterior_nao_verificado:' + anterior)
        regras_anterior = strict_json(vraw).get('regras', 1)
        herdados = herdados_de(validar_manifesto(show_json(root, commit, '%s/%s/manifesto.json' % (DIR, anterior)), anterior),
                               show_json(root, commit, '%s/%s/fechamento.json' % (DIR, anterior)), anterior, MAX_HERANCA[regras if regras_anterior >= 2 else 1])
    plano = validar_plano(show_json(root, commit, '%s/PLANO.json' % DIR))
    plano_congelado_ok(root, anterior, plano, commit, regras, motor)
    proximo = next((b for b in plano['blocos'] if b['id'] not in abertos and (anterior is None or b['id'] > anterior)), None)
    require(proximo is not None, 'plano_concluido')
    require(bid is None or proximo['id'] == bid, 'bloco_fora_da_ordem_do_plano')
    require(not {i['id'] for i in herdados} & {i['id'] for i in proximo['itens']}, 'item_do_plano_repete_herdado')
    itens = [{k: i[k] for k in ('id', 'titulo', 'aceite', 'herdado_de', 'herdado_vezes')} for i in herdados] + \
            [dict(i, herdado_de=None, herdado_vezes=0) for i in proximo['itens']]
    if regras >= 3:
        itens = [dict(i, ficha_sha256=ficha_no_commit(root, commit, i)) for i in itens]
    return proximo, anterior, itens


def parada_atual_ok(root):
    """Observe the operational branch afresh; never merge/reset a working checkout.
    Network/object errors are not absence. Historical manifests do not call this.
    """
    require(not (Path(root)/DIR/'PARE').exists(), 'parado_pelo_dono')
    ref='refs/heads/main'
    try:
        remote=git(root,'ls-remote','origin',ref).stdout.splitlines()
        require(len(remote)==1,'pare_remoto_resposta_invalida')
        row=remote[0].split()
        require(len(row)==2 and re.fullmatch(r'[0-9a-f]{40}',row[0]) and row[1]==ref,
                'pare_remoto_resposta_invalida')
        commit=row[0]
        if git(root,'cat-file','-e',commit+'^{commit}',check=False).returncode:
            git(root,'fetch','origin',ref)
        require(git(root,'cat-file','-e',commit+'^{commit}',check=False).returncode==0,
                'pare_remoto_commit_indisponivel')
        entries=git(root,'ls-tree','--name-only',commit,DIR+'/PARE').stdout
        require(not entries.strip(),'parado_pelo_dono')
        return commit
    except (OSError, subprocess.SubprocessError) as exc:
        raise Blocked('pare_remoto_observacao_falhou') from exc


def barreira_pare_atual(root):
    try:
        parada_atual_ok(root)
    except Blocked as exc:
        return {'acao':'nada' if str(exc)=='parado_pelo_dono' else 'parado','motivo':str(exc)}
    return None


def _abrir(root, now=None):
    """Abre o próximo bloco do plano. Exige o anterior verificado e enviado, nenhum PARE nem aviso
    pendente, avisos antigos resolvidos, congelado intacto e identidade de agente; põe no topo os bloqueados."""
    root = Path(root)
    parada_atual_ok(root)
    require(not (root / DIR / 'AVISO_DONO.md').exists(), 'aviso_ao_dono_pendente')
    require(not git(root, 'status', '--porcelain', '-uall').stdout.strip(), 'arvore_suja_antes_de_abrir')
    identidade_de_agente_ok(root)
    abertos = blocos_abertos(root)
    if abertos:
        require(verificado_e_enviado(root, abertos[-1]), 'anterior_nao_verificado:' + abertos[-1])
    head = git(root, 'rev-parse', 'HEAD').stdout.strip()
    proximo, anterior, itens = derivar_manifesto(root, head)
    manifesto = {'schema': SCHEMA_DO_BLOCO[REGRAS], 'id': proximo['id'], 'titulo': proximo['titulo'], 'anterior': anterior,
                 'origin_commit': head, 'aberto_em': iso(now), 'itens': itens}
    parada_atual_ok(root)
    d = root / DIR / proximo['id']
    d.mkdir(parents=True, exist_ok=True)
    write_once(manifesto, d / 'manifesto.json')
    load_manifesto(root, proximo['id'])
    return manifesto


def manifesto_inalterado(root, bid):
    rel = '%s/%s/manifesto.json' % (DIR, bid)
    additions = git(root, 'log', '--diff-filter=A', '--format=%H', '--', rel).stdout.split()
    require(len(additions) == 1, 'manifesto_sem_origem_unica')
    original = show(root, additions[0], rel)
    require(original is not None and load(Path(root) / rel) == strict_json(original), 'manifesto_alterado')
    m = load_manifesto(root, bid)
    require(ancestral(root, m['origin_commit'], 'HEAD'), 'origem_nao_ancestral')
    plan = strict_json(show(root, m['origin_commit'], '%s/PLANO.json' % DIR) or b'null')
    planned = next(x for x in plan['blocos'] if x['id'] == bid)
    actual = [{k: i[k] for k in ('id', 'titulo', 'aceite')} for i in m['itens'] if i['herdado_de'] is None]
    require(actual == planned['itens'], 'manifesto_diverge_plano_congelado')


def manifesto_derivado_ok(root, bid, regras=REGRAS, historico=False):
    """Regra 2: o manifesto é exatamente o que `abrir` produziria no commit de abertura. O
    commit que acrescenta o manifesto não pode mudar mais nada além dele."""
    m = load_manifesto(root, bid)
    oc = m['origin_commit']
    require(HEX40.fullmatch(oc) is not None, 'origem_invalida')
    if not historico:
        regras_nao_regridem(root, m, regras)
        source = show(root, oc, 'controle/blocos.py')
        if source is not None:
            declared = re.search(rb'^REGRAS\s*=\s*(\d+)\s*(?:#.*)?$', source, re.MULTILINE)
            require(declared is not None and regras >= int(declared.group(1)),
                    'regras_abaixo_do_motor_da_abertura')
    require(m['schema'] == (SCHEMA_DO_BLOCO[regras] if regras >= 3 else 'sc-bloco/1'), 'manifesto_schema_da_versao')
    proximo, anterior, itens = derivar_manifesto(root, oc, bid, regras, motor_da_abertura(root, oc, regras))
    require(m['anterior'] == anterior, 'manifesto_anterior_incorreto')
    require(m['titulo'] == proximo['titulo'] and m['itens'] == itens, 'manifesto_diverge_derivacao')
    rel = '%s/%s/manifesto.json' % (DIR, bid)
    added = git(root, 'log', '--diff-filter=A', '--format=%H', '--', rel).stdout.split()
    require(len(added) == 1 and ancestral(root, oc, added[0]), 'manifesto_sem_origem_unica')
    mudou = [x for x in git(root, 'diff', '--name-only', oc, added[0]).stdout.split() if x != rel]
    require(not mudou, 'abertura_mudou_outros_arquivos:' + ','.join(mudou[:5]))


# ---------------------------------------------------------------- fechamento

def verificar_recibo_testes(root, rel, completo=True, historico=False):
    """O recibo citado é o último aprovado da cadeia e foi gerado sobre o código atual.
    historico=True confere a cópia do commit de fechamento: o inventário exigido é o que valia lá
    (prefixo do atual), porque suítes acrescentadas depois não invalidam fechamentos antigos."""
    rel_ok(rel)
    m = RECIBO.fullmatch(rel)
    require(m is not None, 'recibo_testes_caminho')
    import run_tests
    try:
        ultimo = run_tests.load_history(Path(root) / run_tests.HISTORY)
    except run_tests.Rejected as exc:
        raise Blocked('historico_testes_invalido:' + str(exc)) from exc
    require(ultimo is not None and ultimo['sequence'] == int(m.group(1)), 'recibo_testes_nao_e_o_ultimo')
    tracked = rastreados_de(root)
    history = Path(root) / run_tests.HISTORY
    for receipt_path in sorted(history.glob('approval-*.json')):
        receipt = load(receipt_path)
        paths = [receipt_path]
        manifest_hash = receipt['files'].get('controle/suites_extras.json')
        if manifest_hash:
            manifest_archive = history / 'manifests' / (manifest_hash + '.json')
            if manifest_archive.exists():
                paths.append(manifest_archive)
        for row in receipt['suites']:
            paths.extend(history / row[k] for k in ('log', 'result_file'))
        for path in paths:
            relpath = str(path.relative_to(root))
            require(relpath in tracked, 'recibo_ou_log_nao_versionado:' + relpath)
            committed = show(root, 'HEAD', relpath)
            require(committed is not None and committed == path.read_bytes(), 'recibo_ou_log_fora_commit:' + relpath)
    require(ultimo['status'] == 'APROVADO', 'recibo_testes_reprovado')
    inventario = [r['suite'] for r in ultimo['suites']]
    if historico:
        require(inventario == list(run_tests.SUITES[:len(inventario)]), 'recibo_inventario_incompleto')
    else:
        require(inventario == list(run_tests.SUITES), 'recibo_inventario_incompleto')
    require(not any(r['result']['skipped'] for r in ultimo['suites']), 'recibo_com_skips')
    try:
        current = run_tests.snapshot(Path(root), completo=completo)
    except run_tests.Rejected as exc:
        raise Blocked('snapshot_invalido:' + str(exc)) from exc
    require(ultimo['files'] == current, 'codigo_mudou_depois_dos_testes')
    return ultimo


def evidencia_ok(root, ref, rastreados):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'evidencia_schema')
    rel_ok(ref['path'])
    p = Path(root) / ref['path']
    require(p.resolve().is_relative_to(Path(root).resolve()) and not any(x.is_symlink() for x in [p, *p.parents] if x != Path(root).parent), 'evidencia_caminho_inseguro')
    require(p.is_file() and not p.is_symlink() and p.stat().st_nlink == 1 and p.stat().st_size <= MAX_EVIDENCIA, 'evidencia_ausente:' + ref['path'])
    require(filehash(p.read_bytes()) == ref['sha256'], 'evidencia_mudou:' + ref['path'])
    require(ref['path'] in rastreados, 'evidencia_nao_versionada:' + ref['path'])


def evidencias_ok(root, refs, rastreados, motivo):
    require(isinstance(refs, list) and refs, motivo)
    for ref in refs:
        evidencia_ok(root, ref, rastreados)


def registro_ok(root, chave, r, rastreados, regras=REGRAS):
    require(isinstance(r, dict) and r.get('estado') in ESTADOS, 'estado_proibido:%s:%s' % (chave, r.get('estado') if isinstance(r, dict) else r))
    prova = {'evidencias'} if regras >= 2 else set()
    if r['estado'] == 'concluido':
        require(set(r) == {'estado', 'evidencias'}, 'concluido_sem_evidencia:' + chave)
        evidencias_ok(root, r['evidencias'], rastreados, 'concluido_sem_evidencia:' + chave)
    elif r['estado'] == 'bloqueado_dono':
        require(set(r) == {'estado', 'acao_dono'} | prova, 'bloqueio_schema:' + chave)
        text_ok(r['acao_dono'], 10, 'bloqueado_dono_sem_acao_exata:' + chave)
    else:
        require(set(r) == {'estado', 'causa', 'desbloqueio'} | prova, 'bloqueio_schema:' + chave)
        text_ok(r['causa'], 10, 'bloqueado_externo_sem_causa:' + chave)
        text_ok(r['desbloqueio'], 10, 'bloqueado_externo_sem_desbloqueio:' + chave)
    if r['estado'] != 'concluido' and prova:
        evidencias_ok(root, r['evidencias'], rastreados, 'bloqueio_sem_evidencia:' + chave)


# Closed exceptions: every changed criterion still requires the owner's exact signature.
EMENDAS_FICHA = {
    ('B04', 'B02-05'): {
        'confirmacao': 'docs/decisoes/confirmacoes/B04-ratificacao-conjunta-ordem8.md',
        'linhas': (),
    },
    ('B05', 'B03-01'): {
        'confirmacao': 'docs/decisoes/confirmacoes/B05-ratificacao-conjunta-rota-contingencia.md',
        'linhas': ('SUBSTITUO A OBRIGACAO DE REINICIO B05 B03-01 POR REGISTRO DE CONTINGENCIA; '
                   'REINICIO NAO EXECUTADO; CAUSA external_anchor_unconfigured; '
                   'ACEITO O RISCO DA ANCORA AUSENTE SEM ALEGAR AUDITORIA ANCORADA.',),
    },
    ('B05', 'B05-01'): {
        'confirmacao': 'docs/decisoes/confirmacoes/B05-FICHAS-01.md',
        'linhas': ('EMENDA SOMENTE DE FORMA B05-01/B05-02; CRITERIOS, LIMIAR, TAREFAS, REPROVADO E PLANO PRESERVADOS.',),
    },
    ('B05', 'B05-02'): {
        'confirmacao': 'docs/decisoes/confirmacoes/B05-FICHAS-01.md',
        'linhas': ('EMENDA SOMENTE DE FORMA B05-01/B05-02; CRITERIOS, LIMIAR, TAREFAS, REPROVADO E PLANO PRESERVADOS.',),
    },
}


def termo_ajuste_ordem8(root,bid,item):
    """Build one narrow, hash-bound amendment; this function grants no authority."""
    require((bid,item['id']) in EMENDAS_FICHA,'ajuste_fora_da_ordem8')
    m=load_manifesto(root,bid)
    original=[i for i in m['itens'] if i['id']==item['id']]
    require(len(original)==1 and original[0]==item,'ajuste_item_original_diverge')
    plan=load_plano(root)
    rows=[i for block in plan['blocos'] for i in block['itens'] if i['id']==item['id']]
    require(len(rows)==1,'ajuste_item_plano_ambiguo')
    revised=rows[0]['aceite']
    ficha=fx.carregar(root,item['id'],revised)
    fpath=fx.caminho_ficha(item['id'])
    require(show(root,'HEAD',fpath)==(Path(root)/fpath).read_bytes(),'ajuste_ficha_nao_versionada')
    new_hash=fx.hash_ficha(root,item['id'])
    require(new_hash!=item['ficha_sha256'],'ajuste_sem_mudanca_ficha')
    manifest_rel=DIR+'/'+bid+'/manifesto.json'
    additions=git(root,'log','--diff-filter=A','--format=%H','--',manifest_rel).stdout.split()
    raw=(Path(root)/manifest_rel).read_bytes()
    require(len(additions)==1 and show(root,additions[0],manifest_rel)==raw and
            show(root,'HEAD',manifest_rel)==raw,'ajuste_manifesto_bytes_alterados')
    manifest_hash=filehash(raw)
    term='AJUSTE '+bid+' '+item['id']+' MANIFESTO '+manifest_hash+' FICHA '+item['ficha_sha256']+' -> '+new_hash+' ACEITE '+digest(revised)
    return dict(item,aceite=revised,ficha_sha256=new_hash),term


def ficha_efetiva_ordem8(root,bid,item):
    if item.get('ficha_sha256') is None or fx.hash_ficha(root,item['id'])==item['ficha_sha256']:
        return item
    require((bid,item['id']) in EMENDAS_FICHA,'ficha_mudou_no_bloco:'+item['id'])
    effective,term=termo_ajuste_ordem8(root,bid,item)
    m=load_manifesto(root,bid)
    plano_congelado_ok(root,m['anterior'],load_plano(root),'HEAD',regras_do_bloco(root,bid))
    emenda=EMENDAS_FICHA[(bid,item['id'])]
    rel=emenda['confirmacao']
    raw=show(root,'HEAD',rel)
    frozen=digest(congelado(root,'HEAD',m['anterior'],regras=regras_do_bloco(root,bid)))
    approval='Aprovo a mudanca do congelado com hash '+frozen+'.'
    lines=[term,approval,*emenda['linhas']]
    require(raw is not None and (Path(root)/rel).read_bytes()==raw and
            all(line in raw.decode('utf-8','strict').splitlines() for line in lines),
            'ajuste_ordem8_sem_linha_exata')
    confirmacao_dono_ok(root,rel,lines,chaves_em_vigor(root))
    return effective


def aceite_revisado(root, bid, chave, manifesto, registro, rastreados):
    rel = '%s/%s/aceites.json' % (DIR, bid)
    require(rel in rastreados, 'aceite_sem_revisao_versionada')
    a = load(Path(root) / rel)
    require(a.get('schema') == 'sc-aceites/1' and a.get('bloco') == bid, 'aceites_schema')
    review = a.get('revisor', {})
    require(review.get('sessao_distinta') is True and isinstance(review.get('id'), str)
            and len(review['id']) >= 8, 'revisao_independente_ausente')
    row = a.get('itens', {}).get(chave, {})
    original=next(i for i in manifesto['itens'] if i['id']==chave)
    criterion=ficha_efetiva_ordem8(root,bid,original)['aceite'] if original.get('ficha_sha256') else original['aceite']
    require(row.get('criterio_sha256') == digest(criterion), 'criterio_sem_revisao:' + chave)
    require(row.get('resultado') == 'aceito' and row.get('evidencias') == registro['evidencias'], 'provas_divergem_revisao:' + chave)
    require(isinstance(row.get('fundamento'), str) and len(row['fundamento']) >= 30, 'revisao_sem_fundamento')
    for ref in row.get('evidencias', []):
        evidencia_ok(root, ref, rastreados)
    # Aceite interno. A independência real vem das revisões externas (revisoes_ok), que exigem
    # Claude e Antigravity com canal verificável, e das fichas (fichas_ok), que o código executa.


def ficha_ok(root, bid, item, historico):
    """Regra 3: item concluído só com a ficha do manifesto intacta, aprovada e, no fechamento ao
    vivo, com os negativos derrubando a ficha. Achado herdado não tem ficha."""
    if item.get('ficha_sha256') is None:
        require(fx.ID_ITEM.fullmatch(item['id']) is None, 'ficha_ausente_no_manifesto:' + item['id'])
        return
    item=ficha_efetiva_ordem8(root,bid,item)
    require(fx.hash_ficha(root, item['id']) == item['ficha_sha256'], 'ficha_mudou_no_bloco:' + item['id'])
    ficha = fx.carregar(root, item['id'], item['aceite'])
    em = chaves_em_vigor(root)
    falhas = fx.conferir_ficha(root, ficha, bid, em, historico)
    require(not falhas, 'ficha_reprovada:%s:%s' % (item['id'], ';'.join(falhas)))
    if not historico:
        furos = fx.negativos_ficha(root, ficha, bid, em)
        require(not furos, 'ficha_furada:%s:%s' % (item['id'], ';'.join(furos)))


def propostas_ok(root, rastreados):
    """Toda proposta versionada tem o esquema certo. Proposta não muda nada por si: só a confirmação
    do dono e o registro em PLANO_ALTERACOES.json mudam o congelado."""
    for rel in sorted(x for x in rastreados if x.startswith(PROPOSTAS + '/')):
        p = load(Path(root) / rel)
        require(isinstance(p, dict) and set(p) == {'schema', 'bloco', 'item', 'autor', 'motivo', 'de', 'para', 'criado_em'}
                and p['schema'] == 'sc-proposta/1' and ID.fullmatch(str(p['bloco'])) and ITEM.fullmatch(str(p['item'])), 'proposta_schema:' + rel)
        text_ok(p['motivo'], 20, 'proposta_sem_motivo:' + rel)
        require(isinstance(p['de'], dict) and isinstance(p['para'], dict) and set(p['para']) == {'aceite', 'ficha'}, 'proposta_schema:' + rel)
        require(p['para']['aceite'] is not None or p['para']['ficha'] is not None, 'proposta_vazia:' + rel)


def propor(root, item, motivo, now=None):
    """Grava o esqueleto da proposta; a sessão preenche `para` (aceite e/ou ficha propostos)."""
    root = Path(root)
    require(isinstance(item, str) and fx.ID_ITEM.fullmatch(item), 'proposta_item')
    text_ok(motivo, 20, 'proposta_sem_motivo')
    abertos = blocos_abertos(root)
    require(abertos, 'nenhum_bloco_aberto')
    bid = abertos[-1]
    itens = fx.itens_do_plano(root)
    require(item in itens, 'proposta_item_fora_do_plano:' + item)
    autor = git(root, 'config', 'user.email', check=False).stdout.strip()
    d = root / PROPOSTAS
    d.mkdir(parents=True, exist_ok=True)
    n = 1 + sum(1 for p in d.glob('%s-%s-*.json' % (bid, item)))
    proposta = {'schema': 'sc-proposta/1', 'bloco': bid, 'item': item, 'autor': autor, 'motivo': motivo,
                'de': {'aceite': itens[item]['aceite'], 'ficha_sha256': fx.hash_ficha(root, item)},
                'para': {'aceite': None, 'ficha': None}, 'criado_em': iso(now)}
    write_once(proposta, d / ('%s-%s-%02d.json' % (bid, item, n)))
    return proposta


# ---------------------------------------------------------------- revisão externa (regra 2)

def recibo_revisao(root, commit, bid, revisor):
    raw = show(root, commit, '%s/%s/revisoes/%s.json' % (DIR, bid, revisor))
    return strict_json(raw) if raw is not None else None


def base_revisao(root, bid, revisor, commit='HEAD'):
    """Onde começa o trabalho que o revisor precisa ver neste bloco: no commit que ele revisou no
    bloco anterior. Se ele esteve indisponível, a base anterior continua (nada fica sem revisão).
    Bloco anterior sem revisões (regras antigas) começa na abertura dele."""
    m = validar_manifesto(show_json(root, commit, '%s/%s/manifesto.json' % (DIR, bid)), bid)
    anterior = m['anterior']
    if anterior is None:
        return m['origin_commit']
    v = show_json(root, commit, '%s/%s/verificado.json' % (DIR, anterior))
    r = recibo_revisao(root, v['head'], anterior, revisor)
    if r is None:
        return validar_manifesto(show_json(root, commit, '%s/%s/manifesto.json' % (DIR, anterior)), anterior)['origin_commit']
    return r['base_revisada'] if r['veredito'] == 'indisponivel' else r['commit_revisado']


def ultimo_autor(root, rel):
    return git(root, 'log', '-1', '--format=%ae', '--', rel).stdout.strip()


def cloud_review_signature(root, rel, review, commit='HEAD'):
    """Bind both review artifacts to the same signed cloud commit, not author text."""
    require(review.get('revisor') == 'claude' and review.get('canal') == 'nuvem',
            'revisao_assinatura_canal')
    report = review.get('parecer')
    require(type(report) is dict and set(report) == {'path','sha256'},
            'revisao_assinatura_parecer')
    commits = []
    for path in (rel, report['path']):
        rel_ok(path)
        changed = git(root,'log','-1','--format=%H',commit,'--',path).stdout.strip()
        require(HEX40.fullmatch(changed) is not None, 'revisao_assinatura_origem')
        commits.append(changed)
    signed = commits[0]
    require(commits[1] == signed and ancestral(root, signed, commit) and
            ancestral(root, review['commit_revisado'], signed), 'revisao_assinatura_cobertura')
    raw = show(root,signed,rel)
    require(raw is not None and raw == show(root,commit,rel) and
            strict_json(raw) == review, 'revisao_assinatura_recibo_alterado')
    text = show(root,signed,report['path'])
    require(text is not None and text == show(root,commit,report['path']) and
            filehash(text) == report['sha256'], 'revisao_assinatura_parecer_alterado')
    author = git(root,'log','-1','--format=%ae',signed,'--',rel).stdout.strip()
    require(author == AUTOR_NUVEM, 'revisao_assinatura_autor')
    verified = jb.verify_ssh_commit(root,signed,CLAUDE_PUBLIC_KEY,AUTOR_NUVEM)
    require(verified.returncode == 0, 'revisao_assinatura_ssh_invalida')
    return {'commit':signed,'parecer':text}


def em_ramo_claude(root, rel):
    """Regra 3: o recibo da nuvem chegou por um ramo origin/claude/*, não por cópia à mão."""
    commit = git(root, 'log', '-1', '--format=%H', '--', rel).stdout.strip()
    ramos = git(root, 'branch', '-r', '--contains', commit, '--list', 'origin/claude/*', check=False).stdout.split()
    return bool(commit) and bool(ramos)


def _recibo_vps_ok(root, bid, revisor, review, tracked, *, within_batch=False, verified_batch_packet=None):
    """Bind the native terminal, raw bytes and extracted report to the exact request."""
    receipt = load(Path(root) / review['recibo_nativo']['path'])
    require(type(receipt) is dict and receipt.get('schema') == 'sc-recibo-transporte/1',
            'recibo_nativo_schema')
    require(receipt.get('rota') == revisor and receipt.get('bloco') == bid and
            receipt.get('origin_commit') == review['commit_revisado'], 'recibo_nativo_vinculo')
    pedido_rel = '%s/%s/revisoes/pedido-%s.json' % (DIR, bid, review['commit_revisado'][:12])
    require(pedido_rel in tracked, 'recibo_nativo_pedido_ausente')
    pedido_raw = (Path(root) / pedido_rel).read_bytes()
    require(show(root, 'HEAD', pedido_rel) == pedido_raw, 'recibo_nativo_pedido_alterado')
    if revisor == 'antigravity' and bid in ('B05', 'B06', 'B07', 'B08'):
        pedido_canonico_imutavel(root, pedido_rel, pedido_raw)
    pedido = strict_json(pedido_raw)
    require(pedido.get('schema') == 'sc-pedido-revisao/1' and pedido.get('bloco') == bid and
            pedido.get('commit_revisado') == review['commit_revisado'] and
            pedido.get('bases', {}).get(revisor) == review['base_revisada'], 'recibo_nativo_pedido_diverge')
    pedido_hash = filehash(pedido_raw)
    original = 'sc-' + bid.lower() + '-revisao-' + pedido_hash[:12]
    task = receipt.get('task_id')
    is_part=type(task) is str and bool(re.fullmatch(re.escape(original)+r'-part[0-9]{2}',task))
    require(not is_part or within_batch, 'recibo_parcial_exige_conjunto')
    canonical_part=is_part and revisor=='antigravity' and bid in ('B05','B06','B07','B08')
    require(task == original or canonical_part or (revisor == 'antigravity' and bid == 'B04' and
            original == 'sc-b04-revisao-4523ede70c7c' and
            (task in (original+'-integral1', original+'-multipart1') or is_part)), 'recibo_nativo_tarefa_diverge')
    refs = review['evidencias']
    evidencias_ok(root, refs, tracked, 'recibo_nativo_sem_bytes')
    def artifact(wanted):
        matching = [ref for ref in refs if ref['sha256'] == wanted]
        require(bool(matching), 'recibo_nativo_artefato_ausente')
        return (Path(root) / matching[0]['path']).read_bytes()
    sent, raw = artifact(receipt.get('entrada_sha256')), artifact(receipt.get('saida_sha256'))
    require(len(sent) == receipt.get('bytes_enviados') and sent and
            len(raw) == receipt.get('bytes_recebidos') and raw, 'recibo_nativo_contagem')
    supervision = receipt.get('supervisao')
    require(type(supervision) is dict and supervision.get('supervisor_reason') == 'completed' and
            supervision.get('tree_stopped') is True and type(supervision.get('exit_code')) is int and
            supervision['exit_code'] == 0 and supervision.get('native_bytes') == len(raw),
            'recibo_nativo_supervisao')
    require(receipt.get('evento_terminal') == 'result' and receipt.get('terminal_informational') is False
            and receipt.get('consumo_repetido') is False, 'recibo_nativo_terminal')
    from revisao_juiz import native_execution_profile
    def profile_bytes(path):
        raw = show(root, 'HEAD', path)
        if raw is None:
            return None
        require(jb.protected_bytes(Path(root)/path, MAX_PROFILE_BYTES) == raw,
                'review_native_profile_worktree_changed')
        return raw
    MAX_PROFILE_BYTES = 256 * 1024
    from revisao_juiz import build_packet
    canonical_packet=(build_packet(root,base=review['base_revisada'],target=review['commit_revisado'])
                      if canonical_part and verified_batch_packet is None else verified_batch_packet)
    profile = native_execution_profile(receipt, {'bloco':bid, 'pedido':pedido_rel,
                                        'sha256':pedido_hash}, profile_bytes,packet=canonical_packet)
    if task != original:
        require(profile['validated_policy_ref'] in refs,'recibo_nativo_politica_fixada_ausente')
        policy=profile['validated_policy']
        binding = {'bloco':bid,'pedido':pedido_rel,'sha256':pedido_hash}
        require(policy.get('reviews',{}).get(task) == binding and
                policy['reviews'].get(original) == binding and
                policy.get('tasks',{}).get(task) == supervision.get('task_hash'),
                'recibo_nativo_autoridade_renovacao')
        if task.endswith('-multipart1'):
            require(policy.get('multipart_authority') == {'task_id':task,
                    'request_sha256':supervision.get('task_hash'),'max_turns':35,'retry':False},
                    'recibo_nativo_autoridade_renovacao')
    require(artifact(supervision['stderr_sha256']) == b'', 'review_native_stderr_not_empty')
    from revisao_juiz import ReviewStreamParser
    proof = receipt.get('prova_negacao_ferramentas')
    packet_proof = receipt.get('pacote_integral')
    from revisao_juiz import build_packet, historical_packet, validate_wire, derived_findings, findings_match_review
    builder = historical_packet if original == 'sc-b04-revisao-4523ede70c7c' else build_packet
    require(verified_batch_packet is None or within_batch,'recibo_nativo_cache_fora_do_conjunto')
    packet = builder(root, base=review['base_revisada'], target=review['commit_revisado']) if verified_batch_packet is None else verified_batch_packet
    require(packet_proof == packet['proof'], 'recibo_nativo_pacote')
    if is_part:
        from revisao_juiz import build_batch,replay_part
        batch=build_batch(packet)
        index=int(task[-2:])
        require(1<=index<=len(batch['parts']),'recibo_nativo_parte_indice')
        authority=policy.get('batch_authority',{})
        expected_authority={('source' if canonical_part else 'human_message_id'):
                ('pedido_canonico' if canonical_part else '01a18f30-2d9e-7450-9f96-fbf37c7529da'),
                'retry':False,'max_wire_bytes':64000,'max_conversation_bytes':310590,
                'batch_sha256':batch['sha256'],
                'task_ids':[original+'-part%02d'%i for i in range(1,len(batch['parts'])+1)]}
        require(authority==expected_authority,'recibo_nativo_autoridade_partes')
        require('conversa_multipart' not in receipt,'recibo_nativo_parte_contraditoria')
        session=replay_part(sent,raw,batch['parts'][index-1],requested_model=profile['model'],
                            deny_all_proof=proof,qualified_task=task if 'task_scope' in profile else None)
        require(session.evidence()==receipt.get('parte_integral'),'recibo_nativo_parte_diverge')
        parser=session.parser
    elif 'conversa_multipart' not in receipt:
        validate_wire(sent, packet_proof, route=revisor)
    if not is_part and 'conversa_multipart' in receipt:
        from revisao_juiz import replay_session
        packet = builder(root, base=review['base_revisada'], target=review['commit_revisado'])
        require(packet['proof'] == packet_proof and packet_proof['target'] == review['commit_revisado']
                and packet_proof['base'] == review['base_revisada'], 'recibo_nativo_pacote')
        session = replay_session(sent, raw, packet, requested_model=profile['model'],
                                 deny_all_proof=proof)
        session.finish(0, False)
        require(session.evidence() == receipt['conversa_multipart'], 'recibo_nativo_multipart')
        parser = session.parser
    elif not is_part:
        parser = ReviewStreamParser(revisor, requested_model=profile['model'],
                 permission_mode=receipt['modo_permissao_observado'],
                 deny_all_proof=proof, packet_proof=packet_proof)
        for line in raw.splitlines():
            parser.feed(strict_json(line))
        parser.finish(0, False)
    require(parser.session == review['sessao'] and parser.observed_model == receipt.get('modelo_observado'),
            'recibo_nativo_sessao')
    events = [strict_json(line) for line in raw.splitlines()]
    finals = [e for e in events if e.get('type' if revisor == 'claude' else 'event') == 'result']
    require(finals, 'recibo_nativo_terminal')
    report = finals[-1]['result'] if revisor == 'claude' else finals[-1]['result']['response']
    require((Path(root) / review['parecer']['path']).read_bytes() == report.encode('utf-8'),
            'recibo_nativo_parecer_diverge')
    if not within_batch:
        findings_match_review(review, derived_findings(report, bid, revisor))



def legacy_transcription_checked(root,bid,review,tracked,batch,members):
    """The local writer cannot certify semantic completeness of a free-form legacy batch."""
    from revisao_juiz import legacy_transcribed_findings
    prefix=DIR+'/'+bid+'/revisoes/'
    transcript_path=prefix+'antigravity-transcricao.json'
    check_path=prefix+'antigravity-transcricao-claude.json'
    refs=review['evidencias']
    def exact_ref(path):
        matches=[ref for ref in refs if ref.get('path')==path]
        require(len(matches)==1,'batch_legacy_transcription_requires_signed_cloud_check')
        evidencias_ok(root,matches,tracked,'legacy_transcription_evidence')
        return matches[0]
    transcript_ref=exact_ref(transcript_path)
    exact_ref(check_path)
    transcription=strict_json(jb.protected_bytes(Path(root)/transcript_path,2*1024*1024))
    findings=legacy_transcribed_findings(transcription,batch,members,bid)
    check=strict_json(jb.protected_bytes(Path(root)/check_path,256*1024))
    keys={'schema','bloco','revisor','canal','sessao','base_revisada','commit_revisado',
          'veredito','parecer','transcricao','recibo_nativo','reports','checks'}
    require(type(check) is dict and set(check)==keys and check['schema']=='sc-legacy-transcription-check/1'
            and check['bloco']==bid and check['revisor']=='claude' and check['canal']=='nuvem'
            and check['veredito']=='conferido_integralmente','legacy_transcription_check_schema')
    require(type(check['sessao']) is str and SESSAO_NUVEM.fullmatch(check['sessao']) is not None,
            'legacy_transcription_cloud_session')
    require(check['transcricao']==transcript_ref and check['recibo_nativo']==review['recibo_nativo']
            and check['base_revisada']==review['base_revisada'],'legacy_transcription_binding')
    checked_commit=check['commit_revisado']
    require(type(checked_commit) is str and HEX40.fullmatch(checked_commit)
            and ancestral(root,review['commit_revisado'],checked_commit)
            and ancestral(root,checked_commit,'HEAD'),'legacy_transcription_checked_commit')
    bundle_at_target=show(root,checked_commit,review['recibo_nativo']['path'])
    require(bundle_at_target is not None and filehash(bundle_at_target)==review['recibo_nativo']['sha256'],
            'legacy_transcription_bundle_not_reviewed')
    expected=[{'index':index,'report_sha256':filehash(row['report'].encode('utf-8'))}
              for index,row in enumerate(members,1)]
    require(type(check['checks']) is dict and all(type(v) is bool for v in check['checks'].values())
            and type(check['reports']) is list and all(type(row) is dict and type(row.get('index')) is int for row in check['reports']),
            'legacy_transcription_semantic_check_missing')
    require(check['reports']==expected and check['checks']=={
            'all_34_reports_read':True,'all_findings_transcribed':True,
            'meaning_and_severity_preserved':True,'no_omissions':True},
            'legacy_transcription_semantic_check_missing')
    require(type(check['parecer']) is dict and set(check['parecer'])=={'path','sha256'},'legacy_transcription_check_report')
    report_ref=exact_ref(check['parecer']['path'])
    require(report_ref==check['parecer'],'legacy_transcription_check_report')
    proof=cloud_review_signature(root,check_path,check)
    require(show(root,proof['commit'],transcript_path)==show(root,'HEAD',transcript_path),
            'legacy_transcription_changed_after_signature')
    return findings


def recibos_parciais_ok(root,bid,revisor,review,tracked):
    from revisao_juiz import build_packet,historical_packet,build_batch,validate_batch_members,render_batch_report,derived_findings,findings_match_review
    bundle=load(Path(root)/review['recibo_nativo']['path'])
    require(type(bundle) is dict and set(bundle)=={'schema','bloco','rota','origin_commit','packet','batch_sha256','parts'}
            and bundle['schema']=='sc-recibos-parciais/1' and bundle['bloco']==bid and
            bundle['rota']==revisor=='antigravity' and bundle['origin_commit']==review['commit_revisado'],
            'recibos_parciais_schema')
    from revisao_juiz import BASE as LEGACY_BASE, TARGET as LEGACY_TARGET
    historical = review['base_revisada'] == LEGACY_BASE and review['commit_revisado'] == LEGACY_TARGET
    builder = historical_packet if historical else build_packet
    packet=builder(root,base=review['base_revisada'],target=review['commit_revisado'])
    batch=build_batch(packet)
    require(bundle['packet']==packet['proof'] and bundle['batch_sha256']==batch['sha256'] and
            review['sessao']=='batch-'+batch['sha256'][:32],'recibos_parciais_pedido')
    require(type(bundle['parts']) is list and len(bundle['parts'])==len(batch['parts']),'batch_part_missing')
    evidencias_ok(root,review['evidencias'],tracked,'recibos_parciais_evidencias')
    members=[]
    for expected,row in zip(batch['parts'],bundle['parts']):
        require(type(row) is dict and set(row)=={'index','sessao','recibo','parecer'} and
                type(row['index']) is int and row['index']==expected['proof']['index'],'batch_part_changed_or_repeated')
        for ref in (row['recibo'],row['parecer']):
            require(ref in review['evidencias'],'recibo_parcial_artefato_ausente')
            evidencias_ok(root,[ref],tracked,'recibo_parcial_artefato')
        native=load(Path(root)/row['recibo']['path'])
        require(native.get('parte_integral',{}).get('part')==expected['proof'],'batch_part_changed_or_repeated')
        subreview=dict(review,recibo_nativo=row['recibo'],parecer=row['parecer'],sessao=row['sessao'])
        _recibo_vps_ok(root,bid,revisor,subreview,tracked,within_batch=True,verified_batch_packet=packet)
        members.append({'part':expected['proof'],'conversation_id':row['sessao'],
                        'report':(Path(root)/row['parecer']['path']).read_text(encoding='utf-8')})
    validate_batch_members(batch,members)
    require((Path(root)/review['parecer']['path']).read_bytes()==render_batch_report(batch,members).encode(),
            'recibos_parciais_parecer_diverge')
    # Old prompts have free-form findings. Their transcription requires a signed
    # cloud check; no local declaration can upgrade the incomplete old batch.
    if historical:
        findings=legacy_transcription_checked(root,bid,review,tracked,batch,members)
    else:
        findings = [finding for row in members for finding in
                    derived_findings(row['report'], bid, revisor, row['part']['index'])]
    findings_match_review(review, findings)

def recibo_vps_ok(root, bid, revisor, review, tracked):
    try:
        receipt=load(Path(root)/review['recibo_nativo']['path'])
        if receipt.get('schema')=='sc-recibos-parciais/1':
            return recibos_parciais_ok(root,bid,revisor,review,tracked)
        require('parte_integral' not in receipt and not re.search(r'-part[0-9]{2}$',str(receipt.get('task_id',''))), 'recibo_parcial_exige_conjunto')
        return _recibo_vps_ok(root, bid, revisor, review, tracked)
    except Blocked as exc:
        raise Blocked('recibo_nativo_invalido:' + str(exc)) from exc


def revisao_ok(root, bid, revisor, m, f, rastreados, ultimo_bloco, regras=REGRAS, historico=False):
    rel = '%s/%s/revisoes/%s.json' % (DIR, bid, revisor)
    require(rel in rastreados, 'revisao_externa_ausente:' + revisor)
    r = load(Path(root) / rel)
    chaves = {'schema', 'bloco', 'revisor', 'canal', 'sessao', 'base_revisada', 'commit_revisado', 'veredito',
              'parecer', 'achados', 'recibo_nativo', 'tentativas', 'evidencias'}
    require(isinstance(r, dict) and set(r) == chaves and r['schema'] == 'sc-revisao-externa/1'
            and r['bloco'] == bid and r['revisor'] == revisor, 'revisao_schema:' + revisor)
    require(r['canal'] in CANAIS[revisor], 'revisao_canal:' + revisor)
    text_ok(r['sessao'], 8, 'revisao_sem_sessao:' + revisor)
    require(r['veredito'] in VEREDITOS, 'revisao_veredito:' + revisor)
    for k in ('base_revisada', 'commit_revisado'):
        require(isinstance(r[k], str) and HEX40.fullmatch(r[k]) is not None, 'revisao_commit:' + revisor)
    require(r['base_revisada'] == base_revisao(root, bid, revisor), 'revisao_base_errada:' + revisor)
    require(ancestral(root, r['base_revisada'], r['commit_revisado']) and ancestral(root, r['commit_revisado'], 'HEAD'),
            'revisao_fora_do_historico:' + revisor)
    require(ancestral(root, m['origin_commit'], r['commit_revisado']), 'revisao_antes_da_abertura:' + revisor)
    if r['canal'] == 'nuvem':
        require(SESSAO_NUVEM.fullmatch(r['sessao']) is not None, 'revisao_sessao_nuvem:' + revisor)
        require(ultimo_autor(root, rel) == AUTOR_NUVEM, 'revisao_nuvem_sem_autoria:' + revisor)
        require(r['recibo_nativo'] is None, 'revisao_schema:' + revisor)
        if regras >= 3 and not historico:   # ramo pode ser podado depois; o fechamento já conferiu
            require(em_ramo_claude(root, rel), 'revisao_nuvem_fora_do_ramo_claude:' + revisor)
        if r['veredito'] != 'indisponivel':
            cloud_review_signature(root, rel, r)
    else:
        evidencias_ok(root, [r['recibo_nativo']] if isinstance(r['recibo_nativo'], dict) else [], rastreados, 'revisao_sem_recibo_nativo:' + revisor)
    if r['veredito'] == 'indisponivel':
        require(type(r['tentativas']) is int and r['tentativas'] >= 2, 'revisao_indisponivel_sem_tentativas:' + revisor)
        evidencias_ok(root, r['evidencias'], rastreados, 'revisao_indisponivel_sem_evidencia:' + revisor)
        require(r['parecer'] is None and r['achados'] == [], 'revisao_schema:' + revisor)
        if regras >= 3:
            # Só o dono dispensa uma revisão: confirmação assinada pelo site citando revisor e bloco.
            dispensas = [e['path'] for e in r['evidencias'] if e['path'].startswith(CONFIRMACOES + '/')]
            require(dispensas, 'revisao_indisponivel_sem_dispensa_do_dono:' + revisor)
            confirmacao_dono_ok(root, dispensas[0], ['DISPENSA REVISAO %s %s' % (bid, revisor)], chaves_em_vigor(root))
        anterior = m['anterior']
        if anterior:
            v = show_json(root, 'HEAD', '%s/%s/verificado.json' % (DIR, anterior))
            antes = recibo_revisao(root, v['head'], anterior, revisor)
            require(not (antes and antes['veredito'] == 'indisponivel'), 'revisor_indisponivel_dois_blocos:' + revisor)
        return
    evidencias_ok(root, [r['parecer']] if isinstance(r['parecer'], dict) else [], rastreados, 'revisao_sem_parecer:' + revisor)
    if regras >= 4 and r['canal'] == 'vps-cli':
        recibo_vps_ok(root, bid, revisor, r, rastreados)
    require(isinstance(r['achados'], list), 'revisao_achados:' + revisor)
    require((r['veredito'] == 'com_achados') == bool(r['achados']), 'revisao_veredito_incoerente:' + revisor)
    no_fechamento = {a.get('id') for a in f['achados'] if isinstance(a, dict)}
    for a in r['achados']:
        require(isinstance(a, dict) and set(a) == {'id', 'gravidade', 'resumo'} and isinstance(a['id'], str)
                and ITEM.fullmatch(a['id']) and a['gravidade'] in GRAVIDADES, 'revisao_achado_schema:' + revisor)
        text_ok(a['resumo'], 10, 'revisao_achado_schema:' + revisor)
        require(a['id'] in no_fechamento, 'achado_do_revisor_fora_do_fechamento:' + a['id'])
    if ultimo_bloco:
        depois = [x for x in git(root, 'diff', '--name-only', r['commit_revisado'], 'HEAD').stdout.split()
                  if not (x.startswith('%s/%s/' % (DIR, bid)) or x.startswith('docs/evidencias/testes/'))]
        require(not depois, 'ultimo_bloco_mudou_depois_da_revisao:' + revisor)


def revisoes_ok(root, bid, m, f, rastreados, regras=REGRAS, historico=False):
    plano = load_plano(root)
    ultimo = not any(b['id'] > bid for b in plano['blocos'])
    for revisor in REVISORES:
        revisao_ok(root, bid, revisor, m, f, rastreados, ultimo, regras, historico)


def pedir_revisao(root, bid, now=None):
    """Grava o pedido que os dois revisores atendem: o bloco, o commit a revisar (HEAD enviado) e a
    base de cada um. A sessão do bloco faz commit e push do pedido."""
    root = Path(root)
    require(not git(root, 'status', '--porcelain', '-uall').stdout.strip(), 'arvore_suja_antes_do_pedido')
    head = git(root, 'rev-parse', 'HEAD').stdout.strip()
    branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    remoto = git(root, 'ls-remote', 'origin', 'refs/heads/' + branch, check=False).stdout.split()
    require(remoto and remoto[0] == head, 'pedido_antes_do_push')
    load_manifesto(root, bid)
    pedido = {'schema': 'sc-pedido-revisao/1', 'bloco': bid, 'commit_revisado': head, 'criado_em': iso(now),
              'bases': {r: base_revisao(root, bid, r) for r in REVISORES},
              'resposta': {r: '%s/%s/revisoes/%s.json' % (DIR, bid, r) for r in REVISORES}}
    d = root / DIR / bid / 'revisoes'
    d.mkdir(parents=True, exist_ok=True)
    write_once(pedido, d / ('pedido-%s.json' % head[:12]))
    return pedido


# ---------------------------------------------------------------- verificar e fechar

def regras_do_bloco(root, bid):
    """Versão de regras de um bloco aberto: a do esquema do manifesto gravado na abertura."""
    return REGRAS_DO_SCHEMA[load_manifesto(root, bid)['schema']]


def regras_vigentes(root):
    """Versão de regras para conferir o congelado agora: a do bloco aberto, se houver; senão a atual."""
    abertos = [bid for bid in blocos_abertos(root) if not (Path(root) / DIR / bid / 'verificado.json').is_file()]
    return max(REGRAS, regras_do_bloco(root, abertos[-1])) if abertos else REGRAS


def regras_nao_regridem(root, m, regras):
    """Um bloco não pode usar regras mais fracas que as do bloco anterior (manifesto forjado com
    esquema antigo para fugir das fichas não passa)."""
    if m['anterior'] is None:
        return
    v = strict_json(show(root, 'HEAD', '%s/%s/verificado.json' % (DIR, m['anterior'])) or b'{}')
    require(regras >= v.get('regras', 1), 'regras_regrediram:%d' % regras)


def verificar(root, bid, regras=None, historico=False):
    """Todas as regras de fechamento; devolve a lista de violações (vazia = pode fechar).
    regras=None usa a versão com que o bloco foi aberto. historico=True confere uma cópia no
    commit de fechamento: sem exigir remoto igual."""
    root = Path(root)
    erros = []
    if regras is None:
        try:
            regras = regras_do_bloco(root, bid)
        except (Blocked, OSError, ValueError, KeyError):
            regras = REGRAS

    def checar(fn, *a, **k):
        try:
            return fn(*a, **k)
        except (Blocked, OSError, ValueError, KeyError, TypeError, StopIteration, AttributeError) as e:
            erros.append(str(e) if isinstance(e, Blocked) else '%s:%s' % (type(e).__name__, e))
    m = checar(load_manifesto, root, bid)
    checar(manifesto_inalterado, root, bid)
    if regras >= 2:
        checar(manifesto_derivado_ok, root, bid, regras, historico)
    if m is not None and not historico:
        checar(regras_nao_regridem, root, m, regras)
    if regras >= 3 and m is not None:
        checar(autores_ok, root, m)
        # O congelado vale durante o bloco inteiro, não só na abertura: trocar ficha de outro item,
        # chaves, identidades ou o motor no meio do bloco não vira base legítima no fechamento.
        checar(lambda: plano_congelado_ok(root, m['anterior'], load_plano(root), 'HEAD', regras))
    f = checar(load, root / DIR / bid / 'fechamento.json')
    if m is None or f is None:
        return erros or ['fechamento_ausente']
    if not (isinstance(f, dict) and set(f) == {'schema', 'id', 'itens', 'achados', 'recibo_testes'}
            and f['schema'] == 'sc-fechamento/1' and f['id'] == bid and isinstance(f['itens'], dict) and isinstance(f['achados'], list)):
        return erros + ['fechamento_schema']
    rastreados = rastreados_de(root)
    esperados = [i['id'] for i in m['itens']]
    faltam = [x for x in esperados if x not in f['itens']]
    sobram = [x for x in f['itens'] if x not in esperados]
    if faltam:
        erros.append('item_sem_estado_final:' + ','.join(faltam))
    if sobram:
        erros.append('item_fora_do_manifesto:' + ','.join(sobram))
    limite = MAX_HERANCA[regras if regras >= 2 else 1]
    for chave in esperados:
        if chave in f['itens']:
            checar(registro_ok, root, chave, f['itens'][chave], rastreados, regras)
            item = next(i for i in m['itens'] if i['id'] == chave)
            if f['itens'][chave].get('estado') == 'concluido':
                checar(aceite_revisado, root, bid, chave, m, f['itens'][chave], rastreados)
                if regras >= 3:
                    checar(ficha_ok, root, bid, item, historico)
            if f['itens'][chave].get('estado') != 'concluido' and item['herdado_vezes'] >= limite:
                erros.append('heranca_esgotada:' + chave)
    ids_achados = []
    for a in f['achados']:
        if not (isinstance(a, dict) and isinstance(a.get('id'), str) and ITEM.fullmatch(a['id']) and isinstance(a.get('descricao'), str) and a['descricao'].strip()):
            erros.append('achado_schema'); continue
        ids_achados.append(a['id'])
        clean_record = {k: v for k, v in a.items() if k not in ('id', 'descricao')}
        checar(registro_ok, root, 'achado:' + a['id'], clean_record, rastreados, regras)
        if a.get('estado') == 'concluido':
            checar(aceite_revisado, root, bid, a['id'], {'itens': [{'id': a['id'], 'aceite': a['descricao']}]}, clean_record, rastreados)
    if len(set(ids_achados)) != len(ids_achados) or set(ids_achados) & set(esperados):
        erros.append('achado_ids_repetidos')
    if regras >= 2:
        checar(revisoes_ok, root, bid, m, f, rastreados, regras, historico)
    if regras >= 3:
        checar(propostas_ok, root, rastreados)
    checar(verificar_recibo_testes, root, f['recibo_testes'], completo=regras >= 2, historico=historico)
    sujos = git(root, 'status', '--porcelain', '-uall').stdout.strip()
    if sujos:
        erros.append('arvore_suja:' + ' '.join(l[3:] for l in sujos.splitlines()[:5]))
    if not historico:
        branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
        head = git(root, 'rev-parse', 'HEAD').stdout.strip()
        remoto = git(root, 'ls-remote', 'origin', 'refs/heads/' + branch, check=False).stdout.split()
        if not remoto or remoto[0] != head:
            erros.append('head_diferente_do_remoto')
    return erros


def _fechar(root, bid, now=None):
    root = Path(root)
    target = root / DIR / bid / 'verificado.json'
    if target.exists():
        require(verificado_e_enviado(root, bid), 'fechamento_existente_nao_confirmado')
        return load(target)
    regras = regras_do_bloco(root, bid)
    erros = verificar(root, bid, regras)
    if erros:
        raise Blocked('bloco_nao_fecha:' + ';'.join(erros))
    f = load(root / DIR / bid / 'fechamento.json')
    registro = {'schema': 'sc-bloco-verificado/1', 'id': bid, 'regras': regras,
                'manifesto_sha256': filehash((root / DIR / bid / 'manifesto.json').read_bytes()),
                'fechamento_sha256': filehash((root / DIR / bid / 'fechamento.json').read_bytes()),
                'head': git(root, 'rev-parse', 'HEAD').stdout.strip(), 'recibo_testes': f['recibo_testes'],
                'bloqueados': sorted(k for k, v in f['itens'].items() if v['estado'] != 'concluido'),
                'verificado_em': iso(now)}
    write_once(registro, target)
    return registro


@contextmanager
def copia_no_commit(root, commit):
    """Árvore limpa do repositório num commit, para conferir um bloco já fechado sem depender do
    que mudou depois. Removida ao sair."""
    tmp = Path(tempfile.mkdtemp(prefix='sc-bloco-'))
    alvo = tmp / 'arvore'
    try:
        git(root, 'worktree', 'add', '--detach', '--quiet', str(alvo), commit)
        yield alvo
    finally:
        git(root, 'worktree', 'remove', '--force', str(alvo), check=False)
        git(root, 'worktree', 'prune', check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def verified_record_rules(root, bid, raw, record):
    expected=regras_do_bloco(root,bid)
    if 'regras' in record:
        require(type(record['regras']) is int and record['regras']==expected,
                'verificado_regras_divergem_manifesto')
        return expected
    legacy=LEGACY_VERIFIED_RECORDS.get(bid)
    require(type(legacy) is dict and expected==2 and record.get('head')==legacy['head']
            and filehash(raw)==legacy['sha256'],'verificado_legado_nao_autorizado')
    return 1


def verificado_e_enviado(root, bid):
    """Bloco fechado: verificado.json íntegro, nada do bloco mudou depois do commit de fechamento,
    o registro está versionado e no remoto, e as regras da versão de fechamento passam numa cópia
    daquele commit. Testes e código novos não desfecham blocos antigos."""
    root = Path(root)
    p = root / DIR / bid / 'verificado.json'
    if not p.is_file():
        return False
    try:
        raw=p.read_bytes();v=strict_json(raw)
        base = {'schema', 'id', 'manifesto_sha256', 'fechamento_sha256', 'head', 'recibo_testes', 'bloqueados', 'verificado_em'}
        require(set(v) in (base, base | {'regras'}) and v['schema'] == 'sc-bloco-verificado/1' and v['id'] == bid, 'verificado_schema')
        regras = verified_record_rules(root,bid,raw,v)
        require(HEX40.fullmatch(v['head']) is not None and ancestral(root, v['head'], 'HEAD'), 'verificado_nao_ancestral')
        for name in ('manifesto', 'fechamento'):
            rel = '%s/%s/%s.json' % (DIR, bid, name)
            require(v[name + '_sha256'] == filehash((root / rel).read_bytes()), 'verificado_hash')
        rel = '%s/%s/verificado.json' % (DIR, bid)
        mudou = [x for x in git(root, 'diff', '--name-only', v['head'], 'HEAD', '--', '%s/%s/' % (DIR, bid)).stdout.split() if x != rel]
        require(not mudou, 'bloco_mudou_depois_do_fechamento')
        require(show(root, 'HEAD', rel) == p.read_bytes(), 'verificado_nao_versionado')
        f = load(root / DIR / bid / 'fechamento.json')
        require(v['recibo_testes'] == f['recibo_testes'], 'verificado_recibo')
        require(v['bloqueados'] == sorted(k for k, r in f['itens'].items() if r['estado'] != 'concluido'), 'verificado_bloqueados')
        added = git(root, 'log', '--diff-filter=A', '--format=%H', '--', rel).stdout.split()
        require(len(added) == 1, 'verificado_sem_origem_unica')
        mudou_no_registro = [x for x in git(root, 'diff', '--name-only', v['head'], added[0]).stdout.split() if x != rel]
        require(not mudou_no_registro, 'registro_do_fechamento_mudou_outros_arquivos')
        branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
        remoto = git(root, 'ls-remote', 'origin', 'refs/heads/' + branch, check=False).stdout.split()
        require(len(remoto) == 2 and HEX40.fullmatch(remoto[0]) is not None and
                remoto[1] == 'refs/heads/' + branch, 'verificado_remoto_invalido')
        observed = remoto[0]
        if git(root, 'cat-file', '-e', observed + '^{commit}', check=False).returncode != 0:
            fetched = git(root, 'fetch', 'origin', 'refs/heads/' + branch, check=False)
            require(fetched.returncode == 0, 'verificado_fetch_remoto_falhou')
        require(git(root, 'cat-file', '-e', observed + '^{commit}', check=False).returncode == 0
                and ancestral(root, added[0], observed), 'verificado_nao_enviado')
        with copia_no_commit(root, v['head']) as copia:
            require(not verificar(copia, bid, regras=regras, historico=True), 'provas_do_fechamento_invalidas')
        return True
    except (Blocked, OSError, ValueError, KeyError, TypeError, StopIteration, AttributeError, subprocess.SubprocessError):
        return False


@contextmanager
def repo_lock(root):
    d = Path(root) / DIR
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Blocked('outro_encadeador_em_execucao') from exc
        yield
    finally:
        os.close(fd)


def abrir(root, now=None):
    with repo_lock(root):
        return _abrir(root, now)


def fechar(root, bid, now=None):
    with repo_lock(root):
        return _fechar(root, bid, now)


# ---------------------------------------------------------------- encadeamento

def prompt_do_bloco(m, continuar, atraso=None):
    linhas = ['Sessão nova do bloco %s: %s.' % (m['id'], m['titulo']),
              *(['ATRASADO: o prazo do bloco era %s. Siga sem cortar controle; registre o atraso no fechamento.' % atraso] if atraso else []),
              'Continuação: a sessão anterior deste bloco terminou sem fechamento verificado. Leia blocos/%s/ e retome.' % m['id'] if continuar else
              'Abra lendo AGENTS.md, contexto/INICIAR_SESSAO.txt e blocos/%s/manifesto.json.' % m['id'],
              'Itens (todos obrigatórios; herdados primeiro):']
    for i in m['itens']:
        linhas.append('- %s%s: %s. Aceite: %s' % (i['id'], ' [herdado de %s, %dª vez]' % (i['herdado_de'], i['herdado_vezes']) if i['herdado_de'] else '', i['titulo'], i['aceite']))
    linhas += ['Regra de fechamento (código, não opinião): cada item termina "concluido" com evidência versionada, ou',
               '"bloqueado_dono"/"bloqueado_externo" com ação ou causa exatas E evidência. Nada fica "pendente" ou "parcial".',
               'Cada item tem ficha executável em blocos/fichas/<ID>.json: o que ela verifica é o que fecha o item. Antes de',
               'marcar "concluido", rode python3 -I -B controle/fichas.py conferir <ID> e negativos <ID>; os dois têm de passar.',
               'Não edite fichas, blocos/PLANO.json, chaves ou identidades: só o dono muda isso, por confirmação assinada no site',
               'do GitHub. Para sugerir mudança: python3 -I -B controle/blocos.py propor <ID> "motivo" e preencha "para".',
               'Achado novo deste bloco, seu ou dos revisores: corrigir aqui ou registrar bloqueio com causa e evidência.',
               'Ao terminar o trabalho: rode python3 -I -B controle/run_tests.py; commit e push; rode',
               'python3 -I -B controle/blocos.py pedir-revisao %s; commit e push do pedido.' % m['id'],
               'Revisões obrigatórias: Antigravity pela rota da VPS (recibo nativo em docs/evidencias/) e Claude pela tarefa',
               'agendada na nuvem (busque git fetch origin "refs/heads/claude/*:refs/remotes/origin/claude/*" e faça merge do',
               'recibo blocos/%s/revisoes/claude.json) ou pela rota da VPS. Registre todo achado deles no fechamento.' % m['id'],
               'Não encerre a sessão esperando revisão: depois do pedido, confira a cada 10 minutos, por até 3 horas, os ramos',
               'claude/* e a rota do Antigravity; enquanto espera, corrija o que já tiver achado.',
               'Ação que só o dono faz (confirmação pelo site, login, aprovação de escopo) não para a cadeia: registre o item como',
               '"bloqueado_dono" com a ação exata e evidência, e siga com os outros itens. Ele resolve quando acordar.',
               'controle/gate.py e controle/handoff.py podem mudar (fichas e revisões conferem). O juiz não: blocos.py, fichas.py,',
               'juiz_base.py, run_tests.py e o workflow só mudam com python3 -I -B controle/blocos.py ratificar e o clique do dono.',
               'Depois: grave fechamento.json; rode os testes de novo se o código mudou; commit e push; rode',
               'python3 -I -B controle/blocos.py fechar %s; commit e push de verificado.json; confira HEAD igual ao remoto.' % m['id'],
               'Não altere PLANO.json sem registro em PLANO_ALTERACOES.json nem manifestos já gravados.',
               'Permissão total dentro da VPS e do repositório. Limites duros em código continuam: teto de gasto e guard da',
               'nuvem, GPU só com GO, cegamento permanente, recurso externo intocável por esta frente, PARE do dono.']
    return '\n'.join(linhas) + '\n'


def publicar_aviso_pendente(root):
    """Retry durable notice delivery without rewriting its bytes or launching work."""
    root=Path(root);rel=DIR+'/AVISO_DONO.md'
    try:
        raw=jb.protected_bytes(root/rel,MAX_EVIDENCIA)
        if show(root,'HEAD',rel)!=raw:
            git(root,'add','--',rel)
            committed=git(root,'commit','-q','-m','Encadeamento parado: aviso ao dono','--',rel,check=False)
            require(committed.returncode==0,'aviso_commit_falhou')
        require(show(root,'HEAD',rel)==raw,'aviso_commit_diverge')
        head=git(root,'rev-parse','HEAD').stdout.strip()
        branch=git(root,'rev-parse','--abbrev-ref','HEAD').stdout.strip()
        require(branch and branch!='HEAD','aviso_ramo_ausente')
        ref='refs/heads/'+branch
        remote=git(root,'ls-remote','origin',ref,check=False)
        if remote.returncode==0 and remote.stdout.split()==[head,ref]:
            return True
        sent=git(root,'push','-q',check=False)
        require(sent.returncode==0,'aviso_push_falhou')
        remote=git(root,'ls-remote','origin',ref,check=False)
        return remote.returncode==0 and remote.stdout.split()==[head,ref]
    except (Blocked,OSError,ValueError,subprocess.SubprocessError):
        return False


def aviso(root, texto, git_enabled=True):
    """Persist the stop first; a failed push must not erase it or claim delivery."""
    root = Path(root)
    directory = root / DIR
    protected_path(directory, True)
    p = directory / 'AVISO_DONO.md'
    if p.exists() or p.is_symlink():
        protected_path(p)
    data = ('# Encadeamento de blocos parado\n\n%s\n\nPara retomar: resolva o motivo acima, grave a resolução em '
            'blocos/avisos/<sha256 deste arquivo>.json com evidência e só então apague este arquivo.\n' % texto).encode('utf-8')
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
                and not info.st_mode & 0o022, 'aviso_destino_inseguro')
        os.ftruncate(fd, 0)
        with os.fdopen(os.dup(fd), 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    finally:
        os.close(fd)
    if git_enabled and not publicar_aviso_pendente(root):
        return texto + ' Aviso preservado na VPS; o envio ao GitHub não foi confirmado.'
    return texto


def inicio_processo(pid):
    """Instante de início do processo no kernel (campo 22 de /proc/<pid>/stat), para não confundir
    um pid reaproveitado com a sessão lançada."""
    try:
        raw = Path('/proc/%d/stat' % pid).read_text()
        return raw[raw.rindex(')') + 2:].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def pid_vivo(pid, inicio=None):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        if Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()[0] == 'Z':
            return False   # terminou, só falta ser recolhido
    except (OSError, IndexError):
        pass
    return inicio is None or inicio_processo(pid) == inicio


def recursos_ok(root):
    livre = shutil.disk_usage(root).free
    require(livre >= DISCO_MINIMO, 'disco_insuficiente:%d' % livre)
    try:
        info = dict(l.split(':', 1) for l in Path('/proc/meminfo').read_text().splitlines() if ':' in l)
        disponivel = int(info['MemAvailable'].split()[0]) * 1024
    except (OSError, KeyError, ValueError):
        return
    require(disponivel >= MEMORIA_MINIMA, 'memoria_insuficiente:%d' % disponivel)


def prazo_do_bloco(root, bid):
    for b in load_plano(root)['blocos']:
        if b['id'] == bid:
            return b.get('prazo_utc')
    return None


def executor_isolado(root, identity):
    """Prepare a real UID/GID boundary; no root model process or inherited capabilities."""
    import pwd
    require(type(identity) is dict and set(identity) == {'uid','gid','home','setpriv_sha256'},
            'lancador_identidade_nao_qualificada')
    uid, gid = identity['uid'], identity['gid']
    require(type(uid) is int and uid > 0 and type(gid) is int and gid > 0,
            'lancador_executor_privilegiado')
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise Blocked('lancador_identidade_ausente') from exc
    require(account.pw_gid == gid, 'lancador_grupo_divergente')
    home = Path(identity['home'])
    require(home.is_absolute() and home.is_dir() and not home.is_symlink() and
            home.stat().st_uid == uid and home.stat().st_mode & 0o077 == 0,
            'lancador_home_nao_isolada')
    for ancestor in home.parents:
        require(not ancestor.is_symlink(), 'lancador_home_vinculada')
    binary = Path('/usr/bin/setpriv')
    require(binary.is_file() and binary.stat().st_uid == 0 and
            binary.stat().st_mode & 0o022 == 0 and
            filehash(binary.read_bytes()) == identity['setpriv_sha256'], 'lancador_setpriv_diverge')
    prefix = [str(binary), '--reuid='+str(uid), '--regid='+str(gid), '--clear-groups',
              '--no-new-privs', '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--']
    protected = ['/var/lib/claude-console-research','/var/lib/claude-mobile',
                 '/var/lib/antigravity-mobile', '/root/.ssh', '/root/.codex',
                 str(Path(root)/'.git/sc-auth'), str(Path(root)/'.git/sc-antigravity'),
                 str(Path(root)/'.git/sc-claude'), str(Path(root)/'.git/sc-blocos-state'),
                 *PROTECTED_REVIEW_ROOTS,
                 '.git/sc-auth','.git/sc-antigravity','.git/sc-claude','.git/sc-blocos-state',
                 '/proc/self/cwd/.git/sc-auth','/proc/self/cwd/.git/sc-antigravity',
                 '/proc/self/cwd/.git/sc-claude','/proc/self/cwd/.git/sc-blocos-state']
    control_files=[]
    if RUNTIME_INSTALLATION is not None:
        require(type(RUNTIME_CONTROL_PATHS) is tuple and len(RUNTIME_CONTROL_PATHS)==3
                and len(set(RUNTIME_CONTROL_PATHS))==3
                and RUNTIME_INSTALLATION['transport']['key'] in RUNTIME_CONTROL_PATHS,
                'lancador_contexto_protegido_ausente')
        for path in RUNTIME_CONTROL_PATHS:
            protected_path(path,False)
            control_files.append(path)
    probe = """
import os,json,sys
from pathlib import Path
paths=json.loads(sys.argv[1]);files=json.loads(sys.argv[2])
status=dict(x.split(':',1) for x in Path('/proc/self/status').read_text().splitlines() if ':' in x)
visible=[p for path in paths for p in (path,'/proc/1/root'+path)
         if any(os.access(p,mode) for mode in (os.R_OK,os.W_OK,os.X_OK))]
readable=[]
for path in files:
    for item in (path,'/proc/1/root'+path):
        try:
            fd=os.open(item,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
        except OSError:
            continue
        else:
            os.close(fd);readable.append(item)
print(json.dumps({'uid':os.geteuid(),'gid':os.getegid(),'groups':os.getgroups(),
    'caps':[status[k].strip() for k in ('CapEff','CapPrm','CapInh','CapBnd','CapAmb')],
    'nnp':status['NoNewPrivs'].strip(),'visible':visible,'readable_control_files':readable}))
"""
    check = subprocess.run(prefix+['/usr/bin/python3','-I','-B','-c',probe,json.dumps(protected),json.dumps(control_files)],
                           capture_output=True, timeout=10, cwd=home,
                           env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(home)})
    require(check.returncode == 0 and not check.stderr, 'lancador_isolamento_probe')
    result = strict_json(check.stdout)
    require(result.get('uid') == uid and result.get('gid') == gid and result.get('groups') == []
            and result.get('nnp') == '1' and result.get('visible') == []
            and result.get('readable_control_files') == [] and
            all(int(value,16) == 0 for value in result.get('caps',[])) and
            len(result.get('caps',[])) == 5, 'lancador_isolamento_nao_comprovado')
    directories=[str(Path(root)),str(Path(root)/'.git'),str(Path(root)/'.git/hooks')]
    files=[]
    if RUNTIME_INSTALLATION is not None:
        jb.installed_hashes(RUNTIME_INSTALLATION['installed'],RUNTIME_INSTALLATION['files'])
        directories.extend([RUNTIME_INSTALLATION['installed'],RUNTIME_INSTALLATION['state']])
        files.extend(str(Path(RUNTIME_INSTALLATION['installed'])/name) for name in sorted(jb.INSTALLATION_FILES))
    probe_write_denials(prefix,directories,files,str(home),
                        {'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(home)})
    return prefix


def cessoes_externas_ok(root, estado_dir=None, hist=None):
    """Procedural last act plus independent app observation; no claim of SSH revocation.
    A fresh release is bound to one exact pushed HEAD and consumed in the opening reservation.
    """
    root=Path(root)
    state=Path(estado_dir) if estado_dir is not None else Path(git(root,'rev-parse','--path-format=absolute','--git-common-dir').stdout.strip())/'sc-blocos-state'
    hist=hist if hist is not None else []
    prefix='docs/evidencias/posses/'
    records=sorted({p for p in git(root,'log','--diff-filter=A','--format=','--name-only','--',prefix).stdout.splitlines()
                    if p.startswith(prefix) and p.endswith('.json')})
    releases=[]
    for rel in records:
        raw=show(root,'HEAD',rel);require(raw is not None,'cessao_prova_posse_ausente')
        claim=strict_json(raw);bid=claim['bloco']
        require(verificado_e_enviado(root,bid),'cessao_bloco_nao_verificado')
        cpath='docs/evidencias/cessoes/'+bid+'.json'
        craw=show(root,'HEAD',cpath)
        require(craw is not None,'termino_sessao_externa_nao_qualificado:'+bid)
        require((root/cpath).read_bytes()==craw,'cessao_alterada')
        c=strict_json(craw)
        keys={'schema','bloco','sessao_nativa','turn_id','host_id','metodo','nao_retoma_escrita',
              'head_anterior','posse_sha256','fechamento_sha256','manifesto_sha256'}
        require(type(c) is dict and set(c)==keys and c['schema']=='sc-cessao-posse/2' and c['bloco']==bid and
                c['sessao_nativa']==claim['sessao_nativa'] and c['host_id']=='local' and
                type(c['turn_id']) is str and len(c['turn_id'])>=8 and
                c['metodo']=='ultimo_ato_contratual' and c['nao_retoma_escrita'] is True and
                c['posse_sha256']==filehash(raw) and
                c['manifesto_sha256']==filehash((root/DIR/bid/'manifesto.json').read_bytes()) and
                c['fechamento_sha256']==filehash((root/DIR/bid/'verificado.json').read_bytes()),'cessao_schema_ou_vinculo')
        commit=git(root,'log','-1','--format=%H','--',cpath).stdout.strip()
        require(HEX40.fullmatch(commit or '') and show(root,commit,cpath)==craw and
                git(root,'rev-parse',commit+'^').stdout.strip()==c['head_anterior'] and
                git(root,'diff-tree','--no-commit-id','--name-only','-r',commit).stdout.splitlines()==[cpath],
                'cessao_nao_e_commit_exclusivo')
        token={'bloco':bid,'cessao_commit':commit,'cessao_sha256':filehash(craw)}
        consumed=[h for h in hist if token in h.get('cessoes_externas',[])]
        if consumed:
            require(len(consumed)==1 and consumed[0].get('origin_commit')==commit and
                    (lancamento_reconhecido(consumed[0],consumed[0].get('bloco'),state) or
                      posse_cancelamento_ok(root,consumed[0],consumed[0].get('bloco'))),
                    'cessao_consumo_invalido')
            manifest=load_manifesto(root,consumed[0]['bloco'])
            require(manifest['origin_commit']==commit and ancestral(root,commit,'HEAD'),'cessao_consumo_sem_abertura')
            continue
        observation=state/'observacoes-externas'/(bid+'.json')
        require(observation.is_file() and not observation.is_symlink(),'cessao_observacao_ausente')
        for path in (observation,observation.parent,state):
            require(not path.is_symlink() and path.stat().st_uid==0 and path.stat().st_mode&0o077==0,
                    'cessao_observacao_desprotegida')
        o=strict_json(observation.read_bytes())
        require(type(o) is dict and set(o)=={'schema','source','host_id','thread_id','turn_id','turn_status',
                'thread_status','completed_at_unix','observed_at_unix','cessao_commit','cessao_sha256',
                'native_response_sha256','heartbeat_paused'} and o['schema']=='sc-observacao-turno/1' and
                o['source']=='codex_app.read_thread' and o['host_id']==c['host_id'] and
                o['thread_id']==c['sessao_nativa'] and o['turn_id']==c['turn_id'] and
                o['turn_status']=='completed' and o['thread_status']=='idle' and
                o['heartbeat_paused'] is True and o['cessao_commit']==commit and
                o['cessao_sha256']==filehash(craw) and HEX64.fullmatch(str(o['native_response_sha256'])),
                'cessao_observacao_diverge')
        committed_at=int(git(root,'show','-s','--format=%ct',commit).stdout.strip())
        require(all(type(o[k]) in (int,float) for k in ('completed_at_unix','observed_at_unix')) and
                committed_at<=o['completed_at_unix']<=o['observed_at_unix']<=time.time()+120,
                'cessao_observacao_anterior')
        require(not git(root,'status','--porcelain','-uall').stdout.strip() and
                git(root,'rev-parse','HEAD').stdout.strip()==commit,'cessao_head_mudou')
        branch=git(root,'rev-parse','--abbrev-ref','HEAD').stdout.strip()
        remote=git(root,'ls-remote','origin','refs/heads/'+branch).stdout.split()
        require(remote and remote[0]==commit,'cessao_nao_enviada')
        releases.append(token)
    return releases


def diretorio_runtime_ok(path):
    observed = path.lstat()
    require(stat.S_ISDIR(observed.st_mode) and not path.is_symlink() and
            observed.st_uid == 0 and not observed.st_mode & 0o022,
            'lancador_diretorio_inseguro')


def auxiliares_lancador_ok(binary, binary_sha256):
    """Read-only preflight. Never install a dependency or weaken the sandbox."""
    expected = CODEX_AUXILIARES.get(binary_sha256)
    require(expected is not None, 'lancador_auxiliares_sem_pin')
    try:
        binary = Path(binary).resolve(strict=True)
        diretorio_runtime_ok(binary.parent)
        helper = binary.parent / 'codex-code-mode-host'
        original, observed = binary.stat(), helper.lstat()
        require(stat.S_ISREG(observed.st_mode) and not helper.is_symlink(),
                'lancador_auxiliar_nao_regular')
        require(observed.st_uid == original.st_uid == 0 and
                observed.st_gid == original.st_gid and
                stat.S_IMODE(observed.st_mode) == stat.S_IMODE(original.st_mode) and
                not observed.st_mode & 0o022 and observed.st_mode & 0o111,
                'lancador_auxiliar_permissoes')
        require(filehash(helper.read_bytes()) == expected, 'lancador_auxiliar_mudou')
        sandbox = Path(BWRAP_PATH)
        require(sandbox.is_absolute(), 'lancador_bwrap_path')
        diretorio_runtime_ok(sandbox.parent)
        observed = sandbox.lstat()
        require(stat.S_ISREG(observed.st_mode) and not sandbox.is_symlink() and
                observed.st_uid == observed.st_gid == 0 and
                stat.S_IMODE(observed.st_mode) == 0o755, 'lancador_bwrap_permissoes')
        require(filehash(sandbox.read_bytes()) == BWRAP_SHA256, 'lancador_bwrap_mudou')
        # Same fixed PATH used by comando_unidade_sessao; reject an earlier override.
        import shutil
        selected = shutil.which('bwrap', path='/usr/local/bin:/usr/bin:/bin')
        require(selected is not None and Path(selected).resolve() == sandbox.resolve(),
                'lancador_bwrap_sombreado')
    except OSError as exc:
        raise Blocked('lancador_auxiliar_ausente_ou_ilegivel') from exc


def lancador_real(root, config):
    """Modo real (escolha assinada do dono em B03-05): o argv da sessão de bloco vem de
    lancador.argv_bloco na DT do lançador, fixada por hash na configuração; o binário é conferido
    por sha256 antes de cada lançamento. O prompt entra pela entrada padrão; nada passa por shell."""
    if not jb.isolated_test_namespace():
        require(RUNTIME_INSTALLATION is not None,'real_launcher_requires_installed_judge')
        jb.installed_hashes(RUNTIME_INSTALLATION['installed'],RUNTIME_INSTALLATION['files'])
    rel = config['dt']
    rel_ok(rel)
    raw = show(root, 'HEAD', rel)
    require(raw is not None, 'lancador_dt_nao_versionada')
    require((Path(root) / rel).read_bytes() == raw, 'lancador_dt_fora_do_commit')
    require(filehash(raw) == config['dt_sha256'], 'lancador_dt_mudou')
    dt = strict_json(raw)
    lanc = dt.get('lancador')
    require(isinstance(lanc, dict), 'lancador_dt_schema')
    argv, binario = lanc.get('argv_bloco'), lanc.get('binario')
    require(isinstance(argv, list) and argv and all(isinstance(x, str) and x and '\0' not in x for x in argv), 'lancador_argv_bloco')
    require(isinstance(binario, str) and Path(binario).is_absolute() and argv[0] == binario, 'lancador_binario')
    p = Path(binario)
    require(p.is_file() and os.access(p, os.X_OK), 'lancador_binario_ausente')
    require(filehash(p.resolve().read_bytes()) == lanc.get('binario_sha256'), 'lancador_binario_mudou')
    auxiliares_lancador_ok(p, lanc['binario_sha256'])
    # Pin the complete executable configuration through the already frozen ficha.
    ficha=show_json(root,'HEAD','blocos/fichas/B02-05.json')
    check=next((v for v in ficha.get('verificacoes',[]) if v.get('id')=='V1'),{})
    expected=check.get('campos',{})
    require(check.get('path')==rel and all(k in expected and canonical(expected[k])==canonical(dt.get(k))
            for k in ('estado','lancador','qualificacao')),'lancador_fora_da_ficha_congelada')
    def proof(path):
        raw=show(root,'HEAD',path)
        require(raw is not None and jb.protected_bytes(Path(root)/path,MAX_EVIDENCIA)==raw,
                'launcher_evidence_not_versioned')
        return raw
    expected_host=config.get('native_host_id')
    if RUNTIME_INSTALLATION is not None:
        require(expected_host==RUNTIME_INSTALLATION['native_host_id'],'installation_native_host_diverges')
    jb.launcher_qualification(dt,proof,
        lambda path,terms:confirmacao_dono_ok(root,path,terms,chaves_em_vigor(root)),expected_host)
    protected_path(root, True)
    require(Path(root).stat().st_mode & 0o077 == 0, 'lancador_validador_nao_privado')
    identity = lanc.get('executor')
    prefix = executor_isolado(root, identity)
    worker = Path(lanc.get('checkout_executor', ''))
    home = Path(identity['home'])
    require(worker.is_absolute() and home in worker.parents and worker != Path(root)
            and '..' not in worker.parts, 'lancador_checkout_executor')
    for parent in (worker, *worker.parents):
        require(not parent.is_symlink(), 'lancador_checkout_vinculado')
    require(worker.is_dir() and worker.stat().st_uid == identity['uid']
            and worker.stat().st_mode & 0o077 == 0, 'lancador_checkout_nao_isolado')
    # The executor must resolve/traverse its checkout after dropping privileges.
    # A swap after the preflight must not inherit a privileged parent's cwd.
    command = prefix + ['/usr/bin/env','-C',str(worker),'--'] + argv
    comando_unidade_sessao(command,'sc-bloco-b00-'+'0'*32+'.service',
                           config.get('max_segundos_sessao',21600),str(home))
    return command


def posse_externa(root, estado_dir):
    """Interlock sem prazo/PID: preserva a prova e bloqueia enquanto o bloco não fecha.
    Só verificado_e_enviado torna a posse histórica; os demais gates ainda decidem lançamento.
    """
    prefix = 'docs/evidencias/posses/'
    added = git(root, 'log', '--diff-filter=A', '--format=', '--name-only', '--', prefix).stdout.splitlines()
    records = sorted({p for p in added if p.startswith(prefix) and p.endswith('.json')})
    local = Path(estado_dir) / 'posse-externa.json'
    if not records and not local.exists() and not local.is_symlink():
        return None
    require(records, 'posse_externa_reconciliacao_necessaria')
    active, proofs = [], []
    for rel in records:
        raw = show(root, 'HEAD', rel)
        require(raw is not None and (Path(root) / rel).read_bytes() == raw,
                'posse_externa_evidencia_ausente_ou_alterada')
        claim = strict_json(raw)
        require(type(claim) is dict and claim.get('schema') == 'sc-posse-externa/1' and
                claim.get('repositorio') == str(Path(root).resolve()) and
                isinstance(claim.get('bloco'), str) and fx.ID_BLOCO.fullmatch(claim['bloco']) and
                isinstance(claim.get('sessao_nativa'), str) and claim['sessao_nativa'] and
                claim.get('executor') == '<executor-privado>', 'posse_externa_schema')
        manifest = Path(root) / DIR / claim['bloco'] / 'manifesto.json'
        require(manifest.is_file() and filehash(manifest.read_bytes()) == claim.get('manifesto_sha256'),
                'posse_externa_manifesto_divergente')
        proofs.append(raw)
        if not verificado_e_enviado(root, claim['bloco']):
            closure = DIR + '/' + claim['bloco'] + '/verificado.json'
            recorded = git(root,'log','--diff-filter=A','--format=%H','--',closure).stdout.splitlines()
            if recorded:
                reason='posse_fechamento_historico_divergente:'+claim['bloco']
                require(not git(root,'diff','--name-only','HEAD','--',DIR+'/'+claim['bloco']).stdout.strip(),reason)
                try:
                    current=jb.protected_bytes(Path(root)/closure,MAX_EVIDENCIA)
                except (Blocked,OSError,ValueError):
                    raise Blocked(reason)
                require(current==show(root,'HEAD',closure),reason)
                # A later change cannot turn a historical closure back into a silent
                # active claim. The first closure commit may still be awaiting push.
                latest = git(root,'log','-1','--format=%H','--',DIR+'/'+claim['bloco']).stdout.strip()
                require(len(recorded)==1 and latest==recorded[0],
                        'posse_fechamento_historico_divergente:'+claim['bloco'])
            active.append((claim, raw))
    require(local.is_file() and not local.is_symlink() and local.read_bytes() in proofs,
            'posse_externa_registro_ausente_ou_alterado')
    require(len(active) <= 1, 'posse_externa_reconciliacao_necessaria')
    if active:
        require(local.read_bytes() == active[0][1], 'posse_externa_registro_ausente_ou_alterado')
        return active[0][0]
    return None


def cancelamento_pre_efeito_ok(row):
    return (row.get('estado')=='cancelado_sem_lancamento' and
            row.get('fase')=='antes_popen' and row.get('nenhum_processo_criado') is True and
            row.get('pid') is None and row.get('inicio') is None and 'encerramento' not in row and
            row.get('modo') in ('real','ensaio') and type(row.get('motivo')) is str and
            bool(row['motivo']))


def cancelar_pre_efeito(root, row, reason):
    row.update(estado='cancelado_sem_lancamento',fase='antes_popen',motivo=reason,
               nenhum_processo_criado=True,pid=None,inicio=None)
    manifest=Path(root)/DIR/row['bloco']/'manifesto.json'
    if manifest.is_file():
        row['manifesto_sha256']=filehash(manifest.read_bytes())
        row['origin_commit']=strict_json(manifest.read_bytes())['origin_commit']
        row['abertura_commit']=git(root,'rev-parse','HEAD').stdout.strip()
    elif 'cessoes_externas' in row:
        row['cessoes_nao_consumidas']=row.pop('cessoes_externas')


def posse_cancelamento_ok(root,row,bid):
    manifest=Path(root)/DIR/bid/'manifesto.json'
    return (cancelamento_pre_efeito_ok(row) and row.get('bloco')==bid and manifest.is_file() and
            row.get('manifesto_sha256')==filehash(manifest.read_bytes()) and
            row.get('origin_commit')==strict_json(manifest.read_bytes()).get('origin_commit') and
            HEX40.fullmatch(str(row.get('abertura_commit',''))) and
            ancestral(root,row['abertura_commit'],'HEAD') and
            show(root,row['abertura_commit'],str(manifest.relative_to(root)))==manifest.read_bytes())


def lancamento_reconhecido(row, bid, estado_dir):
    if not (row.get('bloco') == bid and row.get('estado') == 'lancado' and
            type(row.get('pid')) is int and row['pid'] > 0 and
            isinstance(row.get('inicio'), str) and row['inicio'].isdigit() and
            isinstance(row.get('prompt_sha256'), str) and
            re.fullmatch(r'[0-9a-f]{64}', row['prompt_sha256']) and
            isinstance(row.get('log'), str)):
        return False
    log = Path(row['log'])
    return log.parent == Path(estado_dir) and log.is_file() and not log.is_symlink()


def comando_unidade_sessao(argv, unit, seconds, home):
    require(type(unit) is str and SESSION_UNIT.fullmatch(unit), 'sessao_unidade_invalida')
    require(type(seconds) is int and 1 <= seconds <= 21600, 'config_timeout')
    require(type(argv) is list and argv and all(type(a) is str and a and
            not any(c in '$%' or ord(c)<32 or ord(c)==127 for c in a) for a in argv),
            'sessao_argumento_expansivel')
    require(type(home) is str and Path(home).is_absolute() and
            not any(c in '$%' or ord(c)<32 or ord(c)==127 for c in home), 'sessao_home_invalido')
    # No RemainAfterExit: an exited main process must stop its remaining cgroup.
    properties = ('Type=exec', 'WorkingDirectory=/', 'RuntimeMaxSec='+str(seconds),
                  'TimeoutStartSec=10', 'TimeoutStopSec=5', 'KillMode=control-group',
                  'SendSIGKILL=yes', 'Restart=no', 'RemainAfterExit=no',
                  'NoNewPrivileges=yes', 'ProtectControlGroups=yes', 'Delegate=no',
                  'CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_SETPCAP',
                  'AmbientCapabilities=')
    command = ['/usr/bin/systemd-run', '--quiet', '--wait', '--pipe', '--no-ask-password',
               '--description=Pesquisa bloco supervisionado', '--unit='+unit]
    for value in properties:
        command += ['--property', value]
    # The manager's environment cannot become the executor's credentials.
    return command + ['--', '/usr/bin/env', '-i', 'PATH=/usr/local/bin:/usr/bin:/bin',
                      'LANG=C.UTF-8', 'HOME='+home] + argv


def estado_unidade_sessao(unit):
    require(type(unit) is str and SESSION_UNIT.fullmatch(unit), 'sessao_unidade_invalida')
    keys = {'Id','LoadState','ActiveState','MainPID','ControlGroup'}
    result = subprocess.run(['/usr/bin/systemctl','show',unit,
        '--property=Id,LoadState,ActiveState,MainPID,ControlGroup'],
        capture_output=True,text=True,timeout=10,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    require(result.returncode == 0 and not result.stderr and len(result.stdout) <= 4096,
            'sessao_consulta_inconclusiva')
    rows = [line.split('=',1) for line in result.stdout.splitlines()]
    require(len(rows) == len(keys) and all(len(row)==2 for row in rows),
            'sessao_propriedades_invalidas')
    value = dict(rows)
    require(len(value)==len(keys) and set(value)==keys and value['Id']==unit and
            value['LoadState'] in ('loaded','not-found') and
            value['ActiveState'] in ('active','activating','deactivating','inactive','failed','reloading') and
            value['MainPID'].isdigit() and value['ControlGroup'] in ('','/system.slice/'+unit),
            'sessao_propriedades_invalidas')
    return value


def parada_sessao_comprovada(value, unit, wait_rc):
    if type(value) is not dict or set(value) != {'Id','LoadState','ActiveState','MainPID','ControlGroup'}:
        return False
    if value['Id'] != unit or value['MainPID'] != '0' or value['ControlGroup'] != '' or type(wait_rc) is not int:
        return False
    if value['LoadState'] == 'not-found':
        # Absence is only meaningful after this exact native --wait succeeded.
        return wait_rc == 0 and value['ActiveState'] == 'inactive'
    return value['LoadState'] == 'loaded' and value['ActiveState'] in ('inactive','failed')


def encerramento_sessao_ok(row):
    proof = row.get('encerramento')
    if type(proof) is not dict or set(proof) != {'schema','unidade','wait_rc','parada','sucesso'}:
        return False
    return (proof['schema']=='sc-sessao-encerrada/1' and proof['unidade']==row.get('unidade') and
            type(proof['sucesso']) is bool and proof['sucesso'] and type(proof['parada']) is dict and
            type(proof['wait_rc']) is int and proof['wait_rc']==0 and
            proof['parada'].get('ActiveState')=='inactive' and
            parada_sessao_comprovada(proof['parada'],row['unidade'],proof['wait_rc']))


def observar_atividade_sessao(row):
    """A successful command event proves activity, never a useful commit or acceptance.

    Unknown/missing/truncated output fails closed. Agent prose is not tool evidence.
    The protected JSONL is retained independently from the native cgroup receipt.
    """
    result = {'schema':'sc-atividade-sessao/1', 'log_sha256':None,
              'comandos_concluidos':0, 'turno_concluido':False, 'erros_recuperaveis':0,
              'atividade_ferramenta_comprovada':False, 'progresso_util':'nao_avaliado',
              'motivo':'log_ausente_ou_invalido'}
    try:
        path = Path(row['log'])
        require(path.is_absolute(), 'sessao_log_nao_absoluto')
        raw = jb.protected_bytes(path, MAX_EVIDENCIA)
        result['log_sha256'] = filehash(raw)
        events = [strict_json(line) for line in raw.splitlines() if line.strip()]
        require(events and all(type(v) is dict for v in events), 'sessao_eventos_invalidos')
        require(sum(v.get('type') == 'thread.started' for v in events) == 1 and
                sum(v.get('type') == 'turn.started' for v in events) == 1 and
                sum(v.get('type') == 'turn.completed' for v in events) == 1 and
                events[0].get('type') == 'thread.started' and
                events[1].get('type') == 'turn.started' and
                events[-1].get('type') == 'turn.completed' and
                not any(v.get('type') == 'turn.failed' for v in events),
                'sessao_turno_nao_concluido')
        result['turno_concluido'] = True
        result['erros_recuperaveis'] = sum(v.get('type') == 'error' for v in events)
        ids = set()
        for event in events:
            if event.get('type') != 'item.completed':
                continue
            item = event.get('item')
            require(type(item) is dict and type(item.get('id')) is str and
                    item['id'] and item['id'] not in ids, 'sessao_item_duplicado_ou_invalido')
            ids.add(item['id'])
            if item.get('type') == 'command_execution':
                require(type(item.get('exit_code')) is int and
                        item.get('status') in ('completed','failed') and type(item.get('command')) is str and
                        bool(item['command']), 'sessao_comando_invalido')
                if item['exit_code'] == 0 and item['status'] == 'completed':
                    result['comandos_concluidos'] += 1
        result['atividade_ferramenta_comprovada'] = result['comandos_concluidos'] > 0
        result['motivo'] = ('atividade_de_ferramenta_observada' if
            result['atividade_ferramenta_comprovada'] else 'sem_evento_de_ferramenta_concluida')
    except (OSError, ValueError, KeyError, TypeError, IndexError, Blocked):
        result['atividade_ferramenta_comprovada'] = False
        result['motivo'] = 'log_ausente_ou_invalido'
    return result


def atividade_sessao_ok(row):
    value = row.get('atividade')
    return (type(value) is dict and value.get('schema') == 'sc-atividade-sessao/1' and
            type(value.get('comandos_concluidos')) is int and value['comandos_concluidos'] > 0 and
            value.get('turno_concluido') is True and
            value.get('atividade_ferramenta_comprovada') is True and
            value.get('progresso_util') == 'nao_avaliado' and
            type(value.get('log_sha256')) is str and HEX64.fullmatch(value['log_sha256']) is not None)


def falha_auxiliar_sem_trabalho(raw):
    """Only the known CLI 0.166.0 missing-helper shape, never arbitrary stderr."""
    events = []
    native_error = re.compile(
        rb'20[0-9]{2}-[0-9T:.Z-]+ ERROR codex_core::tools::router: error=failed to spawn '
        rb'code-mode host /usr/local/lib/sc-pesquisa/codex-code-mode-host: '
        rb'No such file or directory \(os error 2\)')
    for line in raw.splitlines():
        if native_error.fullmatch(line):
            continue
        require(line.strip(), 'reconciliacao_log_invalido')
        events.append(strict_json(line))
    require(len(events) >= 4 and all(type(v) is dict for v in events),
            'reconciliacao_log_invalido')
    require(events[0].get('type') == 'thread.started' and
            events[-1].get('type') == 'turn.completed' and
            all(sum(v.get('type') == t for v in events) == 1
                for t in ('thread.started','turn.started','turn.completed')),
            'reconciliacao_turno_invalido')
    errors, ids = 0, set()
    for event in events[1:-1]:
        if event.get('type') == 'turn.started':
            continue
        require(event.get('type') == 'item.completed', 'reconciliacao_evento_nao_elegivel')
        item = event.get('item')
        require(type(item) is dict and type(item.get('id')) is str and
                item['id'] and item['id'] not in ids, 'reconciliacao_item_invalido')
        ids.add(item['id'])
        require(item.get('type') in ('agent_message','error'),
                'reconciliacao_com_ferramenta')
        if item['type'] == 'error':
            message = item.get('message')
            require(type(message) is str and message.startswith(
                'Code Mode is unavailable because failed to spawn code-mode host '
                '/usr/local/lib/sc-pesquisa/codex-code-mode-host: host executable was not found.'),
                'reconciliacao_causa_diverge')
            errors += 1
    require(errors == 1, 'reconciliacao_causa_diverge')
    return {'comandos_concluidos':0, 'turno_concluido':True}


def arquivo_reconciliacao_versionado(root, ref):
    require(type(ref) is dict and set(ref) == {'path','sha256'} and
            type(ref['sha256']) is str and HEX64.fullmatch(ref['sha256']),
            'reconciliacao_referencia_invalida')
    rel_ok(ref['path'])
    raw = show(root, 'HEAD', ref['path'])
    require(raw is not None and filehash(raw) == ref['sha256'] and
            jb.protected_bytes(Path(root)/ref['path'], MAX_EVIDENCIA) == raw,
            'reconciliacao_evidencia_diverge')
    return raw


def reconciliacoes_sessoes_ok(root, hist):
    """Read-only, owner-ratified exemption of exactly the two B05 infrastructure failures.

    The original history, native closure and logs are never edited. Reconciliation
    is not work, acceptance, a successful attempt, or an extension of MAX_TENTATIVAS.
    """
    prefix = 'blocos/B05/reconciliacoes/'
    if not (Path(root)/prefix).exists():
        return set()
    names = git(root,'ls-tree','--name-only','HEAD',prefix).stdout.splitlines()
    require(0 < len(names) <= 2, 'reconciliacao_limite')
    ever = set(git(root,'log','--format=','--name-only','--diff-filter=A','HEAD','--',prefix).stdout.split())
    require(ever == set(names) and len(ever) <= 2, 'reconciliacao_historico_diverge')
    accepted, batch = set(), None
    for rel in names:
        unit = Path(rel).name.removesuffix('.json')
        require(rel == prefix+unit+'.json' and unit in RECONCILIACAO_B05_LOGS,
                'reconciliacao_unidade_nao_elegivel')
        changes = git(root,'log','--format=%H','HEAD','--',rel).stdout.split()
        require(len(changes) == 1, 'reconciliacao_nao_append_only')
        raw = show(root,'HEAD',rel)
        require(raw is not None and jb.protected_bytes(Path(root)/rel,MAX_EVIDENCIA) == raw,
                'reconciliacao_fora_do_commit')
        record = strict_json(raw)
        require(type(record) is dict and set(record) == {
            'schema','bloco','unidade','causa','log_sha256','encerramento_sha256',
            'diagnostico_commit','reparo_commit','qualificacao','confirmacao_dono'},
            'reconciliacao_schema')
        require(record['schema'] == 'sc-reconciliacao-sessao/1' and record['bloco'] == 'B05' and
                record['unidade'] == unit and
                record['causa'] == 'runtime_incompleto_auxiliar_ausente',
                'reconciliacao_schema')
        rows = [r for r in hist if r.get('unidade') == unit]
        require(len(rows) == 1, 'reconciliacao_reserva_diverge')
        row = rows[0]
        require(row.get('bloco') == 'B05' and row.get('modo') == 'real' and
                row.get('estado') == 'lancado' and encerramento_sessao_ok(row) and
                digest(row['encerramento']) == record['encerramento_sha256'],
                'reconciliacao_encerramento_diverge')
        log = jb.protected_bytes(Path(row['log']), MAX_EVIDENCIA)
        require(filehash(log) == record['log_sha256'] == RECONCILIACAO_B05_LOGS[unit],
                'reconciliacao_log_diverge')
        falha_auxiliar_sem_trabalho(log)  # Recompute; never accept asserted zero-work fields.
        for key in ('diagnostico_commit','reparo_commit'):
            value = record[key]
            require(type(value) is str and HEX40.fullmatch(value) and ancestral(root,value,'HEAD'),
                    'reconciliacao_commit_invalido')
        qualification = strict_json(arquivo_reconciliacao_versionado(root, record['qualificacao']))
        require(type(qualification) is dict and set(qualification) == {
            'schema','qualificado_em_unix','reparo_commit','codex_sha256','helper_sha256',
            'bwrap_path','bwrap_sha256','log','processo'}, 'reconciliacao_qualificacao_schema')
        require(qualification['schema'] == 'sc-qualificacao-runtime/1' and
                type(qualification['qualificado_em_unix']) in (int,float) and
                row['em'] < qualification['qualificado_em_unix'] <= time.time() and
                qualification['reparo_commit'] == record['reparo_commit'] and
                type(qualification['codex_sha256']) is str and
                qualification['codex_sha256'] in CODEX_AUXILIARES and
                CODEX_AUXILIARES[qualification['codex_sha256']] == qualification['helper_sha256'] and
                qualification['bwrap_path'] == BWRAP_PATH and qualification['bwrap_sha256'] == BWRAP_SHA256,
                'reconciliacao_qualificacao_diverge')
        arquivo_reconciliacao_versionado(root, qualification['log'])
        activity = observar_atividade_sessao({'log':str(Path(root)/qualification['log']['path'])})
        process = strict_json(arquivo_reconciliacao_versionado(root, qualification['processo']))
        require(type(process) is dict and atividade_sessao_ok({'atividade':activity}) and
                activity['comandos_concluidos'] == 1 and process.get('schema') == 'sc-teste-runtime-resultado/1' and
                type(process.get('exit_code')) is int and process['exit_code'] == 0 and
                process.get('log_sha256') == activity['log_sha256'] and
                process.get('execucao_ferramenta_comprovada') is True,
                'reconciliacao_runtime_nao_qualificado')
        observed = process.get('execucoes_kernel_observadas')
        require(type(observed) is list and len(observed) == 1 and
                type(observed[0]) is dict and observed[0].get('uid') == ['991']*4 and
                observed[0].get('gid') == ['991']*4, 'reconciliacao_identidade_diverge')
        # One batch for this cause, not two independent retry allowances.
        identity = (record['causa'],record['diagnostico_commit'],record['reparo_commit'],
                    digest(record['qualificacao']),record['confirmacao_dono'])
        require(batch is None or batch == identity, 'reconciliacao_lote_diverge')
        batch = identity
        confirmacao_dono_ok(root,record['confirmacao_dono'],
            ['RECONCILIAR B05 '+unit+' '+filehash(raw)],chaves_em_vigor(root))
        accepted.add(unit)
    return accepted


def tentativas_do_bloco(hist, bid, reconciliadas, opening=None):
    return sum(1 for row in hist if row['bloco'] == bid and row is not opening and
               not cancelamento_pre_efeito_ok(row) and row.get('unidade') not in reconciliadas)


def barreira_sessoes_reais(root, hist, git_enabled, modo='real'):
    reconciliadas = reconciliacoes_sessoes_ok(root, hist)
    for row in hist:
        if row.get('estado')=='cancelado_sem_lancamento':
            require(cancelamento_pre_efeito_ok(row),'cancelamento_pre_efeito_invalido')
            continue
        if row.get('modo') != 'real' and 'unidade' not in row:
            # Older real and rehearsal writers emitted the same PID-only shape.
            # A dead parent cannot prove that its descendants have terminated.
            # Do not infer a migration from today's configuration or a log file.
            if modo=='real' and row.get('modo')!='ensaio':
                return {'acao':'parado','motivo':aviso(root,
                    'Histórico legado sem identidade nativa da árvore. Preserve os registros e reconcilie a execução antiga antes de habilitar qualquer lançamento real.',git_enabled)}
            continue
        unit = row.get('unidade')
        require(type(unit) is str and SESSION_UNIT.fullmatch(unit), 'sessao_unidade_invalida')
        if 'encerramento' in row:
            if unit in reconciliadas or (encerramento_sessao_ok(row) and atividade_sessao_ok(row)):
                continue
            return {'acao':'parado','motivo':aviso(root,
                'Sessão real sem encerramento e atividade comprovados. Exit zero e recibos antigos não comprovam trabalho. Preserve o histórico e reconcilie antes de novo lançamento.',git_enabled)}
        supervisor = row.get('supervisor_pid')
        start = row.get('supervisor_inicio')
        if (type(supervisor) is int and supervisor > 0 and type(start) is str and
                start.isdigit() and pid_vivo(supervisor,start)):
            return {'acao':'nada','motivo':'supervisor_da_sessao_em_andamento'}
        state = estado_unidade_sessao(unit)
        if state['LoadState']=='loaded' and (state['MainPID']!='0' or state['ControlGroup'] or
                state['ActiveState'] in ('active','activating','deactivating','reloading')):
            return {'acao':'nada','motivo':'arvore_da_sessao_em_andamento'}
        return {'acao':'parado','motivo':aviso(root,
            'Supervisor encerrado sem recibo durável da árvore. Ausência de unidade ou de PID não comprova conclusão; reconciliar a reserva antes de novo lançamento.',git_enabled)}
    return None


def supervisionar_sessao_real(root, config, result, git_enabled=True):
    unit = result.get('unidade')
    require(unit in REAL_PENDING, 'sessao_supervisor_sem_processo')
    proc, path, expected = REAL_PENDING.pop(unit)
    reason = None
    try:
        deadline = time.monotonic()+expected['limite_segundos']+20
        while proc.poll() is None:
            if (Path(root)/DIR/'PARE').exists():
                reason = 'parada_solicitada_pelo_dono'
                break
            if time.monotonic() >= deadline:
                reason = 'supervisao_excedeu_prazo'
                break
            time.sleep(.2)
        if reason:
            subprocess.run(['/usr/bin/systemctl','stop',unit],capture_output=True,
                timeout=15,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
        wait_rc = proc.wait(timeout=10)
        state = estado_unidade_sessao(unit)
        require(parada_sessao_comprovada(state,unit,wait_rc), 'sessao_parada_nao_comprovada')
        success = reason is None and wait_rc==0 and state['ActiveState']=='inactive'
        proof = {'schema':'sc-sessao-encerrada/1','unidade':unit,'wait_rc':wait_rc,
                 'parada':state,'sucesso':success}
        # 'sucesso' in the v1 native receipt means process completion only.
        activity = observar_atividade_sessao(expected)
        # No repository/state lock is held while the model executes. Persist the
        # completion under both locks before any later tick can launch again.
        with repo_lock(root):
            fd = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                hist = strict_json(jb.protected_bytes(path,1024*1024))
                matches = [h for h in hist if h.get('unidade')==unit]
                require(len(matches)==1 and matches[0]==expected,'sessao_reserva_mudou')
                matches[0]['encerramento']=proof
                matches[0]['atividade']=activity
                salvar_historico(path,hist)
            finally:
                os.close(fd)
        if not success:
            return {'acao':'parado','motivo':aviso(root,
                'Sessão real encerrada com falha ou parada solicitada. Recibo preservado; reconciliar antes de continuar.',git_enabled)}
        if not activity['atividade_ferramenta_comprovada']:
            return {'acao':'parado','motivo':aviso(root,
                'Processo saiu com zero, mas não há atividade de ferramenta comprovada. Recibos e log preservados; reconciliar antes de continuar.',git_enabled)}
        return {'acao':'sessao_encerrada','motivo':expected['bloco'],'unidade':unit}
    except Exception:
        # A native runtime deadline remains installed even if this observer dies.
        # No uncertain observation is converted into a completed reservation.
        return {'acao':'parado','motivo':aviso(root,
            'Supervisão real sem conclusão comprovada. Preserve unidade, reserva e registros; reconcilie antes de novo lançamento.',git_enabled)}


def _encadear(root, config, now=None, git_enabled=True):
    """Um passo do encadeamento. Devolve {'acao': ..., 'motivo': ...}. Nunca lança duas sessões."""
    root = Path(root)
    now = agora(now)
    validar_config(config)
    if config['modo'] == 'inativo':
        return {'acao': 'nada', 'motivo': 'lancador_nao_instalado'}
    argv_real = None
    if config['modo'] == 'ensaio':
        url = git(root, 'remote', 'get-url', 'origin', check=False).stdout.strip()
        require(url and '://' not in url and '@' not in url and Path(url).is_absolute(), 'ensaio_em_repositorio_real')
    stop=barreira_pare_atual(root)
    if stop is not None:
        if (root / DIR / 'AVISO_DONO.md').exists():
            # A parada fresca precede ate a publicacao do aviso; preserve a pendencia.
            stop.update(aviso_pendente=True, aviso_entregue=False)
        return stop
    estado_dir = Path(config['estado_dir'])
    canonical_state = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()) / 'sc-blocos-state'
    require(estado_dir == canonical_state and not estado_dir.is_symlink(), 'estado_nao_canonico')
    estado_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = os.open(estado_dir, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return {'acao': 'nada', 'motivo': 'outro_encadeador_em_execucao'}
    try:
        if (root / DIR / 'PARE').exists():
            return {'acao': 'nada', 'motivo': 'parado_pelo_dono'}
        if (root / DIR / 'AVISO_DONO.md').exists():
            delivered=publicar_aviso_pendente(root) if git_enabled else False
            return {'acao': 'nada', 'motivo': 'aviso_ao_dono_pendente', 'aviso_entregue':delivered}
        try:
            claim = posse_externa(root, estado_dir)
        except (Blocked, OSError, ValueError, KeyError, TypeError) as exc:
            return {'acao':'parado','motivo':aviso(root, 'Posse externa sem prova íntegra: ' + str(exc), git_enabled)}
        if claim is not None:
            return {'acao': 'nada', 'motivo': 'sessao_externa_em_andamento:' + claim['bloco']}
        hist_path = estado_dir / 'lancamentos.json'
        hist = json.loads(hist_path.read_text()) if hist_path.exists() else []
        require(isinstance(hist, list) and all(isinstance(h, dict) for h in hist), 'historico_lancamentos_invalido')
        if [h for h in hist if h.get('estado') in ('abrindo', 'reservado')]:
            return {'acao': 'parado', 'motivo': aviso(root, 'Reserva sem resultado confirmado; reconciliar processo e recibo antes de qualquer nova sessão.', git_enabled)}
        real_barrier = barreira_sessoes_reais(root,hist,git_enabled,config['modo'])
        if real_barrier is not None:
            return real_barrier
        vivos = [h for h in hist if 'unidade' not in h and h.get('pid') and pid_vivo(h['pid'], h.get('inicio'))]
        if vivos:
            excedeu = [h for h in vivos if now - h['em'] > config.get('max_segundos_sessao', 21600)]
            if excedeu:
                return {'acao': 'parado', 'motivo': aviso(root, 'A sessão do bloco %s passou do tempo máximo e continua viva. Encerre-a e '
                                                          'reconcilie o estado antes de qualquer sessão nova.' % excedeu[-1]['bloco'], git_enabled)}
            return {'acao': 'nada', 'motivo': 'sessao_em_andamento:' + vivos[-1]['bloco']}
        if git(root, 'status', '--porcelain', '-uall').stdout.strip():
            return {'acao':'parado','motivo':aviso(
                root,'Árvore com alterações antes do encadeamento. Preserve o trabalho, confira o diff, '
                'conclua os commits autorizados e reconcilie a reserva antes de retomar.',git_enabled)}
        if config['modo'] == 'real':
            try:
                argv_real = lancador_real(root, config)
            except (Blocked, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
                return {'acao':'parado','motivo':aviso(
                    root,'Pré-verificação do lançador real recusada: '+str(exc)+'. '
                    'Corrija a qualificação ou a instalação indicada e refaça a sonda antes de retomar.',git_enabled)}
        if sum(1 for h in hist if now - h['em'] < 86400 and not cancelamento_pre_efeito_ok(h)) >= min(config.get('max_lancamentos_dia', MAX_LANCAMENTOS_DIA), MAX_LANCAMENTOS_DIA):
            return {'acao': 'nada', 'motivo': 'limite_diario_de_sessoes'}
        cessoes=[]
        if argv_real is not None:
            try:
                cessoes=cessoes_externas_ok(root,estado_dir,hist)
            except (Blocked,OSError,ValueError,KeyError,TypeError) as exc:
                return {'acao':'parado','motivo':aviso(root,'Cessão externa não comprovada: '+str(exc),git_enabled)}
        abertos = blocos_abertos(root)
        if abertos and not verificado_e_enviado(root, abertos[-1]) and not any(lancamento_reconhecido(h, abertos[-1], estado_dir) or posse_cancelamento_ok(root,h,abertos[-1]) for h in hist):
            return {'acao': 'parado', 'motivo': aviso(root, 'bloco_aberto_sem_posse_reconciliada:' + abertos[-1] + '; reconciliar a reserva e provar ausencia de processo antes de retomar.', git_enabled)}
        try:
            recursos_ok(root)
        except Blocked as e:
            return {'acao': 'parado', 'motivo': aviso(root, 'Recursos da VPS abaixo do mínimo para abrir sessão: `%s`.' % e, git_enabled)}
        opening = None
        continuar = False
        if not abertos or verificado_e_enviado(root, abertos[-1]):
            try:
                origin = git(root, 'rev-parse', 'HEAD').stdout.strip()
                require(all(t['cessao_commit']==origin for t in cessoes),'cessao_head_mudou_antes_reserva')
                planned, _, _ = derivar_manifesto(root, origin)
                opening = {'bloco': planned['id'], 'origin_commit': origin, 'em': now,
                           'estado': 'abrindo', 'executor': 'encadeador', 'pid': None,'modo':config['modo']}
                if cessoes:opening['cessoes_externas']=cessoes
                stop=barreira_pare_atual(root)
                if stop is not None:return stop
                hist.append(opening)
                salvar_historico(hist_path, hist)
                require(git(root,'rev-parse','HEAD').stdout.strip()==origin,'head_mudou_antes_abertura')
                m = _abrir(root, now)
                require(m['origin_commit']==origin and git(root,'rev-parse','HEAD').stdout.strip()==origin,'abertura_origin_diverge')
            except Blocked as e:
                if str(e)=='parado_pelo_dono' or str(e).startswith(('pare_remoto_', 'git_failed:')):
                    if opening is not None and opening in hist:
                        cancelar_pre_efeito(root,opening,str(e))
                        salvar_historico(hist_path,hist)
                    return {'acao':'parado','motivo':str(e)}
                if str(e) == 'plano_concluido':
                    return {'acao': 'nada', 'motivo': 'plano_concluido'}
                return {'acao': 'parado', 'motivo': aviso(root, 'Não foi possível abrir o próximo bloco: `%s`.' % e, git_enabled)}
            if git_enabled:
                git(root, 'add', '--', '%s/%s/manifesto.json' % (DIR, m['id']))
                git(root, 'commit', '-q', '-m', 'Abre o bloco %s por encadeamento automatico' % m['id'])
                git(root, 'push', '-q')
        else:
            m = load_manifesto(root, abertos[-1])
            continuar = True
        if argv_real is not None:
            plano_congelado_ok(root, m['anterior'], load_plano(root), 'HEAD', regras_vigentes(root))
        prazo = prazo_do_bloco(root, m['id'])
        atraso = prazo if prazo and iso(now) > prazo else None   # ordem do dono de 30/10: a cadeia anda à noite
        tentativas = tentativas_do_bloco(hist, m['id'], reconciliacoes_sessoes_ok(root,hist), opening)
        if tentativas >= MAX_TENTATIVAS:
            erros = verificar(root, m['id']) if (root / DIR / m['id'] / 'fechamento.json').exists() else ['fechamento_ausente']
            return {'acao': 'parado', 'motivo': aviso(root, 'O bloco %s terminou %d sessões sem fechamento verificado. Violações: %s.'
                                                     % (m['id'], tentativas, '; '.join(erros)), git_enabled)}
        try:
            recursos_ok(root)
        except Blocked as e:
            return {'acao': 'parado', 'motivo': aviso(root, 'Recursos da VPS abaixo do mínimo para abrir sessão: `%s`.' % e, git_enabled)}
        prompt = prompt_do_bloco(m, continuar, atraso)
        log = estado_dir / ('%s-%03d-%d.log' % (m['id'], len(hist) + 1, int(now)))
        reservation = {'bloco': m['id'], 'pid': None, 'inicio': None, 'em': now, 'continuar': continuar,
                       'prompt_sha256': digest(prompt), 'log': str(log), 'estado': 'reservado',
                       'modo': config['modo']}
        if argv_real is not None:
            reservation.update(modo='real', unidade='sc-bloco-'+m['id'].lower()+'-'+os.urandom(16).hex()+'.service',
                limite_segundos=config.get('max_segundos_sessao',21600),
                supervisor_pid=os.getpid(),supervisor_inicio=inicio_processo(os.getpid()))
            require(type(reservation['supervisor_inicio']) is str and reservation['supervisor_inicio'].isdigit(),
                    'sessao_supervisor_identidade_ausente')
        stop=barreira_pare_atual(root)
        if stop is not None:
            if opening is not None:
                cancelar_pre_efeito(root,opening,stop['motivo'])
                salvar_historico(hist_path,hist)
            return stop
        if opening is not None:
            reservation['origin_commit'] = opening['origin_commit']
            if 'cessoes_externas' in opening:reservation['cessoes_externas']=opening['cessoes_externas']
            reservation['abertura_commit'] = git(root, 'rev-parse', 'HEAD').stdout.strip()
            hist[hist.index(opening)] = reservation
        else:
            hist.append(reservation)
        salvar_historico(hist_path, hist)
        if (root/DIR/'PARE').exists():
            cancelar_pre_efeito(root,reservation,'parado_pelo_dono')
            salvar_historico(hist_path,hist)
            return {'acao':'nada','motivo':'parado_pelo_dono'}
        require(not (root / DIR / 'AVISO_DONO.md').exists(), 'parada_antes_efeito')
        if argv_real is not None:
            # Sessão real: argv fixado na DT, binário conferido de novo logo antes do efeito.
            require(lancador_real(root, config) == argv_real, 'lancador_mudou_durante_o_passo')
            if opening is not None:
                require(git(root,'rev-parse','HEAD').stdout.strip()==reservation['abertura_commit'],'head_mudou_antes_lancamento')
            require(not git(root, 'status', '--porcelain', '-uall').stdout.strip(), 'arvore_suja_antes_efeito')
            plano_congelado_ok(root, m['anterior'], load_plano(root), 'HEAD', regras_vigentes(root))
            entrada = log.with_suffix('.prompt')
            entrada.write_text(prompt, encoding='utf-8')
            home = strict_json(show(root,'HEAD',config['dt']))['lancador']['executor']['home']
            command = comando_unidade_sessao(argv_real,reservation['unidade'],
                                             reservation['limite_segundos'],home)
            stop=barreira_pare_atual(root)
            if stop is not None:
                cancelar_pre_efeito(root,reservation,stop['motivo'])
                salvar_historico(hist_path,hist)
                return stop
            with open(log, 'xb') as out, open(entrada, 'rb') as stdin:
                proc = subprocess.Popen(command, cwd='/', stdin=stdin, stdout=out,
                                        stderr=subprocess.STDOUT, start_new_session=True,
                                        env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                             'HOME': strict_json(show(root,'HEAD',config['dt']))['lancador']['executor']['home']})
        else:
            # Ensaio: sessão postiça que só imprime o prompt.
            command = [sys.executable, '-I', '-B', '-c',
                       'import sys,time; print(sys.argv[1],flush=True); time.sleep(1.5)', prompt]
            with open(log, 'xb') as out:
                proc = subprocess.Popen(command, cwd=root, stdin=subprocess.DEVNULL, stdout=out,
                                        stderr=subprocess.STDOUT, start_new_session=True,
                                        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        reservation.update(pid=proc.pid, inicio=inicio_processo(proc.pid), estado='lancado')
        salvar_historico(hist_path, hist)
        result = {'acao': 'lancado', 'motivo': m['id'], 'pid': proc.pid, 'continuar': continuar, 'atraso': atraso}
        if argv_real is not None:
            REAL_PENDING[reservation['unidade']] = (proc,hist_path,dict(reservation))
            result['unidade'] = reservation['unidade']
        return result
    finally:
        os.close(lock)


def salvar_historico(path, hist):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as stream:
        json.dump(hist, stream, ensure_ascii=False, indent=1)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def validar_config(c):
    require(isinstance(c, dict) and set(c) <= {'modo', 'estado_dir', 'max_lancamentos_dia', 'max_segundos_sessao', 'dt', 'dt_sha256', 'native_host_id'}, 'config_campos')
    require(c.get('modo') in ('ensaio', 'inativo', 'real'), 'encadeador_modo_desconhecido')
    if c['modo'] == 'real':
        require(isinstance(c.get('dt'), str) and isinstance(c.get('dt_sha256'), str) and HEX64.fullmatch(c['dt_sha256']), 'lancador_real_sem_dt')
        require(type(c.get('native_host_id')) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}',c['native_host_id']),'lancador_host_nativo_ausente')
    else:
        require('dt' not in c and 'dt_sha256' not in c and 'native_host_id' not in c, 'config_campos')
    require(isinstance(c.get('estado_dir'), str) and Path(c['estado_dir']).is_absolute(), 'config_estado_dir')
    require(type(c.get('max_lancamentos_dia', 8)) is int and 1 <= c.get('max_lancamentos_dia', 8) <= 8, 'config_limite_diario')
    require(type(c.get('max_segundos_sessao', 21600)) is int and 1 <= c.get('max_segundos_sessao', 21600) <= 21600, 'config_timeout')


def load_config(path):
    c = load(path)
    validar_config(c)
    return c


def encadear(root, config, now=None, git_enabled=True):
    try:
        with repo_lock(root):
            return _encadear(root, config, now, git_enabled)
    except Blocked as exc:
        if str(exc) == 'outro_encadeador_em_execucao':
            return {'acao': 'nada', 'motivo': str(exc)}
        raise


def estado(root):
    root = Path(root)
    abertos = blocos_abertos(root)
    out = {'blocos': [], 'pare': (root / DIR / 'PARE').exists(), 'aviso_ao_dono': (root / DIR / 'AVISO_DONO.md').exists()}
    for bid in abertos:
        fechado = verificado_e_enviado(root, bid)
        linha = {'id': bid, 'verificado_e_enviado': fechado, 'prazo_utc': prazo_do_bloco(root, bid),
                 'violacoes': [] if fechado else verificar(root, bid)}
        if not fechado:
            linha['revisoes'] = {r: ((root / DIR / bid / 'revisoes' / (r + '.json')).is_file()) for r in REVISORES}
            m = load_manifesto(root, bid)
            linha['fichas'] = {i['id']: (fx.conferir(root, i['id'], bid, i['aceite']) if i.get('ficha_sha256') else None) for i in m['itens']}
        out['blocos'].append(linha)
    return out


def repositorio_github(root):
    url = git(root, 'remote', 'get-url', 'origin', check=False).stdout.strip()
    m = re.search(r'github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$', url)
    require(m is not None, 'origem_nao_e_github')
    return '%s/%s' % (m.group(1), m.group(2))


def ratificar(root, motivo, now=None):
    """Prepara a mudança do congelado (plano, fichas, chaves, identidades ou motor) para o dono:
    grava em PLANO_ALTERACOES.json a entrada de = congelado no fechamento do último bloco, para =
    congelado em HEAD, e devolve o texto e o link do site do GitHub que cria a confirmação. Não
    confirma nada: a entrada só vale quando o dono criar o arquivo pelo site, com o hash `para`."""
    from urllib.parse import quote
    root = Path(root)
    text_ok(motivo, 20, 'ratificacao_sem_motivo')
    require(not git(root, 'status', '--porcelain', '-uall').stdout.strip(), 'arvore_suja_antes_de_ratificar')
    fechados = [bid for bid in blocos_abertos(root) if (root / DIR / bid / 'verificado.json').is_file()]
    require(fechados, 'nenhum_bloco_fechado')
    anterior = fechados[-1]
    v = load(root / DIR / anterior / 'verificado.json')
    regras = regras_vigentes(root)
    de, para = digest(congelado(root, v['head'], anterior, regras=regras)), digest(congelado(root, 'HEAD', anterior, regras=regras))
    require(de != para, 'congelado_sem_mudanca')
    rel = '%s/%s-congelado-%s.md' % (CONFIRMACOES, iso(now)[:10], para[:12])
    access_terms=[]
    dt_raw=show(root,'HEAD','docs/decisoes/DT-B03-LANCADOR-01.json')
    dt=strict_json(dt_raw) if dt_raw is not None else {}
    q=dt.get('qualificacao')
    if type(q) is dict and q.get('schema')=='sc-lancador-qualificacao/2':
        require(q.get('lancador_sha256')==digest(dt.get('lancador')),'ratificacao_lancador_diverge')
        proof=q['rota_movel'];raw=show(root,'HEAD',proof['path'])
        require(raw is not None and filehash(raw)==proof['sha256'],'ratificacao_rota_diverge')
        route=strict_json(raw)
        require(route.get('lancador_sha256')==q['lancador_sha256'] and
                route.get('host_id')==dt['lancador'].get('native_host_id') and
                route.get('notebook_demonstrado') is True and route.get('celular_demonstrado') is False,
                'ratificacao_rota_diverge')
        ref=route.get('confirmacao_dono')
        require(type(ref) is dict and set(ref)=={'path'} and
                ref['path']=='docs/decisoes/confirmacoes/B04-ratificacao-conjunta-ordem8.md',
                'ratificacao_conjunta_path')
        access_terms=['CONFIRMO ACESSO NOTEBOOK','CELULAR BLOQUEADO_DONO ORDEM 8',
                      'LANCADOR '+q['lancador_sha256'],'HOST '+route['host_id'],
                      'SESSAO '+route['sessao_nativa']]
        if show(root,'HEAD',ref['path']) is None:
            rel=ref['path']
            if (root/DIR/'B04/manifesto.json').is_file():
                current=load_manifesto(root,'B04')
                targets=[i for i in current['itens'] if i['id']=='B02-05']
                if targets and fx.hash_ficha(root,'B02-05')!=targets[0]['ficha_sha256']:
                    _,term=termo_ajuste_ordem8(root,'B04',targets[0])
                    access_terms.append(term)
        else:
            confirmacao_dono_ok(root,ref['path'],access_terms,chaves_em_vigor(root))
            access_terms=[]
    p = root / DIR / 'PLANO_ALTERACOES.json'
    pa = load(p) if p.is_file() else {'schema': 'sc-plano-alteracoes/1', 'alteracoes': []}
    pa['alteracoes'] = [a for a in pa['alteracoes'] if not (a.get('de_sha256') == de and a.get('para_sha256') == para)]
    pa['alteracoes'].append({'de_sha256': de, 'para_sha256': para, 'motivo': motivo, 'ordem_dono': {'path': rel}})
    p.write_text(json.dumps(pa, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    texto = 'Aprovo a mudanca do congelado com hash %s.\nMotivo: %s\n' % (para, motivo)
    if access_terms:texto+='\n'+'\n'.join(access_terms)+'\n'
    ramo = git(root, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
    link = 'https://github.com/%s/new/%s?filename=%s&value=%s' % (repositorio_github(root), ramo, quote(rel, safe='/'), quote(texto, safe=''))
    return {'de': de, 'para': para, 'confirmacao': rel, 'texto': texto, 'link': link}


def conferir(root):
    """Conferência da integração contínua: blocos fechados continuam fechados, fichas íntegras e
    completas, congelado intacto ou alterado com confirmação do dono. Devolve as violações."""
    root = Path(root)
    erros = []
    abertos = blocos_abertos(root)
    fechados = [bid for bid in abertos if (root / DIR / bid / 'verificado.json').is_file()]
    for bid in fechados:
        if not verificado_e_enviado(root, bid):
            erros.append('bloco_fechado_nao_confere:' + bid)
    for bid in abertos:
        if bid not in fechados:
            try:
                m = load_manifesto(root, bid)
                rules = regras_do_bloco(root, bid)
                regras_nao_regridem(root, m, rules)
                if rules >= 2:
                    manifesto_derivado_ok(root, bid, rules)
            except (Blocked, OSError, ValueError, KeyError, TypeError) as exc:
                erros.append(str(exc))
    # Fechamento registrado um dia continua registrado: apagar verificado.json não "reabre" nada.
    registrados = git(root, 'log', '--diff-filter=A', '--format=', '--name-only', '--', '%s/*/verificado.json' % DIR).stdout.split()
    for rel in sorted(set(registrados)):
        if not (root / rel).is_file():
            erros.append('verificado_removido:' + rel.split('/')[1])
    rel = fx.validar(root)
    erros += ['ficha_faltando:' + x for x in rel['faltam']]
    erros += ['ficha_invalida:%s:%s' % (k, v['estrutura']) for k, v in rel['fichas'].items() if v['estrutura'] != 'ok']
    try:
        plano = load_plano(root)
        plano_congelado_ok(root, fechados[-1] if fechados else None, plano, 'HEAD', regras_vigentes(root))
        identidades(root)
        fx.chaves(root)
        propostas_ok(root, rastreados_de(root))
    except (Blocked, OSError, ValueError, KeyError, TypeError) as e:
        erros.append(str(e) if isinstance(e, Blocked) else '%s:%s' % (type(e).__name__, e))
    return {'ok': not erros, 'violacoes': erros, 'fechados': fechados, 'fichas': {k: v['estrutura'] for k, v in rel['fichas'].items()}}


def installation_authority(root, deployment):
    """The protected installation must match the ratified native freeze at each tick."""
    previous=deployment['frozen_after']; source=deployment['source_commit']
    require(ancestral(root,source,'HEAD'),'installed_source_not_ancestor')
    expected=congelado(root,source,previous)
    require(digest(expected)==deployment['frozen_sha256'],'installation_frozen_hash_diverges')
    require(congelado(root,'HEAD',previous)==expected,'installation_current_freeze_diverges')
    # This reference is pinned by the custodian outside the candidate repository.
    # A candidate cannot choose its own previous approval merely by editing verificado.head.
    anchor=deployment['previous_closure']
    require(ancestral(root,anchor['commit'],source),'installation_closure_not_ancestor')
    closure_path=DIR+'/'+previous+'/verificado.json'
    closure_raw=show(root,anchor['commit'],closure_path)
    require(closure_raw is not None and filehash(closure_raw)==anchor['sha256'],
            'installation_previous_closure_hash')
    require(show(root,source,closure_path)==closure_raw,'installation_previous_closure_changed')
    closure=strict_json(closure_raw);base=closure.get('head')
    require(type(base) is str and HEX40.fullmatch(base) and ancestral(root,base,anchor['commit']),
            'installation_previous_closure_head')
    before=congelado(root,base,previous)
    if before!=expected:
        alteracao_registrada(root,source,before,expected,REGRAS,base)
    for name,wanted in deployment['files'].items():
        raw=show(root,source,'controle/'+name)
        require(raw is not None and filehash(raw)==wanted,'installed_source_commit_diverges')
    return True


def encadeamento_precondicao_falhou(root, etapa, exc, transporte_pronto):
    """Stop visibly after a trusted repository is known; never claim an unproved send."""
    code=str(exc) if isinstance(exc,Blocked) else ''
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,95}',code):
        code=type(exc).__name__
    result={'acao':'parado','motivo':'encadeamento_precondicao:'+etapa+':'+code,
            'aviso_preservado':False,'aviso_entregue':False}
    if root is None:
        result['aviso_erro']='instalacao_nao_validada'
        return result
    try:
        with repo_lock(root):
            path=Path(root)/DIR/'AVISO_DONO.md'
            if path.exists() or path.is_symlink():
                jb.protected_bytes(path,MAX_EVIDENCIA)
            else:
                aviso(root,result['motivo'],git_enabled=False)
            result['aviso_preservado']=True
            if transporte_pronto and not (Path(root)/DIR/'PARE').exists():
                result['aviso_entregue']=publicar_aviso_pendente(root)
    except Exception as notice_error:
        result['aviso_erro']=('outro_encadeador_em_execucao'
            if isinstance(notice_error,Blocked) and str(notice_error)=='outro_encadeador_em_execucao'
            else type(notice_error).__name__)
    return result


def main(argv=None):
    global RUNTIME_INSTALLATION,RUNTIME_CONTROL_PATHS
    RUNTIME_INSTALLATION=None;RUNTIME_CONTROL_PATHS=()
    p = argparse.ArgumentParser(description='Blocos sem pendência herdada, revisão externa e encadeamento por sessão nova.',allow_abbrev=False)
    p.add_argument('--instalacao', help='Manifesto protegido da instalacao do juiz')
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('estado')
    sub.add_parser('abrir')
    sub.add_parser('conferir')
    f = sub.add_parser('fechar'); f.add_argument('bloco')
    r = sub.add_parser('pedir-revisao'); r.add_argument('bloco')
    pr = sub.add_parser('propor'); pr.add_argument('item'); pr.add_argument('motivo')
    rt = sub.add_parser('ratificar'); rt.add_argument('motivo')
    e = sub.add_parser('encadear'); e.add_argument('--config', required=True)
    args = p.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    ok = True
    trusted_notice_root=None;transport_ready=False;stage='installation'
    try:
        deployment = None
        if args.instalacao:
            deployment = validator_installation(args.instalacao)
            root = installed_entrypoint(deployment,__file__,{
                'blocos.py':__file__,'juiz_base.py':jb.__file__,'fichas.py':fx.__file__})
            trusted_notice_root=root;stage='transport'
            configure_validator_transport(deployment['transport'])
            transport_ready=True;stage='authority'
            installation_authority(root,deployment)
            stage='inventory'
            import run_tests
            installed_entrypoint(deployment,__file__,{'run_tests.py':run_tests.__file__})
            run_tests.configure_inventory(root)
            RUNTIME_INSTALLATION=deployment
        if args.cmd == 'estado':
            res = estado(root)
        elif args.cmd == 'abrir':
            res = abrir(root)
        elif args.cmd == 'conferir':
            res = conferir(root)
            ok = res['ok']
        elif args.cmd == 'fechar':
            require(ID.fullmatch(args.bloco), 'bloco_id')
            res = fechar(root, args.bloco)
        elif args.cmd == 'pedir-revisao':
            require(ID.fullmatch(args.bloco), 'bloco_id')
            res = pedir_revisao(root, args.bloco)
        elif args.cmd == 'propor':
            res = propor(root, args.item, args.motivo)
        elif args.cmd == 'ratificar':
            res = ratificar(root, args.motivo)
        else:
            stage='config'
            config = strict_json(jb.protected_bytes(args.config,32768)) if deployment else load_config(args.config)
            if deployment:
                RUNTIME_CONTROL_PATHS=(str(Path(args.instalacao).absolute()),deployment['transport']['key'],
                                       str(Path(args.config).absolute()))
            validar_config(config)
            if config['modo']=='real':
                require(deployment is not None,'real_launcher_requires_installed_judge')
                require(config['estado_dir']==deployment['state'],'installation_state_diverges')
            stage='encadear'
            res = encadear(root, config)
            if config['modo']=='real' and res.get('acao')=='lancado':
                stage='supervisionar'
                res = supervisionar_sessao_real(root,config,res)
                ok = res.get('acao')=='sessao_encerrada'
    except Exception as e:
        if args.cmd=='encadear':
            res=encadeamento_precondicao_falhou(trusted_notice_root,stage,e,transport_ready)
            print(json.dumps({'ok':False,'erro':res['motivo'],'resultado':res},ensure_ascii=False))
            return 1
        if not isinstance(e,Blocked):raise
        print(json.dumps({'ok': False, 'erro': str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({'ok': ok, 'resultado': res}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())

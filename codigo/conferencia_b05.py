"""Conferencia mecanica historica B05; nenhum lancamento ou autorizacao.

Hashes fechados nao autenticam assinaturas. A autenticacao dos pareceres historicos
ocorre no host e deve ser confirmada no parecer formal Claude, cuja autenticidade
continua obrigatoria em revisoes_ok. Sem caminhos livres, Q2 nao substitui Q1.
"""
import hashlib
import json
from pathlib import Path
import sys

CONFIG = {'conferir-dt04': {'files': {'manifest': {'path': 'docs/decisoes/B05-CPU-M1-04-manifesto.json',
                                          'sha256': 'd87d110c78b538fdf1aeee5d1b069104047c0e4d660d237ab030af15a39f5a67'},
                             'base': {'path': 'docs/decisoes/DT-B05-EXECUTOR-01.json',
                                      'sha256': 'f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441'},
                             'criterion': {'path': 'docs/decisoes/DT-B05-CRITERIO-CPU-02.json',
                                           'sha256': '280d14b305f831957c25075d772716792d1d895fe1cb593c56f8d233b052680b'},
                             'prepared': {'path': 'docs/evidencias/bloco5-2026-10-31/cpu-m1-04-preparacao/dt-preparada.json',
                                          'sha256': 'aa58641191ddccc1bdf5bff1ef64bbf77c7973f48f42186cb1b37807b5c62737'},
                             'review': {'path': 'coord/outbox/claude/sc-b05-cpu-m1-04-preparacao-revisao.json',
                                        'sha256': '56e2571970c88c8fe8ea26eb5f6f6dfad14980a05336d99b8a920fffd2c40bf9'}},
                   'link': {'manifesto_sha256': 'd87d110c78b538fdf1aeee5d1b069104047c0e4d660d237ab030af15a39f5a67',
                            'base_dt_sha256': 'f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441',
                            'criterio_sha256': '280d14b305f831957c25075d772716792d1d895fe1cb593c56f8d233b052680b',
                            'prepared_dt_sha256': 'aa58641191ddccc1bdf5bff1ef64bbf77c7973f48f42186cb1b37807b5c62737',
                            'preparacao_cpu_sha256': '92099d45dee7c49cc74f5082628a0641b114c06dfdb78aa1fe3c2fd43c2410f8'},
                   'review_commit': '1df2600ce0c6fca37fc84cb0fa865f3207a88259'},
 'conferir-cpu01': {'files': {'manifest': {'path': 'docs/decisoes/B05-CPU-M1-03-manifesto.json',
                                           'sha256': '1a991fb36e80eedb2d66c4b326c5b470a5210d6f2c55ea951fa6f04c443d3bbe'},
                              'base': {'path': 'docs/decisoes/DT-B05-EXECUTOR-01.json',
                                       'sha256': 'f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441'},
                              'criterion': {'path': 'docs/decisoes/DT-B05-CRITERIO-CPU-01.json',
                                            'sha256': '5d53ae937e4e7ca197fecd0fc756ff5bbd64e17fa3db8373086abaaf2791a9d1'},
                              'prepared': {'path': 'docs/evidencias/bloco5-2026-10-31/cpu-m1-03-preparacao/dt-preparada.json',
                                           'sha256': 'd652bab4251dce76ae452ac9a70aec9fa180a182ea38468727dd1cb547f781a4'},
                              'review': {'path': 'coord/outbox/claude/sc-b05-cpu-m1-03-preparacao-revisao.json',
                                         'sha256': '667acfd83a94f9c8f878ecfbb811a6c4cfd4e825e67f8a52125055bcca747dc4'},
                              'result': {'path': 'docs/evidencias/bloco5-2026-10-31/teste-cpu-resultado.json',
                                         'sha256': '574d221bfa7a1b71ac66b501178530b670c45bddd9a0f19dbed16afe5c6139ff'},
                              'log': {'path': 'docs/evidencias/bloco5-2026-10-31/teste-cpu-log.jsonl',
                                      'sha256': '0255b176c59a70197a8cbab3950f594da0ef700310a3d7efdd9e73f6eb4efa6f'}},
                    'link': {'manifesto_sha256': '1a991fb36e80eedb2d66c4b326c5b470a5210d6f2c55ea951fa6f04c443d3bbe',
                             'base_dt_sha256': 'f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441',
                             'criterio_sha256': '5d53ae937e4e7ca197fecd0fc756ff5bbd64e17fa3db8373086abaaf2791a9d1',
                             'prepared_dt_sha256': 'd652bab4251dce76ae452ac9a70aec9fa180a182ea38468727dd1cb547f781a4',
                             'preparacao_cpu_sha256': 'cdcb1065030dda2c14ccc0223b6f0605c3a0271f53045190a1bba58eca986bee'},
                    'review_commit': '515be0157f3c337dde36f44e623051a6f01540be'}}
SOURCES = {'controle/cpu_exec.py': '204cb2c204473b5a1203e96ebd90c082a1a31b5f4e8109c465654afea5582f81',
 'controle/cpu_launcher.py': 'b746c1cda28985e3e57ad5c98a3a33b42cf3751c9ecc88f0f71c3b229b7f2b7c',
 'controle/executor_modelo.py': '425c0e0aa62a9bb7cf2e7b4533085330b531cfcd8298725d9e14cf0693f39553',
 'controle/frontend_cpu.py': '5b84ce2edaf7df43c262bb307ea4dd346d0bc1a8baf28935e7547105e15a8a5e',
 'controle/harness.py': 'c09b3ce136657976be6b72267c6b344220b0965f7f0aa464707e8f21a8cadd29',
 'controle/m1.py': '371b399c05bab4262c921c8121d7ba3f73a07a5aaa477d47ac4efb1397dc48a0',
 'controle/m1_exec.py': '43528361957fa3698077fc83403fb04c7cfa0ea7362b51c074f7b3e6f7ff8cb3'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def pinned(root, ref):
    path = root / ref['path']
    require(path.is_file() and not path.is_symlink(), 'arquivo_fechado_ausente')
    raw = path.read_bytes()
    require(len(raw) <= 1048576 and hashlib.sha256(raw).hexdigest() == ref['sha256'], 'bytes_fechados_divergem')
    return raw


def load_bundle(root, command):
    require(command in CONFIG, 'comando_fechado_invalido')
    cfg = CONFIG[command]
    raw = {key: pinned(root, ref) for key, ref in cfg['files'].items()}
    # JSON and dependent source bytes are pinned before repository imports.
    docs = {key: json.loads(value) for key, value in raw.items() if key != 'log'}
    require(docs['review'].get('veredito') == 'aprovado', 'parecer_nao_aprovado')
    require(docs['review'].get('vinculo_preparacao') == cfg['link'], 'vinculo_fechado_diverge')
    link = cfg['link']
    for file_key, link_key in [('manifest','manifesto_sha256'),('base','base_dt_sha256'),
                               ('criterion','criterio_sha256'),('prepared','prepared_dt_sha256')]:
        require(cfg['files'][file_key]['sha256'] == link[link_key], 'pin_vinculo_diverge')
    for key, role in [('base_dt','base'),('criterion','criterion')]:
        require(docs['manifest'][key] == cfg['files'][role], 'manifesto_caminho_diverge')
    require(docs['prepared']['executor']['preparacao_cpu_sha256'] == link['preparacao_cpu_sha256'], 'preparacao_pin_diverge')
    return docs, raw


def confer(root, command):
    root = Path(root).resolve()
    docs, raw = load_bundle(root, command)
    for path, sha in SOURCES.items():
        pinned(root, {'path': path, 'sha256': sha})
    sys.path.insert(0, str(root))
    from controle import cpu_exec as collector
    from controle import executor_modelo as executor
    # Reject modules imported from any other checkout in a reused interpreter.
    for name in ('cpu_exec','cpu_launcher','frontend_cpu','executor_modelo','harness','m1','m1_exec'):
        require(Path(sys.modules['controle.' + name].__file__).resolve() == root / ('controle/' + name + '.py'), 'modulo_fora_da_arvore')
    old = tuple(getattr(executor, key) for key in collector.PIN_NAMES)
    try:
        prepared = collector.bind_preparation(docs['base'], docs['prepared'], CONFIG[command]['link'],
                                               docs['manifest'], CONFIG[command]['link']['manifesto_sha256'], docs['criterion'])
        if command == 'conferir-cpu01':
            verdict = executor.conferir_teste_cpu(raw['criterion'], raw['result'], raw['log'], prepared, qualification=1)
            require(verdict == 'REPROVADO', 'veredito_primario_diverge')
            return 'TESTE_CPU_CONFERIDO REPROVADO; vinculo03 mecanico, sem nova execucao'
        return 'DT_COERENTE; vinculo04 mecanico, sem nova execucao'
    finally:
        for key, value in zip(collector.PIN_NAMES, old):
            setattr(executor, key, value)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        require(len(args) == 1 and args[0] in CONFIG, 'comando_fechado_invalido')
        print(confer(Path(__file__).resolve().parents[1], args[0]))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        print('CONFERENCIA_B05_DIVERGE')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

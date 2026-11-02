"""Contrato candidato B05; confere bytes, sem lançar modelo ou acessar a rede.

Os pins permanecem ausentes até a qualificação real do artefato e do runtime.
Fixture aprovada não prova inferência em CPU, isolamento nem aprovação da DT.
"""
import argparse
import base64
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controle.harness import read_file

ARTEFATO_SHA256 = None
EXECUTOR_NOME = None
EXECUTOR_VERSAO = None
EXECUTOR_SHA256 = None
PERFIL_CPU_SHA256 = "29e629104005cbb06e721fcec65fe34673458f6d7780bb67021b27502e18bd69"
PREPARACAO_CPU_SHA256 = None
SAIDA_FORA_DO_ESQUEMA = "SAIDA_FORA_DO_ESQUEMA"
DT_PATH = "docs/decisoes/DT-B05-EXECUTOR-01.json"
CRITERIO_PATH = "docs/decisoes/DT-B05-CRITERIO-CPU-01.json"
LOG_PATH = "docs/evidencias/bloco5-2026-10-31/teste-cpu-log.jsonl"
MAX_SAIDA = 16384
MAX_DOCUMENTO = 1048576
HASH = re.compile(r"[0-9a-f]{64}\Z")
TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
UTC_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z\Z")
SAIDA_ESQUEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["schema", "tarefa", "resposta"],
    "properties": {
        "schema": {"const": "sc-modelo-saida/1"},
        "tarefa": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"},
        "resposta": {"type": "string", "maxLength": 4096},
    },
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), "campos_invalidos")


def strict_json(raw):
    require(type(raw) is bytes and len(raw) <= MAX_DOCUMENTO, "json_limite")
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, "json_chave_duplicada")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("json_numero_nao_finito")
    value = json.loads(raw.decode("utf-8", errors="strict"),
                       object_pairs_hook=pairs, parse_constant=invalid)
    # Also reject overflow (1e999) and unpaired escaped UTF-16 surrogates.
    canonical(value)
    return value


def conferir_saida(raw):
    require(type(raw) is bytes and len(raw) <= MAX_SAIDA, "saida_limite")
    value = strict_json(raw)
    exact(value, ["schema", "tarefa", "resposta"])
    require(value["schema"] == "sc-modelo-saida/1", "saida_schema")
    require(type(value["tarefa"]) is str and TASK.fullmatch(value["tarefa"]), "saida_tarefa")
    require(type(value["resposta"]) is str and len(value["resposta"]) <= 4096, "saida_resposta")
    return value


def conferir_identidade(artefato_sha256, executor_versao, executor_sha256):
    require(type(ARTEFATO_SHA256) is str and HASH.fullmatch(ARTEFATO_SHA256)
            and type(EXECUTOR_SHA256) is str and HASH.fullmatch(EXECUTOR_SHA256)
            and type(EXECUTOR_VERSAO) is str and EXECUTOR_VERSAO
            and type(EXECUTOR_NOME) is str and EXECUTOR_NOME, "executor_nao_qualificado")
    require(artefato_sha256 == ARTEFATO_SHA256, "artefato_sha256_diverge")
    require(executor_versao == EXECUTOR_VERSAO, "executor_versao_diverge")
    require(executor_sha256 == EXECUTOR_SHA256, "executor_sha256_diverge")


def conferir_dt(dt):
    require(type(dt) is dict, "dt_invalida")
    artifact, executor, output = dt["artefato"], dt["executor"], dt["saida"]
    conferir_identidade(artifact["sha256"], executor["versao"], executor["sha256"])
    require(dt["id"] == "DT-B05-EXECUTOR-01" and dt["item"] == "B05-01", "dt_item")
    require(executor["nome"] == EXECUTOR_NOME and
            executor["modulo"] == "controle/executor_modelo.py", "dt_executor")
    require(type(artifact["bytes"]) is int and artifact["bytes"] >= 1000000000
            and type(artifact["quantizacao_bits"]) is int
            and artifact["quantizacao_bits"] == 4, "dt_artefato")
    require(output["fora_do_esquema"] == "falha_fechada"
            and output["reparo_json"] is False and output["reparo_textual"] is False
            and output["esquema"] == SAIDA_ESQUEMA, "dt_saida")
    from controle.frontend_cpu import profile_ok, preparation_ok
    profile_ok(dt)
    preparation_ok(dt)
    return dt


def finite(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def utc(value):
    require(type(value) is str and UTC_TIMESTAMP.fullmatch(value), "horario_sem_utc")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None
            and parsed.utcoffset().total_seconds() == 0, "horario_sem_utc")
    return parsed


def conferir_teste_cpu(criterio_raw, resultado_raw, log_raw, dt, *, qualification=1):
    """Recalcula cada aceite e a taxa; autenticidade da execução é aceite externo."""
    require(type(qualification) is int and qualification in (1, 2), "qualificacao_invalida")
    criterion_path, log_path = (
        (CRITERIO_PATH, LOG_PATH) if qualification == 1 else
        ("docs/decisoes/DT-B05-CRITERIO-CPU-02.json",
         "docs/evidencias/bloco5-2026-10-31/qualificacao2-cpu-log.jsonl"))
    conferir_dt(dt)
    document, result = strict_json(criterio_raw), strict_json(resultado_raw)
    require(document["id"] == "DT-B05-CRITERIO-CPU-%02d" % qualification and
            document["item"] == "B05-02", "criterio_item")
    from controle import frontend_cpu as frontend
    criterion = document["criterio"]
    require(criterion["executor_dt"] == DT_PATH and
            criterion["artefato_sha256"] == ARTEFATO_SHA256, "criterio_executor")
    require(type(criterion["repeticoes_por_tarefa"]) is int and
            criterion["repeticoes_por_tarefa"] == 3 and
            criterion["tarefas_fora_do_dominio_alvo"] is True and
            criterion["uma_rodada_sem_alegacao_estatistica"] is True, "criterio_repeticoes")
    tasks = criterion["tarefas"]
    require(type(tasks) is list and 3 <= len(tasks) <= 5, "criterio_tarefas")
    expected = {}
    for task in tasks:
        exact(task, ["id", "enunciado", "aceite"])
        require(type(task["id"]) is str and TASK.fullmatch(task["id"])
                and task["id"] not in expected, "tarefa_duplicada_ou_invalida")
        require(type(task["enunciado"]) is str and 0 < len(task["enunciado"]) <= 8192,
                "enunciado_invalido")
        exact(task["aceite"], ["resposta_exata"])
        require(type(task["aceite"]["resposta_exata"]) is str
                and len(task["aceite"]["resposta_exata"]) <= 4096, "aceite_invalido")
        expected[task["id"]] = task["aceite"]["resposta_exata"]
    threshold = criterion["limiar"]
    exact(threshold, ["metrica", "valor", "regra"])
    require(threshold["metrica"] == "fracao_saidas_aceitas"
            and threshold["regra"] == ">=" and finite(threshold["valor"])
            and threshold["valor"] <= 1, "limiar_invalido")
    require(type(criterion["teto_relogio_s"]) is int and criterion["teto_relogio_s"] > 0,
            "teto_invalido")
    generation = criterion["parametros_geracao"]
    exact(generation, ["seed", "temperatura", "max_tokens"])
    require(type(generation["seed"]) is int and finite(generation["temperatura"])
            and type(generation["max_tokens"]) is int and generation["max_tokens"] > 0,
            "geracao_invalida")
    frontend.preparation_ok(dt, document)
    profile_generation = dt["executor"]["perfil_proposto"]["geracao"]
    require(all(generation[k] == profile_generation[k] for k in generation), "geracao_perfil_diverge")
    exact(result, ["schema", "item", "criterio", "log", "artefato_sha256", "executor",
                   "maquina", "iniciado_em_utc", "terminado_em_utc", "tarefas",
                   "repeticoes_por_tarefa", "uma_rodada_sem_alegacao_estatistica",
                   "limiar", "valor_observado", "veredito", "perfil_sha256", "preparacao_sha256"])
    require(result["schema"] == "sc-teste-cpu/2" and result["item"] == "B05-02", "resultado_item")
    require(result["perfil_sha256"] == PERFIL_CPU_SHA256 and
            result["preparacao_sha256"] == PREPARACAO_CPU_SHA256, "resultado_perfil")
    require(result["criterio"] == {"path": criterion_path, "sha256": digest(criterio_raw)},
            "criterio_sha256_diverge")
    require(result["log"] == {"path": log_path, "sha256": digest(log_raw)}, "log_sha256_diverge")
    require(result["artefato_sha256"] == ARTEFATO_SHA256 and
            result["executor"] == {"nome": EXECUTOR_NOME, "versao": EXECUTOR_VERSAO,
                                    "sha256": EXECUTOR_SHA256}, "resultado_executor")
    require(type(result["repeticoes_por_tarefa"]) is int and
            result["repeticoes_por_tarefa"] == 3 and
            result["uma_rodada_sem_alegacao_estatistica"] is True, "resultado_repeticoes")
    exact(result["maquina"], ["cpu", "ram_total_bytes", "dispositivo", "rede"])
    require(type(result["maquina"]["cpu"]) is str and result["maquina"]["cpu"]
            and type(result["maquina"]["ram_total_bytes"]) is int
            and result["maquina"]["ram_total_bytes"] > 0
            and result["maquina"]["dispositivo"] == "cpu"
            and result["maquina"]["rede"] is False, "maquina_invalida")
    elapsed = (utc(result["terminado_em_utc"]) - utc(result["iniciado_em_utc"])).total_seconds()
    require(0 <= elapsed <= criterion["teto_relogio_s"], "duracao_total_invalida")
    require(canonical(result["limiar"]) == canonical(threshold), "limiar_diverge")
    require(type(log_raw) is bytes and len(log_raw) <= MAX_DOCUMENTO
            and log_raw.endswith(b"\n"), "log_limite_ou_truncado")
    rows = {}
    accepted = 0
    duration = 0.0
    for line in log_raw.splitlines(keepends=True):
        record = strict_json(line)
        require(canonical(record) + b"\n" == line, "log_nao_canonico")
        exact(record, ["schema", "criterio_sha256", "artefato_sha256", "executor_sha256",
                       "tarefa", "repeticao", "saida_base64", "saida_sha256", "aceita",
                       "duracao_s", "parametros_geracao", "invocacao"])
        require(record["schema"] == "sc-teste-cpu-chamada/2" and
                record["criterio_sha256"] == digest(criterio_raw) and
                record["artefato_sha256"] == ARTEFATO_SHA256 and
                record["executor_sha256"] == EXECUTOR_SHA256 and
                canonical(record["parametros_geracao"]) == canonical(generation), "log_identidade")
        require(type(record["tarefa"]) is str and record["tarefa"] in expected
                and type(record["repeticao"]) is int and 1 <= record["repeticao"] <= 3,
                "log_tarefa")
        key = record["tarefa"], record["repeticao"]
        require(key not in rows, "log_repeticao_duplicada")
        require(type(record["saida_base64"]) is str, "saida_codificacao")
        raw = base64.b64decode(record["saida_base64"], validate=True)
        require(base64.b64encode(raw).decode("ascii") == record["saida_base64"]
                and len(raw) <= MAX_SAIDA and digest(raw) == record["saida_sha256"], "saida_hash")
        captured, boundary_ok = frontend.verify_invocation(record["invocacao"], dt, record["tarefa"])
        require(captured == raw, "saida_diverge_stdout_bruto")
        try:
            output = conferir_saida(raw)
            ok = boundary_ok and output["tarefa"] == record["tarefa"] and output["resposta"] == expected[record["tarefa"]]
        except (ValueError, UnicodeError):
            ok = False
        require(type(record["aceita"]) is bool and record["aceita"] == ok, "aceite_diverge")
        require(finite(record["duracao_s"]), "duracao_invalida")
        duration += record["duracao_s"]
        accepted += int(ok)
        rows[key] = {field: record[field] for field in ("repeticao", "saida_sha256", "aceita", "duracao_s")}
    require(set(rows) == {(task, n) for task in expected for n in range(1, 4)}, "log_incompleto")
    require(duration <= elapsed, "duracoes_excedem_relogio")
    require(type(result["tarefas"]) is list and len(result["tarefas"]) == len(expected), "resultado_tarefas")
    seen = set()
    for task in result["tarefas"]:
        exact(task, ["id", "repeticoes"])
        require(type(task["id"]) is str and task["id"] in expected and task["id"] not in seen,
                "resultado_tarefa_duplicada")
        seen.add(task["id"])
        require(type(task["repeticoes"]) is list and len(task["repeticoes"]) == 3, "resultado_chamadas")
        # Canonical comparison distinguishes booleans from integers.
        require(canonical(task["repeticoes"]) == canonical([rows[(task["id"], n)] for n in range(1, 4)]),
                "resultado_log_diverge")
    rate = accepted / len(rows)
    require(finite(result["valor_observado"]) and result["valor_observado"] == rate, "metrica_diverge")
    verdict = "APROVADO" if rate >= threshold["valor"] else "REPROVADO"
    require(result["veredito"] == verdict, "veredito_diverge")
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("conferir-saida", "conferir-dt"):
        sub.add_parser(name).add_argument("path", type=Path)
    cpu = sub.add_parser("conferir-teste-cpu")
    for name in ("criterio", "resultado", "log"):
        cpu.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "conferir-saida":
            raw = read_file(args.path, MAX_SAIDA)
            conferir_saida(raw)
            print("SAIDA_OK")
        elif args.command == "conferir-dt":
            conferir_dt(strict_json(read_file(args.path)))
            print("DT_COERENTE")
        else:
            dt = strict_json(read_file(Path(__file__).resolve().parents[1] / DT_PATH))
            conferir_teste_cpu(read_file(args.criterio), read_file(args.resultado), read_file(args.log), dt)
            print("TESTE_CPU_CONFERIDO")
        return 0
    except OSError:
        # Missing fixture must not masquerade as rejection of an actual model response.
        print("ENTRADA_INDISPONIVEL")
        return 2
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError, RecursionError):
        print({"conferir-saida": SAIDA_FORA_DO_ESQUEMA, "conferir-dt": "DT_DIVERGE",
               "conferir-teste-cpu": "TESTE_CPU_DIVERGE"}[args.command])
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

"""Controle sintético B04. Nenhum cliente de modelo, rede ou código de proposta.
O replay verifica bytes e vínculos; nunca chama modelo ou ferramenta.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from datetime import datetime, timezone

MAX_ATTEMPTS_PER_STEP = 3
MAX_MODEL_CALLS_PER_STEP = 3
MAX_WALL_SECONDS_PER_STEP = 120
REPEATED_PROPOSAL_LIMIT = 2
MAX_FILE_BYTES = 1048576
MAX_LOG_BYTES = 8388608
MAX_RECORDS = 1000
FAILURE_CLASSES = ("infra", "ferramenta", "modelo", "politica", "limite")
ZERO = "0" * 64
HEX = re.compile(r"[0-9a-f]{64}\Z")
LABEL = "ensaio do plano de controle, modelo substituído"


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "chave_duplicada")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("numero_nao_finito")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), "campos_invalidos")


def plain_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), "link_recusado")
    return path


def read_file(path, limit=MAX_FILE_BYTES):
    path = plain_path(path)
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    fd = None
    try:
        require(all(part not in (".", "..") for part in path.parts), "caminho_invalido")
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and before.st_size <= limit, "arquivo_invalido")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after = os.fstat(fd)
        require(len(raw) <= limit and len(raw) == before.st_size and
                (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "arquivo_alterado")
        return raw
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def timing(value):
    require(type(value["timestamp_utc"]) is str, "horario_invalido")
    parsed = datetime.fromisoformat(value["timestamp_utc"].replace("Z", "+00:00"))
    require(parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
            "horario_sem_utc")
    duration = value["duracao_ms"]
    require(type(duration) in (int, float) and math.isfinite(duration)
            and 0 <= duration <= MAX_WALL_SECONDS_PER_STEP * 1000, "duracao_invalida")


def call_hash(call):
    exact(call, ["timestamp_utc", "duracao_ms", "pesos_sha256", "artefato_sha256",
                 "prompt_sha256", "saida_sha256", "seed", "amostragem",
                 "tokens", "classe_de_falha"])
    timing(call)
    for key in ("pesos_sha256", "artefato_sha256", "prompt_sha256", "saida_sha256"):
        require(type(call[key]) is str and HEX.fullmatch(call[key]), "hash_invalido")
    require(type(call["seed"]) is int and type(call["amostragem"]) is dict
            and type(call["tokens"]) is int and call["tokens"] >= 0
            and call["classe_de_falha"] in (None, *FAILURE_CLASSES), "chamada_invalida")
    return digest(canonical({k: v for k, v in call.items()
                             if k not in ("timestamp_utc", "duracao_ms")}))


def record_hash(record):
    covered = {k: v for k, v in record.items()
               if k not in ("timestamp_utc", "duracao_ms", "sha256")}
    if record["kind"] == "response":
        covered["body"] = dict(covered["body"])
        covered["body"]["chamada"] = {
            k: v for k, v in covered["body"]["chamada"].items()
            if k not in ("timestamp_utc", "duracao_ms")}
    return digest(canonical(covered))


def safe_relative(value):
    require(type(value) is str and value and len(value) <= 240 and
            not value.startswith("/") and "\\" not in value and ":" not in value
            and all(p not in ("", ".", "..") for p in value.split("/")),
            "caminho_invalido")


def proposal_hash(proposal):
    exact(proposal, ["tool_id", "script", "reads", "writes"])
    require(type(proposal["tool_id"]) is str and type(proposal["script"]) is dict,
            "proposta_invalida")
    for key in ("reads", "writes"):
        values = proposal[key]
        require(type(values) is list and all(type(v) is str for v in values)
                and values == sorted(set(values)), "declaracoes_invalidas")
        for value in values:
            safe_relative(value)
    return digest(canonical(proposal))


def execute_tool(proposal):
    """Única ferramenta B04: soma limitada de inteiros, sem efeitos em arquivos."""
    proposal_hash(proposal)
    require(proposal["tool_id"] == "soma_inteiros" and
            proposal["reads"] == [] and proposal["writes"] == [], "ferramenta_nao_liberada")
    exact(proposal["script"], ["valores"])
    values = proposal["script"]["valores"]
    require(type(values) is list and 1 <= len(values) <= 64 and
            all(type(v) is int and abs(v) <= 10**9 for v in values), "parametros_invalidos")
    return {"soma": sum(values)}


class SyntheticModel:
    """Fixture limitada; não recebe código, endpoints nem credenciais."""
    def __init__(self, responses):
        require(type(responses) is list and 1 <= len(responses) <= MAX_MODEL_CALLS_PER_STEP,
                "fixture_invalida")
        raw = canonical(responses)
        require(len(raw) <= MAX_FILE_BYTES, "fixture_excede_teto")
        self.responses = decode(raw)
        self.artifact_sha256 = digest(raw)
        self.calls = 0

    def call(self, prompt):
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class Ledger:
    def __init__(self, path, step_key):
        require(type(step_key) is str and re.fullmatch(r"[a-z0-9-]{1,64}", step_key),
                "step_key_invalido")
        self.path = plain_path(path)
        self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.step_key, self.head, self.count, self.size = step_key, ZERO, 0, 0
        try:
            os.fsync(self.fd)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except BaseException:
            self.close()
            raise

    def append(self, kind, body):
        record = {"schema": "sc-harness-registro/1", "seq": self.count + 1,
                  "previous_sha256": self.head, "step_key": self.step_key,
                  "kind": kind, "timestamp_utc": utc_now(), "duracao_ms": 0,
                  "body": body}
        record["sha256"] = record_hash(record)
        raw = canonical(record) + b"\n"
        require(self.count < MAX_RECORDS and self.size + len(raw) <= MAX_LOG_BYTES,
                "limite_registro")
        offset = 0
        while offset < len(raw):
            written = os.write(self.fd, raw[offset:])
            require(written > 0, "falha_gravacao")
            offset += written
        os.fsync(self.fd)  # Pedido durável antes da chamada ao modelo.
        self.count += 1
        self.size += len(raw)
        self.head = record["sha256"]
        return record

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def run_step(path, step_key, model, prompt="Some 2 e 3 no ensaio sintético.", *, clock=time.monotonic):
    require(type(model) is SyntheticModel and model.calls == 0, "somente_modelo_substituido_novo")
    require(type(prompt) is str and len(prompt.encode("utf-8")) <= 8192, "prompt_invalido")
    ledger = Ledger(path, step_key)
    begin, repeated, attempts, rejected = clock(), {}, 0, 0
    state, failure = "inconclusiva", "limite"
    try:
        while attempts < MAX_ATTEMPTS_PER_STEP and model.calls < MAX_MODEL_CALLS_PER_STEP:
            if clock() - begin >= MAX_WALL_SECONDS_PER_STEP:
                break
            request = ledger.append("request", {"prompt": prompt, "modelo": "substituído",
                                                "artefato_sha256": model.artifact_sha256})
            start = clock()
            output = model.call(prompt)
            duration = max(0, (clock() - start) * 1000)
            attempts += 1
            result, phash = None, None
            if duration > MAX_WALL_SECONDS_PER_STEP * 1000 or clock() - begin >= MAX_WALL_SECONDS_PER_STEP:
                state, failure = "inconclusiva", "limite"
                duration = min(duration, MAX_WALL_SECONDS_PER_STEP * 1000)
            elif type(output) is dict and output == {"estado": "abstained"}:
                state, failure = "abstained", None
            elif type(output) is dict and output.get("finish_reason") == "length":
                state, failure = "inconclusiva", "modelo"
            else:
                try:
                    phash = proposal_hash(output)
                    repeated[phash] = repeated.get(phash, 0) + 1
                    if repeated[phash] > REPEATED_PROPOSAL_LIMIT:
                        state, failure = "inconclusiva", "limite"
                    else:
                        result = execute_tool(output)
                        state, failure = "accepted", None
                except (ValueError, TypeError, OverflowError):
                    state, failure = "rejected", "politica"
                    rejected += 1
            call = {"timestamp_utc": utc_now(), "duracao_ms": duration,
                    "pesos_sha256": digest(b"modelo-substituido-b04"),
                    "artefato_sha256": model.artifact_sha256,
                    "prompt_sha256": digest(prompt.encode()), "saida_sha256": digest(canonical(output)),
                    "seed": 0, "amostragem": {"modo": "fixture"}, "tokens": 0,
                    "classe_de_falha": failure}
            ledger.append("response", {"pedido_sha256": request["sha256"], "saida": output,
                                      "chamada": call, "chamada_sha256": call_hash(call),
                                      "estado": state, "proposta_sha256": phash,
                                      "resultado": result})
            if state != "rejected":
                break
        if state == "rejected":
            state, failure = "inconclusiva", "limite"
        ledger.append("terminal", {"estado": state, "classe_de_falha": failure,
                                  "tentativas": attempts, "rejeicoes": rejected})
        return {"schema": "sc-harness-cabeca/1", "modelo": "substituído", "rotulo": LABEL,
                "cabeca_sha256": ledger.head, "registros": ledger.count,
                "estado": state, "classe_de_falha": failure, "tentativas": attempts,
                "rejeicoes": rejected}
    finally:
        ledger.close()


def reproduce(log, head_path):
    raw = read_file(log, MAX_LOG_BYTES)
    head = decode(read_file(head_path))
    exact(head, ["schema", "modelo", "rotulo", "cabeca_sha256", "registros",
                 "estado", "classe_de_falha", "tentativas", "rejeicoes"])
    require(head["schema"] == "sc-harness-cabeca/1" and head["modelo"] == "substituído"
            and head["rotulo"] == LABEL, "cabeca_invalida")
    require(type(head["tentativas"]) is int and type(head["rejeicoes"]) is int
            and type(head["estado"]) is str
            and head["classe_de_falha"] in (None, *FAILURE_CLASSES), "cabeca_invalida")
    require(raw.endswith(b"\n"), "registro_truncado")
    lines = raw[:-1].split(b"\n")
    require(1 <= len(lines) <= MAX_RECORDS and type(head["registros"]) is int
            and len(lines) == head["registros"], "contagem_diverge")
    previous, pending, key, terminal = ZERO, None, None, None
    attempts, rejected = 0, 0
    last_state, last_failure = None, None
    repeated = {}
    for seq, line in enumerate(lines, 1):
        try:
            record = decode(line.decode("utf-8", "strict"))
            require(canonical(record) == line, "registro_nao_canonico")
        except UnicodeError as exc:
            raise ValueError("registro_utf8_invalido") from exc
        exact(record, ["schema", "seq", "previous_sha256", "step_key", "kind",
                       "timestamp_utc", "duracao_ms", "body", "sha256"])
        timing(record)
        require(record["schema"] == "sc-harness-registro/1" and type(record["seq"]) is int
                and record["seq"] == seq and record["previous_sha256"] == previous
                and terminal is None, "cadeia_diverge")
        if key is None:
            key = record["step_key"]
            require(type(key) is str and re.fullmatch(r"[a-z0-9-]{1,64}", key), "step_key_invalido")
        require(record["step_key"] == key, "step_key_diverge")
        kind, body = record["kind"], record["body"]
        require(kind in ("request", "response", "terminal"), "tipo_desconhecido")
        if kind == "request":
            exact(body, ["prompt", "modelo", "artefato_sha256"])
            require(pending is None and last_state in (None, "rejected")
                    and attempts < MAX_ATTEMPTS_PER_STEP and type(body["prompt"]) is str and
                    len(body["prompt"].encode()) <= 8192 and body["modelo"] == "substituído"
                    and type(body["artefato_sha256"]) is str and HEX.fullmatch(body["artefato_sha256"]),
                    "pedido_invalido")
            pending = record
        elif kind == "response":
            exact(body, ["pedido_sha256", "saida", "chamada", "chamada_sha256",
                         "estado", "proposta_sha256", "resultado"])
            require(pending is not None and body["pedido_sha256"] == pending["sha256"],
                    "resposta_sem_pedido")
            call = body["chamada"]
            require(call_hash(call) == body["chamada_sha256"]
                    and call["prompt_sha256"] == digest(pending["body"]["prompt"].encode())
                    and call["saida_sha256"] == digest(canonical(body["saida"])),
                    "hash_chamada_diverge")
            require(call["pesos_sha256"] == digest(b"modelo-substituido-b04")
                    and call["artefato_sha256"] == pending["body"]["artefato_sha256"]
                    and type(call["seed"]) is int and call["seed"] == 0
                    and call["amostragem"] == {"modo": "fixture"} and call["tokens"] == 0,
                    "identidade_sintetica_diverge")
            require(body["estado"] in ("accepted", "abstained", "rejected", "inconclusiva"),
                    "estado_invalido")
            if body["estado"] == "rejected":
                try:
                    expected_proposal = proposal_hash(body["saida"])
                except (ValueError, TypeError, OverflowError):
                    expected_proposal = None
                require(body["proposta_sha256"] == expected_proposal, "hash_proposta_omitido")
            if body["proposta_sha256"] is not None:
                require(proposal_hash(body["saida"]) == body["proposta_sha256"], "hash_proposta_diverge")
                phash = body["proposta_sha256"]
                repeated[phash] = repeated.get(phash, 0) + 1
                if repeated[phash] > REPEATED_PROPOSAL_LIMIT:
                    require(body["estado"] == "inconclusiva" and call["classe_de_falha"] == "limite",
                            "proposta_repetida_sem_parada")
            if body["estado"] == "accepted":
                require(body["proposta_sha256"] is not None and call["classe_de_falha"] is None,
                        "aceite_invalido")
                proposal = body["saida"]
                require(proposal["tool_id"] == "soma_inteiros" and proposal["reads"] == []
                        and proposal["writes"] == [], "ferramenta_nao_liberada")
                exact(proposal["script"], ["valores"])
                values = proposal["script"]["valores"]
                require(type(values) is list and 1 <= len(values) <= 64
                        and all(type(v) is int and abs(v) <= 10**9 for v in values),
                        "parametros_invalidos")
                exact(body["resultado"], ["soma"])
                require(type(body["resultado"]["soma"]) is int
                        and abs(body["resultado"]["soma"]) <= 64 * 10**9, "resultado_invalido")
            else:
                require(body["resultado"] is None, "resultado_inesperado")
            if body["estado"] == "rejected":
                require(call["classe_de_falha"] == "politica", "rejeicao_invalida")
            if body["estado"] == "inconclusiva":
                require(call["classe_de_falha"] in ("limite", "modelo"), "falha_invalida")
                if call["classe_de_falha"] == "modelo":
                    require(type(body["saida"]) is dict and body["saida"].get("finish_reason") == "length",
                            "truncamento_invalido")
            if body["estado"] == "abstained":
                require(body["saida"] == {"estado": "abstained"} and body["resultado"] is None
                        and call["classe_de_falha"] is None, "abstencao_invalida")
            attempts += 1
            rejected += body["estado"] == "rejected"
            require(attempts <= MAX_ATTEMPTS_PER_STEP and attempts <= MAX_MODEL_CALLS_PER_STEP,
                    "teto_excedido")
            last_state, last_failure = body["estado"], call["classe_de_falha"]
            pending = None
        else:
            exact(body, ["estado", "classe_de_falha", "tentativas", "rejeicoes"])
            require(pending is None and seq == len(lines)
                    and body["estado"] in ("accepted", "abstained", "inconclusiva")
                    and body["classe_de_falha"] in (None, *FAILURE_CLASSES)
                    and type(body["tentativas"]) is int and body["tentativas"] == attempts
                    and type(body["rejeicoes"]) is int and body["rejeicoes"] == rejected,
                    "terminal_invalido")
            expected_state = last_state if last_state in ("accepted", "abstained", "inconclusiva") else "inconclusiva"
            expected_failure = last_failure if last_state in ("accepted", "abstained", "inconclusiva") else "limite"
            require(body["estado"] == expected_state and body["classe_de_falha"] == expected_failure,
                    "terminal_sem_resultado_correspondente")
            terminal = body
        require(type(record["sha256"]) is str and HEX.fullmatch(record["sha256"])
                and record_hash(record) == record["sha256"], "hash_registro_diverge")
        previous = record["sha256"]
    require(pending is None and terminal is not None and previous == head["cabeca_sha256"]
            and all(head[k] == v for k, v in terminal.items()), "replay_incompleto")
    return previous


def check_spec(path):
    spec = decode(read_file(path))
    caps = {name: globals()[name] for name in ("MAX_ATTEMPTS_PER_STEP", "MAX_MODEL_CALLS_PER_STEP",
            "MAX_WALL_SECONDS_PER_STEP", "REPEATED_PROPOSAL_LIMIT")}
    require(spec["schema"] == "sc-harness-especificacao/1"
            and spec["tetos"] == {**caps, "ao_esgotar": "inconclusiva"}
            and all(type(spec["tetos"][k]) is int for k in caps)
            and spec["falhas"]["classes"] == list(FAILURE_CLASSES)
            and spec["saida"]["codigos"] == {"REPLAY_OK": 0, "erro_de_entrada": 2, "REPLAY_MISS": 3}
            and spec["rede"]["modelo_real_habilitado"] is False, "ESPECIFICACAO_DIVERGE")
    return "ESPECIFICACAO_OK " + " ".join(f"{k}={v}" for k, v in caps.items()) + \
           " classes_de_falha=" + ",".join(FAILURE_CLASSES) + " REPLAY_OK=0 REPLAY_MISS=3"


def save_head(path, value):
    path = plain_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    spec = sub.add_parser("especificacao")
    spec.add_argument("--arquivo", required=True)
    replay = sub.add_parser("reproduzir")
    replay.add_argument("--log", required=True)
    replay.add_argument("--cabeca", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "especificacao":
            print(check_spec(args.arquivo))
        else:
            head = reproduce(args.log, args.cabeca)
            print(f"REPLAY_OK cabeca={head} ferramentas_executadas=0")
        return 0
    except (OSError, UnicodeError) as exc:
        print("ERRO_ENTRADA ferramentas_executadas=0")
        return 2
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        if args.command == "reproduzir":
            print("REPLAY_MISS ferramentas_executadas=0")
            return 3
        print("ESPECIFICACAO_DIVERGE")
        return 2


if __name__ == "__main__":
    sys.exit(main())

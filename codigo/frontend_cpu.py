"""Frontend candidato b11960. Sem CLI de lançamento nem autorização operacional.

GGUF/pins reais continuam ausentes. EOG exige sufixo e telemetria independente,
contagem de entrada previamente revisada e margem de contexto; sem reparo JSON.
"""
import base64
import copy
import hashlib
import os
import re
from pathlib import Path
import struct
import subprocess

from controle import executor_modelo as e

TEMPLATE_SHA256 = "a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715"
ENGINE = {"nome": "Jinja2", "versao": "3.0.3", "sandbox": "ImmutableSandboxedEnvironment",
          "undefined": "StrictUndefined", "trim_blocks": True, "lstrip_blocks": True,
          "keep_trailing_newline": False, "autoescape": False, "extensions": ["jinja2.ext.loopcontrols"],
          "globais_padrao_preservados": True}
KWARGS = {"add_generation_prompt": True, "enable_thinking": False, "tools": None}
SUFFIX = b" [end of text]\n\n\n"
MARKER = b"[end of text]"
MAX_PROMPT = 65536
MAX_STDERR = 1048576
MAX_METADATA = 64 * 1024 * 1024
OVERRIDE_KV = 'tokenizer.ggml.add_bos_token=bool:false,tokenizer.ggml.add_eos_token=bool:false'
EOS_POLICY = {"completion_override_kv": OVERRIDE_KV, "tokenizer_override_kv": None,
              "tokenizer_proof": "ids_sem_bos_eos_reconstroem_bytes",
              "completion_prompt_count": "prompt_eval_unico_igual_P"}


def blob(raw):
    return {"base64": base64.b64encode(raw).decode("ascii"), "bytes": len(raw), "sha256": e.digest(raw)}


def unblob(value, limit):
    e.exact(value, ["base64", "bytes", "sha256"])
    e.require(type(value["base64"]) is str and len(value["base64"]) <= (limit + 2) // 3 * 4,
              "blob_limite")
    raw = base64.b64decode(value["base64"], validate=True)
    e.require(type(value["bytes"]) is int and len(raw) <= limit and blob(raw) == value, "blob_diverge")
    return raw


def gguf_metadata(path, expected_hash):
    """Leitor limitado ao cabeçalho GGUF v3 LE; não carrega tensores nem executa."""
    e.require(type(expected_hash) is str and e.HASH.fullmatch(expected_hash), "gguf_pin_ausente")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        import stat
        before = os.fstat(stream.fileno())
        e.require(stat.S_ISREG(before.st_mode), "gguf_nao_regular")
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
        e.require(hasher.hexdigest() == expected_hash, "gguf_hash_diverge")
        stream.seek(0)
        def read(n):
            e.require(type(n) is int and 0 <= n <= MAX_METADATA and
                      stream.tell() + n <= MAX_METADATA, "gguf_metadata_limite")
            value = stream.read(n)
            e.require(len(value) == n, "gguf_truncado")
            return value
        def number(fmt):
            return struct.unpack("<" + fmt, read(struct.calcsize("<" + fmt)))[0]
        def string():
            size = number("Q")
            e.require(size <= MAX_PROMPT, "gguf_string_limite")
            return read(size).decode("utf-8", errors="strict")
        def value(kind, nested=False):
            formats = {0:"B", 1:"b", 2:"H", 3:"h", 4:"I", 5:"i", 6:"f",
                       10:"Q", 11:"q", 12:"d"}
            if kind in formats:
                return number(formats[kind])
            if kind == 7:
                v = number("B")
                e.require(v in (0, 1), "gguf_bool")
                return bool(v)
            if kind == 8:
                return string()
            e.require(kind == 9 and not nested, "gguf_tipo")
            subtype, count = number("I"), number("Q")
            e.require(count <= 1000000 and subtype != 9, "gguf_array_limite")
            return [value(subtype, True) for _ in range(count)]
        e.require(read(4) == b"GGUF" and number("I") == 3, "gguf_formato")
        number("Q")  # tensor_count: tensor data are intentionally not read
        count = number("Q")
        e.require(count <= 100000, "gguf_kv_limite")
        result = {}
        for _ in range(count):
            key = string()
            e.require(key not in result, "gguf_chave_duplicada")
            result[key] = value(number("I"))
        after = os.fstat(stream.fileno())
        e.require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                  (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "gguf_mudou")
        return result


def template_local(path, expected_hash, eos_policy=None):
    e.require(eos_policy is None or eos_policy == EOS_POLICY, "politica_bos_eos_diverge")
    meta = gguf_metadata(path, expected_hash)
    template = meta.get("tokenizer.chat_template")
    e.require(type(template) is str and e.digest(template.encode()) == TEMPLATE_SHA256,
              "template_hash_diverge")
    missing_eos = "tokenizer.ggml.add_eos_token" not in meta
    e.require(meta.get("tokenizer.ggml.model") == "gpt2" and
              meta.get("tokenizer.ggml.add_bos_token") is False and
              (meta.get("tokenizer.ggml.add_eos_token") is False or
               missing_eos and eos_policy == EOS_POLICY), "vocab_bos_eos_nao_qualificado")
    e.require(meta.get("general.architecture") == "qwen35", "arquitetura_nao_qualificada")
    tokens = meta.get("tokenizer.ggml.tokens")
    e.require(type(tokens) is list and tokens.count("<|im_end|>") == 1, "vocab_im_end")
    end = tokens.index("<|im_end|>")
    e.require(type(meta.get("tokenizer.ggml.eos_token_id")) is int and
              meta["tokenizer.ggml.eos_token_id"] == end, "vocab_eog_nao_qualificado")
    # Missing EOS metadata remains absent; IDs and each invocation must prove the path.
    return template.encode(), {"architecture": "qwen35", "model": "gpt2", "add_bos_token": False, "add_eos_token": None if missing_eos else False,
                               "bos_token_id": meta.get("tokenizer.ggml.bos_token_id"),
                               "im_end_id": end, "eos_token_id": end,
                               "bos_eos_origem": "ids_e_contagem_por_chamada" if missing_eos else "gguf"}


def assistant_template_messages(messages):
    """Render-only defaults; the validated role/content history stays unchanged.

    Fixed TEMPLATE_SHA256, lines 91-92: reasoning_content (is string).
    None preserves the missing-key fall-through at lines 93-97, including </think>.
    Lines 105-106: tool_calls (truth/iteration). An empty list preserves false.
    No tool/function fields are added: that branch stays unreachable when absent.
    """
    return [dict(message, **{key: value for key, value in
            (("reasoning_content", None), ("tool_calls", [])) if key not in message})
            if type(message) is dict and message.get("role") == "assistant" else message
            for message in messages]


def render(template, messages):
    e.require(type(template) is bytes and e.digest(template) == TEMPLATE_SHA256, "template_hash_diverge")
    try:
        import jinja2
        from jinja2.sandbox import ImmutableSandboxedEnvironment
        from jinja2.ext import loopcontrols
    except ImportError as exc:
        raise ValueError("jinja_ausente_sem_instalacao_automatica") from exc
    e.require(jinja2.__version__ == ENGINE["versao"], "jinja_versao_diverge")
    environment = ImmutableSandboxedEnvironment(undefined=jinja2.StrictUndefined,
        trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=False, autoescape=False,
        extensions=[loopcontrols])
    def fail(message):
        raise ValueError("template_recusou_entrada")
    environment.globals["raise_exception"] = fail
    raw = environment.from_string(template.decode("utf-8", errors="strict")).render(
        messages=assistant_template_messages(messages), **KWARGS).encode("utf-8")
    e.require(0 < len(raw) <= MAX_PROMPT and b"\x00" not in raw, "prompt_limite")
    return raw


def prepare(dt, criterion, gguf_path):
    """Retorna DT preparada para revisão; não grava, não lança e não autoriza."""
    profile = profile_ok(dt)
    e.require(dt["artefato"]["sha256"] == profile["model_sha256"], "preparacao_modelo_diverge")
    template, vocab = template_local(gguf_path, profile["model_sha256"], profile["bos_eos"])
    tasks = criterion["criterio"]["tarefas"]
    e.require(len(tasks) == 3 and len({t["id"] for t in tasks}) == 3, "prompts_tarefas")
    prompts = {}
    for task in tasks:
        raw = render(template, [{"role": "user", "content": task["enunciado"]}])
        # --file removes exactly one terminal LF; append one transport LF.
        prompts[task["id"]] = {"entrada_sha256": e.digest(task["enunciado"].encode()),
                              "efetivo": blob(raw), "arquivo": blob(raw + b"\n"),
                              "tokens_entrada": None, "tokenizacao": None}
    prepared = {"schema": "sc-prompts-cpu/1", "perfil_sha256": e.digest(e.canonical(profile)),
                "criterio_canonico_sha256": e.digest(e.canonical(criterion)), "engine": copy.deepcopy(ENGINE),
                "kwargs": copy.deepcopy(KWARGS), "template": blob(template),
                "vocabulario": vocab, "prompts": prompts}
    result = copy.deepcopy(dt)
    result["executor"]["preparacao_cpu"] = prepared
    result["executor"]["preparacao_cpu_sha256"] = e.digest(e.canonical(prepared))
    return result


def profile_ok(dt):
    executor = dt["executor"]
    profile = executor["perfil_proposto"]
    e.require(e.digest(e.canonical(profile)) == executor["perfil_sha256"] == e.PERFIL_CPU_SHA256,
              "perfil_diverge")
    e.require(profile.get("bos_eos") == EOS_POLICY, "politica_bos_eos_diverge")
    return profile


def preparation_ok(dt, criterion=None):
    profile = profile_ok(dt)
    ex = dt["executor"]
    value = ex["preparacao_cpu"]
    e.exact(value, ["schema", "perfil_sha256", "criterio_canonico_sha256", "engine", "kwargs",
                    "template", "vocabulario", "prompts"])
    e.require(value["schema"] == "sc-prompts-cpu/1" and
              e.digest(e.canonical(value)) == ex["preparacao_cpu_sha256"] == e.PREPARACAO_CPU_SHA256 and
              value["perfil_sha256"] == e.PERFIL_CPU_SHA256, "preparacao_diverge")
    e.require(value["engine"] == ENGINE and value["kwargs"] == KWARGS, "renderer_diverge")
    e.require(e.digest(unblob(value["template"], MAX_PROMPT)) == TEMPLATE_SHA256,
              "template_hash_diverge")
    vocab = value["vocabulario"]
    e.exact(vocab, ["architecture", "model", "add_bos_token", "add_eos_token", "im_end_id", "eos_token_id", "bos_token_id", "bos_eos_origem"])
    e.require(vocab["architecture"] == "qwen35" and vocab["model"] == "gpt2" and vocab["add_bos_token"] is False and
              ((vocab["bos_eos_origem"] == "gguf" and vocab["add_eos_token"] is False) or
               (vocab["bos_eos_origem"] == "ids_e_contagem_por_chamada" and vocab["add_eos_token"] is None)) and
              (vocab["bos_token_id"] is None or type(vocab["bos_token_id"]) is int and vocab["bos_token_id"] >= 0) and
              type(vocab["im_end_id"]) is int and vocab["im_end_id"] >= 0 and
              vocab["im_end_id"] == vocab["eos_token_id"], "vocab_diverge")
    e.require(type(value["prompts"]) is dict and len(value["prompts"]) == 3, "prompts_tarefas")
    for key, prompt in value["prompts"].items():
        e.require(type(key) is str and e.TASK.fullmatch(key), "prompt_tarefa")
        e.exact(prompt, ["entrada_sha256", "efetivo", "arquivo", "tokens_entrada", "tokenizacao"])
        # Count must be measured with the pinned tokenizer, reviewed together
        # with these exact bytes, and covered by the independent preparation pin.
        prompt_budget(prompt["tokens_entrada"], profile["geracao"]["max_tokens"],
                      profile["geracao"]["n_ctx"])
        raw = unblob(prompt["efetivo"], MAX_PROMPT)
        transport = unblob(prompt["arquivo"], MAX_PROMPT + 1)
        e.require(raw and b"\x00" not in raw and transport == raw + b"\n", "prompt_transporte")
        proof = prompt["tokenizacao"]
        e.exact(proof, ["schema", "task", "model_sha256", "perfil_sha256", "tokenizer_sha256",
                        "ids_stdout", "resultado"])
        e.require(proof["schema"] == "sc-tokenizacao-cpu/1" and proof["task"] == key and
                  proof["model_sha256"] == profile["model_sha256"] and
                  proof["perfil_sha256"] == e.PERFIL_CPU_SHA256 and
                  type(proof["tokenizer_sha256"]) is str and e.HASH.fullmatch(proof["tokenizer_sha256"]),
                  "tokenizacao_vinculo")
        ids = e.strict_json(unblob(proof["ids_stdout"], MAX_STDERR))
        e.require(type(ids) is list and ids and all(type(i) is int and i >= 0 for i in ids),
                  "token_ids")
        checked = proof["resultado"]
        e.exact(checked, ["P", "first_id", "last_id", "last_piece", "prompt_sha256",
                          "scope", "operational_go"])
        # Reconstruction was done against the hashed GGUF at binding. This
        # check does not replace that read or the independent native-capture pin.
        e.require(type(checked["P"]) is int and checked["P"] == len(ids) == prompt["tokens_entrada"] and
                  type(checked["first_id"]) is int and checked["first_id"] == ids[0] and
                  type(checked["last_id"]) is int and checked["last_id"] == ids[-1] and
                  checked["prompt_sha256"] == e.digest(raw) and
                  checked["scope"] == "provided_ids_byte_consistency_only" and checked["operational_go"] is False and
                  (vocab["bos_token_id"] is None or ids[0] != vocab["bos_token_id"]) and
                  ids[-1] != vocab["eos_token_id"], "tokenizacao_diverge")
        last_piece = unblob(checked["last_piece"], MAX_PROMPT)
        e.require(last_piece and raw.endswith(last_piece), "token_ultimo_piece")
    e.require(len({p["tokenizacao"]["tokenizer_sha256"] for p in value["prompts"].values()}) == 1,
              "tokenizador_diverge")
    if criterion is not None:
        e.require(value["criterio_canonico_sha256"] == e.digest(e.canonical(criterion)), "prompt_criterio")
        tasks = criterion["criterio"]["tarefas"]
        e.require(set(value["prompts"]) == {t["id"] for t in tasks}, "prompts_tarefas")
        for task in tasks:
            e.require(value["prompts"][task["id"]]["entrada_sha256"] ==
                      e.digest(task["enunciado"].encode()), "prompt_entrada")
    return value


def closed_arguments(profile, executable, model, prompt_file, turn=None):
    """Closed profile argv, without authority; only the two signed M1 budgets differ."""
    e.require(e.digest(e.canonical(profile)) == e.PERFIL_CPU_SHA256, "perfil_hash_diverge")
    g = copy.deepcopy(profile["geracao"])
    if turn is not None:
        e.require(type(turn) is int and turn in (1, 2), "m1_turn")
        g.update(max_tokens=512 if turn == 1 else 2048, n_ctx=8192)
    for value in (executable, model, prompt_file):
        e.require(type(value) is str and Path(value).is_absolute() and "\x00" not in value, "invocacao_path")
    argv = [executable, "--model", model, "--file", prompt_file, "--no-conversation",
            "--no-jinja", "--no-escape", "--no-display-prompt", "--simple-io",
            "--no-warmup", "--no-context-shift", "--seed", str(g["seed"]),
            "--override-kv", profile["bos_eos"]["completion_override_kv"]]
    flags = {"temperatura":"--temp", "max_tokens":"--predict", "n_ctx":"--ctx-size",
             "threads":"--threads", "threads_batch":"--threads-batch", "batch_size":"--batch-size",
             "ubatch_size":"--ubatch-size", "gpu_layers":"--gpu-layers", "flash_attn":"--flash-attn",
             "top_k":"--top-k", "top_p":"--top-p", "min_p":"--min-p", "typical_p":"--typical",
             "repeat_penalty":"--repeat-penalty", "repeat_last_n":"--repeat-last-n",
             "presence_penalty":"--presence-penalty", "frequency_penalty":"--frequency-penalty",
             "mirostat":"--mirostat", "dry_multiplier":"--dry-multiplier",
             "xtc_probability":"--xtc-probability", "samplers":"--samplers"}
    e.require(set(g) == {"seed", *flags}, "perfil_geracao")
    for key, flag in flags.items():
        argv += [flag, str(g[key])]
    return argv


def arguments(dt, task, executable, model, prompt_file):
    profile = profile_ok(dt)
    preparation_ok(dt)
    e.require(task in dt["executor"]["preparacao_cpu"]["prompts"], "prompt_tarefa")
    return closed_arguments(profile, executable, model, prompt_file)



def tokenization_bytes_ok(ids_stdout, meta, rendered):
    """Pure consistency check of collected IDs; not a native capture/authorization."""
    ids = e.strict_json(ids_stdout)
    tokens = meta.get("tokenizer.ggml.tokens")
    e.require(type(tokens) is list and type(ids) is list and ids and
              all(type(x) is int and 0 <= x < len(tokens) for x in ids), "token_ids")
    e.require(type(rendered) is bytes and 0 < len(rendered) <= MAX_PROMPT, "token_prompt")
    eos = meta.get("tokenizer.ggml.eos_token_id")
    e.require(type(eos) is int and 0 <= eos < len(tokens) and tokens[eos] == "<|im_end|>", "token_eos")
    bos = meta.get("tokenizer.ggml.bos_token_id")
    e.require(bos is None or type(bos) is int and 0 <= bos < len(tokens), "token_bos")
    e.require((bos is None or ids[0] != bos) and ids[-1] != eos, "token_bos_eos_extra")
    # GPT-2 byte-to-Unicode inverse; special token strings use literal ASCII.
    visible = list(range(33,127))+list(range(161,173))+list(range(174,256))
    inverse = {chr(x):x for x in visible}
    for index,byte in enumerate(x for x in range(256) if x not in visible):
        inverse[chr(256+index)] = byte
    pieces = []
    total = 0
    for index in ids:
        token = tokens[index]
        e.require(type(token) is str and token and all(x in inverse for x in token), "token_piece")
        piece = bytes(inverse[x] for x in token)
        total += len(piece)
        e.require(total <= MAX_PROMPT, "token_prompt")
        pieces.append(piece)
    e.require(b"".join(pieces) == rendered, "token_bytes_divergem")
    return {"P":len(ids), "first_id":ids[0], "last_id":ids[-1],
            "last_piece":blob(pieces[-1]), "prompt_sha256":e.digest(rendered),
            "scope":"provided_ids_byte_consistency_only", "operational_go":False}



def bind_tokenizations(dt, gguf_path, tokenizations, tokenizer_sha256):
    """Bind collected stdout once; no native execution or independent pin creation."""
    profile = profile_ok(dt)
    e.require(type(tokenizer_sha256) is str and e.HASH.fullmatch(tokenizer_sha256), "tokenizador_pin")
    result = copy.deepcopy(dt)
    prepared = result["executor"]["preparacao_cpu"]
    e.require(e.digest(e.canonical(prepared)) == dt["executor"]["preparacao_cpu_sha256"] and
              prepared["perfil_sha256"] == e.digest(e.canonical(profile)), "preparacao_diverge")
    e.require(type(tokenizations) is dict and set(tokenizations) == set(prepared["prompts"]) == {"T1", "T2", "T3"},
              "tokenizacao_tarefas")
    e.require(all(p["tokens_entrada"] is None and p["tokenizacao"] is None
                  for p in prepared["prompts"].values()), "tokenizacao_ja_vinculada")
    meta = gguf_metadata(gguf_path, profile["model_sha256"])
    for task, prompt in prepared["prompts"].items():
        raw_ids = tokenizations[task]
        e.require(type(raw_ids) is bytes and len(raw_ids) <= MAX_STDERR, "token_ids_limite")
        checked = tokenization_bytes_ok(raw_ids, meta, unblob(prompt["efetivo"], MAX_PROMPT))
        e.require(meta.get("tokenizer.ggml.eos_token_id") == prepared["vocabulario"]["eos_token_id"] and
                  meta.get("tokenizer.ggml.bos_token_id") == prepared["vocabulario"]["bos_token_id"],
                  "token_vocab_diverge")
        e.require(checked["P"] > 1, "prompt_contagem_nao_informativa")
        prompt_budget(checked["P"], profile["geracao"]["max_tokens"], profile["geracao"]["n_ctx"])
        prompt["tokens_entrada"] = checked["P"]
        prompt["tokenizacao"] = {"schema": "sc-tokenizacao-cpu/1", "task": task,
            "model_sha256": profile["model_sha256"], "perfil_sha256": prepared["perfil_sha256"],
            "tokenizer_sha256": tokenizer_sha256, "ids_stdout": blob(raw_ids), "resultado": checked}
    result["executor"]["preparacao_cpu_sha256"] = e.digest(e.canonical(prepared))
    return result  # PREPARACAO_CPU_SHA256 stays independent and unchanged.


B11960_INFO_PREFIX = rb"[0-9]+\.[0-9]{2}\.[0-9]{3}\.[0-9]{3} I "


def prompt_eval_count(stderr):
    lines = [line for line in stderr.splitlines(keepends=True) if b"prompt eval time" in line]
    number = rb"[0-9]+\.[0-9]{2}"
    pattern = (B11960_INFO_PREFIX + rb"common_perf_print: prompt eval time = +" + number +
               rb" ms / +([0-9]{1,10}) tokens \( *" + number +
               rb" ms per token, *" + number + rb" tokens per second\)\n")
    match = re.fullmatch(pattern, lines[0]) if len(lines) == 1 else None
    return int(match[1]) if match else None


def prompt_budget(tokens_entrada, max_tokens, n_ctx):
    e.require(all(type(v) is int for v in (tokens_entrada, max_tokens, n_ctx)) and
              tokens_entrada > 0 and max_tokens > 0 and
              tokens_entrada + max_tokens <= n_ctx - 4, "prompt_contagem_ou_contexto")


def capture(stdout, stderr, returncode, tokens_entrada=None, max_tokens=None, n_ctx=None):
    e.require(type(stdout) is bytes and len(stdout) <= e.MAX_SAIDA and
              type(stderr) is bytes and len(stderr) <= MAX_STDERR, "captura_limite")
    e.require(type(returncode) is int, "captura_exit")
    present = stdout.endswith(SUFFIX)
    # b11960 completion calls common_perf_print, not llama_perf_sampler_print.
    # Chain accepts prompt tokens too; its count is not the generated count.
    lines = [line for line in stderr.split(b"\n") if b"samplers time" in line]
    match = re.fullmatch(B11960_INFO_PREFIX + rb"common_perf_print:    samplers time = +[0-9]+\.[0-9]{2} ms / +([0-9]{1,10}) tokens",
                         lines[0]) if len(lines) == 1 else None
    total = int(match[1]) if match else None
    prompt_count = prompt_eval_count(stderr)
    prompt_matches = type(tokens_entrada) is int and tokens_entrada > 1 and prompt_count == tokens_entrada
    generated = None
    if all(type(v) is int for v in (tokens_entrada, max_tokens, n_ctx)):
        prompt_budget(tokens_entrada, max_tokens, n_ctx)
        if total is not None and prompt_matches:
            generated = total - tokens_entrada
    eog = (returncode == 0 and present and stdout.count(MARKER) == 1 and
           generated is not None and 0 < generated < max_tokens)
    # A missing/ambiguous proof never licenses removing any byte. In particular
    # the identical token-limit collision retains its complete invalid output.
    boundary = prompt_matches and (eog or (returncode == 0 and MARKER not in stdout))
    output = stdout[:-len(SUFFIX)] if eog else stdout
    return {"stdout": blob(stdout), "stderr": blob(stderr), "returncode": returncode,
            "marcador_presente": present, "fronteira_valida": boundary,
            "tokens_aceitos": total, "tokens_prompt_runtime": prompt_count,
            "contagem_prompt_valida": prompt_matches, "tokens_gerados_incluindo_eog": generated,
            "motivo": "contagem_prompt_ausente_ambigua_ou_divergente" if not prompt_matches else
                      "eog_contagem_vinculada" if eog else
                      ("sem_marcador" if boundary else "termino_ambiguo_ou_falha"),
            "saida": blob(output)}


def invocation_record(dt, task, executable, model, prompt_file, stdout, stderr, returncode):
    prepared = preparation_ok(dt)
    argv = arguments(dt, task, executable, model, prompt_file)
    return {"schema": "sc-invocacao-cpu/1", "perfil_sha256": e.PERFIL_CPU_SHA256,
            "preparacao_sha256": dt["executor"]["preparacao_cpu_sha256"],
            "prompt_sha256": prepared["prompts"][task]["efetivo"]["sha256"],
            "argv": argv, "argv_sha256": e.digest(e.canonical(argv)),
            "captura": capture(stdout, stderr, returncode,
                prepared["prompts"][task]["tokens_entrada"],
                dt["executor"]["perfil_proposto"]["geracao"]["max_tokens"],
                dt["executor"]["perfil_proposto"]["geracao"]["n_ctx"])}


def verify_invocation(value, dt, task):
    e.exact(value, ["schema", "perfil_sha256", "preparacao_sha256", "prompt_sha256",
                    "argv", "argv_sha256", "captura"])
    argv = value["argv"]
    e.require(type(argv) is list and len(argv) > 5, "invocacao_argv")
    e.require(argv == arguments(dt, task, argv[0], argv[2], argv[4]), "invocacao_argv")
    cap = value["captura"]
    stdout, stderr = unblob(cap["stdout"], e.MAX_SAIDA), unblob(cap["stderr"], MAX_STDERR)
    expected = invocation_record(dt, task, argv[0], argv[2], argv[4], stdout, stderr, cap["returncode"])
    e.require(e.canonical(value) == e.canonical(expected), "invocacao_diverge")
    return unblob(cap["saida"], e.MAX_SAIDA), cap["fronteira_valida"]


def invoke(dt, criterion, task, executable, model, prompt_file, timeout_s):
    """Library only: caller must provide qualified isolation/owner authority.

    Real pins are unset in the candidate; no operational CLI or automatic retry.
    """
    e.conferir_dt(dt)
    preparation_ok(dt, criterion)
    e.require(os.geteuid() == 991 and os.getegid() == 991, "invocacao_uid_gid")
    e.require(type(timeout_s) in (int, float) and 0 < timeout_s <= 900, "invocacao_timeout")
    from .juiz_base import protected_path
    for path in (executable, model, prompt_file):
        protected_path(path)
    e.require(e.digest(Path(executable).read_bytes()) == e.EXECUTOR_SHA256, "executor_sha256_diverge")
    template_local(model, e.ARTEFATO_SHA256, profile_ok(dt)["bos_eos"])
    prompt = dt["executor"]["preparacao_cpu"]["prompts"][task]
    e.require(Path(prompt_file).read_bytes() == unblob(prompt["arquivo"], MAX_PROMPT + 1),
              "prompt_arquivo_diverge")
    argv = arguments(dt, task, str(executable), str(model), str(prompt_file))
    completed = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
        timeout=timeout_s, check=False,
        env={"PATH":"/usr/bin:/bin", "HOME":"/nonexistent", "LANG":"C.UTF-8"})
    return invocation_record(dt, task, str(executable), str(model), str(prompt_file),
                             completed.stdout, completed.stderr, completed.returncode)

# Revisão final do Claude — B05

- Pedido nativo: `blocos/B05/revisoes/pedido-7bafddb25670.json`, publicado em main `64efde7`, sha256 `9b54c2149427055e53300ee1e3f5b19c4507e3a970f0354fdb040c5676cb6347` (recalculado pelo Claude).
- Alvo: `7bafddb25670a6bbd026c5e15aec7a9e06d823e0`. Base do Claude: `2b3034b81b7f5bdb6c19ebd55e3a5c2453825454` (alvo da revisão do Claude no B04), ancestral do alvo.
- Sessão: sessão de nuvem do Claude (link interno, não público)
- Veredito: **com achados**. Um achado alto, que já existia: CL-B04-04, que agora bloqueia a revisão do Antigravity no próprio B05. Nenhum achado novo contra o conteúdo do B05.

## Método e limites

- Revisão feita só pelo revisor principal, sem agentes em paralelo. Proporcional (ordem 12): cobre o delta desde a base, apoiada nas revisões assinadas que o Claude já fez de cada passo do B05, conferidas de novo onde a ficha exige.
- Nenhuma inferência, nenhuma CI nova, nenhum acesso à VPS. As afirmações sobre a instalação vêm das evidências versionadas.
- Cegamento: não li referência, gabarito, parecer reservado, comparação do guardião nem anexo do guardião. O Claude conhece apenas o fato de a comparação ter sido feita pelo dono.

## Cobertura do código desde a base

Os arquivos de código que mudaram entre `2b3034b` e o alvo têm, no alvo, os bytes aprovados nos pareceres assinados abaixo, todos com assinatura SSH conferida criptograficamente agora:

- `controle/cpu_exec.py`, `cpu_launcher.py`, `m1_exec.py`, `m1.py`, `frontend_cpu.py`, `executor_modelo.py` e `harness.py`: iguais aos hashes do manifesto 07 `7e8df498…` (parecer `4b9ea6b`). Esses são também os hashes fixados em `controle/conferencia_b05.py`.
- `controle/blocos.py`, `revisao_juiz.py`, `review_packet.py`, `antigravity_b04.py` e `claude_b04.py`:
  - rota canônica e contingência: pareceres `fdfe14e` (candidata `38facba`) e `50d7654` (candidata `8b01691`, ato conjunto `bb33a7f`);
  - emenda de forma B05-FICHAS-01: pareceres `013ecc0` e `09c78b6` (candidata `92dafca`).
- `controle/release_lot.py`: parecer `1fefbdf` (conferência documental M1, `56c5d52`).
- `controle/verificador.py`: parecer `ea26f88` (preparo B06 de literais, `7d52ae9`). Entrou em main durante o B05, não é usado pelo B05 e não autoriza B06.
- Promoção da emenda (`e00f04e`): os oito arquivos do manifesto `4209fe3e…` têm em main os mesmos bytes da candidata `92dafca`. O ato `8e830a9` (OpenPGP do dono pelo GitHub) tem exatamente os bytes `943553ff…` aprovados.
- CI da candidata da emenda: run `41441645358`, 1016/1016 testes em 18 suítes. A conclusão `failure` veio só de `plano_alterado_sem_registro`, antes do ato.

## Itens do bloco

**B05-01, DT do executor.** A ficha emendada lê a DT preparada04 `aa586411…`. Rodei `python3 controle/conferencia_b05.py conferir-dt04` duas vezes: as duas saídas foram iguais, `DT_COERENTE; vinculo04 mecanico, sem nova execucao`.

**B05-02, teste CPU.** Rodei `python3 controle/conferencia_b05.py conferir-cpu01` duas vezes: as duas saídas foram iguais, `TESTE_CPU_CONFERIDO REPROVADO; vinculo03 mecanico, sem nova execucao`.
- O resultado primário continua REPROVADO 6/9, com o critério 01, o resultado `574d221b…` e o log `0255b176…` sem mudança.
- A qualificação 2 (9/9, critério 02) fica separada e não substitui a primária.

**B05-03, M1.** O congelamento `0abf77a2…` passou em `release_lot.py conferir-m1` (`M1_CONFERIDO`).
- Primária M1-06: inconclusiva pelo contrato (duas recusas V1 e o teto de 30 minutos); o estado nativo continua `incidente`.
- Secundária M1-R: aceita e selada na primeira tentativa (selo `e9346296…`). Foi pré-registrada depois da falha e não é réplica independente.
- O corpo cego v2 foi congelado antes da comparação (corpo `b55c1615…`, recibo `59783337…`). A comparação foi feita só pelo dono e nada dela entrou no projeto.

## Linhas exigidas pelas fichas

O sentido de "sessão distinta" nas linhas V9 é o mesmo do campo `revisor.sessao_distinta` das DTs: o confirmador é uma sessão diferente da do autor (Codex). Os pareceres citados foram escritos nesta mesma sessão do Claude.
- Hoje refiz a conferência de cada um sem confiar em memória: verifiquei a assinatura Ed25519 do SSHSIG (namespace git) contra a `CLAUDE_PUBLIC_KEY` de `controle/blocos.py`. Os cinco são válidos e têm autor `noreply@anthropic.com`. O controle negativo (mensagem adulterada) falha, como deve.
- Os hashes dos dois pareceres de preparação e o campo `vinculo_preparacao` de cada um são iguais aos fixados no conferidor.
- A confirmação das DTs está nos pareceres históricos: `166418e` e `9210619` aprovaram as versões anteriores da DT do executor. `2d4f43d` aprovou o manifesto `a8e22dc6…`, que fixa a DT final `f0e619df…` e o critério `5d53ae93…`.

B05-FICHAS-01 B05-01: confirmei por sessao distinta a assinatura nativa do parecer 1df2600ce0c6fca37fc84cb0fa865f3207a88259 SHA256 56e2571970c88c8fe8ea26eb5f6f6dfad14980a05336d99b8a920fffd2c40bf9 e seu vinculo exato manifesto d87d110c78b538fdf1aeee5d1b069104047c0e4d660d237ab030af15a39f5a67, base f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441, criterio 280d14b305f831957c25075d772716792d1d895fe1cb593c56f8d233b052680b, DT preparada aa58641191ddccc1bdf5bff1ef64bbf77c7973f48f42186cb1b37807b5c62737, preparacao CPU 92099d45dee7c49cc74f5082628a0641b114c06dfdb78aa1fe3c2fd43c2410f8; confirmacao das DTs nos pareceres historicos 166418e, 9210619 e 2d4f43d conferida; criterios e resultado primario REPROVADO preservados: conforme.

B05-FICHAS-01 B05-02: confirmei por sessao distinta a assinatura nativa do parecer 515be0157f3c337dde36f44e623051a6f01540be SHA256 667acfd83a94f9c8f878ecfbb811a6c4cfd4e825e67f8a52125055bcca747dc4 e seu vinculo exato manifesto 1a991fb36e80eedb2d66c4b326c5b470a5210d6f2c55ea951fa6f04c443d3bbe, base f0e619dff820c5d61340a8131507cda9e8e022cc26f642bb245e59d603ec4441, criterio 5d53ae937e4e7ca197fecd0fc756ff5bbd64e17fa3db8373086abaaf2791a9d1, DT preparada d652bab4251dce76ae452ac9a70aec9fa180a182ea38468727dd1cb547f781a4, preparacao CPU cdcb1065030dda2c14ccc0223b6f0605c3a0271f53045190a1bba58eca986bee; confirmacao das DTs nos pareceres historicos 166418e, 9210619 e 2d4f43d conferida; criterios e resultado primario REPROVADO preservados: conforme.

M1 B05-03: constantes conferidas contra CODATA e NIST por revisor distinto do autor: conforme

Explicação da linha B05-03, conferida por conta própria: o arquivo `docs/evidencias/bloco5-2026-10-31/m1/constantes.json` (sha256 `67a1ce31…`, igual ao do congelamento, autor custodia-dono) tem `"constantes": []`. A etapa M1 só divide dois valores de entrada dados (Q = Y/E_in) e não usa nenhuma constante física. A conformidade com CODATA e NIST é, portanto, vazia: não há constante a comparar, e não houve divergência.

## Achado

**CL-B04-04 (alta), aberto no B04 e agora no caminho do B05.** A revisão do Antigravity não pode ser transportada.
- O delta da base dele (`b9fac75`) até o alvo tem 4541 caminhos, e o construtor e o juiz exigem no máximo 1000.
- Desses, 4374 estão em `docs/evidencias/` e `coord/` (recibos brutos, logs de teste e coordenação). Só 167 caminhos ficam fora dessas pastas (código, decisões, fichas, blocos).
- Nenhuma tentativa foi iniciada nem consumida, e a política e os limites não mudaram. Correto.
- Diagnóstico: não é defeito do conteúdo do B05. É o teto do pacote integral, previsto no B04.
- Caminhos possíveis, todos com enquadramento aprovado antes de qualquer uso:
  1. Emenda estreita do pacote do Antigravity para o B05: uma lista fechada de pastas de evidência bruta fica fora do conteúdo e entra só por inventário com hash. O teto de 1000 e a base não mudam, e os arquivos de evidência que as fichas citam continuam dentro. Exige candidata, CI, parecer do Claude e ato do dono.
  2. Dispensa assinada pelo dono (`DISPENSA REVISAO B05 antigravity`). O juiz também exige duas tentativas reais registradas, e criar tentativas que se sabe que vão falhar seria artificial. Não recomendo.
  3. Manter o B05 aberto e declarar o fechamento pendente. O artigo da ordem 18 não depende do fechamento formal.

## Observações de baixa gravidade (sem pedido de mudança de bytes)

- O registro cumulativo `36e3d037… → 3956f92e…` em `blocos/PLANO_ALTERACOES.json` (`02f4d97`) é a composição de duas transições assinadas: `bb33a7f` (`36e3… → 0601…`) e `8e830a9` (`0601… → 3956…`). Os registros anteriores foram preservados: os 14 primeiros itens são iguais, só mudou a formatação, e foi acrescentado um item. O texto do ato autoriza literalmente só `0601… → 3956…`. O fechamento deve citar os dois atos.
- Main ficou com `controle/test_executor_modelo.py` antigo e vermelho entre as promoções qualificadas e `e00f04e`. Nenhum relato deve dizer que main passou na CI integral nesse intervalo.
- Para o artigo: manter a primária inconclusiva, a M1-R como secundária e não independente, a Q2 separada e o REPROVADO 6/9.

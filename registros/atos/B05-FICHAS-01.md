# Ato B05-FICHAS-01 — emenda de forma para o fechamento nativo

Confirmo somente a emenda de forma abaixo, posterior aos resultados, porque as fichas antigas exigem confirmação dentro de DTs imutáveis, um esquema de resultado anterior e comandos sem vínculo com as preparações históricas. Aprovo apenas os bytes da candidata 92dafca594ca4173dbb02b8281c5279651ee8d20 delimitados pelo manifesto abaixo, depois da revisão assinada do Claude sobre código, testes, manifesto, texto integral e URL. O agente não pode assinar por mim.

fichas_manifesto_sha256: 4209fe3e548cefc27b9990f6127ed383f7565feceb829f24ae5740354daad924

EMENDA SOMENTE DE FORMA B05-01/B05-02; CRITERIOS, LIMIAR, TAREFAS, REPROVADO E PLANO PRESERVADOS.

AJUSTE B05 B05-01 MANIFESTO edb535ac45efa68c5b6e48b0ceff4b1a62709c3600caa2f9acda3927c70d53ca FICHA 3c75917073a6c098804238b5276de70d20c0f387e6f91c41067f5e2db2f158ff -> 38260f95743583026987a5725714792d3354876282a237b83babc5351eab6cea ACEITE 3b19d20ef2039b62050ea16a31db5fbf8658f213fff3a0d18c965ce5071b8c3e

AJUSTE B05 B05-02 MANIFESTO edb535ac45efa68c5b6e48b0ceff4b1a62709c3600caa2f9acda3927c70d53ca FICHA 40e80237edcaa6e2d2a232295998139e33ed718f6b611a5c08f4065714c97d9f -> 1b11950a81dc37c311ee53e3e10d1abde23a80a7af9067c27a0c59834bb8b0a7 ACEITE 4e9e06e1eda5b7a82f9ed886a301da9fee2d57712ce30f5750ea566cb3084ae3

Aprovo a mudanca do congelado com hash 3956f92e22089b70b176f3252abb1ffd0da027ef4bd326094c5a797402d59181.

Autorizo acrescentar, sem apagar registros anteriores, a transição do congelado 0601687904e464ea07bde7c0caad1072d07e86e8577869a7ce8cd56d37991217 para 3956f92e22089b70b176f3252abb1ffd0da027ef4bd326094c5a797402d59181 em blocos/PLANO_ALTERACOES.json, vinculada a docs/decisoes/confirmacoes/B05-FICHAS-01.md. PLANO.json e o manifesto original do B05 permanecem nos mesmos bytes e hashes.

B05-01 V1 passa a ler a DT preparada04 aprovada, SHA256 aa58641191ddccc1bdf5bff1ef64bbf77c7973f48f42186cb1b37807b5c62737. B05-01 e B05-02 passam ao tipo julgamento somente para admitir a confirmação externa nas linhas exatas V9, pelo parecer formal autenticado do Claude, com os commits, hashes e cinco vínculos históricos. Preservar todos os demais controles mecânicos e negativos; não preencher retroativamente campos de revisor nas DTs.

B05-02 V2 reconhece o esquema sc-teste-cpu/2 efetivamente produzido pelo código aprovado. O novo conferidor mecânico fechado usa preparação04 somente para conferir a DT preparada04; para a rodada primária usa exclusivamente preparação03, critério01, resultado01 e log01. Exige REPROVADO e não substitui a primária pela qualificação2. Hashes no conferidor não autenticam assinaturas: as assinaturas históricas são conferidas no host e confirmadas pelo Claude no fechamento nativo.

Autorizo promover ao repositório somente os oito arquivos de código, testes e fichas listados em docs/decisoes/B05-FICHAS-01-manifesto.json, nos hashes exatos, e os recibos de teste e metadados correspondentes. No juiz instalado, autorizo exclusivamente blocos.py SHA256 9af67f7e096a8ac2a8bb1b30701c65eb7c297d4fd82285b8337fbe80f7d6d4a6, com os dois pares fechados de emenda B05/B05-01 e B05/B05-02, e revisao_juiz.py SHA256 e3c3bf1b696befe0236ad2a704b37a9e73b41a37917fe024856a69a9417814dc, alterado somente no pin fixo do novo blocos.py. Partir do manifesto de instalação SHA256 61187f05b3c1e1eff17a1ea89573baac2bbdac4ed74ad3ee0b64409b76ca5f1d; atualizar apenas os metadados mínimos necessários e registrar a promoção. Preservar os demais módulos instalados, fiscal, recurso externo, kernel, AppArmor e sandbox.

A política de transporte será derivada somente do contrato aprovado, do pedido final do único bloco aberto e dos pins fixos revisados. Preservar a política histórica, os pedidos e todos os consumos; nenhum pin vivo, tentativa artificial, retry ou aumento de limites. Não repetir CI sobre os mesmos bytes. A CI da candidata final é 41441645358, tentativa1; seus testes administrativos precisam passar. A CI anterior41438475997 reprovou fixtures antigas incompatíveis com as fontes atuais; preservar seus recibos. Reintegrar somente o arquivo de testes já aprovado em4552b888, acrescido dos sete testes da conferência histórica, sem mudar fontes produtivas; a regressão focal passou64/64. Eventual bloqueio de autoridade pela ausência deste ato deve ser explicitado e conferido nativamente após a assinatura, nunca chamado de CI integral aprovada.

Depois da assinatura nativa conferida, da promoção qualificada e dos controles mecânicos aplicáveis, publicar HEAD final limpo e emitir novo pedido canônico B05 pelo juiz. Os checks dependentes dos pareceres serão satisfeitos somente com os dois pareceres externos autênticos: Claude e Antigravity. Cada revisor confere por conta própria a lista vazia de constantes e inclui a linha literal exigida por B05-03 com essa explicação. Nenhum pedido ou parecer histórico substitui a revisão final. Fechamento somente pelo caminho nativo, com todos os gates satisfeitos.

Continuam preservados critério, limiar, tarefas, plano e veredito primário B05-02 REPROVADO (6/9); a qualificação2 9/9 permanece separada. A primária M1-06 continua inconclusiva; M1-R é secundária aceita, não replicação independente. Preservar corpo cego v2 congelado, incidentes, registros e consumos. A comparação do guardião foi concluída exclusivamente pelo dono; seu conteúdo e resultado não entram no projeto.

Este ato não autoriza inferência, nova corrida, tokenização, execução de código gerado, download, instalação de pacotes, repetição do teste UID/GID991, comparação pelos agentes, leitura de referência, mudança de PARE/AVISO ou timer, GPU, API paga, B06 ou B07. Ordem17 permanece abandonada e os prazos vigentes não são estendidos. MODO NOTURNO encerrado por decisão expressa do dono; não criar novos alarmes.

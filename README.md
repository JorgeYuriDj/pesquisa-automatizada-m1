# Pesquisa automatizada — etapa M1

**Reprodução cega e verificada por contrato de uma etapa computacional publicada por um modelo de linguagem local de 9B: arquitetura e estudo de caso**

*Blinded, contract-verified reproduction of a published computational step by a local 9B language model: architecture and case study*

[English below](#english)

## Português

Este repositório é a cópia pública e organizada de um estudo de caso de pesquisa automatizada. Agentes de IA construíram, executaram e revisaram uma reprodução de uma etapa computacional publicada: o ganho científico de energia (Q_sci) de um disparo do National Ignition Facility. Um juiz automático e atos assinados pelo dono controlaram cada passo. A resposta publicada ficou sob custódia humana, fora do alcance dos agentes. O modelo avaliado foi o Qwen3.5-9B, quantizado em 4 bits e executado em CPU, sem rede.

**Situação:** versão de conferência de 2 de novembro de 2026. Os campos de autoria e as declarações ainda estão pendentes. O texto não foi submetido a nenhuma revista e não tem DOI.

### Resultado em uma frase

A corrida primária terminou inconclusiva (duas saídas recusadas por formato e limite de tempo atingido). Uma corrida secundária, escolhida depois da falha e registrada antes de rodar, foi aceita pelo contrato na primeira tentativa. Nada disso estabelece correção científica, efeito causal ou réplica independente; os detalhes e limites estão no artigo.

### Estrutura

```
artigo/
  pt/           artigo em português (Markdown e PDF)
  en/           artigo em inglês (Markdown e PDF)
  suplemento/   material suplementar (parâmetros, cronologia, REFORMS, trilha de auditoria)
  figuras/      figuras SVG em PT e EN, dados usados e o gerador
  render/       estilo e script usados para gerar os PDFs
etapa-m1/       pacote permitido da etapa: escopo, contrato, exemplos de formato,
                constantes (lista vazia) e congelamento
codigo/         código de referência da execução M1 (coletor, lançador, harness,
                verificador e conferência histórica)
  juiz/         núcleo do juiz automático (plano, fichas de aceite e revisões)
registros/
  plano/        plano de blocos e fichas de aceite do bloco 5
  decisoes/     decisões técnicas, critérios e manifesto da corrida M1-R
  atos/         atos do dono ligados à etapa M1
  corridas/     recibos das qualificações e das corridas M1-06 e M1-R
  revisoes/     parecer de fechamento do bloco 5 escrito pelo Claude
PROVENIENCIA.json   origem de cada arquivo no repositório de trabalho privado
SHA256SUMS          impressões digitais SHA-256 de todos os arquivos
```

### Como conferir

1. Integridade desta cópia: `sha256sum -c SHA256SUMS`.
2. Procedência: `PROVENIENCIA.json` liga cada arquivo ao caminho e ao commit do repositório de trabalho, que é privado. Os poucos arquivos alterados para a publicação estão marcados, com o motivo e as duas impressões digitais. As cópias de atos assinados que tiveram trechos redigidos (caminhos e identificadores da instalação privada) são derivadas e não valem como bytes assinados; os originais assinados ficam no repositório privado.
3. Os links internos de alguns registros apontam para o repositório privado e não abrem para o público; as impressões digitais permitem a conferência por quem tiver acesso autorizado.

### O que não está aqui, e por quê

- **A resposta publicada e a comparação.** O valor de referência está no trabalho de origem (Wurzel e Hsu, 2025, referência [3] do artigo). A comparação feita pelo guardião e o anexo do guardião são publicados pelo autor, separadamente.
- **A saída numérica do modelo.** Fica com a comparação, no anexo do guardião.
- **Registros brutos, transcrições e mensagens internas de coordenação.** Ficam no repositório de trabalho privado.
- **Credenciais, endereços de servidores e dados pessoais.** Esta cópia foi varrida antes da publicação em busca de chaves, tokens, senhas, e-mails pessoais, IPs, nomes de máquina e caminhos pessoais.
- **Pesos do modelo e binários.** São identificados por versão e hash no suplemento; não são redistribuídos.

### Cegamento

Nenhum gabarito, diferença, veredito ou dica volta aos agentes que executaram, verificaram ou redigiram o estudo. Quem for usar agentes de IA sobre este repositório deve manter o anexo do guardião fora do alcance deles.

### Licenças

- Código (`codigo/`, `artigo/figuras/gerar_figuras.py`, `artigo/render/`): Apache License 2.0, em `LICENSE`.
- Texto, figuras e dados documentais: Creative Commons Attribution 4.0 International, em `LICENSE-CC-BY-4.0.txt`.
- Materiais de terceiros mantêm suas próprias licenças (por exemplo, a checklist REFORMS e os pesos do modelo).

### Como citar e contato

Os dados de autoria, a forma de citar e o contato serão acrescentados quando o autor completar os campos pendentes do artigo.

---

## English

This repository is the public, curated copy of an automated research case study. AI agents built, ran, and reviewed the reproduction of one published computational step: the scientific energy gain (Q_sci) of a National Ignition Facility shot. An automatic judge and acts signed by the owner controlled each step. The published answer stayed in human custody, out of the agents' reach. The evaluated model was Qwen3.5-9B, quantized to 4 bits and run on CPU without network access.

**Status:** review version of 2 November 2026. Authorship fields and declarations are still pending. The text has not been submitted to any journal and has no DOI.

### Result in one sentence

The primary run ended inconclusively (two outputs rejected for format and the time limit reached). A secondary run, selected after the failure and registered before execution, was accepted by the contract on its first attempt. None of this establishes scientific correctness, a causal effect, or independent replication; details and limits are in the article.

### Layout

See the tree above: `artigo/` (article in PT and EN, supplement, figures, render), `etapa-m1/` (permitted step package), `codigo/` (reference code for the M1 run and the judge core), `registros/` (plan, acceptance cards, decisions, owner acts, run receipts, closing review), `PROVENIENCIA.json`, and `SHA256SUMS`.

### How to verify

1. Integrity of this copy: `sha256sum -c SHA256SUMS`.
2. Provenance: `PROVENIENCIA.json` maps each file to its path and commit in the private working repository. The few files changed for publication are flagged, with the reason and both hashes. Copies of signed acts with redacted passages (paths and identifiers of the private installation) are derivatives and do not count as signed bytes; the signed originals remain in the private repository.
3. Internal links in some records point to the private repository and do not open publicly; the hashes allow verification by anyone with authorized access.

### What is not here, and why

- **The published answer and the comparison.** The reference value is in the source work (Wurzel and Hsu, 2025, reference [3] of the article). The guardian's comparison and appendix are published by the author separately.
- **The model's numerical output.** It goes with the comparison, in the guardian's appendix.
- **Raw logs, transcripts, and internal coordination messages.** They remain in the private working repository.
- **Credentials, server addresses, and personal data.** This copy was scanned before publication for keys, tokens, passwords, personal e-mail addresses, IPs, machine names, and personal paths.
- **Model weights and binaries.** They are identified by version and hash in the supplement; they are not redistributed.

### Blinding

No reference answer, difference, verdict, or hint returns to the agents that executed, verified, or wrote the study. Anyone using AI agents on this repository should keep the guardian's appendix out of their reach.

### Licences

- Code (`codigo/`, `artigo/figuras/gerar_figuras.py`, `artigo/render/`): Apache License 2.0, in `LICENSE`.
- Text, figures, and documentary data: Creative Commons Attribution 4.0 International, in `LICENSE-CC-BY-4.0.txt`.
- Third-party materials keep their own licences (for example, the REFORMS checklist and the model weights).

### Citation and contact

Authorship data, citation format, and contact will be added when the author completes the pending fields of the article.

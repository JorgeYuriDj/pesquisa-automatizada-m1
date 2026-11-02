# Pesquisa automatizada — etapa M1

**Reprodução cega e verificada por contrato de uma etapa computacional publicada por um modelo de linguagem local de 9B: arquitetura e estudo de caso**

*Blinded, contract-verified reproduction of a published computational step by a local 9B language model: architecture and case study*

[English below](#english)

## Português

Este repositório é a cópia pública e organizada de um estudo de caso de pesquisa automatizada. Agentes de IA construíram, executaram e revisaram uma reprodução de uma etapa computacional publicada: o ganho científico de energia (Q_sci) de um disparo do National Ignition Facility. Um juiz automático e atos assinados pelo dono controlaram cada passo. A resposta publicada ficou sob custódia humana, fora do alcance dos agentes. O modelo avaliado foi o Qwen3.5-9B, quantizado em 4 bits e executado em CPU, sem rede.

**Situação:** preprint, versão 1, de 2 de novembro de 2026, lido e aprovado pelo autor. A versão de registro é a inglesa. O texto não foi revisado por pares nem submetido a revista. O depósito no Zenodo, com DOI, é feito pelo autor; o DOI será acrescentado aqui.

### Resultado em uma frase

A corrida primária terminou inconclusiva (duas saídas recusadas por formato e limite de tempo atingido). Uma corrida secundária, escolhida depois da falha e registrada antes de rodar, foi aceita pelo contrato na primeira tentativa. Nada disso estabelece correção científica, efeito causal ou réplica independente; os detalhes e limites estão no artigo.

### Estrutura

```
artigo/
  pt/           artigo em português (Markdown e PDF)
  en/           artigo em inglês (Markdown e PDF)
  suplemento/   material suplementar em Markdown e PDF (parâmetros, cronologia, REFORMS,
                trilha de auditoria)
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
CITATION.cff        dados de citação em formato legível por máquina
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

**Autor:** Jorge Yuri dos Santos Correa, pesquisador independente, Brasília, DF, Brasil. ORCID [0009-0006-7378-4098](https://orcid.org/0009-0006-7378-4098). Contato: crvenergia@gmail.com.

**Como citar (enquanto o DOI não existir):** Correa, J. Y. S. (2026). *Blinded, contract-verified reproduction of a published computational step by a local 9B language model: architecture and case study* (Preprint, versão 1). https://github.com/JorgeYuriDj/pesquisa-automatizada-m1

O trabalho original reproduzido é de Wurzel e Hsu (2025), DOI [10.1063/5.0297357](https://doi.org/10.1063/5.0297357); o mérito científico dele é dos autores originais, que não participaram deste estudo nem o endossam.

---

## English

This repository is the public, curated copy of an automated research case study. AI agents built, ran, and reviewed the reproduction of one published computational step: the scientific energy gain (Q_sci) of a National Ignition Facility shot. An automatic judge and acts signed by the owner controlled each step. The published answer stayed in human custody, out of the agents' reach. The evaluated model was Qwen3.5-9B, quantized to 4 bits and run on CPU without network access.

**Status:** preprint, version 1, of 2 November 2026, read and approved by the author. English is the version of record. The text has not been peer reviewed or submitted to a journal. The Zenodo deposit, with a DOI, is made by the author; the DOI will be added here.

### Result in one sentence

The primary run ended inconclusively (two outputs rejected for format and the time limit reached). A secondary run, selected after the failure and registered before execution, was accepted by the contract on its first attempt. None of this establishes scientific correctness, a causal effect, or independent replication; details and limits are in the article.

### Layout

See the tree above: `artigo/` (article in PT and EN, supplement, figures, render), `etapa-m1/` (permitted step package), `codigo/` (reference code for the M1 run and the judge core), `registros/` (plan, acceptance cards, decisions, owner acts, run receipts, closing review), `PROVENIENCIA.json`, `SHA256SUMS`, and `CITATION.cff`.

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

**Author:** Jorge Yuri dos Santos Correa, independent researcher, Brasília, DF, Brazil. ORCID [0009-0006-7378-4098](https://orcid.org/0009-0006-7378-4098). Contact: crvenergia@gmail.com.

**How to cite (until a DOI exists):** Correa, J. Y. S. (2026). *Blinded, contract-verified reproduction of a published computational step by a local 9B language model: architecture and case study* (Preprint, version 1). https://github.com/JorgeYuriDj/pesquisa-automatizada-m1

The reproduced original work is by Wurzel and Hsu (2025), DOI [10.1063/5.0297357](https://doi.org/10.1063/5.0297357); its scientific merit belongs to the original authors, who did not participate in or endorse this study.

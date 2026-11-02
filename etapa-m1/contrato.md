# Contrato da etapa M1-QSCI-N230729

Fixado pela custódia antes de qualquer resultado da reprodução. Vale para a corrida inteira e não muda durante ela.

## Entradas permitidas

- Arquivos do lote: escopo.md, contrato.md, exemplo_certo.md, exemplo_a_recusar.md e constantes.json. O lote também traz MANIFEST.txt, que só contém os hashes desses cinco arquivos para conferência de integridade e não é entrada. Nenhum outro arquivo, pasta ou endereço de rede.
- Campos de entrada: somente E_in e Y, com os valores, as unidades e as procedências de escopo.md, copiados sem alteração.
- Constantes físicas: somente as de constantes.json. A lista está vazia porque esta etapa não usa constantes.
- Os exemplos mostram só o formato. Seus números são fictícios e não podem ser usados como entrada.

## Operações permitidas

- ler as duas entradas de escopo.md;
- executar, numa ferramenta de cálculo em Python, um único bloco de código que atribui as duas entradas, calcula q = Y / E_in uma única vez por tentativa, em ponto flutuante de dupla precisão, e imprime, uma por linha e nesta ordem, repr(q) e format(q, ".3g");
- copiar a primeira linha impressa para saida.valor, como número, e a segunda para saida.valor_3_algarismos, como texto;
- escolher a frase de interpretação pela regra abaixo;
- entregar a saída no esquema abaixo.

Proibido: conta "de cabeça" ou número escrito sem execução; arredondar as entradas; converter unidades; usar qualquer número que não venha de escopo.md; acessar a rede, o artigo, figuras, tabelas ou outros arquivos; alterar o escopo, o contrato ou as entradas.

## Esquema exato da saída

Entregar somente um objeto JSON em UTF-8, sem cercas de código (as três crases do markdown) e sem nenhum texto antes ou depois, no arquivo de saída indicado pelo harness. O objeto tem exatamente estas chaves, nem mais nem menos. O ponto indica aninhamento: entradas.E_in.valor é a chave valor dentro de E_in, que está dentro de entradas.

| Chave | Tipo | Regra |
|---|---|---|
| etapa | texto | exatamente "M1-QSCI-N230729" |
| grandeza | texto | exatamente "Q_sci" |
| formula | texto | exatamente "Q_sci = Y / E_in" |
| entradas.E_in.valor | número | igual ao valor de E_in em escopo.md |
| entradas.E_in.unidade | texto | exatamente "J" |
| entradas.E_in.procedencia | texto | igual à procedência de E_in em escopo.md |
| entradas.Y.valor | número | igual ao valor de Y em escopo.md |
| entradas.Y.unidade | texto | exatamente "J" |
| entradas.Y.procedencia | texto | igual à procedência de Y em escopo.md |
| saida.valor | número | primeira linha impressa: repr(q), com q = Y / E_in |
| saida.valor_3_algarismos | texto | segunda linha impressa: format(q, ".3g") |
| saida.unidade | texto | exatamente "adimensional" |
| calculo.ferramenta | texto | exatamente "python" |
| calculo.codigo | texto | o código executado, completo |
| calculo.saida_bruta | texto | o que a execução imprimiu, sem edição |
| interpretacao | texto | uma das três frases abaixo, sem alteração |

Frase de interpretação, pela comparação de saida.valor com 1:

- maior que 1: "Q_sci > 1: a energia de fusão liberada (Y) superou a energia do laser (E_in)."
- menor que 1: "Q_sci < 1: a energia de fusão liberada (Y) foi menor que a energia do laser (E_in)."
- igual a 1: "Q_sci = 1: a energia de fusão liberada (Y) igualou a energia do laser (E_in)."

## Critérios de aceite

O verificador aplica estas regras sem conhecer nenhuma resposta publicada:

- V1. A saída é um único objeto JSON válido em UTF-8, com exatamente as chaves e os tipos do esquema.
- V2. etapa, grandeza, formula, calculo.ferramenta e as unidades são exatamente as do esquema: "J" nas entradas, "adimensional" na saída e "python" na ferramenta.
- V3. Os valores das entradas são iguais, em dupla precisão, aos de escopo.md, e as procedências são iguais às de escopo.md, caractere por caractere.
- V4. A diferença entre saida.valor e Y / E_in, recalculado pelo verificador a partir de escopo.md, é no máximo 1e-9 vezes o valor recalculado.
- V5. saida.valor_3_algarismos é igual a format(saida.valor, ".3g").
- V6. calculo.codigo e calculo.saida_bruta são idênticos ao que o harness registrou na execução. calculo.saida_bruta tem exatamente duas linhas, cada uma terminada por quebra de linha: a primeira é repr(saida.valor) e a segunda é saida.valor_3_algarismos.
- V7. interpretacao é a frase que corresponde a saida.valor pela regra acima.

## Comparação com a referência

Só a custódia faz a comparação, depois do selo, e o resultado dela nunca volta a quem executou a etapa. Há concordância se a diferença entre saida.valor e a referência publicada for no máximo 1 % da referência. Esta tolerância está fixada agora, antes de qualquer resultado da reprodução.

## Condições de parada

- Sucesso: o verificador aceita V1 a V7. A saída é congelada por hash, a etapa termina e não há nova tentativa.
- Inconclusiva: 3 saídas recusadas pelo verificador, 3 erros de execução ou 30 minutos de relógio sem saída aceita. A etapa fica inconclusiva; não se repete até "dar certo".
- Interrupção imediata, registrada como incidente: ordem PARE do dono; tentativa de acesso à rede ou a arquivo fora do lote; saída com número que não venha de escopo.md nem da calculo.saida_bruta registrada pelo harness; qualquer alteração do escopo, do contrato ou das entradas.
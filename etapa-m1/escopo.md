# Escopo da etapa M1-QSCI-N230729

## Rótulo

M1-QSCI-N230729: ganho científico de energia (Q_sci) do disparo N230729 do NIF.

## Objetivo

Calcular o ganho científico de energia Q_sci do disparo N230729 do National Ignition Facility (NIF), um experimento de fusão por confinamento inercial com laser em acionamento indireto, usando somente as duas entradas permitidas abaixo, e registrar o resultado no formato definido em contrato.md.

## Entradas permitidas

Somente estas duas. Os valores estão escritos exatamente como no arquivo de origem. A custódia extraiu os dois valores; o arquivo de dados completo não faz parte do lote. Cada procedência deve ser copiada sem alteração e sem as crases.

- `E_in` = `2.05e6` J, energia do laser.
  Procedência: `pacote dos autores: data/experimental_results.pkl, rótulo de índice 22 (Shot N230729), coluna E_ext`
- `Y` = `3.88e6` J, energia de fusão liberada (rendimento).
  Procedência: `pacote dos autores: data/experimental_results.pkl, rótulo de índice 22 (Shot N230729), coluna E_F`

## Método

    Q_sci = Y / E_in

Definição em base de energia para experimentos de fusão inercial com laser: razão entre a energia de fusão liberada (Y) e a energia do laser (E_in). Fonte: Wurzel & Hsu 2025, arXiv 2505.03834v6, legenda da Fig. 4, p. 15.

As duas entradas estão na mesma unidade (J). O cálculo não usa conversão de unidade nem constante física; por isso constantes.json traz a lista vazia.

## Saída

Uma única grandeza: Q_sci, adimensional. Vai como número de ponto flutuante de dupla precisão e também como texto com 3 algarismos significativos, junto com a frase de interpretação definida pela regra do contrato, tudo no esquema JSON de contrato.md.

## Fora do escopo

- qualquer outro disparo, experimento ou grandeza (parâmetro de Lawson, produto triplo, Q_fuel, Q_eng, ganho de tomada);
- Q_sci em base de potência, usada para tokamaks;
- propagação de incertezas;
- consultar o artigo, suas figuras ou tabelas, o arquivo de dados completo, a internet ou qualquer valor publicado;
- comparar o resultado com qualquer referência, o que só a custódia faz, depois do selo.
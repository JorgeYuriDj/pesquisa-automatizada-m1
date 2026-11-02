# Exemplo certo (fictício)

Exemplo INVENTADO, só para mostrar o formato do contrato. O disparo, os números e as procedências são fictícios: não vêm do artigo nem do pacote dos autores e não podem ser usados como entrada.

Escopo fictício deste exemplo: etapa EXEMPLO-FICTICIO-A; E_in = 1.34e6 J, procedência "exemplo fictício, campo E_in"; Y = 5.81e5 J, procedência "exemplo fictício, campo Y". Em relação a esse escopo, a saída abaixo está certa. Na etapa real, a etapa, as entradas e as procedências vêm de escopo.md, e a frase de interpretação sai da regra do contrato, pelo valor calculado.

As cercas de código abaixo só delimitam o exemplo neste arquivo; a saída real vai sem elas.

```json
{
  "etapa": "EXEMPLO-FICTICIO-A",
  "grandeza": "Q_sci",
  "formula": "Q_sci = Y / E_in",
  "entradas": {
    "E_in": {"valor": 1.34e6, "unidade": "J", "procedencia": "exemplo fictício, campo E_in"},
    "Y": {"valor": 5.81e5, "unidade": "J", "procedencia": "exemplo fictício, campo Y"}
  },
  "saida": {"valor": 0.4335820895522388, "valor_3_algarismos": "0.434", "unidade": "adimensional"},
  "calculo": {
    "ferramenta": "python",
    "codigo": "E_in = 1.34e6\nY = 5.81e5\nq = Y / E_in\nprint(repr(q))\nprint(format(q, \".3g\"))",
    "saida_bruta": "0.4335820895522388\n0.434\n"
  },
  "interpretacao": "Q_sci < 1: a energia de fusão liberada (Y) foi menor que a energia do laser (E_in)."
}
```

Por que está certo: tem todas as chaves e tipos do esquema; as entradas estão em "J", a saída é "adimensional" e a ferramenta é "python"; o código executado imprime repr(q) e format(q, ".3g"), e as duas linhas impressas foram copiadas para saida.valor e saida.valor_3_algarismos; e a frase de interpretação é a que corresponde a um valor menor que 1.
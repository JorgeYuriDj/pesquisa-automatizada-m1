# Exemplo a recusar (fictício)

Exemplo INVENTADO de saída que o verificador deve recusar. O disparo, os números e as procedências são fictícios: não vêm do artigo nem do pacote dos autores e não derivam de nenhuma resposta de referência.

Escopo fictício deste exemplo: etapa EXEMPLO-FICTICIO-B; E_in = 1.42e6 J, procedência "exemplo fictício, campo E_in"; Y = 1.11e6 J, procedência "exemplo fictício, campo Y".

```json
{
  "etapa": "EXEMPLO-FICTICIO-B",
  "grandeza": "Q_sci",
  "formula": "Q_sci = Y / E_in",
  "entradas": {
    "E_in": {"valor": 1.42e3, "unidade": "kJ", "procedencia": "exemplo fictício, campo E_in"},
    "Y": {"valor": 1.11e6, "unidade": "J"}
  },
  "saida": {"valor": 781.6901408450705, "valor_3_algarismos": "782", "unidade": "adimensional"},
  "calculo": {
    "ferramenta": "python",
    "codigo": "E_in = 1.42e3\nY = 1.11e6\nq = Y / E_in\nprint(repr(q))\nprint(format(q, \".3g\"))",
    "saida_bruta": "781.6901408450705\n782\n"
  },
  "interpretacao": "Q_sci > 1: a energia de fusão liberada (Y) superou a energia do laser (E_in)."
}
```

Motivos da recusa:

- Unidade errada: entradas.E_in.unidade é "kJ", e o contrato exige "J" (V2).
- Entrada diferente do escopo: entradas.E_in.valor está em kJ e não é o valor em J do escopo (V3).
- Campo obrigatório ausente: entradas.Y não tem "procedencia" (V1 e V3).
- Unidades misturadas: saida.valor divide joules por quilojoules, então não é Y / E_in com as duas energias em J (V4).
# -*- coding: utf-8 -*-
r"""Tabela de COMPOSIÇÃO FINANCEIRA: parcelas viram itens, resultados não.

O formato (ARTEMIS 207.2026) não tem quantidade nem preço unitário. É uma
lista de parcelas e, no meio delas, dois valores que NÃO são parcelas:

    Produtos (04 conjuntos completos de Racks + PDUs)   R$ 19.131,20  parcela
    Frete Rodoviário Total Estimado (Fracionado)        R$  6.300,00  parcela
    Investimento Bruto Global                           R$ 25.431,20  SUBTOTAL
    Desconto Especial Aplicado (12%)                  - R$  3.051,74  parcela
    VALOR FINAL LÍQUIDO DA PROPOSTA                     R$ 22.379,46  TOTAL

A referência é a AF pronta, preenchida à mão (AF-E-369/2026-GE): ela traz
exatamente três itens — Racks 19.131,20, Frete 6.300,00 e Desconto -3.051,74.

POR QUE A ARITMÉTICA, E NÃO PALAVRA-CHAVE
-----------------------------------------
Separar parcela de resultado por nome ("bruto", "subtotal", "líquido") é
adivinhação: cada fornecedor batiza do seu jeito, e a lista de nomes nunca
fica completa. A conta não depende de vocabulário — um valor igual à soma do
que veio antes é resultado, e pronto.

E a regra de segurança: só devolve itens se a soma deles bater com o total
anunciado. Item inventado é pior que item nenhum, porque vira dinheiro na AF.

O QUE ESTE TESTE GUARDA
-----------------------
  • o subtotal e o total NÃO viram item;
  • o desconto vira item NEGATIVO (sem ele a conta não fecha);
  • a soma bate com o total anunciado;
  • quando a conta NÃO fecha, o leitor devolve vazio em vez de chutar.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

from core.extrator import ExtratorProposta
from core.modelos import brl_para_float

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# o texto como o pdfplumber o entrega (medido no PDF real da ARTEMIS)
TEXTO = """3. COMPOSIÇÃO FINANCEIRA E RESUMO
Descrição do Componente Valor
Produtos (04 conjuntos completos de Racks + PDUs) R$ 19.131,20
Frete Rodoviário Total Estimado (Fracionado) R$ 6.300,00
Investimento Bruto Global R$ 25.431,20
Desconto Especial Aplicado (12%) - R$ 3.051,74
VALOR FINAL LÍQUIDO DA PROPOSTA R$ 22.379,46
Economia concedida ao cliente: R$ 3.051,74 (12% sobre o Investimento Bruto Global).
"""

ex = ExtratorProposta()
itens = ex._itens_composicao(TEXTO, "22.379,46")
vals = [round(brl_para_float(i.preco_total_com), 2) for i in itens]
descs = " | ".join(i.descricao for i in itens)

print("== as parcelas viram itens; os resultados, não ==")
ok("saem 3 itens", len(itens) == 3, "%d: %s" % (len(itens), descs))
ok("o SUBTOTAL não vira item", 25431.20 not in vals, str(vals))
ok("o TOTAL não vira item", 22379.46 not in vals, str(vals))
ok("os produtos entram", 19131.20 in vals, str(vals))
ok("o frete entra", 6300.00 in vals, str(vals))

print("\n== o desconto é item NEGATIVO ==")
ok("entra com sinal de menos", -3051.74 in vals, str(vals))
ok("e não como positivo", 3051.74 not in vals,
   "somado em vez de subtraído, a AF pagaria 6.103,48 a mais")

print("\n== a conta fecha com o total anunciado ==")
soma = sum(vals)
ok("soma == total", abs(soma - 22379.46) < 0.01, "%.2f" % soma)
# a mesma referência da AF preenchida à mão
ok("os três valores são os do gabarito AF-E-369",
   vals == [19131.20, 6300.00, -3051.74], str(vals))

print("\n== sem oráculo, não chuta ==")
ok("total que não bate -> devolve vazio",
   ex._itens_composicao(TEXTO, "99.999,99") == [],
   "sem a conta fechar, qualquer item é palpite")
ok("sem total -> devolve vazio", ex._itens_composicao(TEXTO, "") == [])
ok("texto sem tabela -> devolve vazio",
   ex._itens_composicao("Uma frase qualquer sem valores.", "22.379,46") == [])

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

# -*- coding: utf-8 -*-
r"""Uma regra só para reconhecer a moeda — e a conversão que dependia dela.

O bug, que era silencioso e grave
---------------------------------
Havia DUAS regras para descobrir que moeda é essa, e elas discordavam:

    engine / Excel   ->  moeda_info(nome)   : busca EXATA no catálogo
    desenho do HTML  ->  _simbolo(nome)     : busca por PEDAÇO do nome

O extrator lê a proposta com `\b(Real|D[óo]lar|Euro)\b` e devolve **"Dólar"** —
que não é a chave do catálogo ("Dólar Americano"). Efeito: o documento imprimia
"US$ 100.000,00", porque o desenho reconhecia o pedaço "dólar"; e a conversão
para reais devolvia R$ 100.000,00, porque o motor não reconhecia e caía no
default (Real).

Duas consequências, nesta ordem de gravidade:

1. A **ALÇADA** sai errada. Ela é escolhida pela faixa de valor EM REAIS
   (`alcada_para(valor_reais_n)`): uma compra de US$ 100 mil era julgada como se
   fossem R$ 100 mil e ia para um nível de aprovação mais baixo.
2. O **Saldo** e o "Valor em R$" saem errados, e digitar a cotação não muda
   nada — foi assim que o problema apareceu.

Agora `moeda_info` normaliza (sem acento, minúsculas) e aceita apelido e
símbolo, `_simbolo` do desenho delega a ela, e o extrator já devolve a chave do
catálogo — senão o `<select>` da tela não consegue marcar a opção.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import engine
from core.modelos import MOEDAS, moeda_info, moeda_nome
from core.html_render import _simbolo, montar_cpm_html

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


print("== o motor e o desenho concordam, para todo nome ==")
NOMES = list(MOEDAS) + ["Dólar", "dolar", "DÓLAR", "USD", "US$", "EUR", "€",
                        "yuan", "renminbi", "brl", "R$", "abacaxi", "", None]
divergem = [n for n in NOMES if moeda_info(n)["simb"] != _simbolo(n)]
ok("nenhum nome recebe dois símbolos diferentes", not divergem, repr(divergem))

print("\n== o que o extrator devolve é reconhecido ==")
# o extrator lê a proposta com \b(Real|D[óo]lar|Euro)\b — nenhum deles, exceto
# "Real", é chave do catálogo
for lido, esperado in (("Dólar", "Dólar Americano"), ("Dolar", "Dólar Americano"),
                       ("Euro", "Euro"), ("Real", "Real")):
    ok("proposta diz %r -> %s" % (lido, esperado), moeda_nome(lido) == esperado,
       moeda_nome(lido))
ok("nome irreconhecível vira Real", moeda_nome("abacaxi") == "Real")
ok("e todo nome do catálogo continua ele mesmo",
   all(moeda_nome(k) == k for k in MOEDAS))

print("\n== a cotação converte de verdade ==")
BASE = {"fornecedor": "DATACOM", "numero": "1", "ano": "2026", "prefixo": "AF-E",
        "objeto": "x", "capex": "1.000.000,00", "valor_total": "100.000,00",
        "cotacao": "5,00", "itens": []}


def celulas(**extra):
    h = montar_cpm_html(engine.cpm_de_form(dict(BASE, **extra)))
    return dict((k, re.sub(r"<[^>]+>", "", v).strip()) for k, v in re.findall(
        r'<div class="cel[^"]*"><div class="cl">(.*?)</div>'
        r'<div class="cv">(.*?)</div></div>', h, re.S))


# US$ 100.000,00 a 5,00 = R$ 500.000,00; verba de 1 milhão deixa saldo de 500 mil
for m in ("Dólar Americano", "Dólar", "USD"):
    c = celulas(moeda=m)
    ok("moeda %-16r converte para reais" % m, c.get("Valor em R$") == "R$ 500.000,00",
       str(c.get("Valor em R$")))
    ok("moeda %-16r dá o saldo certo" % m, c.get("Saldo") == "R$ 500.000,00",
       str(c.get("Saldo")))

print("\n== e a ALÇADA, que é escolhida pela faixa em reais ==")
# É aqui que o bug doía de verdade: a compra ia para o nível de aprovação
# errado. Para o teste PROVAR isso, o valor convertido tem de CRUZAR uma faixa —
# US$ 100 mil a 5,00 dá R$ 500 mil, que ainda cai na mesma faixa de R$ 100 mil
# (30.000,01 a 500.000,00) e não provaria nada. A 6,00 dá R$ 600 mil, que sobe.
ALTO = dict(BASE, cotacao="6,00")
a_certo = engine.cpm_de_form(dict(ALTO, moeda="Dólar Americano")).get("alcada")
a_apelido = engine.cpm_de_form(dict(ALTO, moeda="Dólar")).get("alcada")
a_real = engine.cpm_de_form(dict(ALTO, moeda="Real")).get("alcada")
ok("o apelido cai na mesma alçada do nome oficial", a_certo == a_apelido,
   "%r vs %r" % (a_certo, a_apelido))
ok("US$ 100 mil (= R$ 600 mil) não cai na alçada de R$ 100 mil", a_certo != a_real,
   "os dois deram %r" % (a_certo,))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

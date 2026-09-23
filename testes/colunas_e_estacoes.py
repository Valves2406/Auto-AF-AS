# -*- coding: utf-8 -*-
r"""Coluna pelo CABEÇALHO, e o quadro de estações como local de entrega.

Dois defeitos da mesma proposta (Padtec 2026-1979 V4, Recife e Rio).

1. QUANTIDADE E UNITÁRIO VINHAM DA COLUNA ERRADA
-------------------------------------------------
A tabela tem uma coluna de quantidade POR SITE antes da coluna "Total":

    Código | Descrição | Recife | Recife Tecto | Total | Preço unit. | Preço TOTAL sem imp. | …
    MUX…   | …         |   1    |      1       |   2   |  10.786,37  |      21.572,74       |

A regra antiga pegava o primeiro inteiro depois da descrição — "Recife" (1) em
vez de "Total" (2) — e o segundo preço como unitário, que aqui é o TOTAL sem
impostos. Saía "1 x R$ 21.572,74" no lugar de "2 x R$ 10.786,37".

E PASSAVA DESPERCEBIDO: o total da linha continuava certo, a soma fechava com
o valor da proposta e nenhum aviso disparava. Só a quantidade e o preço
unitário iam errados para a AF — que é o que o fornecedor lê para separar o
material. Numa proposta de um site só a contagem acertava por sorte; bastou a
segunda localidade para deslocar tudo.

2. O QUADRO DE ESTAÇÕES ERA JOGADO FORA
----------------------------------------
A proposta fecha com a tabela de entrega pronta:

    Nome da Estação | Sigla do POP | Endereço            | Município | UF
    Recife          | RCE-RCE      | Rodovia PE-7, km 20 | Jaboatão… | PE

Saíam ZERO locais. E sem local de entrega não há UF, logo também não havia
filial de faturamento: um campo vazio levava o outro junto.

ARMADILHA MEDIDA: no arquivo do Rio o cabeçalho quebra no lugar errado —
'Nome da Estação Sigla' | 'do POP' | 'Endereço' | … — com "Sigla" migrando
para a primeira célula. Casar por igualdade ou por posição funciona em Recife
e falha no Rio, e os dois são a MESMA proposta em outra cidade.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

from core.extrator import ExtratorProposta

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


ex = ExtratorProposta()

# ----------------------------------------------------------------- 1 -----
print("== a coluna certa é a que o cabeçalho aponta ==")
CAB = ["Código", "Descrição Completa", "Recife", "Recife Tecto", "Total",
       "Preço unit. sem impostos (com PIS/COFINS) (R$)",
       "Preço TOTAL sem impostos (com PIS/COFINS) (R$)",
       "Preço TOTAL com impostos (com PIS/COFINS) (R$)",
       "Preço TOTAL com impostos (sem ICMS) (R$)"]
LINHA = ["MDDEN2643291PW", "MUX/DEMUXDWDM 32 Canais 150 GHz 1U", "1", "1", "2",
         "10.786,37", "21.572,74", "23.851,12", "25.646,36"]

col = ex._cols_qtd_unit([CAB])
ok("acha a coluna de quantidade", col.get("qtd") == 4, repr(col))
ok("e a do preço unitário", col.get("unit") == 5, repr(col))

it = ex._item_de_celulas(LINHA, frozenset(), {}, col)
ok("o item sai", it is not None)
if it:
    ok("quantidade = a coluna Total, não a do 1º site", it.quantidade == "2",
       repr(it.quantidade))
    ok("unitário = o unitário, não o total da linha",
       it.preco_unit_sem == "10.786,37", repr(it.preco_unit_sem))
    ok("e o total continua o mesmo", it.preco_total_com == "25.646,36",
       repr(it.preco_total_com))
    # 2 x 10.786,37 = 21.572,74 — o "Preço TOTAL sem impostos" da própria linha
    ok("a conta do item fecha com a coluna de total sem impostos",
       abs(2 * 10786.37 - 21572.74) < 0.01)

print("\n== sem cabeçalho, a heurística antiga continua valendo ==")
SEM_CAB = ["COD1", "Produto simples", "3", "100,00", "300,00"]
it2 = ex._item_de_celulas(SEM_CAB, frozenset(), {}, {})
ok("ainda lê item de tabela sem cabeçalho", it2 is not None)
if it2:
    ok("com a quantidade certa", it2.quantidade == "3", repr(it2.quantidade))

# NOME COLIDIDO: `_CAB_QTD` já existe nesta classe com outro sentido. Duas
# constantes de mesmo nome não dão erro — a última vence, e a detecção cala.
print("\n== os nomes das constantes não colidem ==")
ok("a constante da COLUNA tem nome próprio",
   hasattr(ExtratorProposta, "_CAB_COL_QTD"))
ok("e a antiga continua existindo, intacta",
   hasattr(ExtratorProposta, "_CAB_QTD")
   and ExtratorProposta._CAB_QTD is not ExtratorProposta._CAB_COL_QTD,
   "se forem a mesma, uma delas foi sobrescrita")

# ----------------------------------------------------------------- 2 -----
print("\n== o quadro de estações vira local de entrega ==")
RECIFE = [["Nome da Estação", "Sigla do POP", "Endereço", "Município", "UF", "Cedente"],
          ["---", "---", "---", "---", "---", "---"],
          ["Recife", "RCE-RCE", "Rodovia PE-7, km 20",
           "Jaboatão dos Guararapes", "PE", "Subestação Chesf"]]
e = ex._estacoes_de_tabela(RECIFE)
ok("lê a estação", len(e) == 1, "%d" % len(e))
if e:
    ok("nome", e[0]["nome"] == "Recife", repr(e[0]["nome"]))
    ok("sigla do POP", e[0]["sigla"] == "RCE-RCE", repr(e[0]["sigla"]))
    ok("endereço", e[0]["endereco"].startswith("Rodovia PE-7"), repr(e[0]["endereco"]))
    ok("município", e[0]["municipio"] == "Jaboatão dos Guararapes")
    ok("UF", e[0]["uf"] == "PE", repr(e[0]["uf"]))

print("\n== e aguenta o cabeçalho quebrado no lugar errado (Rio) ==")
RIO = [["Nome da Estação Sigla", "do POP", "Endereço", "Município", "UF", "Cedente"],
       ["---", "---", "---", "---", "---", "---"],
       ["RJ2 Datacenter", "RJ2", "Estrada Adhemar Bebiano, 1380 - Del Castilho",
        "Rio de Janeiro", "RJ", "Datacenter Equinix"],
       ["Teleporto", "TLP", "Rua Afonso Cavalcanti, 58 - Cidade Nova",
        "Rio de Janeiro", "RJ", "Eletronet"]]
r = ex._estacoes_de_tabela(RIO)
ok("lê as duas estações", len(r) == 2, "%d" % len(r))
if len(r) == 2:
    ok("a sigla vem de 'do POP', não da 1ª célula",
       [x["sigla"] for x in r] == ["RJ2", "TLP"], str([x["sigla"] for x in r]))
    ok("e o nome NÃO é 'Nome da Estação Sigla'",
       [x["nome"] for x in r] == ["RJ2 Datacenter", "Teleporto"],
       str([x["nome"] for x in r]))

print("\n== tabela que não é de entrega fica de fora ==")
ok("tabela de preços não vira local",
   ex._estacoes_de_tabela([CAB, LINHA]) == [])
ok("tabela curta demais também não",
   ex._estacoes_de_tabela([["Nome da Estação", "Endereço"]]) == [])

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

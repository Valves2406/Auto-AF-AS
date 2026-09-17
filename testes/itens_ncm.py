# -*- coding: utf-8 -*-
r"""Tabela com NCM e ENDEREÇO DE ENTREGA na mesma linha do produto.

Caso real (proposta de 01/09/2026): o endereço vinha grudado no fim da linha e
virava a DESCRIÇÃO do item — a AF saía com "Rodovia GO 330 Km 07" no lugar de
"RACK 44U 19"". O leitor só aceita o resultado quando a soma das linhas bate
com o SUBTOTAL/TOTAL que a própria proposta declara.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta
from core.modelos import brl_para_float

ex = ExtratorProposta()
falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


RACK = 'RACK 44U 19" L600XP800XA2100MM COM PORTA TIPO COLMEIA - PRETO'
PDU = 'PDU3U 19-21" 200A 2 VIAS - 8X63A/6X32A/6X20A WEG COM PROT FRONTAL E TRASEIRA - PRETO'
ENDERECOS = [
    "Rodovia GO 330 Km 07 - Rodovia Anápolis/ Leopoldo",
    "Bulhões / ANAPÓLIS-GO",
    "BR-153, km 510, s/n - Chácara Marivânia - Subestação",
    "de Bandeirantes/APARECIDA DE GOIANIA-GO",
]
# reproduz o texto como o pdfplumber entrega: número com espaço dentro
# ("R$ 5 .462,50", "R$ 9 48,69") e endereço colado no fim da linha
linhas = ["Condição pagamento: 45 DDL", "ELETRONET Versão: 01 01/09/2026",
          "ITEM SOLICITAÇÃO DESCRIÇÃO DOS MATERIAIS UNID. NCM QT R$ TOTAL ENTREGA / DIAS ENDEREÇO DE ENTREGA"]
for i in range(8):
    linhas.append(f'1 {RACK} CJ 85177900 1 R$ 5 .462,50 R$ 5 .462,50 22 {ENDERECOS[(2 * i) % 4]}')
    linhas.append(f'2 {PDU} CJ 85371090 1 R$ 9 48,69 R$ 9 48,69 22 {ENDERECOS[(2 * i + 1) % 4]}')
linhas += ["SUBTOTAL R$ 51.289,52", "Observação: FRETE R$ 14.938,50",
           "Prazo de entrega frete até 5 dias úteis TOTAL R$ 66.228,02"]
TEXTO = "\n".join(linhas)

print("== leitura da tabela com NCM ==")
itens = ex._itens(TEXTO)
ok("leu as 16 linhas", len(itens) == 16, f"leu {len(itens)}")

if itens:
    sujas = [it.descricao for it in itens
             if re.search(r"rodovia|km |s/n|estrada|subesta", it.descricao or "", re.I)]
    ok("nenhuma descrição contaminada com endereço", not sujas, str(sujas[:2]))
    ok("descrição do 1º item é o produto", (itens[0].descricao or "").startswith("RACK 44U"),
       repr(itens[0].descricao))
    ok("descrição do 2º item é o produto", (itens[1].descricao or "").startswith("PDU3U"),
       repr(itens[1].descricao))
    ok("quantidade lida", itens[0].quantidade == "1", repr(itens[0].quantidade))
    ok("unidade lida", itens[0].unidade == "CJ", repr(itens[0].unidade))

    # o número com espaço dentro tem de virar o valor certo
    ok("R$ 5 .462,50 -> 5462.50", brl_para_float(itens[0].preco_total_com) == 5462.50,
       repr(itens[0].preco_total_com))
    ok("R$ 9 48,69 -> 948.69", brl_para_float(itens[1].preco_total_com) == 948.69,
       repr(itens[1].preco_total_com))

    soma = sum(brl_para_float(it.preco_total_com) or 0 for it in itens)
    ok("a soma fecha com o SUBTOTAL declarado", abs(soma - 51289.52) < 0.01, f"{soma:.2f}")

print("\n== a trava: soma que não fecha é RECUSADA ==")
# mesma tabela, mas com o SUBTOTAL adulterado: o leitor não pode confiar nele
adulterado = TEXTO.replace("SUBTOTAL R$ 51.289,52", "SUBTOTAL R$ 99.999,99") \
                  .replace("TOTAL R$ 66.228,02", "TOTAL R$ 88.888,88")
brutos = ex._itens_com_ncm(adulterado)
ok("o padrão ainda casa as linhas", len(brutos) == 16, f"{len(brutos)}")
ok("mas a conferência recusa", not ex._confere_soma(brutos, adulterado))

print("\n== proposta comum não é afetada ==")
COMUM = ("1 Switch DmSwitch 2104 2 R$ 1.000,00 R$ 1.100,00 R$ 2.200,00\n"
         "2 Fonte PSU DC 1 R$ 500,00 R$ 550,00 R$ 550,00\n")
sem_ncm = ex._itens_com_ncm(COMUM)
ok("tabela sem NCM não casa o padrão novo", not sem_ncm, f"casou {len(sem_ncm)}")
comuns = ex._itens(COMUM)
ok("e continua sendo lida pelo caminho de sempre", len(comuns) == 2, f"leu {len(comuns)}")
if len(comuns) == 2:
    ok("com a descrição certa", "DmSwitch" in (comuns[0].descricao or ""), repr(comuns[0].descricao))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

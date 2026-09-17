# -*- coding: utf-8 -*-
r"""A conta de cada linha e a soma do pedido.

Regra pedida:
  · COM imposto ...: unitário s/ imposto + alíquotas = unitário c/ imposto
  · nos dois casos .: unitário c/ imposto × QTD = total da linha
  · pedido ........: soma dos totais de linha (+ o que a proposta cobra fora
                     da tabela: frete, seguro, desconto)

Este teste espelha a regra em Python; a implementação de verdade está em
web/app.js (recalcularItem / atualizarValorTotal).
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from decimal import Decimal, ROUND_HALF_UP

from core.extrator import ExtratorProposta
from core.modelos import brl_para_float


def arred(v):
    """Arredondamento COMERCIAL (meio para cima), como o app faz.

    O round() do Python usa arredondamento BANCÁRIO (meio para o par):
    5735,625 vira 5735,62. O JavaScript — e a praxe fiscal brasileira —
    arredonda meio para CIMA: 5735,63. Espelhar a regra errada aqui faria o
    teste acusar o app de um erro de centavo que é dele, do teste."""
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def linha(qtd, unit_sem, aliquotas=(), unit_com=None):
    """Espelha recalcularItem: devolve (unitário c/ imposto, total da linha).

    O unitário é ARREDONDADO a 2 casas ANTES de multiplicar pela quantidade.
    Isso não é detalhe: o documento imprime o unitário com 2 casas, e quem
    confere multiplica o que VÊ. Usando o valor cheio (5462,50 × 1,05 =
    5735,625), o total impresso não fecharia com unitário × quantidade na
    própria folha — a AF não bateria com ela mesma."""
    q = brl_para_float(qtd)
    base = brl_para_float(unit_sem) if unit_sem else None
    if base is not None and aliquotas:
        uc = arred(base * (1 + sum(aliquotas) / 100))
    elif unit_com:
        uc = brl_para_float(unit_com)
    else:
        uc = base
    return uc, (arred(uc * q) if uc is not None and q else None)


print("== com imposto ==")
uc, tot = linha("2", "100.000,00", (5,))
ok("unitário c/ IPI 5%", round(uc, 2) == 105000.00, f"{uc}")
ok("total = unitário c/ imposto × qtd", round(tot, 2) == 210000.00, f"{tot}")

uc, tot = linha("1", "100.995,32", (2, 0.65))
ok("duas alíquotas somam", round(uc, 2) == 103671.70, f"{uc}")
ok("qtd 1 não altera o total", round(tot, 2) == 103671.70, f"{tot}")

# o caso que pegou meu próprio teste errado: 5462,50 + IPI 5% × 3
uc, tot = linha("3", "5.462,50", (5,))
ok("unitário arredondado antes de multiplicar", uc == 5735.63, f"{uc}")
ok("total = unitário IMPRESSO × qtd", tot == 17206.89,
   f"{tot} (com o valor cheio daria 17206.88 e a folha não fecharia)")

print("\n== sem imposto: conta simples ==")
uc, tot = linha("3", "1.500,00")
ok("unitário c/ imposto = unitário s/ imposto", round(uc, 2) == 1500.00, f"{uc}")
ok("total = qtd × unitário", round(tot, 2) == 4500.00, f"{tot}")

uc, tot = linha("4", "", (), "250,00")     # só o unitário c/ imposto preenchido
ok("digitando só o unitário c/ imposto", round(tot, 2) == 1000.00, f"{tot}")

print("\n== so quantidade e valor sem imposto preenchem tudo ==")
# e o caso mais comum: a proposta traz qtd e preco unitario, e nada mais
uc, tot = linha("5", "1.200,00")
ok("unitario c/ imposto sai preenchido", uc == 1200.00, f"{uc}")
ok("total sai preenchido", tot == 6000.00, f"{tot}")


def refaz(qtd, unit_sem, uc_anterior, uc_auto=True):
    """Espelha o comportamento com a marca ucAuto (web/app.js).

    CORRIGIR o preco depois tem de refazer a conta. A regra antiga so preenchia
    o unitario c/ imposto enquanto o campo estivesse VAZIO, entao ele ficava
    parado no valor velho e o total saia errado."""
    base = brl_para_float(unit_sem)
    uc = base if uc_auto else brl_para_float(uc_anterior)
    return uc, arred(uc * brl_para_float(qtd))


uc2, tot2 = refaz("5", "2.400,00", "1.200,00", uc_auto=True)
ok("corrigir o preco refaz o unitario c/ imposto", uc2 == 2400.00, f"{uc2}")
ok("e refaz o total", tot2 == 12000.00, f"{tot2} (com o bug antigo daria 6000,00)")

uc3, tot3 = refaz("2", "2.400,00", "2.500,00", uc_auto=False)
ok("valor DIGITADO a mao e respeitado", uc3 == 2500.00, f"{uc3}")
ok("e o total usa o valor digitado", tot3 == 5000.00, f"{tot3}")

print("\n== soma do pedido (caso real da proposta) ==")
# 8 racks + 8 PDUs, como na proposta de 01/09/2026
itens = [("1", "5.462,50")] * 8 + [("1", "948,69")] * 8
soma = 0
for q, u in itens:
    _, t = linha(q, u)
    soma += t
ok("soma das 16 linhas = SUBTOTAL da proposta", abs(soma - 51289.52) < 0.01, f"{soma:.2f}")

FRETE = brl_para_float("14.938,50")
ok("soma + frete = TOTAL da proposta", abs((soma + FRETE) - 66228.02) < 0.01, f"{soma + FRETE:.2f}")

print("\n== o extra da proposta sobrevive à edição ==")
# a pessoa muda uma quantidade depois de importar: o frete não pode sumir
extra = 66228.02 - 51289.52
itens2 = [("2", "5.462,50")] + [("1", "5.462,50")] * 7 + [("1", "948,69")] * 8
soma2 = sum(linha(q, u)[1] for q, u in itens2)
ok("nova soma reflete a edição", abs(soma2 - (51289.52 + 5462.50)) < 0.01, f"{soma2:.2f}")
ok("e o frete continua somado", abs((soma2 + extra) - (66228.02 + 5462.50)) < 0.01,
   f"{soma2 + extra:.2f}")

print("\n== número com espaço não chega mais ao formulário ==")
for bruto, esperado in [("R$ 5 .462,50", "5.462,50"), ("9 48,69", "948,69"),
                        ("R$ 51.289,52", "51.289,52"), ("1 .234,56", "1.234,56")]:
    limpo = ExtratorProposta._limpar_dinheiro(bruto)
    ok(f"{bruto!r} -> {esperado!r}", limpo == esperado, repr(limpo))
    ok(f"  e ainda converte certo", brl_para_float(limpo) == brl_para_float(bruto))

# e pela leitura de verdade da tabela com NCM
RACK = 'RACK 44U 19" L600XP800XA2100MM COM PORTA TIPO COLMEIA - PRETO'
TXT = ("ITEM SOLICITAÇÃO DESCRIÇÃO DOS MATERIAIS UNID. NCM QT R$ TOTAL ENTREGA / DIAS ENDEREÇO\n"
       + "\n".join(f'1 {RACK} CJ 85177900 1 R$ 5 .462,50 R$ 5 .462,50 22 Rodovia GO 330' for _ in range(8))
       + "\n" + "\n".join('2 PDU3U 19-21" 200A CJ 85371090 1 R$ 9 48,69 R$ 9 48,69 22 BR-153' for _ in range(8))
       + "\nSUBTOTAL R$ 51.289,52\n")
itens3 = ExtratorProposta()._itens(TXT)
ok("leu as 16 linhas", len(itens3) == 16, f"{len(itens3)}")
if itens3:
    com_espaco = [it.preco_total_com for it in itens3 if " " in (it.preco_total_com or "")]
    ok("nenhum preço com espaço no meio", not com_espaco, str(com_espaco[:3]))
    ok("preço do rack limpo", itens3[0].preco_total_com == "5.462,50", repr(itens3[0].preco_total_com))
    ok("preço do PDU limpo", itens3[8].preco_total_com == "948,69", repr(itens3[8].preco_total_com))

print("\n== o calculo automatico pode ser DESLIGADO ==")
# Nem toda proposta fecha na conta: chega planilha com arredondamento proprio,
# desconto embutido numa linha so, unitario ja com frete rateado. Nesses casos
# o app "corrigir" o numero e atrapalhar — a AF tem de sair com o que o
# fornecedor escreveu. O marcador desliga a conta e quem digita manda.
js = io.open(os.path.join(PROJ, "frontend", "app.js"), encoding="utf-8").read()
htm = io.open(os.path.join(PROJ, "frontend", "index.html"), encoding="utf-8").read()

ok("existe o marcador na tela", 'id="ckCalcular"' in htm)
ok("ele vem LIGADO por padrao", 'id="ckCalcular" checked' in htm,
   "desligado por padrao, quem nunca mexeu perderia o preenchimento automatico")
ok("a conta de cada linha respeita o marcador",
   "function recalcularItem(it) {\n  if (!calcLigado()) return;" in js,
   "sem essa guarda o app continua sobrescrevendo o que a pessoa digitou")
ok("a soma do pedido tambem respeita",
   "function atualizarValorTotal() {\n  if (!calcLigado()) return;" in js)
ok("o marcador esta ligado ao evento", '$("ckCalcular").onchange = toggleCalcular;' in js)
ok("a escolha sobrevive a fechar o app", "localStorage.setItem(CALC_PREF" in js)
ok("religar recalcula o que ficou para tras", "if (on) items.forEach(recalcularItem);" in js,
   "senao os valores digitados com a conta desligada nunca mais batem com a regra")
ok("sem o marcador na tela, calcula (padrao seguro)", "return !ck || ck.checked;" in js)

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

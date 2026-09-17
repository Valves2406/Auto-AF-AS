# -*- coding: utf-8 -*-
r"""As divisórias do quadro ORÇAMENTO não podem sumir.

O sintoma na tela: algumas divisórias apareciam e outras não. A horizontal
existia sob parte da linha, o fio vermelho do SALDO aparecia, e as verticais
entre IDENTIFICAÇÃO / FORNECEDOR / VALOR não.

A causa, medida no navegador: as células caíam em posições FRACIONÁRIAS — a
primeira terminava em x=344,656 e a segunda começava em 345,656. O fio era o
fundo do container aparecendo por um `gap` de 1px, ou seja, coisa PINTADA.
Quando as duas caixas vizinhas são encaixadas nos pixels do dispositivo, elas
se aproximam e o vão de 1px pode fechar: o fio desaparece. Some numas colunas
e não em outras, porque cada uma cai numa fração diferente — daí o padrão
irregular.

A prova estava na própria folha: o fio do saldo negativo é `inset 3px` e
nunca sumiu. Três pixels sobrevivem ao encaixe; um vão de um, não.

A correção troca o MECANISMO: a divisória passa a ser BORDA das células.
Borda faz parte da caixa e entra no layout, então o encaixe a preserva.

Este teste guarda o mecanismo, não a aparência:
  • nenhum `gap` no container (vão pintado não volta);
  • borda de verdade à direita e embaixo das células;
  • moldura externa sem traço dobrado (topo/esquerda no container,
    direita/baixo nas células);
  • o fio vermelho do saldo continua sendo o de dentro.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

from core.html_render import montar_cpm_html

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


C = {"cpm_id": "CPS-E-363/2026-GE", "tipo": "CPS", "af_id": "AS-E-363/2026-GE",
     "finalidade": "Aquisição de licenças", "fornecedor_completo": "CIENA",
     "valor": "140,18", "moeda": "Dólar", "cotacao": "5,15",
     "valor_reais": "721,93", "saldo": "-721,93", "data_cpm": "16/09/2026",
     "prazo_entrega": "30 dias", "forma_pagamento": "à vista",
     "alcada": "Gerente da área"}
html = montar_cpm_html(C)


def regra(seletor):
    """O corpo da regra CSS do seletor, como está na folha gerada."""
    m = re.search(re.escape(seletor) + r"\{([^}]*)\}", html)
    return re.sub(r"\s+", "", m.group(1)) if m else ""


cont, cel, neg = regra(".orc"), regra(".orc .cel"), regra(".orc .cel.neg")

print("== o vão pintado não volta ==")
ok("o container não tem gap", "gap:1px" not in cont, cont[:90])
ok("nem pinta o fundo de cinza para vazar pelo vão",
   "background:#c9d2e5" not in cont, cont[:90])

print("\n== a divisória é BORDA de verdade ==")
ok("borda à direita da célula", "border-right:1pxsolid#c9d2e5" in cel, cel[:110])
ok("borda embaixo da célula", "border-bottom:1pxsolid#c9d2e5" in cel, cel[:110])
ok("e não sobrou sombra fazendo o papel de fio",
   "box-shadow" not in cel, cel[:110])

print("\n== a moldura externa não fica com traço dobrado ==")
# topo e esquerda vêm do container; direita e baixo, das células da ponta
ok("container tem borda em cima e à esquerda",
   "border-top:1pxsolid#c9d2e5" in cont and "border-left:1pxsolid#c9d2e5" in cont,
   cont[:110])
ok("e NÃO tem borda à direita/embaixo (seria fio dobrado)",
   "border-right" not in cont and "border-bottom" not in cont, cont[:110])
ok("o canto arredondado continua aparando", "overflow:hidden" in cont)

print("\n== o saldo negativo mantém o fio vermelho por dentro ==")
ok("fio interno de 3px", "inset3px0 0#d9534f" in neg.replace(" ", "")
   or "inset3px00#d9534f" in neg, neg[:110])
ok("e não repete os fios cinza", "#c9d2e5" not in neg, neg[:110])

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

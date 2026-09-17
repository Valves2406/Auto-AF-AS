# -*- coding: utf-8 -*-
"""O total da proposta manda sobre a soma das linhas.

Caso real (proposta HOYER, 01/09/2026): a tabela somava SUBTOTAL 51.289,52 e o
frete de 14.938,50 vinha FORA dela, com TOTAL 66.228,02. O app somava as linhas
e escrevia por cima do total lido — a AF sairia R$ 14.938,50 mais barata.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from core.modelos import brl_para_float

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# ---- 1. o número como este PDF entrega: com espaço no meio -------------------
print("== números com espaço dentro (assim saem do PDF) ==")
for bruto, esperado in [("5 .462,50", 5462.50), ("9 48,69", 948.69),
                        ("51.289,52", 51289.52), ("66.228,02", 66228.02)]:
    ok(f"{bruto!r} -> {esperado}", brl_para_float(bruto) == esperado, str(brl_para_float(bruto)))

# ---- 2. a regra de conciliação (a mesma do conciliarValorTotal no front) -----
print("\n== total da proposta x soma das linhas ==")


def concilia(total_proposta, soma_itens):
    """Espelha web/app.js:conciliarValorTotal — devolve (valor, avisa)."""
    t = brl_para_float(total_proposta) if total_proposta else None
    s = brl_para_float(soma_itens) if soma_itens else None
    if t is None:
        return soma_itens, False
    return total_proposta, (s is not None and abs(t - s) >= 0.01)


v, avisa = concilia("66.228,02", "51.289,52")
ok("frete fora da tabela: vale o total da proposta", v == "66.228,02", v)
ok("e avisa da diferença", avisa)

v, avisa = concilia("51.289,52", "51.289,52")
ok("quando batem, sem alarme falso", v == "51.289,52" and not avisa)

v, avisa = concilia("", "51.289,52")
ok("proposta sem total: usa a soma", v == "51.289,52" and not avisa)

v, avisa = concilia("48.000,00", "51.289,52")
ok("desconto fora da tabela também vale", v == "48.000,00" and avisa)

# ---- 3. a diferença é a do caso real ----------------------------------------
dif = brl_para_float("66.228,02") - brl_para_float("51.289,52")
ok("a diferença é exatamente o frete da proposta", abs(dif - brl_para_float("14.938,50")) < 0.01,
   f"{dif:.2f}")

# ---- 4. fornecedor que só existe no logotipo --------------------------------
print("\n== fornecedor fora do texto ==")
TEXTO = ("Condição pagamento: 45 DDL\nELETRONET Versão: 01 01/09/2026\n"
         "ITEM SOLICITAÇÃO DESCRIÇÃO DOS MATERIAIS UNID. NCM QT R$ TOTAL\n"
         "1 RACK 44U 19\" L600XP800XA2100MM COM PORTA TIPO COLMEIA - PRETO CJ 85177900 1 R$ 5 .462,50\n"
         "SUBTOTAL R$ 51.289,52\nObservação: FRETE R$ 14.938,50\nTOTAL R$ 66.228,02\n")
ok("o nome do fornecedor realmente não está no texto",
   not re.search(r"hoyer", TEXTO, re.I))
ok("nem o CNPJ dele", not re.search(r"25\.?402", TEXTO))

# e o catálogo identifica quando o nome ESTÁ no texto
from core.extrator import ExtratorProposta
ex = ExtratorProposta()
achou = ex.identificar_do_catalogo(TEXTO + "\nHoyer Equipamentos Ltda\n")
ok("com o nome presente, o catálogo acha", bool(achou) and "Hoyer" in (achou or {}).get("empresa", ""),
   str(achou))
ok("sem o nome, não inventa fornecedor", not ex.identificar_do_catalogo(TEXTO))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

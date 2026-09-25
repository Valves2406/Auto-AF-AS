# -*- coding: utf-8 -*-
r"""Duas coisas que a proposta JÁ TRAZ e o app deixava passar.

1. SUBTOTAL DE SEÇÃO contado como produto (Padtec 2026-2023 v2)
----------------------------------------------------------------
A tabela tem duas linhas que são soma de grupo, não produto:

    Equipamentos -                  573.711,44   <- soma as 2 de baixo
      Duplo Muxponder 400G   x5     565.628,22
      Unidade de Ventilação  x5       8.083,23
    Licenças e Software -             1.020,41   <- soma a de baixo
      Licença interface DWDM x10      1.020,41

Entrando na lista, a soma dava 1.149.463,71 numa proposta de 574.731,85 — o
dobro. A regra antiga só enxergava UM subtotal, o que valia "a soma de todas
as outras"; aqui são dois, cada um cobrindo a sua seção.

Duas armadilhas medidas ao consertar:

  • Exigir "linha sem quantidade" não serve: "Licenças e Software de
    Gerência -" traz quantidade 1 e mesmo assim é subtotal. Quem acusa é a
    conta, não a aparência.

  • Nem todo candidato é subtotal. O último produto (1.020,41) espelha o
    subtotal logo acima e entra na lista de suspeitos. Removendo os três a
    conta não fecha; o certo é remover dois. Por isso se prova combinação por
    combinação, das menores para as maiores, e vale a primeira que bate com o
    total anunciado.

2. LOCAIS DE ENTREGA e FILIAIS que a proposta ENUMERA (ARTEMIS 207.2026)
------------------------------------------------------------------------
A proposta traz um bloco por localidade, com tudo pronto:

    PA - GUAMÁ
    Entrega: Avenida Perimetral, 33 - Guamá - Belém/PA
    ELETRONET S.A - FILIAL | CNPJ: 03.052.673/0023-99 | UF: PA

Saíam ZERO locais e UMA filial. A filial parava na primeira porque a função
devolvia dentro do laço.

A referência é a AF preenchida à mão (AF-E-369/2026-GE): quatro locais, com
as siglas 1BLM-GUA, 1FOZ-FOZ, BES e ERI, e quatro filiais.
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
from core.modelos import DadosProposta, ItemAF, brl_para_float

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


ex = ExtratorProposta()

# ---------------------------------------------------------------- 1 -------
print("== subtotal de seção não é produto ==")


def montar(linhas):
    d = DadosProposta()
    d.valor_total = "574.731,85"
    for desc, qtd, tot in linhas:
        d.itens.append(ItemAF(descricao=desc, quantidade=qtd,
                              preco_total_com=tot))
    return d


d = montar([
    ("Equipamentos -", "", "573.711,44"),
    ("Duplo Muxponder 400G - TMD400G-SD", "5", "565.628,22"),
    ("Unidade de Ventilação - TMD400G-SD", "5", "8.083,23"),
    ("Licenças e Software de Gerência -", "1", "1.020,41"),
    ("Licença interface DWDM Line", "10", "1.020,41"),
])
ex._tirar_linhas_de_grupo(d)
descs = [i.descricao for i in d.itens]
soma = sum(brl_para_float(i.preco_total_com) for i in d.itens)
ok("sobram 3 itens", len(d.itens) == 3, "%d: %s" % (len(d.itens), descs))
ok("o subtotal SEM quantidade saiu", "Equipamentos -" not in descs, str(descs))
ok("o subtotal COM quantidade 1 também saiu",
   "Licenças e Software de Gerência -" not in descs,
   "exigir 'sem quantidade' deixava este passar")
ok("o produto que espelha o subtotal FICOU",
   "Licença interface DWDM Line" in descs,
   "remover os três candidatos faria a conta não fechar")
ok("a soma passa a bater com o total", abs(soma - 574731.85) <= 0.02,
   "%.2f" % soma)

print("\n== sem oráculo, não mexe ==")
d2 = montar([("Equipamentos -", "", "573.711,44"),
             ("Duplo Muxponder", "5", "565.628,22"),
             ("Ventilação", "5", "8.083,23")])
d2.valor_total = ""                      # sem total anunciado
ex._tirar_linhas_de_grupo(d2)
ok("sem total anunciado, não remove nada", len(d2.itens) == 3,
   "%d" % len(d2.itens))

d3 = montar([("Produto A", "1", "100,00"), ("Produto B", "2", "200,00"),
             ("Produto C", "3", "300,00")])
d3.valor_total = "600,00"
ex._tirar_linhas_de_grupo(d3)
ok("tabela sem subtotal fica intacta", len(d3.itens) == 3, "%d" % len(d3.itens))

# ---------------------------------------------------------------- 2 -------
print("\n== os blocos por localidade viram locais de entrega ==")
TEXTO = """4. OBSERVAÇÕES LOGÍSTICAS, ENDEREÇOS DE ENTREGA E DADOS DE FATURAMENTO
PA - GUAMÁ
Entrega: Avenida Perimetral, 33 - Guamá - Belém/PA
ELETRONET S.A - FILIAL | CNPJ: 03.052.673/0023-99 | Código: 53023 | UF: PA
Faturamento: Av. Governador José Malcher, 153 - Nazaré - Belém
PR - FOZ DO IGUAÇU
Entrega: Av. Tarquinio Joslin dos Santos, 23 - Foz do Iguaçu/PR
ELETRONET S.A - FILIAL | CNPJ: 03.052.673/0006-98 | Código: 54006 | UF: PR
BA - BARREIRAS
Entrega: Rodovia BA-477 (Anel Viário), KM 01 - Barreiras/BA
ELETRONET S.A - FILIAL | CNPJ: 03.052.673/0020-46 | Código: 51020 | UF: BA
RS - PASSO FUNDO
Entrega: LT Passo Fundo - Farroupilha - Torre 218 - Entre Rios do Sul/RS
ELETRONET S.A - FILIAL | CNPJ: 03.052.673/0005-07 | Código: 54005 | UF: RS
"""

blocos = ex._entregas_rotuladas(TEXTO)
nomes = [b["nome"] for b in blocos]
ok("acha os 4 blocos", len(blocos) == 4, "%d: %s" % (len(blocos), nomes))
ok("o nome vem do CABEÇALHO, não do endereço",
   nomes == ["Guamá", "Foz do Iguaçu", "Barreiras", "Passo Fundo"], str(nomes))
ok("a UF acompanha", [b["uf"] for b in blocos] == ["PA", "PR", "BA", "RS"],
   str([b["uf"] for b in blocos]))
ok("o endereço da entrega é preservado",
   blocos[0]["endereco"].startswith("Avenida Perimetral, 33"),
   blocos[0]["endereco"])
ok("e o município sai do fim do endereço",
   blocos[3]["municipio"] == "Entre Rios do Sul", repr(blocos[3]["municipio"]))

print("\n== TODAS as filiais citadas, não só a primeira ==")
# Catálogo FIXO. O real junta o modelo com o cadastro da equipe, que mora na
# pasta de rede — e é lá que está a filial do PA (/0023-99). Com a VPN fora,
# este teste falhava sem defeito nenhum no código: o que ele guarda é a
# lógica (todas, na ordem da proposta), não o que o servidor tem hoje.
import core.dados_eletronet as _de
_de.locais_faturamento = lambda: [
    {"uf": "RS", "cnpj": "03.052.673/0005-07"},
    {"uf": "PR", "cnpj": "03.052.673/0006-98"},
    {"uf": "BA", "cnpj": "03.052.673/0020-46"},
    {"uf": "PA", "cnpj": "03.052.673/0023-99"},
]
fats = ex._faturamento_da_proposta(TEXTO, "48.128.759/0001-80")
ufs = [f.get("uf") for f in fats]
ok("as 4 filiais entram", len(fats) == 4, "%d: %s" % (len(fats), ufs))
ok("na ORDEM da proposta", ufs == ["PA", "PR", "BA", "RS"], str(ufs))
ok("o CNPJ do fornecedor não entra",
   all("48.128.759" not in str(f.get("cnpj")) for f in fats))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

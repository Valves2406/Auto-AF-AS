# -*- coding: utf-8 -*-
r"""As regras do leitor de AF, cada uma no caso real que a fez existir.

A ida e volta (ler_af_ida_e_volta.py) prova que o que o app escreve HOJE volta
igual. Mas o acervo tem AF feita à mão, de outras gerações do desenho e de
outros jeitos de imprimir, e cada um desses quebrou uma regra. Medido em 93
AFs com PDF e Excel da mesma autorização. Os dados aqui são fictícios; o que
se reproduz é a FORMA do problema.

    PDF em CMYK              o cinza do rótulo sai fora da faixa do RGB
    rótulo sem espaço        "Razãosocial", "Datadeemissão"
    rótulos lado a lado      "Garantia ... Prazo de entrega" na mesma linha
    colunas coladas          "93,06558,36": unitário grudado no total
    notas numeradas          "9 Fazem parte..." em minúsculas; "30 dias" não é nota
    endereço sem sigla       modelo de 2025: o POP sai pelo endereço
    Excel com linhas a mais  itens e pagamento fora das células fixas
    mais de 15 locais        o teto antigo cortava; "Enviar NF" virava local
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

from core import leitor_af as L
from core.html_render import ler_af

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def P(t, x0, top, fonte="SegoeUI", cor=(0.42, 0.46, 0.53), tam=8.6, larg=None, pag=0):
    """Uma palavra de PDF fictícia, com estilo."""
    x1 = x0 + (larg if larg is not None else 4.6 * len(t))
    return L._P({"text": t, "x0": x0, "x1": x1, "top": top, "bottom": top + tam,
                 "size": tam, "fontname": fonte, "non_stroking_color": cor}, pag)


ESCURO, SEMI = (0.11, 0.14, 0.2), "SegoeUI-Semibold"

print("== estilo decide rótulo x valor ==")
ok("rótulo em RGB", P("CNPJ", 50, 100).rotulo)
ok("rótulo em CMYK (o PDF mais novo)", P("CNPJ", 50, 100, cor=(0.62, 0.48, 0.36, 0.08)).rotulo)
ok("valor seminegrito não é rótulo", not P("12.345", 50, 110, SEMI, cor=(0.85, 0.75, 0.53, 0.62)).rotulo)
ok("'Razãosocial' sem espaço é 'Razão social'", L._rotulo("Razãosocial") == "RAZAO SOCIAL")
ok("'Datadeemissão' é 'Data de emissão'", L._rotulo("Datadeemissão") == "DATA DE EMISSAO")

print("\n== rótulos lado a lado na mesma linha ==")
ps = [P("Garantia", 51, 100), P("Não", 110, 100, SEMI, ESCURO), P("há.", 130, 100, SEMI, ESCURO),
      P("Prazo", 300, 100), P("de", 330, 100), P("entrega", 345, 100),
      P("24", 300, 114, SEMI, ESCURO), P("Dias", 315, 114, SEMI, ESCURO),
      P("Forma", 51, 130), P("de", 80, 130), P("pagamento", 95, 130),
      P("30", 51, 144, SEMI, ESCURO), P("DDL", 66, 144, SEMI, ESCURO)]
rv = L._rotulos_valores(ps)
ok("a garantia fica com a garantia", rv.get("GARANTIA") == "Não há.", repr(rv.get("GARANTIA")))
ok("o prazo com o prazo", rv.get("PRAZO DE ENTREGA") == "24 Dias", repr(rv.get("PRAZO DE ENTREGA")))
ok("e o pagamento com o pagamento", rv.get("FORMA DE PAGAMENTO") == "30 DDL", repr(rv.get("FORMA DE PAGAMENTO")))
rv = L._rotulos_valores([P("Razão", 53, 100), P("DIACOM", 110, 100, SEMI, ESCURO),
                         P("social", 53, 112), P("LTDA", 110, 112, SEMI, ESCURO), P("CNPJ", 53, 130)])
ok("rótulo quebrado em 2 linhas (v1) volta inteiro", rv.get("RAZAO SOCIAL") == "DIACOM LTDA", str(rv))

print("\n== células de preço ==")
cel = L._celulas([P("R$", 424, 500, larg=10), P("93,06", 437, 500, larg=22),
                  P("R$", 462, 500, larg=10), P("558,36", 475, 500, larg=27)])
ok("colunas coladas: o total não gruda no unitário", [" ".join(p.t for p in c) for c in cel] ==
   ["R$ 93,06", "R$ 558,36"], str([[p.t for p in c] for c in cel]))
# Formato contábil do Excel: "R$" na borda esquerda da célula (11pt antes do
# número, medido na AF-E-078) e o número partido pelo PDF ("2" + "5.520,44")
cel = L._celulas([P("R$", 630.9, 500, larg=6.8), P("2", 649.2, 500, larg=2.9), P("5.520,44", 652.1, 500, larg=20.2)])
ok("número partido pelo PDF volta inteiro",
   [L._dinheiro(" ".join(p.t for p in c)) for c in cel] == ["", "25.520,44"],
   str([[p.t for p in c] for c in cel]))

print("\n== notas numeradas do modelo ==")
linhas = [[P(t, 40, 100 + 12 * i)] for i, t in enumerate([
    "1 A Proposta da EMPRESA com a numeração: 123, está anexada.", "2 Os preços estão em Reais (R$)",
    "3 CONDIÇÕES DE FATURAMENTO E PAGAMENTO", "As importâncias ... conforme segue:",
    "30 dias após a entrega", "3.1 Em parcela única", "4 GARANTIA", "12 meses",
    "5 PRAZO DE ENTREGA", "10 dias úteis", "6 Fazem parte desta Proposta os seguintes anexos:",
    "ANEXO I - PLANILHA DE PREÇOS"])]
secs = L._secoes_das_notas(linhas)
txt = lambda k: [" ".join(p.t for p in l) for l in secs.get(k, [])]  # noqa: E731
ok("'30 dias...' é texto do pagamento, não nota 30",
   txt("pag") == ["As importâncias ... conforme segue:", "30 dias após a entrega", "3.1 Em parcela única"],
   str(txt("pag")))
ok("garantia", txt("gar") == ["12 meses"], str(txt("gar")))
ok("nota em minúsculas encerra o prazo", txt("prazo") == ["10 dias úteis"], str(txt("prazo")))

print("\n== local de entrega sem sigla (modelo de 2025) ==")
POPS = [{"nome": "Granja Exemplo", "sigla": "GEX", "endereco": "Av. Exemplo de Souza, 100", "municipio": "São Paulo", "uf": "SP"}]
achado = L._pop_por_endereco("Av. Exemplo de Souza, 100 / 13ºA Bloco D - Chácara/SP", POPS)
ok("o endereço acha o POP", achado and achado["sigla"] == "GEX", str(achado))
ok("número da rua diferente não acha", L._pop_por_endereco("Av. Exemplo de Souza, 200", POPS) is None)

print("\n== Excel feito à mão: linhas inseridas ==")
from openpyxl import Workbook
wb = Workbook()
pg1 = wb.active
pg1.title = "AF-pg1"
pg2 = wb.create_sheet("AF-pg2")
pg1["O10"] = "AF-E-900/2026-TR"
pg1["A10"], pg1["B10"] = "Fornecedor:", "EMPRESA EXEMPLO LTDA"
pg1["A15"], pg1["B15"] = "CNPJ:", "12.345.678/0001-95"          # uma linha abaixo do modelo
pg1["A16"], pg1["B16"] = "Insc. Est.", "123.456.789"
pg1["A27"], pg1["C27"] = "Item", "Descrição do Item"
for i in range(30):                                             # 30 itens: bem além da linha 44
    r = 28 + i
    pg1[f"A{r}"], pg1[f"B{r}"], pg1[f"C{r}"] = i + 1, "COD-%02d" % (i + 1), "Produto %d" % (i + 1)
    pg1[f"L{r}"], pg1[f"R{r}"] = 1, 100.0
pg1["N58"], pg1["R58"] = "TOTAL FORNECIMENTO:", 3000.0
pg1["A60"], pg1["B60"] = 3, "CONDIÇÕES DE FATURAMENTO E PAGAMENTO"
pg1["B61"] = "As importâncias objeto desta AF deverão ser pagas, conforme segue:"
pg1["B62"] = "30 dias após a entrega"
pg1["A64"], pg1["B64"] = "3.1", "Parcela única"                  # subnota depois de linha vazia
pg2["B3"] = "NOTAS (Continuação)"
pg2["A5"], pg2["B5"] = 4, "GARANTIA"
pg2["B6"] = "A garantia para o objeto desta oferta é de 12 meses."   # contém a palavra do título
pg2["A8"], pg2["B8"] = 5, "PRAZO DE ENTREGA"
pg2["B9"] = "10 dias úteis"
pg2["A58"], pg2["B58"] = 8, "LOCAIS DE ENTREGA"                  # abaixo da linha 56
for i in range(18):                                             # 18 locais: além do teto de 15
    r = 60 + i
    pg2[f"B{r}"], pg2[f"C{r}"], pg2[f"E{r}"], pg2[f"F{r}"] = "Estação %d" % i, "E%02d" % i, "Cidade", "MG"
pg2["B78"] = "Enviar NF para controladoria@exemplo.com"          # colada, sem linha vazia
cam = os.path.join(tempfile.mkdtemp(), "af_mao.xlsx")
wb.save(cam)
d = ler_af(cam)
ok("30 itens (não só as linhas 28-44)", len(d["itens"]) == 30, str(len(d["itens"])))
ok("total da linha 'TOTAL FORNECIMENTO'", str(d["total"]).startswith("3000"), repr(d["total"]))
ok("pagamento pelo rótulo, com a subnota",
   d["pagamento"] == "30 dias após a entrega\n3.1 Parcela única", repr(d["pagamento"]))
ok("inscrição estadual pelo rótulo (linha 16)", d["ie"] == "123.456.789", repr(d["ie"]))
ok("CNPJ pelo rótulo (linha 15)", d["cnpj"] == "12.345.678/0001-95", repr(d["cnpj"]))
ok("garantia inteira, mesmo com a palavra do título no texto",
   d["garantia"] == "A garantia para o objeto desta oferta é de 12 meses.", repr(d["garantia"]))
ok("18 locais, e 'Enviar NF' não é local", len(d["entregas"]) == 18, str(len(d["entregas"])))

print("\n== a conta confere a leitura ==")
import engine
_orig = L.ler_af_pdf
L.ler_af_pdf = lambda c: {"ok": True, "af_id": "AF-E-1/2026-TR", "fornecedor": "X", "valor_total": "1.000,00",
                          "itens": [{"preco_total_com": "600,00"}, {"preco_total_com": "300,00"}]}
try:
    r = engine._importar_af_pdf("qualquer.pdf")
finally:
    L.ler_af_pdf = _orig
ok("soma dos itens diferente do total vira aviso",
   any("não fecha" in a for a in r.get("avisos", [])), str(r.get("avisos")))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

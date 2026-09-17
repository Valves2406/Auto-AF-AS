# -*- coding: utf-8 -*-
r"""Planilha de preços desenhada como TEXTO POSICIONADO (NEC/Nokia, ANEXO I).

O caso real: NEC Latin America, proposta 0100103488, anexo com 33 itens
somando R$ 1.068.559,59.

Por que nada era lido
---------------------
A folha não tem fios de grade, então `extract_tables()` não acha tabela. E o
`extract_text()` devolve a folha COLUNA A COLUNA: primeiro todos os "Type"
grudados ("HWHWHWHWHW..."), depois todos os "Item" (1.1, 1.2, 1.3...), depois
todos os CNPJs. Nenhuma linha do texto corresponde a uma linha da tabela.

Resultado: 0 itens, e o "valor total" pegava o PRIMEIRO preço da folha
(R$ 5.884,56) em vez dos R$ 1.068.559,59 do fim — uma AF de um milhão saindo
por cinco mil.

Duas medidas tiradas da folha, não chutadas
-------------------------------------------
1. A FONTE PARTE AS PALAVRAS: "IMPORTADO" vira "IM PO RTADO", "POWER" vira
   "PO W ER". Medindo os vãos: pedaço da mesma palavra fica a 0,00-0,10pt e um
   espaço de verdade a ~1,00pt. A folga entre os dois é grande, então cortar em
   0,5pt remonta as palavras sem colar o que era separado.
2. DESCRIÇÃO LARGA invade a coluna seguinte: "PSS8 SHELF KIT -PSS8KIT (1XPSS8,
   1X8FAN) 1" cai inteiro na coluna Qty. A quantidade é o último pedaço; o
   resto volta para a descrição.

A prova de que as colunas foram lidas certo é a soma: os 33 itens dão
exatamente o total impresso na folha.
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

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()


def p(texto, x0, top, larg=None):
    """Uma 'palavra' como o pdfplumber devolve: texto mais posição na folha."""
    return {"text": texto, "x0": x0, "x1": x0 + (larg if larg is not None else len(texto) * 2.0),
            "top": top}


# o cabeçalho real da folha, com os x medidos no PDF
CAB = [p("Type", 67.7, 116, 9.1), p("Item", 96.3, 116, 8.8),
       p("cnpj", 127.9, 116, 8.0), p("de", 137.0, 116, 4.8),
       p("faturam", 142.8, 116, 15.5), p("ento", 158.3, 116, 8.8),
       p("Código", 197.7, 116, 13.0), p("NEC", 211.7, 116, 7.6),
       p("Código", 243.4, 116, 13.0), p("Fabricante", 257.5, 116, 20.0),
       p("Description", 316.3, 116, 21.7), p("Q", 378.0, 116, 3.1),
       p("ty", 381.1, 116, 3.8), p("NCM", 408.4, 116, 9.4),
       p("O", 443.4, 116, 3.1), p("RIGEM", 446.5, 116, 12.9),
       p("Unit", 483.6, 116, 7.9), p("Total", 516.7, 116, 9.8)]


def linha_dados(y, item, cod, desc_ws, qtd_x, qtd, unit, total):
    ws = [p(item, 96.3, y), p("49.074.412/0006-70", 127.9, y, 60),
          p(cod, 197.7, y, 40), p(cod, 243.4, y, 40)]
    ws += desc_ws
    ws += [p(qtd, qtd_x, y), p("8517.79.00", 408.4, y, 30),
           p("IM", 443.4, y, 5), p("PO", 448.5, y, 5), p("RTADO", 453.7, y, 13),
           p(unit, 483.6, y, 26), p(total, 516.7, y, 26)]
    return ws


LINHAS = [CAB]
# 1.1 — a descrição ESTOURA a coluna: "1X8FAN)" cai na faixa de Qty, e o "1" da
# quantidade vem depois dele. Coordenadas MEDIDAS no PDF (não aproximadas): a
# descrição vai de 286,28 a 366,28 e a quantidade fica em 380,47.
LINHAS.append(linha_dados(
    131, "1.1", "3KC48900AA",
    [p("PSS8", 286.28, 131, 8.93), p("SHELF", 296.21, 131, 11.19),
     p("KIT", 308.41, 131, 5.98), p("-PSS8KIT", 315.43, 131, 16.32),
     p("(1XPSS8,", 332.79, 131, 16.28), p("1X8FAN)", 350.16, 131, 16.12)],
    380.47, "1", "5.884,56", "5.884,56"))
# 1.2 — "POWER" chega partido pela fonte: PO / W / ER, colados
LINHAS.append([
    p("1.2", 96.3, 137), p("49.074.412/0006-70", 127.9, 137, 60),
    p("3KC49822AA", 197.7, 137, 40), p("3KC49822AA", 243.4, 137, 40),
    p("CA-DC", 286.3, 137, 13), p("PO", 300.0, 137, 5.0),
    p("W", 305.02, 137, 4.0), p("ER", 309.03, 137, 4.5),
    p("CABLE", 314.5, 137, 14),
    p("2", 378.0, 137), p("8544.42.00", 408.4, 137, 30),
    p("NACIO", 443.4, 137, 12), p("NAL", 455.5, 137, 8),
    p("202,55", 483.6, 137, 20), p("405,10", 516.7, 137, 20)])
# linha de fecho
LINHAS.append([p("Valor", 470.0, 415, 12), p("Total", 483.0, 415, 12),
               p("R$", 496.0, 415, 6), p("1.068.559,59", 510.0, 415, 30)])

print("== o vão diz o que é palavra partida e o que é espaço ==")
# medido na folha: 0,00-0,10pt dentro da palavra; ~1,00pt entre palavras
ok("'PO'+'W'+'ER' viram POWER",
   E._juntar_palavras([p("PO", 330.0, 1, 5.0), p("W", 335.02, 1, 4.0),
                       p("ER", 339.03, 1, 4.5)]) == "POWER")
ok("'IM'+'PO'+'RTADO' viram IMPORTADO",
   E._juntar_palavras([p("IM", 443.4, 1, 5), p("PO", 448.5, 1, 5),
                       p("RTADO", 453.7, 1, 13)]) == "IMPORTADO")
ok("mas duas palavras de verdade continuam separadas",
   E._juntar_palavras([p("KIT", 343.5, 1, 8), p("-PSS8KIT", 352.5, 1, 20)])
   == "KIT -PSS8KIT")

print("\n== as linhas são reconstruídas pela posição ==")
reconst = E._linhas_por_posicao([w for ws in LINHAS for w in ws])
ok("uma linha por faixa de Y", len(reconst) == len(LINHAS), "%d" % len(reconst))
ok("e ordenadas por X dentro da linha",
   E._juntar_palavras(reconst[0]).startswith("Type Item"),
   E._juntar_palavras(reconst[0])[:40])

print("\n== o cabeçalho diz o que é cada coluna ==")
itens, total = E._ler_planilha(reconst, CAB)
ok("achou os dois produtos", len(itens) == 2, "%d" % len(itens))
ok("e a linha 'Valor Total' virou o total, não um item",
   total == "1.068.559,59", repr(total))

if len(itens) == 2:
    a, b = itens
    print("\n== descrição larga não rouba a quantidade ==")
    # "PSS8 SHELF KIT -PSS8KIT (1XPSS8, 1X8FAN)" passa da coluna e o "1" da
    # quantidade cai depois dela
    ok("quantidade é 1, não o rabo da descrição", a.quantidade == "1", a.quantidade)
    ok("e a descrição volta inteira",
       a.descricao == "PSS8 SHELF KIT -PSS8KIT (1XPSS8, 1X8FAN)", a.descricao)

    print("\n== código, preço e total de cada linha ==")
    ok("código do fabricante", a.codigo == "3KC48900AA", a.codigo)
    ok("unitário", a.preco_unit_com == "5.884,56", a.preco_unit_com)
    ok("total", a.preco_total_com == "5.884,56", a.preco_total_com)
    ok("a palavra partida pela fonte chega inteira na descrição",
       "POWER" in b.descricao, b.descricao)
    ok("segunda linha: qtd 2, unitário 202,55, total 405,10",
       b.quantidade == "2" and b.preco_unit_com == "202,55"
       and b.preco_total_com == "405,10",
       "%s / %s / %s" % (b.quantidade, b.preco_unit_com, b.preco_total_com))

print("\n== a soma é a prova de que as colunas estão certas ==")
soma = sum(brl_para_float(i.preco_total_com) or 0 for i in itens)
ok("itens somam o que deviam", abs(soma - (5884.56 + 405.10)) < 0.01, "%.2f" % soma)

print("\n== folha que não é planilha de preços não é confundida ==")
outra = [[p("Fornecedor", 50, 10, 25), p("SEICOM", 200, 10, 20)],
         [p("Item", 50, 20, 10), p("Preço", 200, 20, 14)]]
sem_cab = next((ws for ws in outra
                if "Description" in E._juntar_palavras(ws)), None)
ok("não acha cabeçalho onde não há", sem_cab is None)

# ===========================================================================
# A MESMA PROPOSTA, REVISADA (0100103488 versão 03): um serviço só
#
# A revisão trocou o desenho da folha, e o leitor parou de enxergar o item —
# 0 itens, com o aviso "os itens parecem estar num anexo". Três problemas:
#
# 1. O CABEÇALHO PASSOU A TER TRÊS ALTURAS: os rótulos ("Description", "Qty"),
#    o grupo de cada preço ("Net Sales", "Sales With Tax") e o tipo do valor
#    ("Unit Price R$"). Montando as colunas a partir de UMA linha, nenhuma se
#    chamava "Unit" nem "Total" — e a última conferência do leitor é
#    exatamente essa. O item tinha descrição, tinha preço, e era descartado.
#
# 2. JUNTAR AS LINHAS PELO VÃO NÃO RESOLVE: na linha do meio, "Unit Price R$"
#    e "Total Price R$" ficam a 3pt uma da outra — menos que um vão de coluna
#    — e as duas colunas de preço viram uma só. O que resolve é ler as
#    DIVISÓRIAS que a folha desenha (verticais nas fronteiras exatas).
#
# 3. O PREÇO LIDO ERA O LÍQUIDO. A planilha traz o mesmo item três vezes:
#    Net Sales 136.201,62 | Sales Without Tax 150.397,28 | Sales With Tax
#    153.466,62. Vinha o primeiro. A AF se faz pelo valor COM imposto — é o
#    que a Eletronet paga e o que fecha com o "Valor Total R$" da folha.
# ===========================================================================
print("\n== NEC VC03: cabeçalho de três linhas, colunas pelas divisórias ==")


def reguas(xs):
    """As verticais que a folha desenha, como o pdfplumber as devolve.

    `_bordas_desenhadas` recebe a LISTA de réguas, não a página: elas vêm do
    cache do passe único de leitura, e não há objeto-página para entregar.
    """
    return [{"x0": x, "x1": x, "top": 135.0, "bottom": 162.0} for x in xs]


# Palavras e divisórias MEDIDAS no PDF (faixa da tabela, y 130..175). Não são
# estimadas: coordenada chutada faz o teste falhar com o código certo, e já
# custou caro neste projeto.
PALAVRAS = [
    ("Sales", 397.8, 137, 7.0),
    ("W", 405.6, 137, 3.1),
    ("ithout", 408.6, 137, 8.6),
    ("Sales", 422.7, 137, 7.0),
    ("W", 430.5, 137, 3.1),
    ("ithout", 433.5, 137, 8.6),
    ("Net", 322.8, 139, 5.0),
    ("Sales", 328.6, 139, 7.0),
    ("Net", 347.7, 139, 5.0),
    ("Sales", 353.4, 139, 7.0),
    ("PIS(%)", 371.3, 139, 4.6),
    ("Cofins", 383.6, 139, 8.7),
    ("ICMS", 448.5, 139, 7.2),
    ("IPI", 464.5, 139, 3.6),
    ("ISS(%)", 478.3, 139, 4.6),
    ("Sales", 490.1, 139, 7.0),
    ("W", 497.9, 139, 3.1),
    ("ith", 500.9, 139, 3.8),
    ("Tax", 505.5, 139, 4.9),
    ("Sales", 514.9, 139, 7.0),
    ("W", 522.7, 139, 3.1),
    ("ith", 525.8, 139, 3.8),
    ("Tax", 530.3, 139, 4.9),
    ("Type", 64.8, 141, 6.7),
    ("Item", 85.8, 141, 6.5),
    ("cnpj", 109.2, 141, 5.9),
    ("de", 115.9, 141, 3.5),
    ("faturamento", 120.1, 141, 17.9),
    ("Código", 150.3, 141, 9.6),
    ("Fabricante", 160.7, 141, 14.8),
    ("Description", 201.6, 141, 16.0),
    ("Qty", 248.5, 141, 5.1),
    ("NCM", 271.0, 141, 6.9),
    ("ORIGEM", 296.7, 141, 11.8),
    ("Tax", 405.1, 141, 4.9),
    ("Tax", 430.0, 141, 4.9),
    ("Unit", 320.2, 143, 5.9),
    ("Price", 326.9, 143, 6.9),
    ("R$", 334.5, 143, 3.5),
    ("Total", 344.5, 143, 7.2),
    ("Price", 352.4, 143, 6.9),
    ("R$", 360.0, 143, 3.5),
    ("(%)", 385.8, 143, 4.6),
    ("(%)", 449.8, 143, 4.6),
    ("(%)", 464.0, 143, 4.6),
    ("Unit", 491.3, 143, 5.9),
    ("Price", 498.0, 143, 6.9),
    ("R$", 505.6, 143, 3.5),
    ("Total", 515.6, 143, 7.2),
    ("Price", 523.5, 143, 6.9),
    ("R$", 531.1, 143, 3.5),
    ("Unit", 398.7, 145, 5.9),
    ("Price", 405.4, 145, 6.9),
    ("R$", 413.1, 145, 3.5),
    ("Total", 423.0, 145, 7.2),
    ("Price", 430.9, 145, 6.9),
    ("R$", 438.5, 145, 3.5),
    ("SV", 66.5, 154, 3.4),
    ("1.4", 87.1, 154, 4.3),
    ("49.074.412/0002-46", 109.8, 154, 27.8),
    ("SERV", 159.6, 154, 6.9),
    ("Serviço", 177.9, 154, 9.9),
    ("de", 188.6, 154, 3.5),
    ("instalação", 192.9, 154, 14.1),
    ("-", 207.8, 154, 1.0),
    ("Região", 209.6, 154, 9.3),
    ("GO/DF/MG", 219.7, 154, 15.9),
    ("1", 250.4, 154, 1.7),
    ("31.01", 270.7, 154, 7.7),
    ("NACIONAL", 295.4, 154, 14.7),
    ("136.201,62", 326.0, 154, 15.1),
    ("136.201,62", 349.6, 154, 15.3),
    ("1,65%", 369.6, 154, 8.2),
    ("7,60%", 383.9, 154, 8.2),
    ("150.397,28", 404.4, 154, 15.1),
    ("150.397,28", 428.0, 154, 15.3),
    ("2,00%", 476.7, 154, 8.2),
    ("153.466,62", 496.0, 154, 15.1),
    ("153.466,62", 520.7, 154, 15.3),
    ("Valor", 490.4, 164, 7.4),
    ("Total", 498.6, 164, 7.2),
    ("R$", 506.5, 164, 3.5),
    ("153.466,62", 521.3, 164, 15.3),
]
DIVISORIAS = [79.5, 98.7, 148.6, 177.4, 241.9, 260.4, 288.6, 316.8, 341.6, 366.5, 380.8, 395.2, 420.0, 444.9, 459.2, 473.5, 487.9, 512.7]

TUDO = [p(t, x, y, larg) for t, x, y, larg in PALAVRAS]

L3 = E._linhas_por_posicao(TUDO)
cab3 = next((ws for ws in L3
             if "Description" in E._juntar_palavras(ws)
             and re.search(r"\bQ\s?ty\b", E._juntar_palavras(ws))), None)
ok("acha o cabeçalho mesmo espalhado em três alturas", cab3 is not None)

bordas = E._bordas_desenhadas(reguas(DIVISORIAS), 135, 147)
ok("lê as divisórias que a folha desenha", len(bordas) == len(DIVISORIAS) + 2,
   str(len(bordas)))

itens3, total3 = E._ler_planilha(L3, cab3, bordas)
ok("o item deixa de ser descartado", len(itens3) == 1, str(len(itens3)))
if itens3:
    it = itens3[0]
    ok("código", it.codigo == "SERV", it.codigo)
    ok("quantidade 1 (e não o rabo da descrição)", it.quantidade == "1", it.quantidade)
    ok("a região fica na descrição",
       "GO/DF/MG" in it.descricao and "instalação" in it.descricao, it.descricao)
    # o coração deste teste: 153.466,62 e não 136.201,62
    ok("unitário é o COM imposto, não o líquido",
       it.preco_unit_com == "153.466,62", it.preco_unit_com)
    ok("total é o COM imposto, não o líquido",
       it.preco_total_com == "153.466,62", it.preco_total_com)
ok("o 'Valor Total R$' do pé da folha é lido", total3 == "153.466,62", total3)

print("\n== sem divisória desenhada, continua valendo o vão entre palavras ==")
ok("folha sem traço não devolve bordas", E._bordas_desenhadas(reguas([]), 0, 999) == [])
ok("moldura de página não é tabela",
   E._bordas_desenhadas(reguas([50.0, 545.0]), 0, 999) == [])

print("\n== a condição de pagamento escrita como FRASE, sem rótulo ==")
# A NEC não escreve "Condição de pagamento:". O título é "2.4 Forma e
# Condições de Faturamento e Pagamento" e a condição vem numa frase solta.
TXT = ("Prazos de Pagamento (eventos)\n a) Serviços:\n"
       "O valor do evento faturado será pago no prazo de 90 (noventa) dias da "
       "emissão da respectiva nota fiscal.\n")
ok("lê o prazo pela frase",
   E._pagamento(TXT) == "O pagamento deve ser efetuado 90 dias após a emissão da nota fiscal",
   E._pagamento(TXT))
ok("concorda em português (não 'após da')", " após da " not in E._pagamento(TXT))
ok("um dia é dia, não dias",
   "1 dia após" in E._pagamento(TXT.replace("90 (noventa)", "1 (um)")),
   E._pagamento(TXT.replace("90 (noventa)", "1 (um)")))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

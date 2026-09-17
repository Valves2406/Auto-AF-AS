# -*- coding: utf-8 -*-
r"""A proposta da ALG: folha de uma página com tudo dentro.

Quatro arquivos, um por FILIAL DA ELETRONET (Belém, Foz do Iguaçu, Barreiras,
Entre Rios), e os quatro formam UMA AF — o mesmo caso da SEICOM. O cliente no
cabeçalho é a filial, com o CNPJ dela: o local de faturamento vem escrito.

O que se perdia antes, e por quê:

  código do item   vazio — os itens vinham pelo Docling, que traz descrição e
                   preço mas não a coluna "Código" (35020060099).
  prazo/pagamento  vazios — estão numa tabela SEM GRADE no topo ("PRAZO
                   ENTREGA" em cima, "45 dias úteis" embaixo), e nenhuma regra
                   de texto corrido acha isso.
  garantia         ERRADA — vinha "garantia do produto.", rabo da frase sobre
                   embalagem violada, em vez de "GARANTIA: De acordo com a
                   linha de produto."
  frete            não virava item, e por isso a conta não fechava:
                   5.246,38 de produtos + 520,00 de frete = 5.766,38.

Duas armadilhas que este teste guarda, porque me pegaram:

* COLUNA SE DECIDE PELO COMEÇO DA PALAVRA, não pelo meio. Os valores são
  alinhados à esquerda no mesmo x do rótulo; pelo meio, "Alves" (fim do nome
  do contato, palavra larga) atravessava a fronteira e o pagamento saía
  "Alves 30 dias".

* CÓDIGO DE PRODUTO TEM DÍGITO. Soltando o gatilho do leitor posicional para
  aceitar cabeçalho em português, ele passou a ler como item o cabeçalho de
  condições ("cod=ELETRONET") e o parágrafo "RECEBIMENTO DA MERCADORIA:"
  ("cod=RECEBIMENTO"). Exigir dígito no código e dinheiro no total barra os
  dois.

As palavras abaixo são MEDIDAS no PDF (faixa y 60..210), não estimadas:
coordenada chutada já me fez caçar defeito onde não havia.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()


def p(texto, x0, top, larg):
    return {"text": texto, "x0": x0, "x1": x0 + larg, "top": top}


PALAVRAS = [
    ('CLIENTE', 45.4, 99, 29.8),
    ('CNPJ', 195.0, 99, 18.4),
    ('CONTATO', 305.4, 99, 36.7),
    ('CONDIÇÃO', 414.7, 99, 40.6),
    ('PGTO', 457.2, 99, 20.4),
    ('PRAZO', 517.8, 99, 24.8),
    ('ENTREGA', 544.5, 99, 34.0),
    ('FRETE', 618.9, 99, 22.0),
    ('TRANSPORTADORA', 711.0, 99, 70.2),
    ('CONSULTOR', 822.1, 99, 45.3),
    ('ELETRONET', 45.4, 110, 42.5),
    ('S.A', 89.7, 110, 11.1),
    ('-', 102.6, 110, 2.8),
    ('FILIAL', 107.2, 110, 21.7),
    ('BELÉM', 130.7, 110, 24.5),
    ('03.052.673/0023-99', 195.0, 110, 70.7),
    ('Vinicius', 305.4, 110, 26.3),
    ('Matos', 333.5, 110, 21.3),
    ('Alves', 356.6, 110, 18.3),
    ('30', 414.7, 110, 8.7),
    ('dias', 425.2, 110, 13.3),
    ('45', 517.8, 110, 8.7),
    ('dias', 528.3, 110, 13.3),
    ('úteis', 543.4, 110, 16.2),
    ('CIF', 618.9, 110, 11.4),
    ('-', 632.2, 110, 2.8),
    ('R$', 636.8, 110, 9.2),
    ('520,00', 647.8, 110, 23.5),
    ('Leomar', 711.0, 110, 25.1),
    ('Christian', 822.1, 110, 29.9),
    ('Barth', 853.9, 110, 18.6),
    ('Código', 45.7, 144, 18.9),
    ('Descrição', 108.2, 144, 26.4),
    ('NCM', 198.9, 144, 14.3),
    ('Qtde', 248.1, 144, 13.7),
    ('Valor', 277.7, 144, 14.4),
    ('NET', 293.5, 144, 11.7),
    ('PIS/COFINS', 332.8, 144, 33.5),
    ('s/', 385.8, 144, 5.4),
    ('ICMS', 392.7, 144, 14.7),
    ('e', 408.9, 144, 3.2),
    ('IPI', 413.6, 144, 7.3),
    ('ICMS', 440.9, 144, 14.7),
    ('ISS', 489.7, 144, 8.4),
    ('Preço', 513.0, 144, 15.5),
    ('sem', 529.9, 144, 10.9),
    ('IPI', 542.3, 144, 7.3),
    ('IPI', 569.7, 144, 7.3),
    ('%', 578.4, 144, 4.9),
    ('IPI', 604.5, 144, 7.3),
    ('R$', 613.2, 144, 7.3),
    ('Preço', 653.3, 144, 15.5),
    ('Final', 670.2, 144, 12.8),
    ('Total', 742.8, 144, 13.8),
    ('35020060099', 45.7, 165, 41.5),
    ('RI-42-19-600-600-AC', 108.2, 165, 64.4),
    ('-', 174.3, 165, 2.4),
    ('85177900', 198.9, 165, 30.2),
    ('1', 248.1, 165, 3.8),
    ('R$', 277.7, 165, 7.8),
    ('2.853,32', 287.2, 165, 25.6),
    ('R$', 332.8, 165, 7.8),
    ('290,83', 342.3, 165, 20.3),
    ('R$', 385.8, 165, 7.8),
    ('3.144,15', 395.4, 165, 25.6),
    ('R$', 440.9, 165, 7.8),
    ('255,85', 450.4, 165, 20.3),
    ('—', 489.7, 165, 5.2),
    ('R$', 513.0, 165, 7.8),
    ('3.400,00', 522.5, 165, 25.6),
    ('7.50%', 569.7, 165, 18.1),
    ('R$', 604.5, 165, 7.8),
    ('255,00', 614.0, 165, 20.3),
    ('R$', 653.3, 165, 7.8),
    ('3.655,00', 662.8, 165, 25.6),
    ('R$', 742.8, 165, 7.9),
    ('3.655,00', 752.3, 165, 25.7),
    ('Rack', 108.2, 172, 13.7),
    ('Indoor', 123.6, 172, 18.8),
    ('19"', 144.1, 172, 9.9),
    ('42U', 155.7, 172, 12.3),
    ('Larg.', 169.7, 172, 13.8),
    ('600', 108.2, 180, 11.3),
    ('x', 121.2, 180, 3.2),
    ('Prof.', 126.1, 180, 13.8),
    ('600mm', 141.5, 180, 22.0),
    ('25010012083', 45.7, 201, 41.5),
    ('PDU-QDCC-150A', 108.2, 201, 53.0),
    ('-', 162.9, 201, 2.4),
    ('85044040', 198.9, 201, 30.2),
    ('1', 248.1, 201, 3.8),
    ('R$', 277.7, 201, 7.8),
    ('1.214,78', 287.2, 201, 25.6),
    ('R$', 332.8, 201, 7.8),
    ('123,82', 342.3, 201, 20.3),
    ('R$', 385.8, 201, 7.8),
    ('1.338,60', 395.4, 201, 25.6),
    ('R$', 440.9, 201, 7.8),
    ('111,40', 450.4, 201, 20.3),
    ('—', 489.7, 201, 5.2),
    ('R$', 513.0, 201, 7.8),
    ('1.450,00', 522.5, 201, 25.6),
    ('9.75%', 569.7, 201, 18.1),
    ('R$', 604.5, 201, 7.8),
    ('141,38', 614.0, 201, 20.3),
    ('R$', 653.3, 201, 7.8),
    ('1.591,38', 662.8, 201, 25.6),
    ('R$', 742.8, 201, 7.9),
    ('1.591,38', 752.3, 201, 25.7),
    ('Quadro', 108.2, 209, 21.7),
    ('de', 131.6, 209, 7.1),
    ('Distribuição', 140.4, 209, 34.4),
    ('de', 176.4, 209, 7.1),
    ('19"x3U,', 108.2, 216, 23.2),
    ('com', 133.1, 216, 12.1),
    ('barramentos', 146.9, 216, 36.1),
    ('para', 108.2, 224, 12.5),
    ('150', 122.3, 224, 11.3),
    ('A,', 135.3, 224, 5.9),
    ('separados', 142.9, 224, 28.9),
    ('via', 173.4, 224, 8.1),
    ('A', 183.2, 224, 4.4),
    ('e', 108.2, 231, 3.4),
    ('B,', 113.3, 231, 5.7),
    ('com', 120.6, 231, 12.1),
    ('8x', 134.4, 231, 7.0),
    ('63A,', 143.1, 231, 13.4),
    ('6x', 158.2, 231, 7.0),
    ('32A', 166.9, 231, 11.9),
    ('e', 180.5, 231, 3.4),
    ('6x', 108.2, 239, 7.0),
    ('20A', 116.9, 239, 11.9),
    ('Subtotal', 653.3, 260, 30.0),
    ('produtos', 685.2, 260, 32.2),
    ('R$', 742.8, 260, 9.8),
    ('5.246,38', 754.5, 260, 31.6),
    ('Frete', 653.3, 284, 19.0),
    ('R$', 742.8, 284, 9.8),
    ('520,00', 754.5, 284, 25.1),
    ('TOTAL', 653.3, 307, 25.8),
    ('GERAL', 681.0, 307, 25.3),
    ('R$', 742.8, 307, 9.8),
    ('5.766,38', 754.5, 307, 31.6),
    ('OBSERVAÇÕES', 45.4, 345, 57.7),
    ('Alíquota', 45.4, 360, 26.5),
    ('ICMS:', 73.5, 360, 18.9),
    ('7%', 94.2, 360, 9.8),
    ('|', 109.1, 360, 1.8),
    ('Alíquota', 116.0, 360, 26.5),
    ('PIS/COFINS:', 144.2, 360, 40.8),
    ('9.25%', 186.7, 360, 19.6),
    ('|', 211.4, 360, 1.8),
    ('Alíquota', 218.3, 360, 26.5),
    ('ISS:', 246.5, 360, 11.5),
    ('4%', 259.7, 360, 9.8),
    ('OPÇÕES', 45.4, 375, 23.9),
    ('DE', 70.8, 375, 8.0),
    ('PAGAMENTO*:', 80.4, 375, 42.1),
    ('À', 124.0, 375, 4.1),
    ('vista,', 129.6, 375, 13.6),
    ('Cartão', 144.8, 375, 17.7),
    ('de', 164.0, 375, 6.5),
    ('crédito,', 172.1, 375, 19.9),
    ('Cartão', 193.5, 375, 17.7),
    ('BNDEs,', 212.8, 375, 20.4),
    ('Boleto', 234.8, 375, 17.4),
    ('ou', 253.7, 375, 6.7),
    ('Depósito', 262.0, 375, 24.1),
    ('Bancário.', 287.6, 375, 24.5),
    ('*Compras', 45.4, 389, 26.0),
    ('no', 72.9, 389, 6.8),
    ('cartão', 81.2, 389, 16.6),
    ('de', 99.3, 389, 6.5),
    ('crédito', 107.4, 389, 18.6),
    ('com', 127.5, 389, 11.2),
    ('parcelamento', 140.2, 389, 36.0),
    ('até', 177.7, 389, 8.3),
    ('6', 187.5, 389, 3.5),
    ('vezes', 192.5, 389, 14.7),
    ('e', 208.8, 389, 3.2),
    ('parcela', 213.5, 389, 19.0),
    ('mínima', 234.0, 389, 19.1),
    ('de', 254.6, 389, 6.5),
    ('R$', 262.7, 389, 7.2),
    ('150,00.', 271.4, 389, 20.2),
    ('*Compras', 45.4, 402, 26.0),
    ('à', 72.9, 402, 3.0),
    ('vista', 77.4, 402, 12.3),
    ('e', 91.2, 402, 3.2),
    ('com', 95.9, 402, 11.2),
    ('entrada,', 108.7, 402, 21.5),
    ('terão', 131.7, 402, 13.9),
    ('seu', 147.2, 402, 9.1),
    ('prazo', 157.8, 402, 14.6),
    ('de', 174.0, 402, 6.5),
    ('fabricação', 182.0, 402, 27.2),
    ('contados', 210.7, 402, 24.1),
    ('a', 236.4, 402, 3.0),
    ('partir', 240.9, 402, 14.3),
    ('da', 256.7, 402, 6.3),
    ('compensação', 264.6, 402, 35.9),
    ('dos', 302.0, 402, 9.4),
    ('valores.', 312.9, 402, 20.3),
    ('*As', 45.4, 416, 9.2),
    ('condições', 56.1, 416, 26.4),
    ('de', 84.1, 416, 6.5),
    ('pagamento', 92.1, 416, 29.4),
    ('descritas', 123.1, 416, 23.3),
    ('acima', 148.0, 416, 15.2),
    ('estão', 164.7, 416, 14.3),
    ('condicionadas', 180.6, 416, 37.4),
    ('a', 219.5, 416, 3.0),
    ('aprovação', 224.0, 416, 27.3),
    ('de', 252.8, 416, 6.5),
    ('cadastro.', 260.9, 416, 23.9),
]

TUDO = [p(t, x, y, larg) for t, x, y, larg in PALAVRAS]
LINHAS = E._linhas_por_posicao(TUDO)

print("== o cabeçalho da tabela de itens é reconhecido em PORTUGUÊS ==")
ok("'Código Descrição NCM Qtde ...' é cabeçalho",
   E._eh_cabecalho_de_itens("Código Descrição NCM Qtde Valor NET Preço Final Total"))
ok("e o inglês da NEC continua sendo",
   E._eh_cabecalho_de_itens("Type Item Description Qty NCM ORIGEM"))
ok("mas prosa com a palavra 'descrição' não é",
   not E._eh_cabecalho_de_itens("Informar claramente a descrição técnica do projeto"))

print("\n== os itens saem com CÓDIGO, e a prosa fica de fora ==")
cab = next(ws for ws in LINHAS if E._eh_cabecalho_de_itens(E._juntar_palavras(ws)))
itens, _ = E._ler_planilha(LINHAS, cab)
ok("dois itens, nem um a mais", len(itens) == 2,
   "%d: %s" % (len(itens), [i.codigo for i in itens]))
codigos = [i.codigo for i in itens]
ok("o código da coluna 'Código' chega na AF",
   codigos == ["35020060099", "25010012083"], str(codigos))
ok("o cabeçalho de condições não virou item",
   not any("ELETRONET" in (i.codigo or "") for i in itens))
ok("nem o parágrafo 'RECEBIMENTO DA MERCADORIA'",
   not any("RECEBIMENTO" in (i.codigo or "") for i in itens))
if len(itens) == 2:
    a, b = itens
    ok("preço: o 'Preço Final', com imposto",
       a.preco_total_com == "3.655,00" and b.preco_total_com == "1.591,38",
       "%s / %s" % (a.preco_total_com, b.preco_total_com))
    ok("quantidade", a.quantidade == "1" and b.quantidade == "1")
    # a descrição do produto vem NAS LINHAS DE BAIXO da linha do item
    ok("a descrição é costurada com as linhas seguintes",
       "Rack Indoor" in a.descricao and "Quadro de Distribuição" in b.descricao,
       a.descricao[:60])
    # A COSTURA TEM DE PARAR. Ela aceitava qualquer linha sem dinheiro e sem
    # código — e depois do último item isso é a folha inteira: a descrição saiu
    # na AF com "OBSERVAÇÕES Alíquota ICMS: 12% ... CNPJ: 05.985.391/0001-64
    # ALGcompany — Transformando Ideias em Futuro". Agora só entra linha que
    # COMEÇA dentro da coluna "Descrição" (x 108 na folha); as observações
    # começam na margem (x 45).
    sujeira = ("OBSERVA", "Alíquota", "CNPJ", "ALGcompany", "pagamento")
    for it in itens:
        ok("a descrição de %s para no produto" % it.codigo,
           not any(x in it.descricao for x in sujeira), it.descricao[-70:])
    ok("e a descrição bate com a da proposta",
       " ".join(b.descricao.split()).endswith("com 8x 63A, 6x 32A e 6x 20A"),
       b.descricao[-50:])

print("\n== as condições do topo: cada valor no x do seu rótulo ==")
# reproduz o que _condicoes_no_cabecalho faz, sem precisar do PDF
cabc = next(ws for ws in LINHAS
            if "CLIENTE" in E._juntar_palavras(ws) and "PGTO" in E._juntar_palavras(ws))
i_cab = LINHAS.index(cabc)
cols = []
for w in cabc:
    alvo = next((c for pre, c in E._COND_CABECALHO if pre in w["text"].lower()), None)
    if cols and alvo and cols[-1][1] == alvo:
        continue
    cols.append((w["x0"], alvo))
valores = {}
for w in LINHAS[i_cab + 1]:
    dono = None
    for x, alvo in cols:
        if x <= w["x0"] + 2:
            dono = alvo
        else:
            break
    if dono:
        valores.setdefault(dono, []).append(w)
lido = {k: E._juntar_palavras(sorted(v, key=lambda w: w["x0"])).strip(" -:")
        for k, v in valores.items()}
ok("prazo de entrega", lido.get("prazo") == "45 dias úteis", str(lido.get("prazo")))
ok("condição de pagamento", lido.get("pagamento") == "30 dias", str(lido.get("pagamento")))
ok("e NÃO arrasta o sobrenome do contato",
   "Alves" not in (lido.get("pagamento") or ""), str(lido.get("pagamento")))
ok("frete", "520,00" in (lido.get("frete") or ""), str(lido.get("frete")))

print("\n== garantia: o rótulo no começo da linha ganha ==")
TXT = ("RECEBIMENTO DA MERCADORIA: O recebimento de mercadorias com embalagens\n"
       "danificadas e/ou violadas implica na perda de garantia do produto.\n"
       "GARANTIA: De acordo com a linha de produto.\n")
ok("lê a linha rotulada", E._garantia(TXT) == "De acordo com a linha de produto.",
   E._garantia(TXT))
ok("e não o rabo da frase sobre embalagem", "embalagens" not in E._garantia(TXT))

print("\n== frete numa linha só também é frete ==")
ok("'Frete R$ 520,00' no bloco de totais",
   E._valor_frete("Subtotal produtos R$ 5.246,38\nFrete R$ 520,00\n"
                  "TOTAL GERAL R$ 5.766,38\n") == 520.0)
ok("a cláusula que explica o CIF não vira valor de frete",
   E._valor_frete("O frete é CIF e corre por conta do fornecedor.\n") is None)

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

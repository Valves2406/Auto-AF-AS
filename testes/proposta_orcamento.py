# -*- coding: utf-8 -*-
r"""Proposta em forma de ORÇAMENTO: itens, frete fora da tabela e a filial.

O caso real: SEICOM, PR-156 - ELETRONET RS. Uma folha, duas colunas no topo
(fornecedor à esquerda, Eletronet à direita) e a tabela de itens em largura
fixa, sem fios entre as linhas.

O que saía errado, e por quê
----------------------------
Os dois produtos viravam DUAS LINHAS DE TOTAL. Sem fios horizontais, o
pdfplumber funde os itens numa célula só — "001 002", "BTRMT2004 DTEND0107", as
descrições coladas — e o que sobra reconhecível na tabela são as linhas de
fecho. "ICMS INCLUSO NOS VALORES ACIMA TOTAIS DA PÁGINA 1" e "TOTAIS DO
ORÇAMENTO" entravam como produtos, somando R$ 12.512,88 numa proposta de
R$ 13.256,44. (A guarda de linha de fecho existia, mas olhava `\btotal\b` e não
casava "TOTAIS", no plural.)

O TEXTO da mesma folha está limpo, um produto por linha. É de lá que os itens
saem agora, ancorados no par QUANTIDADE + UNIDADE ("1,000 PC") — o que separa a
descrição (texto livre, cheia de números e barras) da fila de valores.

E três coisas que a proposta trazia e o app ignorava:

* "CONDIÇÃO DE PAGTO.......: 503 - 30 DDL" — abreviado, com pontinhos, um
  código interno do fornecedor na frente e a coluna da direita começando na
  mesma linha. Vira a frase inteira, por pedido do usuário: a sigla é do dia a
  dia de quem compra, não de quem assina uma AF que sai da empresa.
* O PRAZO DE ENTREGA, na última coluna de cada item.
* A FILIAL da Eletronet a quem a proposta foi endereçada, casada pelo CNPJ.

O frete
-------
Os itens somam R$ 6.256,44 e a proposta diz R$ 13.256,44: a diferença é
exatamente o frete CIF de R$ 7.000,00, cobrado fora da tabela ("TOTAL +
DESPESAS"). O aviso dizia só que divergia — e divergência sem explicação faz
duvidar do documento inteiro. Agora, quando a conta fecha com o frete, ele diz.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta
from core.modelos import DadosProposta, brl_para_float

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()

# a folha da PR-156 como o pdfplumber devolve o TEXTO, sem depender do PDF
TEXTO = """PROPOSTA COMERCIAL Nº 000.156
SEICOM ELETRONET S.A
CONTATO: EDUARDO A/C:
RUA YASHICA, 535, JD GONÇALVES AVENIDA CARLOS GOMES, 1950 - ANDAR 3 SALA 4 TRES FIGUEIRAS
Sorocaba - SP CEP: 18.016-440 Porto Alegre-RS CEP: 90.470-282
CNPJ: 10.843.079/0001-76 I.E.: 669639015115 CNPJ: 03.052.673/0005-07 I.E.: 096/2.834.505
CONDIÇÃO DE PAGTO.......: 503 - 30 DDL TRANSPORTADORA........: 000 - TRANSUNI - ENCOME
FATURAMENTO MÍNIMO......: R$ 0,00 FRETE.................: CIF - VALOR: 7.000,00
EMISSÃO ................: 09/09/2026 TELEFONE..............:
VALIDADE................: 15 dias VENDEDOR .............: 01 - SEICOM
ÍNDICE/MOEDA ...........: R$ - REAL
QUANTIDADE VALOR % VR UNIT.R$ % % VALOR VALOR TOTAL PRAZO
ÍTEM MATERIAL DESCRIÇÃO ORÇADA U.M. UNIT.R$ DESCONTO C/DESCONTO ICMS IPI IPI (C/IMPOSTO) ENTREGA
001 BTRMT2004 BASTIDOR 44U EIA-ETSI 19-21POL L600 X P600 X A2100MM 1,000 PC 4.650,0000 0,0 4.650,000 12,00 7,50 809,36 5.459,36 5
002 DTEND0107 PDU 3U 200A 2V 1P COM DISJ 1P 6X20A/6X32A/8X63A 1,000 PC 650,0000 0,0 650,000 12,00 9,75 147,08 797,08 5
ICMS INCLUSO NOS VALORES ACIMA TOTAIS DA PÁGINA 1 : 2,000 956,44 6.256,44
TOTAIS DO ORÇAMENTO : 2,000 956,44 6.256,44
TOTAL + DESPESAS : 13.256,44
OBSERVACOES
PÁGINA 1"""

itens = E._itens_orcamento(TEXTO)

print("== os PRODUTOS, e não as linhas de total ==")
ok("achou os dois produtos", len(itens) == 2, "%d item(ns)" % len(itens))
ok("nenhuma linha de TOTAIS virou produto",
   not any("total" in it.descricao.lower() for it in itens))
if len(itens) == 2:
    a, b = itens
    ok("código do 1º", a.codigo == "BTRMT2004", a.codigo)
    ok("descrição do 1º",
       a.descricao == "BASTIDOR 44U EIA-ETSI 19-21POL L600 X P600 X A2100MM", a.descricao)
    ok("quantidade '1,000' vira 1", a.quantidade == "1", a.quantidade)
    ok("unidade", a.unidade == "PC", a.unidade)
    # 4.650,00 + 809,36 de IPI = 5.459,36: o unitário da coluna é SEM imposto
    ok("unitário SEM impostos, com 2 casas", a.preco_unit_sem == "4.650,00", a.preco_unit_sem)
    ok("unitário COM impostos sai do total ÷ qtd", a.preco_unit_com == "5.459,36",
       a.preco_unit_com)
    ok("total da linha", a.preco_total_com == "5.459,36", a.preco_total_com)
    ok("prazo de entrega do item", a.prazo == "5 dias", a.prazo)
    # a descrição do 2º tem barras e números — não pode ser cortada
    ok("descrição do 2º sai inteira",
       b.descricao == "PDU 3U 200A 2V 1P COM DISJ 1P 6X20A/6X32A/8X63A", b.descricao)

print("\n== 'TOTAIS' no plural também é linha de fecho ==")
# `\btotal\b` não casa "TOTAIS" — foi essa fresta que deixou passar dois falsos
for frase in ("TOTAIS DO ORÇAMENTO :",
              "ICMS INCLUSO NOS VALORES ACIMA TOTAIS DA PÁGINA 1 :",
              "TOTAL + DESPESAS :"):
    ok("descarta %r" % frase[:34], not E._eh_descricao_de_item(frase))
ok("mas um produto de verdade passa",
   E._eh_descricao_de_item("BASTIDOR 44U EIA-ETSI 19-21POL"))

print("\n== a condição de pagamento, por extenso ==")
lido = E._pagamento(TEXTO)
ok("lê apesar de 'PAGTO', dos pontinhos e do código '503 -'",
   lido == "O pagamento deve ser efetuado 30 dias após o faturamento", lido)
ok("e não arrasta a coluna da direita (TRANSPORTADORA)",
   "TRANSPORTADORA" not in lido and "TRANSUNI" not in lido)

print("\n== o frete explica a diferença, em vez de só acusar ==")
ok("acha o valor do frete", E._valor_frete(TEXTO) == 7000.0, str(E._valor_frete(TEXTO)))
d = DadosProposta(valor_total="13.256,44", itens=itens)
E.ultimo_texto = TEXTO
E._avisar_divergencia_total(d)
aviso = " ".join(d.avisos)
ok("o aviso diz que é o frete", "frete" in aviso.lower(), aviso or "(nenhum aviso)")
ok("e não trata como erro", "⚠" not in aviso, aviso)
# sem frete no texto, a divergência volta a ser um alerta de verdade
d2 = DadosProposta(valor_total="99.999,99", itens=itens)
E.ultimo_texto = "proposta sem frete nenhum"
E._avisar_divergencia_total(d2)
ok("divergência inexplicada continua alertando", "⚠" in " ".join(d2.avisos),
   " ".join(d2.avisos) or "(nenhum aviso)")

print("\n== o frete fora da tabela vira um ITEM ==")
# Mesmo pedido da Artemis. A trava: só entra quando a ARITMÉTICA prova que ele
# falta — soma dos itens + frete tem de fechar com o total da proposta. Numa
# proposta em que o frete já está embutido no preço de cada linha, acrescentar o
# item contaria o frete duas vezes.
_d = DadosProposta(valor_total="13.256,44", itens=list(itens))
E._frete_como_item(_d, TEXTO)
_fretes = [i for i in _d.itens if i.descricao == "Frete"]
ok("o frete entrou como item", len(_fretes) == 1, "%d" % len(_fretes))
if _fretes:
    ok("quantidade 1", _fretes[0].quantidade == "1", _fretes[0].quantidade)
    ok("com o valor da proposta", _fretes[0].preco_total_com == "7.000,00",
       _fretes[0].preco_total_com)
_soma = sum(brl_para_float(i.preco_total_com) or 0 for i in _d.itens)
ok("agora os itens somam o total da proposta", abs(_soma - 13256.44) < 0.01,
   "%.2f" % _soma)
ok("e o app avisa que mexeu na lista",
   any("frete" in a.lower() and "item" in a.lower() for a in _d.avisos),
   str(_d.avisos))
# chamado de novo, não duplica
E._frete_como_item(_d, TEXTO)
ok("chamar duas vezes não duplica o frete",
   len([i for i in _d.itens if i.descricao == "Frete"]) == 1)
# e quando o frete JÁ está no preço das linhas, a conta não fecha e nada entra
_e = DadosProposta(valor_total="6.256,44", itens=list(itens))
E._frete_como_item(_e, TEXTO)
ok("frete já embutido no preço não vira item de novo",
   not any(i.descricao == "Frete" for i in _e.itens))

print("\n== a filial da Eletronet vem da própria proposta ==")
fat = E._faturamento_da_proposta(TEXTO, "10.843.079/0001-76")
ok("achou uma filial", len(fat) == 1, "%d" % len(fat))
if fat:
    ok("é a do RS", fat[0].get("uf") == "RS", str(fat[0].get("uf")))
    ok("pelo CNPJ que está na folha", fat[0].get("cnpj") == "03.052.673/0005-07",
       str(fat[0].get("cnpj")))
# o CNPJ do FORNECEDOR também está na folha e não pode ser confundido
ok("não casa o CNPJ do fornecedor",
   not E._faturamento_da_proposta("CNPJ: 10.843.079/0001-76", "10.843.079/0001-76"))
ok("proposta sem CNPJ da Eletronet não inventa filial",
   not E._faturamento_da_proposta("proposta qualquer, sem CNPJ nenhum", ""))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

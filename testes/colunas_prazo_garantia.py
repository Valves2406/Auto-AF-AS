# -*- coding: utf-8 -*-
r"""Prazo, garantia e código quando eles vêm em COLUNA da tabela.

O caso real: DATACOM, PRPT 9363_26B. A proposta traz, por item, "Prazo Entrega
(dias)" e "Prazo de Garantia (meses)" nas duas últimas colunas — e os valores
DIFEREM entre itens (15 dias em quase tudo e 70 numa fonte; 24 meses em quase
tudo e 12 em duas). As regras antigas procuravam só texto corrido ("Garantia é
de 24 meses"), então os dois campos saíam vazios.

Quatro armadilhas desta tabela, cada uma com um teste aqui
----------------------------------------------------------
1. O cabeçalho vem PARTIDO em várias linhas: "Prazo" numa, "Entrega" na
   seguinte, "(dias)" mais abaixo. Olhar linha a linha não enxerga nenhum
   rótulo inteiro — as linhas de cabeçalho precisam ser empilhadas por coluna.

2. O CÓDIGO do produto é só dígito e ponto ("800.5304"). A heurística de Part
   Number exige uma LETRA no token, então não reconhecia nada. Quem sabe onde
   está o código é o cabeçalho.

3. A linha de LICENÇA vem de uma sub-tabela com colunas próprias (ISS no lugar
   de ICMS/IPI) e cai deslocada na grade da tabela grande. Medido pela posição
   X na folha: 882,00 | 6 | 2 | 18,00 | 900,00 | 5.400,00 é
   unit s/imp | QTD | ISS% | valor do ISS | unit c/imp | total.
   Lida ao pé da letra, a quantidade virava 2 — e 6 x 900,00 = 5.400,00 impresso
   na mesma linha diz que são 6. AF com quantidade errada é pedido errado.

4. A linha "Valor Global da Proposta com Impostos: R$ 902.275,28" virava um
   PRODUTO, porque bastava a célula CONTER um número para ser preço. Somava a
   proposta inteira outra vez: o total dos itens dava o dobro do da proposta.
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

# A tabela da DATACOM como o pdfplumber a devolve: cabeçalho partido em 7 linhas
# e 13 colunas. Reproduzida aqui para o teste não depender do PDF do usuário.
CAB = [
    ["", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "", "", "", "Preço", "", "", "Preço", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "Preço total", "Prazo", "Prazo de"],
    ["", "", "Classif.", "Código", "", "", "unitário", "", "", "unitário", "", "", ""],
    ["Código", "", "", "", "Descrição", "Qtde", "", "% ICMS", "% IPI", "", "com", "Entrega", "Garantia"],
    ["", "", "Fiscal", "Finame", "", "", "sem ICMS", "", "", "com", "", "", ""],
    ["", "", "", "", "", "", "", "", "", "", "Imposto", "(dias)", "(meses)"],
    ["", "", "", "", "", "", "e sem IPI", "", "", "Impostos", "", "", ""],
]
COMUTADOR = ["800.5304", "", "8517.62.34", "3611178", "DM4270 48XS+6CX - Comutador Ethernet",
             "6", "15.700,00", "12", "9,75", "19.844,24", "119.065,42", "15", "24"]
FONTE = ["800.5257", "", "8504.40.30", "3723177", "PSU 600 DC-F - Fonte de alimentação DC",
         "9", "1.550,00", "12", "15", "2.067,86", "18.610,78", "70", "24"]
FONTE_AC = ["820.0018", "", "8504.40.21", "", "PSU 600 AC-F - Fonte de alimentação AC",
            "1", "2.000,00", "4", "3,75", "2.164,84", "2.164,84", "15", "12"]
# a licença, deslocada: descrição na coluna do código e os números empurrados
LICENCA = ["Licença DM4270 48P - SW MPLS", "", "", "", "", "", "",
           "882,00", "6", "2", "18,00", "900,00", "5.400,00"]
FECHO = ["Valor Global da Proposta com Impostos: R$ 902.275,28", "", "", "", "",
         "", "", "", "", "", "", "", ""]

TABELA = CAB + [COMUTADOR, FONTE, FONTE_AC, LICENCA, FECHO]
itens = E._itens_de_tabela(TABELA)


def item(trecho):
    """O item cuja descrição contém este trecho."""
    return next(it for it in itens if trecho in it.descricao)

print("== o cabeçalho partido em 7 linhas ainda diz onde está cada coluna ==")
cols = E._cols_prazo_garantia(TABELA)
ok("achou a coluna do código", cols.get("codigo", (None,))[0] == 0, str(cols.get("codigo")))
ok("e não confundiu com 'Código Finame' nem 'Classif. Fiscal'",
   cols.get("codigo", (None,))[0] not in (2, 3))
ok("achou a coluna do prazo, em dias", cols.get("prazo") == (11, "dias"), str(cols.get("prazo")))
ok("achou a coluna da garantia, em meses", cols.get("garantia") == (12, "meses"),
   str(cols.get("garantia")))

print("\n== cada item guarda o SEU prazo e a SUA garantia ==")
ok("comutador: 15 dias / 24 meses",
   item("DM4270").prazo == "15 dias" and item("DM4270").garantia == "24 meses")
ok("fonte DC: 70 dias (o prazo diferente)", item("PSU 600 DC-F").prazo == "70 dias",
   item("PSU 600 DC-F").prazo)
ok("fonte AC: 12 meses (a garantia diferente)",
   item("PSU 600 AC-F").garantia == "12 meses", item("PSU 600 AC-F").garantia)

print("\n== o documento resume sem esconder que os itens diferem ==")
ok("prazos 15 e 70 viram '15 a 70 dias'",
   E._resumir_duracoes(["15 dias", "70 dias", "15 dias"]) == "15 a 70 dias")
ok("garantias 24 e 12 viram '12 a 24 meses'",
   E._resumir_duracoes(["24 meses", "12 meses", "24 meses"]) == "12 a 24 meses")
ok("todos iguais dão o valor, sem faixa",
   E._resumir_duracoes(["15 dias", "15 dias"]) == "15 dias")
ok("um só, no singular", E._resumir_duracoes(["1 meses"]) == "1 mês")
ok("vazio continua vazio", E._resumir_duracoes(["", None, "  "]) == "")
ok("'Pronta-entrega' passa inteiro", E._resumir_duracoes(["Pronta-entrega"]) == "Pronta-entrega")

print("\n== o código do produto ==")
ok("código só de dígitos é aceito", item("DM4270").codigo == "800.5304",
   item("DM4270").codigo)
ok("e não pegou o NCM nem o Finame",
   item("DM4270").codigo not in ("8517.62.34", "3611178"))

print("\n== a linha de LICENÇA ==")
lic = next((it for it in itens if it.descricao.lower().startswith("licen")), None)
ok("a licença virou item", lic is not None)
if lic:
    ok("código = LICENÇA", lic.codigo == "LICENÇA", lic.codigo)
    # 6 x 900,00 = 5.400,00 — a conta diz que são 6, não os 2 da coluna do ISS
    ok("quantidade conferida pela conta (6, não 2)", lic.quantidade == "6", lic.quantidade)
    ok("unitário com impostos", lic.preco_unit_com == "900,00", lic.preco_unit_com)
    ok("total", lic.preco_total_com == "5.400,00", lic.preco_total_com)
    # 882,00 estava na coluna que o cabeçalho chama de "% ICMS"
    ok("sem impostos é 882,00, não os 18,00 do ISS", lic.preco_unit_sem == "882,00",
       lic.preco_unit_sem)
    ok("licença não inventa prazo a partir de '900,00'", lic.prazo == "", lic.prazo)
    ok("nem garantia a partir de '5.400,00'", lic.garantia == "", lic.garantia)

print("\n== a linha de fecho NÃO é produto ==")
ok("'Valor Global da Proposta' ficou de fora",
   not any("valor global" in it.descricao.lower() for it in itens))
ok("sobraram só os 4 itens de verdade", len(itens) == 4, "%d itens" % len(itens))
soma = sum(float(it.preco_total_com.replace(".", "").replace(",", ".")) for it in itens)
ok("e a soma é a dos itens, sem dobrar", abs(soma - 145241.05) < 0.01, "%.2f" % soma)

print("\n== 'Condição de pagamento' no SINGULAR ==")
# O padrão antigo era `Condi[çc][õo]es?`: cobre "Condições"/"Condicoes" mas exige
# um "o"/"õ" onde o singular tem "ão". A DATACOM escreve "Condição de pagamento:
# 30/60/90 dias." — e a forma de pagamento saía VAZIA numa proposta que a trazia
# escrita com todas as letras.
# "DDL" ("dias data líquida") é sigla do dia a dia de quem compra, não de quem
# assina a AF — e a AF sai da empresa. Por pedido do usuário ela vira a frase
# inteira; o que já vem escrito por extenso passa como está.
_FRASE = "O pagamento deve ser efetuado %d dias após o faturamento"
for texto, esperado in (
        ("Condição de pagamento: 30/60/90 dias.", "30/60/90 dias"),
        ("Condições de pagamento: 30 DDL", _FRASE % 30),
        ("Condicao de pagamento: 30/60/90", "30/60/90"),
        ("Condicoes de pagamento: 28 ddl", _FRASE % 28),
        # número sozinho = uma parcela com aquele prazo de carência
        ("CONDIÇÕES DE PAGAMENTO: 28 dias",
         "O pagamento será realizado em 1x com até 28 dias de carência"),
        ("Forma de pagamento: à vista", "à vista"),
        # abreviado, com pontinhos e o código interno do fornecedor na frente,
        # e a coluna da direita começando na mesma linha (folha de 2 colunas)
        ("CONDIÇÃO DE PAGTO.......: 503 - 30 DDL TRANSPORTADORA........: 000 - TRANSUNI",
         _FRASE % 30),
        ("Condição de pagamento: 1 DDL", "O pagamento deve ser efetuado 1 dia após o faturamento")):
    lido = E._pagamento(texto)
    ok("lê %r" % texto[:34], lido == esperado, "veio %r" % lido)

print("\n== dinheiro não vira prazo, e prazo absurdo é descartado ==")
ok("'900,00' não é duração", E._dur_da_celula("900,00", "dias") == "")
ok("'5.400,00' também não", E._dur_da_celula("5.400,00", "meses") == "")
ok("'15' com o cabeçalho em dias", E._dur_da_celula("15", "dias") == "15 dias")
ok("'1' vira singular", E._dur_da_celula("1", "meses") == "1 mês")
ok("garantia de 999 meses é erro de leitura", E._dur_da_celula("999", "meses") == "")

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

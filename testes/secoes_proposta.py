# -*- coding: utf-8 -*-
r"""Proposta organizada em SEÇÕES numeradas.

Muita proposta vem assim — título numerado e o conteúdo embaixo:

    3.3 CONDIÇÕES DE PAGAMENTO
    ➢ Pagamentos 30 (trinta) dias após o envio da nota fiscal...
    3.5 VALOR
    ➢ R$ 13.934,70 (treze mil novecentos e trinta e quatro reais...)

As regras campo-a-campo do extrator leem UMA linha ("Garantia: 12 meses"). Aqui
o valor está na linha SEGUINTE ao título e às vezes ocupa várias — por isso
garantia e condição de pagamento saíam vazias mesmo estando escritas com todas
as letras na proposta, e o escopo saía cortado no meio da frase.

O texto abaixo reproduz a proposta BRU-OR-0172/25 (Zopone, SE Araraquara), que
foi o caso real.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


# O sumário vem antes de propósito: ele repete os mesmos títulos seguidos de
# pontilhado e do número da página, e é a armadilha óbvia deste formato.
TEXTO = """À
ELETRONET
A/C: Sr. Douglas Kutudjian
N.º: BRU-OR-0172/25
REF.: Proposta Comercial
Adicional - Kit de Aterramento

SUMÁRIO
3.1 ESCOPO DE FORNECIMENTO ....................................................................... 6
3.3 CONDIÇÕES DE PAGAMENTO ....................................................................... 6
3.5 VALOR .................................................................................................................... 6
3.10 GARANTIA ............................................................................................................ 7

3. ESPECIFICAÇÕES COMERCIAIS
3.1 ESCOPO DE FORNECIMENTO
1. Fornecimento de 02 (dois) kits certificados de aterramento
temporário para veículos, destinados à equipotencialização e proteção
durante a execução de atividades na Subestação Araraquara (SE
Araraquara).
3.2 EXCLUSÕES
➢ Qualquer item não explicitamente descrito no escopo de
fornecimento.
3.3 CONDIÇÕES DE PAGAMENTO
➢ Pagamentos 30 (trinta) dias após o envio da nota fiscal referente
a 100% do valor desta proposta.
3.4 IMPOSTOS
➢ Todos os impostos estão inclusos.
3.5 VALOR
➢ R$ 13.934,70 (treze mil novecentos e trinta e quatro reais e
setenta centavos).
3.6 VALIDADE DA PROPOSTA
➢ 30 (trinta) dias.
Av. Rodrigues Alves, 34-53 Vila Coralina
Bauru/SP Cep: 17030-000
www.zopone.com.br
3.10 GARANTIA
➢ O período de garantia será de 5 (cinco) anos a contar da
notificação de conclusão da obra.
➢ Para equipamentos a garantia será de 1 (um) ano.
3.11 INFORMAÇÕES CADASTRAIS
Razão Social Zopone Engenharia e Comércio Ltda
Endereço Completo Avenida Rodrigues Alves, 34-53 – Vila Coralina – Bauru / SP –
CEP: 17030-000
CNPJ 59.225.698/0001-96
Inscrição Estadual 209.114.915-115
"""

e = ExtratorProposta()

print("== o sumário não é confundido com o conteúdo ==")
sec = e._secoes(TEXTO)
ok("achou as seções", len(sec) >= 6, "%d seção(ões)" % len(sec))
ok("o conteúdo do VALOR é o valor, não a lista de títulos",
   "13.934,70" in sec.get("VALOR", ""), repr(sec.get("VALOR", "")[:60]))
ok("nenhuma seção guardou o pontilhado do sumário",
   not any("......" in c for c in sec.values()))

print("\n== os campos que só existem dentro de uma seção ==")
ok("garantia", e._garantia(TEXTO).startswith("O período de garantia será de 5 (cinco) anos"),
   repr(e._garantia(TEXTO)[:70]))
ok("as duas linhas da garantia entram",
   "1 (um) ano" in e._garantia(TEXTO), repr(e._garantia(TEXTO)[-40:]))
pg = e._pagamento(TEXTO)
ok("condição de pagamento", pg.startswith("Pagamentos 30 (trinta) dias"), repr(pg[:60]))
ok("e não arrasta a seção seguinte", "IMPOSTOS" not in pg and "impostos" not in pg.lower(),
   repr(pg[-50:]))
obj = e._objeto(TEXTO, [])
ok("escopo de fornecimento vira o objeto", obj.startswith("Fornecimento de 02 (dois) kits"),
   repr(obj[:60]))
ok("o objeto NÃO sai cortado no meio da frase", "Araraquara" in obj, repr(obj[-40:]))
ok("a numeração '1.' não entra no texto", not obj.startswith("1."), repr(obj[:12]))

print("\n== o rodapé que se repete em toda folha fica de fora ==")
for campo, valor in (("garantia", e._garantia(TEXTO)), ("pagamento", pg), ("objeto", obj)):
    ok("%s sem o rodapé" % campo,
       "zopone.com.br" not in valor and "Rodrigues Alves" not in valor, repr(valor[-40:]))

print("\n== número da proposta ==")
ok("lê 'N.º: BRU-OR-0172/25'", e._numero_proposta(TEXTO) == "BRU-OR-0172/25",
   repr(e._numero_proposta(TEXTO)))
# a regra genérica lia "REF.: Proposta Comercial" e devolvia "Comercial"
ok("palavra sem dígito nenhum não é número de proposta",
   e._numero_proposta("REF.: Proposta Comercial\nnada mais aqui") == "",
   repr(e._numero_proposta("REF.: Proposta Comercial\nnada mais aqui")))

print("\n== endereço com rótulo sem dois-pontos ==")
end = e._endereco(TEXTO)
ok("lê 'Endereço Completo  Avenida...'", end.startswith("Avenida Rodrigues Alves, 34-53"), repr(end[:50]))
ok("sem o traço solto no fim", not end.rstrip().endswith("–"), repr(end[-20:]))

print("\n== o que a proposta NÃO diz continua vazio ==")
# esta proposta nao tem prazo de entrega; inventar um seria pior que deixar vazio
ok("prazo de entrega fica vazio", e._prazo(TEXTO) == "", repr(e._prazo(TEXTO)))

print("\n== proposta SEM seções continua lida pela regra de linha ==")
SIMPLES = ("Nossa referência: PRPT 9363_26A\n"
           "Valor Global da Proposta ......... R$ 140.474,70\n"
           "Prazo de entrega: 45 dias\n"
           "Garantia: 12 meses\n")
ok("número", e._numero_proposta(SIMPLES) == "PRPT 9363_26A", repr(e._numero_proposta(SIMPLES)))
ok("valor", e._valor_total(SIMPLES) == "140.474,70", repr(e._valor_total(SIMPLES)))
ok("prazo", e._prazo(SIMPLES) == "45 dias", repr(e._prazo(SIMPLES)))
ok("garantia", e._garantia(SIMPLES) == "12 meses", repr(e._garantia(SIMPLES)))

print("\n== a garantia em FRASE não vira número + unidade errada ==")
# "O período de garantia será de 5 (cinco) anos a contar da…" saía no formulário
# como 5 + a unidade PADRÃO do campo, ou seja "5 Meses": cinco anos viraram
# cinco meses no documento. A unidade passou a ser obrigatória no regex — sem
# ela colada ao número, o texto inteiro vai para a opção "Livre".
# Comportamento conferido no app rodando; aqui fica a regra.
js = io.open(os.path.join(PROJ, "frontend", "app.js"), encoding="utf-8").read()
# a janela cobre a função inteira: ela cresceu quando passou a decidir também
# se a frase É a duração ou apenas CONTÉM uma
corpo = js[js.index("function splitDur("):][:1800]
ok("a unidade é obrigatória no regex de duração",
   "(dias?|m[eê]s(?:es)?|anos?)\\b/i" in corpo,
   "com a unidade opcional, o 1º número de um texto corrido virava a duração")
ok("texto sem duração reconhecível vai para 'Livre'",
   'if ((prefix === "garantia" || prefix === "prazo") && raw && !num && !un' in js)
ok("nenhum byte de controle sobrou no arquivo", "\x08" not in js,
   "um heredoc já gravou \\b aqui como byte de backspace, e o regex parou de casar")

print("\n== a extração não gasta o Docling onde não há tabela ==")
# Medido: a proposta de preço fechado levava 28,6s (22s só o Docling procurando
# itens que não existem). Uma tabela de N itens traz pelo menos N preços; esta
# proposta tem 1 preço no documento inteiro.
ok("proposta de preço fechado dispensa o Docling", not e._pode_ter_tabela(TEXTO),
   "%d preço(s) distintos" % len(set(e._DINHEIRO_DOC.findall(TEXTO))))
MUITOS = "R$ 1.000,00\nR$ 2.500,50\nR$ 300,00\nR$ 4.000,00\n"
ok("proposta com vários preços continua tentando", e._pode_ter_tabela(MUITOS))
ok("o corte fica abaixo do caso que o Docling resolve", e._MIN_PRECOS_TABELA <= 4,
   "a PADTEC tem 4 preços e é onde o Docling comprovadamente acha os itens")

print("\n== preço fechado vira UMA linha de item, tirada do escopo ==")
# A proposta de serviço cotado num número só não tem tabela de itens, mas a AF
# precisa de pelo menos uma linha dizendo o que está sendo comprado — e o escopo
# de fornecimento diz, com todas as letras.
it = e._item_do_escopo(TEXTO, e._objeto(TEXTO, []), "13.934,70")
ok("montou o item", it is not None)
ok("a descrição é o escopo", it.descricao.startswith("Fornecimento de 02 (dois) kits"),
   repr(it.descricao[:50]))
ok("a quantidade sai do texto ('02 (dois)')", it.quantidade == "2", repr(it.quantidade))
ok("o total da linha é o valor da proposta", it.preco_total_com == "13.934,70",
   repr(it.preco_total_com))
ok("o unitário é o total dividido pela quantidade", it.preco_unit_com == "6.967,35",
   "%r — conta, não chute" % it.preco_unit_com)
# a linha não pode contradizer o total declarado, senão a AF sai brigando consigo
soma = float(it.preco_total_com.replace(".", "").replace(",", "."))
ok("linha × quantidade fecha com o total", abs(soma - 13934.70) < 0.01, str(soma))

print("\n== e não inventa item onde não cabe ==")
ok("sem escopo, não monta nada", e._item_do_escopo(TEXTO, "", "13.934,70") is None)
ok("sem valor, não monta nada", e._item_do_escopo(TEXTO, "Fornecimento de kits", "") is None)
ok("valor zerado não monta nada", e._item_do_escopo(TEXTO, "Fornecimento de kits", "0,00") is None)
so_um = e._item_do_escopo(TEXTO, "Prestação de serviço de manutenção", "1.000,00")
ok("escopo sem quantidade escrita fica com 1", so_um.quantidade == "1", repr(so_um.quantidade))
ok("e o unitário é o próprio total", so_um.preco_unit_com == "1.000,00", repr(so_um.preco_unit_com))

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

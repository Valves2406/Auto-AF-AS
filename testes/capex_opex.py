# -*- coding: utf-8 -*-
r"""A verba do CPM/CPS pode ser CAPEX ou OPEX.

CAPEX é investimento (o bem vira patrimônio); OPEX é custeio (despesa do dia a
dia). Quem decide é quem preenche, numa cortina ao lado do valor.

A escolha muda SÓ O NOME da verba no documento. A conta do saldo continua sendo
verba − valor, e o Excel oficial continua escrevendo os mesmos números nas mesmas
células — mexer nisso seria mudar o documento oficial, que não foi o pedido.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import engine
from core.html_render import montar_cpm_html

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


BASE = {"fornecedor": "PADTEC S/A", "valor_total": "63.311,60", "numero": "346",
        "ano": "2026", "prefixo": "AS-E", "modificacao": "TR", "revisao": "0",
        "moeda": "Real", "objeto": "Caracterizacao de fibras", "cenario": "sem",
        "capex": "100.000,00"}


def documento(tipo):
    return montar_cpm_html(engine.cpm_de_form(dict(BASE, tipo_verba=tipo)))


def rotulo_e_valor(html):
    m = re.search(r'<div class="cl">(CAPEX|OPEX)</div><div class="cv">([^<]*)', html)
    return (m.group(1), m.group(2).strip()) if m else (None, None)


def saldo(html):
    m = re.search(r'Saldo</div><div class="cv">([^<]*)', html)
    return m.group(1).strip() if m else None


print("== a cortina troca o nome da verba ==")
for pedido, esperado in (("", "CAPEX"), ("CAPEX", "CAPEX"), ("OPEX", "OPEX"), ("opex", "OPEX")):
    rot, val = rotulo_e_valor(documento(pedido))
    ok("formulario %-7r -> documento diz %s" % (pedido, esperado), rot == esperado, str(rot))

print("\n== o que vier fora da lista nao chega ao documento ==")
# a cortina so oferece dois valores, mas o motor nao pode confiar no formulario
rot, _ = rotulo_e_valor(documento("Verba Livre S/A"))
ok("texto estranho cai no padrao CAPEX", rot == "CAPEX", str(rot))

print("\n== a conta NAO muda com o tipo da verba ==")
cap, ope = documento("CAPEX"), documento("OPEX")
ok("mesmo valor de verba", rotulo_e_valor(cap)[1] == rotulo_e_valor(ope)[1])
ok("mesmo saldo", saldo(cap) == saldo(ope) == "R$ 36.688,40",
   "%r vs %r" % (saldo(cap), saldo(ope)))

print("\n== sem verba informada, os dois se comportam igual ==")
vazio_c = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="", tipo_verba="CAPEX")))
vazio_o = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="", tipo_verba="OPEX")))
ok("diz 'nao informado' nos dois", "não informado" in vazio_c and "não informado" in vazio_o)
# o saldo APARECE mesmo sem verba (pedido do usuario): verba zero menos o valor.
# Quem le ve "nao informado" na verba ao lado e sabe de onde veio o numero.
ok("mas o saldo aparece nos dois", saldo(vazio_c) == saldo(vazio_o) == "R$ -63.311,60",
   "%r vs %r" % (saldo(vazio_c), saldo(vazio_o)))

print("\n== a cortina existe na tela e volta preenchida ==")
htm = io.open(os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read()
js = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()
css = io.open(os.path.join(PROJ, "web", "app.css"), encoding="utf-8").read()
ok("a cortina esta na tela", 'id="cpmTipoVerba"' in htm)
ok("oferece os dois e so os dois",
   htm.count('<option value="CAPEX">') == 1 and htm.count('<option value="OPEX">') == 1)
ok("o rotulo do campo E a cortina", 'class="rotsel"' in htm,
   "o nome do campo deixou de ser texto fixo")
ok("tem o estilo da casa", ".rotsel select" in css)
ok("o apoio nao quebra em duas linhas", "text-overflow: ellipsis" in
   css[css.index(".rotsel .muted"):css.index(".rotsel .muted") + 220])
ok("vai no formulario enviado ao motor", 'cpmTipoVerba: "tipo_verba"' in js)
ok("volta preenchida ao importar um CPM", 'if ($("cpmTipoVerba")) $("cpmTipoVerba").value =' in js)
ok("trocar a cortina redesenha a previa", '$("cpmTipoVerba").onchange = cpmPreview;' in js)

print("\n== saldo negativo aparece SEMPRE ==")
# Regra escolhida pelo usuario: o saldo aparece com ou sem verba informada, e
# negativo e vermelho nos dois casos. Eu tinha escondido o saldo quando a verba
# vinha em branco, com medo de o vermelho acusar um rombo que ninguem declarou —
# o usuario preferiu ver o numero, e a verba "nao informado" fica do lado.
curto = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="10.000,00")))
ok("verba menor que o valor -> saldo negativo", "-53.311,60" in (saldo(curto) or ""), saldo(curto))
ok("e marcado em vermelho", "cel neg" in curto)
folga = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="100.000,00")))
ok("verba maior -> saldo positivo, sem vermelho",
   "cel neg" not in folga and "36.688,40" in (saldo(folga) or ""), saldo(folga))
vazio = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="")))
ok("sem verba, o saldo e o valor negativado", saldo(vazio) == "R$ -63.311,60", saldo(vazio))
ok("e sai em vermelho", "cel neg" in vazio)
ok("com a verba dizendo que nao foi informada", "n\u00e3o informado" in vazio)
# so o documento AINDA VAZIO (sem verba E sem valor) mantem o travessao: nao ha
# conta a fazer, e "R$ 0,00" seria ruido num formulario em branco
branco = montar_cpm_html(engine.cpm_de_form(dict(BASE, capex="", valor_total="")))
ok("documento em branco mantem o travessao", "cel neg" not in branco)

print("\n== cotacao so existe em moeda estrangeira ==")
# Em Real nao ha taxa de conversao: o campo pedia um numero que nao se aplica, e
# quem preenchesse por engano poria uma conversao inventada no documento.
ok("o campo de cotacao tem id proprio", 'id="cpmCotacaoLinha"' in htm)
ok("e some quando a moeda e Real", '$("cpmCotacaoLinha").hidden = isReal;' in js)
ok("a linha de conversao tambem some", '$("cpmConvLinha").hidden = isReal;' in js)
ok("a verba ocupa a linha inteira quando a cotacao some",
   '$("cpmVerbaLinha").classList.toggle("c12", isReal);' in js,
   "senao fica meia linha vazia ao lado")
ok("e volta a meia linha em moeda estrangeira",
   '$("cpmVerbaLinha").classList.toggle("c6", !isReal);' in js)

print("\n== o Excel oficial nao muda ==")
ger = io.open(os.path.join(PROJ, "core", "gerador.py"), encoding="utf-8").read()
ok("as celulas do Excel continuam as mesmas", '"I21": capex' in ger and '"I27": capex - valor' in ger,
   "o pedido foi trocar o nome no documento, nao mexer no modelo oficial")

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

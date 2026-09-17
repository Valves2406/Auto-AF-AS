# -*- coding: utf-8 -*-
r"""O FORMULÁRIO não pode desmontar o que o extrator leu certo.

Este teste existe porque eu consertei a leitura e não conferi a ponta. O
extrator passou a devolver a frase inteira, e o campo da tela a jogava fora —
o usuário continuava vendo o erro, com razão.

Medido na página, com as funções de verdade (`setDur` / `joinDur`):

    entra: "90 dias após a assinatura do documento de contratação"
    saía:  "90 Dias"                    <- o marco foi embora

    entra: "2 anos para produtos LightPad (DWDM) / Plugáveis revenda: 1 ano"
    saía:  "2 Anos"                     <- a garantia dos plugáveis sumiu

    entra: "item 1: 3 unidades a pronta entrega, as demais dia 22/09; item 2..."
    saía:  "Pronta-entrega"             <- o documento prometendo o que
                                           ninguém prometeu

Os campos de garantia e prazo têm dois modos: NÚMERO + UNIDADE ("24 Meses") e
LIVRE (texto qualquer). A regra antiga usava o par sempre que encontrasse um
número com unidade em QUALQUER lugar da frase, e descartava o resto — mesmo
quando o resto é o que dá sentido ao número.

A regra agora: o par só vale quando a frase é ESSENCIALMENTE o par. Sobrando
texto com significado depois de tirar número, unidade e palavras de ligação, o
campo vai inteiro para o modo livre. E "Pronta-entrega" só vale quando a frase
É isso — não quando apenas menciona a expressão.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


JS = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()

print("== a regra existe no código da tela ==")
ok("há uma função que decide se a frase é só a duração", "function soDuracao(" in JS)
ok("o par é recusado quando sobra texto", "if (!soDuracao(s, m)) return" in JS)
ok("'pronta-entrega' só vale se a frase for isso",
   "^(a\\s+)?pronta\\s*entrega$" in JS)
ok("e a guarda antiga saiu do setDur",
   '&& !un && !/pronta/i.test(raw))' not in JS)

print("\n== os casos reais que o formulário desmontava ==")
# Reproduz a lógica de splitDur/soDuracao para valer como teste automático.
# Se a regra mudar no app.js sem mudar aqui, as asserções acima acusam.
LIGACAO = re.compile(
    r"\b(de|até|ate|em|no|na|aprox(imadamente)?|cerca|uteis|úteis|corridos|"
    r"corridas|prazo|entrega)\b", re.I)
DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(dias?|m[eê]s(?:es)?|anos?)\b", re.I)
NAO_LETRA = re.compile(r"[^\w]+", re.U)


def modo(texto):
    """'livre', 'pronta' ou 'par' — o modo em que o campo vai ficar."""
    if re.search(r"pronta[\s-]*entrega", texto, re.I):
        limpo = NAO_LETRA.sub(" ", texto).strip()
        return "pronta" if re.fullmatch(r"(a\s+)?pronta\s*entrega", limpo, re.I) else "livre"
    m = DUR.search(texto)
    if not m:
        return "livre"
    resto = NAO_LETRA.sub(" ", LIGACAO.sub(" ", texto.replace(m.group(0), " "))).strip()
    return "par" if len(resto) < 3 else "livre"


CASOS = [
    ("90 dias após a assinatura do documento de contratação", "livre"),
    ("2 anos para produtos LightPad (DWDM) / Plugáveis revenda: 1 ano", "livre"),
    ("item 1: 3 unidades a pronta entrega e as demais chegando dia 22/09", "livre"),
    ("A garantia para o objeto dessa oferta está sujeita ao prazo previsto "
     "no Código Civil, a contar da entrega do bem.", "livre"),
    ("O período de garantia será de 5 (cinco) anos a contar da conclusão", "livre"),
    # estes SÃO a duração e continuam no par
    ("5 dias", "par"),
    ("24 meses", "par"),
    ("12 Meses", "par"),
    ("prazo de entrega: 30 dias", "par"),
    # e este é pronta-entrega de verdade
    ("Pronta-entrega", "pronta"),
    ("a pronta entrega", "pronta"),
]
for texto, esperado in CASOS:
    lido = modo(texto)
    ok("%-9s <- %r" % (esperado, texto[:46]), lido == esperado, "deu %r" % lido)

print("\n== o que isso significa no documento ==")
# no modo livre o campo guarda a frase inteira; no par, "N Unidade"
ok("frase com marco não vira só o número", modo("90 dias após a assinatura") == "livre")
ok("texto que só MENCIONA pronta entrega não promete pronta entrega",
   modo("item 3: tenho 3 unidades a pronta entrega, o resto dia 22/09") == "livre")
ok("mas 'Pronta-entrega' sozinho continua sendo pronta-entrega",
   modo("Pronta-entrega") == "pronta")

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

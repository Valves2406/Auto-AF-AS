# -*- coding: utf-8 -*-
"""Testa o aprendizado: que ROTULO ele guarda e se consegue reler com ele."""
import sys, io, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
from core import aprendizado as ap

# Trechos no estilo das propostas reais: tabela com pontinhos, prosa corrida,
# cabecalho de tabela com varias colunas.
CASOS = [
    ("rotulo classico com dois-pontos",
     "Prezados, segue nossa proposta. Valor Global da Proposta: R$ 1.142.297,80 "
     "conforme detalhamento anexo.", "valor_total", "1.142.297,80"),

    ("rotulo com pontinhos de preenchimento",
     "Resumo de Precos\nValor Total ............. R$ 252.000,00\n"
     "Entrega em 45 dias corridos", "valor_total", "252.000,00"),

    ("prosa corrida SEM rotulo (nao deve aprender nada util)",
     "As datas a serem disponibilizadas obedecerao o cronograma do projeto e o "
     "prazo de entrega sera de 90 dias apos o aceite.", "prazo_entrega", "90 dias"),

    ("cabecalho de tabela com varias colunas",
     "Escopo Valor em R$ sem ISS ISS (%) Valor em R$ com ISS 1.500.000,00 5 1.575.000,00",
     "valor_total", "1.575.000,00"),

    ("numero da proposta",
     "Sao Paulo, 09 de junho de 2026. Nossa referencia: PRPT 6117_26A. "
     "Ao Sr. Comprador,", "numero_proposta", "PRPT 6117_26A"),

    ("valor precedido de outro valor",
     "Subtotal R$ 100.000,00 Impostos R$ 18.000,00 Valor Global R$ 118.000,00",
     "valor_total", "118.000,00"),
]

# O que cada caso DEVE fazer. "aceita" = o rotulo tem de reler o mesmo valor;
# "recusa" = confere() tem de barrar, porque releria outra coisa (e ai o app
# preferiria nao aprender a aprender torto).
ESPERADO = {
    "rotulo classico com dois-pontos": "aceita",
    "rotulo com pontinhos de preenchimento": "aceita",
    "prosa corrida SEM rotulo (nao deve aprender nada util)": "recusa",
    "cabecalho de tabela com varias colunas": "recusa",
    "numero da proposta": "aceita",
    "valor precedido de outro valor": "aceita",
}

falhas = []
print("%-42s %-30s %-8s %s" % ("CASO", "ROTULO GUARDADO", "DEVIA", "DEU"))
print("-" * 96)
for nome, texto, campo, valor in CASOS:
    rot = ap.rotulo_antes(texto, valor)
    aceito = bool(rot) and ap.confere(texto, rot, campo, valor)
    devia = ESPERADO.get(nome, "aceita")
    ok = (devia == "aceita") == aceito
    # rotulo nao pode comecar no meio de uma palavra: e o defeito que fazia o
    # app guardar "copo valor em r$" (rabo de "Escopo")
    if rot:
        plano = ap._norm_linhas(texto).replace(chr(10), " ")
        pos = ap._sem_acento(plano).find(rot[:14])
        if pos > 0 and plano[pos - 1].isalpha():
            ok = False
            rot += "  <- comeca no meio de palavra"
    if not ok:
        falhas.append(nome)
    print("%-42s %-30s %-8s %s%s" % (nome[:42], (rot or "(nada)")[:30], devia,
                                     "aceitou" if aceito else "recusou",
                                     "" if ok else "   <<< NAO ERA ISSO"))

print("%s%s" % (chr(10), "TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

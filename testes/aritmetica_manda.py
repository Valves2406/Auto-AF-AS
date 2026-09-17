# -*- coding: utf-8 -*-
r"""Quando os números da proposta se contradizem, quem decide é a conta.

Rodando o extrator nas 21 propostas que já passaram pelo app, a soma dos itens
fechava com o total impresso em 16. Duas das que não fechavam punham DINHEIRO
ERRADO na AF:

  Padtec Furnas-Brasília
      total lido ......... R$   4.378,86   <- a DIÁRIA de período improdutivo
      soma dos itens ..... R$  63.311,60   <- o total de verdade
      A proposta escreve o total dentro da tabela, sem "R$"
      ("62.045,37 2% 63.311,60"), e o último recurso só aceitava valores com
      "R$". Sobrou "cobrança de R$ 4.378,86 por dia".

  Precision PSC260514-01
      total anunciado .... R$  44.829,12
      soma dos itens ..... R$  49.849,12   <- R$ 5.020,00 a mais
      Os itens A+B somam exatamente o "Total R$ 44.829,12" impresso. C, D, E e
      F são opcionais por evento (adicional noturno, fim de semana, visita
      adicional, mobilização) e estavam entrando na conta.

E uma terceira, que NÃO é defeito e só assustava:

  DIACOM 260215-1LT
      itens .............. R$  34.151,20  (com ICMS)
      IPI (linha à parte)  R$   3.329,74
      total .............. R$  37.480,94
      Está tudo certo; o aviso é que dizia só "difere".

O QUE ESTE TESTE TAMBÉM GUARDA É UM RECUO. Eu tinha escrito "se o total não
veio de um rótulo conhecido, adote a soma dos itens". A suíte derrubou, e com
razão: "sem rótulo" não é "não anunciado", é "anunciado de um jeito que eu não
reconheço" — a lista de rótulos não reconhecia o "Total R$ 44.829,12" da
Precision, e a regra teria trocado o total do fornecedor pela soma COM os
opcionais. Trocar o número que o fornecedor escreveu é pior do que avisar.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta
from core.modelos import DadosProposta, ItemAF

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()


def item(desc, total):
    return ItemAF(descricao=desc, quantidade="1", preco_unit_com=total,
                  preco_total_com=total)


print("== tarifa não concorre a valor total (Padtec) ==")
TXT_PADTEC = ("O escopo cobre a caracterização de fibras.\n"
              "62.045,37 2% 63.311,60\n"
              "será cobrado da ELETRONET o valor de R$ 4,96 por quilômetro de\n"
              "Nessas situações, será contabilizado o período improdutivo, "
              "com cobrança de R$ 4.378,86 por dia\n")
ok("a diária não vira o total", E._valor_total(TXT_PADTEC) != "4.378,86",
   E._valor_total(TXT_PADTEC))

d = DadosProposta(valor_total="", itens=[item("Caracterização de Fibras", "63.311,60")])
E.ultimo_texto = TXT_PADTEC
E._avisar_divergencia_total(d)
ok("sem total anunciado, a soma dos itens assume", d.valor_total == "63.311,60",
   d.valor_total)
ok("e o aviso diz que foi isso",
   any("soma dos itens" in a for a in d.avisos), " | ".join(d.avisos))
ok("sem deixar o aviso velho de 'não identificado'",
   not any("não identificado" in a for a in d.avisos), " | ".join(d.avisos))

print("\n== o prefixo que fecha delimita o pedido (Precision) ==")
TXT_PREC = ("A R$ 5.603,64 07 R$ 39.225,48\n"
            "B R$ 5.603,64 01 R$ 5.603,64\n"
            "  Total R$ 44.829,12\n"
            "C R$ 820,00 1 R$ 820,00\n")
ok("uma linha que é só 'Total R$ x' conta como anúncio",
   E._valor_total_rotulado(TXT_PREC) == "44.829,12", E._valor_total_rotulado(TXT_PREC))
ok("mas 'Comprimento total da fibra' não vira total",
   E._valor_total_rotulado("Comprimento total da fibra 63.311,60\n") == "")

d = DadosProposta(valor_total="44.829,12", itens=[
    item("Rota Guarulhos - Barreiro", "39.225,48"),
    item("Rota Barreiro - Taquaril", "5.603,64"),
    item("Adicional Noturno", "820,00"),
    item("Adicional Final de semana", "1.200,00"),
    item("Visita adicional", "1.200,00"),
    item("Mobilização adicional", "2.800,00")])
E.ultimo_texto = TXT_PREC
E._avisar_divergencia_total(d)
ok("os opcionais saem da lista", len(d.itens) == 2, "%d itens" % len(d.itens))
ok("e o total do fornecedor é preservado", d.valor_total == "44.829,12", d.valor_total)
ok("o aviso explica por que saíram",
   any("opcional" in a for a in d.avisos), " | ".join(d.avisos))

print("\n== a diferença do IPI é explicada, não acusada (DIACOM) ==")
d = DadosProposta(valor_total="37.480,94", itens=[
    item("Cordão óptico", "34.151,20")])
E.ultimo_texto = ("Valor total com ICMS: R$ 34.151,20\n"
                  "Valor IPI: R$ 3.329,74\n"
                  "Valor total com todos os Impostos: R$ 37.480,94\n")
E._avisar_divergencia_total(d)
aviso = " ".join(d.avisos)
ok("o aviso diz que é o IPI", "IPI" in aviso, aviso or "(nenhum)")
ok("e não trata como erro", "⚠" not in aviso, aviso)

print("\n== o recuo: total anunciado NUNCA é trocado pela soma ==")
d = DadosProposta(valor_total="99.999,99", itens=[item("qualquer coisa", "6.256,44")])
E.ultimo_texto = "proposta sem total anunciado em lugar nenhum"
E._avisar_divergencia_total(d)
ok("o número do fornecedor fica de pé", d.valor_total == "99.999,99", d.valor_total)
ok("e a divergência vira alerta", "⚠" in " ".join(d.avisos), " ".join(d.avisos))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

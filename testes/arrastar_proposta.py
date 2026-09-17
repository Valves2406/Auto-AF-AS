# -*- coding: utf-8 -*-
r"""Arrastar a proposta para a tela.

Soltar o arquivo em qualquer ponto da janela lê a proposta, igual ao botão
"Ler proposta" — e pelo MESMO caminho, não por uma cópia dele.

AS DUAS ARMADILHAS DO RECURSO, e por que estão no código
--------------------------------------------------------
1. Sem `preventDefault` no `dragover`, o `drop` nunca chega a acontecer — e
   pior: o navegador ABRE o arquivo solto, trocando a página. Quem estivesse
   com a AF meio preenchida perde tudo. Por isso o `preventDefault` vale para
   a janela inteira, inclusive fora da área útil.

2. `dragleave` dispara ao cruzar CADA elemento filho. Escondendo a capa nele,
   ela pisca sem parar enquanto o arquivo atravessa a tela. O contador de
   entradas resolve: só some quando as saídas alcançam as entradas.

MEDIDO NO NAVEGADOR (eventos de arrasto sintéticos, com DataTransfer real):
  so PDF ............. -> lerProposta(["proposta.pdf"])
  duas partes ........ -> lerProposta(["tecnica.pdf", "comercial.pdf"])
  excel CIENA ........ -> lerProposta(["DDPTool.xlsx"])
  arquivo invalido ... -> recusado, e a mensagem NOMEIA o arquivo
  misturado .......... -> lê o válido e diz quantos ignorou

Este teste guarda o CÓDIGO que sustenta esse comportamento; a medição acima
foi feita no app rodando.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


js = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()
htm = io.open(os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read()
css = io.open(os.path.join(PROJ, "web", "app.css"), encoding="utf-8").read()

print("== a capa existe e cobre a janela ==")
ok("a capa está na tela", 'id="dropCapa"' in htm)
ok("e fora de qualquer aba (vale em todas)",
   htm.index('id="dropCapa"') < htm.index('<header class="topbar"'),
   "dentro de uma aba, só funcionaria naquela")
ok("cobre a janela inteira", re.search(r"\.drop-capa\s*\{[^}]*position:\s*fixed", css) is not None)
ok("por cima de tudo", re.search(r"\.drop-capa\s*\{[^}]*z-index:\s*[12]\d\d", css) is not None)

print("\n== o navegador não pode abrir o arquivo solto ==")
corpo = js[js.index("function ligarArrastar"):]
corpo = corpo[:corpo.index("\nfunction ")] if "\nfunction " in corpo else corpo
ok("dragover é impedido", re.search(r'"dragover"[\s\S]{0,220}preventDefault', corpo) is not None,
   "sem isto o drop não acontece E a página é trocada pelo PDF")
ok("drop é impedido", re.search(r'"drop"[\s\S]{0,220}preventDefault', corpo) is not None)

print("\n== a capa não pisca ao atravessar a tela ==")
ok("há contador de entradas", re.search(r"dentro\s*\+\+", corpo) is not None)
ok("e a saída só fecha quando zera",
   re.search(r"dentro\s*=\s*Math\.max\(0,\s*dentro\s*-\s*1\)", corpo) is not None
   and re.search(r"if\s*\(!dentro\)", corpo) is not None,
   "sem o contador, cada filho cruzado esconde a capa")

print("\n== só entra o que é proposta ==")
ok("filtra por extensão", "_EXT_PROPOSTA" in js and "pdf|xlsx|xlsm" in js)
ok("recusa o resto com mensagem", 'Só leio proposta em PDF ou Excel' in js)
ok("e diz o que ignorou numa mistura", 'Ignorei ' in js)

print("\n== é o MESMO caminho do botão, não uma cópia ==")
ok("lerProposta aceita a lista solta", "async function lerProposta(soltos)" in js)
ok("e continua lendo do seletor quando não há lista",
   'soltos && soltos.length ? [...soltos] : [...$("filePdf").files]' in js)
ok("o soltar chama lerProposta", re.search(r"lerProposta\(aceitos\)", corpo) is not None)
# Passada direto como manipulador, lerProposta receberia o Event no lugar da lista.
ok("o seletor não passa o Event como lista",
   '$("filePdf").onchange = () => lerProposta();' in js,
   "onchange = lerProposta entrega um Event onde se espera FileList")

print("\n== a capa não fica presa na tela ==")
ok("some ao sair da janela", '"blur", fechar' in corpo or "'blur', fechar" in corpo)
ok("e ao trocar de aba do navegador", "visibilitychange" in corpo)

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

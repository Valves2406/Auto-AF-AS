# -*- coding: utf-8 -*-
r"""O PDF Visual não troca o layout do documento por conta própria.

O que aconteceu na máquina: a AS e a CPS saíram com o aviso "O PDF Visual
falhou — foi gerado o PDF oficial (Excel) no lugar". O app trocou o desenho do
documento sozinho, e o aviso não dizia por quê. Para quem está padronizando
documento isso é o pior dos mundos: sai um layout hoje e outro amanhã, e não
há o que investigar.

A falha é INTERMITENTE — não se reproduz de encomenda. Quatro documentos em
sequência saem certos, o executável antigo também imprime, e nem plantando um
`SingletonLock` no perfil do Edge ela aparece. Depende do estado do Edge
naquele instante: atualizando, perfil ocupado por uma execução que morreu mal,
máquina carregada.

Contra falha intermitente não adianta caçar a causa; adianta não deixar que
ela mude o documento. Daí as duas garantias que este teste guarda:

  1. UMA FALHA NÃO BASTA PARA DESISTIR. A segunda tentativa usa um perfil
     descartável recém-criado, imune a qualquer sujeira deixada no perfil
     compartilhado. Aqui a 1ª tentativa é sabotada de propósito (um ARQUIVO
     no lugar da pasta do perfil) e o PDF tem de sair assim mesmo.

  2. SE DESISTIR, DIZ POR QUÊ. O motivo viaja na exceção e chega à tela. Sem
     isso a troca de layout é invisível — foi o que impediu o diagnóstico da
     primeira vez, ainda mais com o log em arquivo desligado.

Precisa do Edge instalado; sem ele o teste se declara pulado em vez de acusar
falha que não é do código.
"""
import io
import os
import shutil
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from core import gerador
from core.gerador import _edge_exe, gerar_af_pdf_html

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


if not _edge_exe():
    print("  (Microsoft Edge não encontrado nesta máquina — teste pulado)")
    print("\nTUDO OK")
    sys.exit(0)

HTML = "<h1>AF de teste</h1><p>O layout não pode mudar sozinho.</p>"
PERFIL = os.path.join(tempfile.gettempdir(), "geradoraf_edge_pdf")
guardado = PERFIL + ".guardado_teste"

print("== o caminho normal continua funcionando ==")
saida = os.path.join(tempfile.gettempdir(), "teste_visual_normal.pdf")
if os.path.exists(saida):
    os.remove(saida)
try:
    gerar_af_pdf_html(saida, HTML)
    ok("imprime o HTML em PDF", os.path.exists(saida) and os.path.getsize(saida) > 1000,
       "%d bytes" % (os.path.getsize(saida) if os.path.exists(saida) else 0))
except Exception as exc:
    ok("imprime o HTML em PDF", False, str(exc))

print("\n== com o perfil do Edge estragado, a 2ª tentativa salva o documento ==")
# um ARQUIVO onde deveria haver a pasta do perfil: o Edge não usa e sai sem
# imprimir — o mesmo efeito de um perfil corrompido por execução mal encerrada
if os.path.isdir(PERFIL):
    shutil.rmtree(guardado, ignore_errors=True)
    os.rename(PERFIL, guardado)
io.open(PERFIL, "w", encoding="utf-8").write("isto não é uma pasta")
saida2 = os.path.join(tempfile.gettempdir(), "teste_visual_2a.pdf")
if os.path.exists(saida2):
    os.remove(saida2)
try:
    gerar_af_pdf_html(saida2, HTML)
    ok("o PDF sai assim mesmo — o documento não troca de layout",
       os.path.exists(saida2) and os.path.getsize(saida2) > 1000)
except Exception as exc:
    ok("o PDF sai assim mesmo — o documento não troca de layout", False, str(exc))
finally:
    try:
        os.remove(PERFIL)
    except OSError:
        pass
    if os.path.isdir(guardado):
        os.rename(guardado, PERFIL)

print("\n== desistindo, o motivo chega junto ==")
fonte = io.open(os.path.join(PROJ, "backend", "core", "gerador.py"), encoding="utf-8").read()
ok("a exceção carrega o motivo, não uma frase genérica",
   'raise RuntimeError("; ".join(_motivo)' in fonte)
ok("o subprocesso amarra as TRÊS entradas (exige do .exe sem console)",
   "stdin=subprocess.DEVNULL" in fonte)
ok("há duas tentativas, a 2ª com perfil descartável",
   "for tentativa in (1, 2)" in fonte and "mkdtemp" in fonte)
motor = io.open(os.path.join(PROJ, "backend", "engine.py"), encoding="utf-8").read()
ok("e o aviso da tela mostra esse motivo",
   motor.count('"O PDF Visual falhou (%s) — foi gerado o PDF oficial "') == 2,
   str(motor.count('"O PDF Visual falhou (%s) — foi gerado o PDF oficial "')))

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

# -*- coding: utf-8 -*-
r"""Comodidades da tela: desfazer, rascunho e atalhos.

Não há Node aqui, então o comportamento foi conferido no app rodando (o
formulário volta inteiro depois do Limpar; o rascunho reaparece ao abrir; o
painel do "?" abre até com o foco dentro da prévia). O que esta suíte guarda são
as REGRAS que, se sumirem de novo, quebram tudo isso em silêncio — cada uma
custou um erro real durante a implementação.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()
CSS = io.open(os.path.join(PROJ, "web", "app.css"), encoding="utf-8").read()

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


print("== desfazer o Limpar ==")
# Dentro da PROPRIA funcao: `$("catalogo").value = "-1"` tambem aparece antes
# dela no arquivo, e comparar posicoes no texto inteiro dava falso negativo
# sobre codigo certo.
_i = JS.index("function limparAF(")
CORPO_LIMPAR = JS[_i:JS.index("\nfunction limparCPM(", _i)]
ok("a foto e tirada ANTES de apagar",
   "_antesDeLimpar = fotoAF();" in CORPO_LIMPAR
   and CORPO_LIMPAR.index("_antesDeLimpar = fotoAF();")
   < CORPO_LIMPAR.index('$("catalogo").value = "-1";'),
   "tirada depois, a foto guarda o formulario ja vazio")
ok("existe como desfazer", "function desfazerLimpar()" in JS)
ok("a foto cobre os itens", '"itens: copia(items)"' in JS or "itens: copia(items)" in JS)
ok("cobre faturamento, entrega, assinantes e observacoes",
   all(k in JS for k in ("faturamentos: copia(faturamentos)", "entregas: copia(entregas)",
                         "assinantes: copia(assinantesAF)", "obs: obsRows()")))
ok("a mensagem do Limpar avisa que da para desfazer", "Ctrl+Z desfaz" in JS,
   "atalho que ninguem descobre nao existe")
ok("restaurar sem item nenhum nao deixa a tabela vazia",
   "if (!items.length) items.push(novoItem());" in JS)

print("\n== rascunho ==")
# ESTE foi o furo: ao abrir o app o formulario esta vazio, o autosave disparava
# 1,2s depois e apagava o rascunho que acabara de ser oferecido na tela.
ok("tela vazia NAO apaga o rascunho", "if (!temConteudo(f)) return;" in JS,
   "com removeItem aqui, o rascunho morre 1,2s depois de ser oferecido")
ok("o descarte e explicito", "function descartarRascunho()" in JS)
ok("gerar o documento descarta o rascunho",
   "descartarRascunho();     // virou documento" in JS)
ok("rascunho velho e jogado fora", "DIAS_RASCUNHO" in JS)
ok("nao oferece por cima de tela ja preenchida", "if (temConteudo(fotoAF())) return;" in JS,
   "quem ja comecou a digitar nao quer o rascunho de ontem por cima")
ok("guardar e adiado (nao grava a cada tecla)", "_tmrRascunho = setTimeout" in JS)
ok("falha de storage nao derruba a tela", "catch (e) { /* cota cheia" in JS)
ok("o alvo da barra existe no HTML",
   '#viewGerar .form-col' in JS and 'id="viewGerar"' in io.open(
       os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read())

print("\n== atalhos ==")
ok("existe a lista de atalhos", "const ATALHOS" in JS)
ok("Ctrl+S nao deixa abrir a caixa do navegador", "e.preventDefault(); acao();" in JS,
   "sem preventDefault, Ctrl+S abre 'salvar pagina como' e nao gera nada")
for tecla, alvo in (("s", "btnPdf"), ("o", "btnLer"), ("e", "btnExcel")):
    ok("Ctrl+%s aciona %s" % (tecla.upper(), alvo), '%s: () => $("%s")' % (tecla, alvo) in JS)
ok("Ctrl+1..4 troca de aba", 'switchTab("cadastros"), 4: () => switchTab("excluir")' in JS)
# a tecla "?" nao pode roubar a digitacao
ok('"?" e ignorado dentro de campo de texto', 'e.key === "?" && !digitando(e)' in JS)
ok("Ctrl+Z dentro de campo continua sendo o desfazer do navegador",
   '"z" && !digitando(e)' in JS)
# ESTE foi o segundo furo: a previa ocupa metade da tela; clicar nela tirava o
# foco do documento e nenhum atalho respondia
ok("os atalhos tambem valem com o foco na PREVIA",
   'f.contentDocument.addEventListener("keydown", _atalho)' in JS,
   "sem isso, clicar na previa desliga todos os atalhos")
ok("as duas previas sao cobertas", '["preview", "cpmPreview"]' in JS)
ok("outra origem no iframe nao quebra o app", "catch (e) { /* outra origem */ }" in JS)

print("\n== aparencia ==")
ok("a barra de rascunho tem estilo", ".rascunho {" in CSS)
ok("o painel de atalhos tem estilo", ".atalhos {" in CSS)
ok("o painel funciona nos dois temas (usa variaveis)",
   "var(--card)" in CSS[CSS.index(".atalhos {"):CSS.index(".atalhos {") + 900])

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

# -*- coding: utf-8 -*-
r"""Rodapé de rubrica, e o total que não pode contradizer os itens.

A rubrica é UMA linha (~44mm), da Eletronet, no rodapé de toda folha, com ~13mm
livres acima dela para escrever. Não leva nome: o documento é da Eletronet,
dizer de quem é a rubrica seria repetir o óbvio. O fornecedor não rubrica folha
a folha; ele assina no fim. Na última folha o rodapé cai logo abaixo das
assinaturas, que é onde ele deve ficar.

Como o rodapé é feito, e por que não é `position:fixed`
-------------------------------------------------------
O documento inteiro vira o `<tbody>` de uma tabela e a rubrica vira o `<tfoot>`.
`display:table-footer-group` repete o rodapé no pé de TODA folha e — o que
importa — RESERVA o espaço dele no fluxo.

`position:fixed` também repete, mas não reserva nada: no motor do Edge ele é
pintado DENTRO da área de conteúdo, ou seja, ocupa a última faixa da folha,
justamente onde o texto e as bordas dos cartões chegam. Medido com conteúdo
denso enchendo a folha: `fixed` deixava 2pt entre o texto e o rodapé — na
prática, por cima; `tfoot` deixa 21pt. Foi isso que pôs a rubrica sobre o cartão
de "Locais de entrega" numa AF real.

Aumentar a margem da página não resolve com `fixed`: a faixa sobe junto com a
área de conteúdo e a distância até o texto não muda. E empurrar a faixa para
dentro da margem (bottom negativo, translateY, margem negativa, top calculado)
faz o Chromium tirá-la da primeira folha e jogá-la no TOPO das seguintes — as
quatro foram medidas.

Duas armadilhas de medição, registradas para não repetir
--------------------------------------------------------
1. O rótulo sai MAIÚSCULO no PDF (`text-transform`). Procurar por "Rubrica" em
   minúsculas não acha nada e dá a impressão de que a caixa sumiu.
2. Medir só a última linha de TEXTO da folha não basta: um cartão tem borda e
   enchimento que descem abaixo da última palavra, e é a borda que colide.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
import engine

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


FORM = {"fornecedor": "PADTEC S/A", "valor_total": "63.311,60", "numero": "346",
        "ano": "2026", "prefixo": "AS-E", "modificacao": "TR", "revisao": "0",
        "moeda": "Real", "objeto": "Caracterizacao de fibras",
        "itens": [{"descricao": "Servico", "quantidade": "1", "preco_unit_sem": "62.045,37"}]}

sem = engine.montar_preview(dict(FORM))
# O PADRAO e so a ultima folha. "Todas as folhas" tem de ser pedido.
com = engine.montar_preview(dict(FORM, rubricas=True, rubricas_todas=True))
ultima = engine.montar_preview(dict(FORM, rubricas=True))
compacto = com.replace(" ", "").replace("\n", "")

print("== o campo e OPCIONAL ==")
ok("sem marcar, nao ha linha nenhuma", 'class="rubricas"' not in sem)
ok("sem marcar, nao existe tabela-pagina", 'class="pagina"' not in sem,
   "quem nao pediu rubrica nao paga o preco de estrutura nenhuma")
ok("marcado, a linha entra", 'class="rubricas"' in com)

print("\n== e UMA caixa, da Eletronet, A ESQUERDA ==")
i = com.rindex('<div class="rubricas"')
linha = com[i:com.index("</div>", com.index("<i></i>", i))]
ok("uma linha, nao varias", linha.count("<i></i>") == 1, "%d linha(s)" % linha.count("<i></i>"))
ok("o fornecedor nao tem linha", "PADTEC" not in linha)
ok("o rotulo e 'Rubrica'", ">Rubrica<" in linha)
ok("nao repete espaco de assinatura", "assin" not in linha)
# A ESQUERDA: e o lado da Eletronet no documento, e a Eletronet e quem rubrica.
ok("a faixa fica a ESQUERDA", "align-items:flex-start" in compacto,
   "flex-end joga a rubrica para o lado do fornecedor")
ok("nao sobrou o alinhamento a direita", "align-items:flex-end" not in compacto)
ok("o rotulo acompanha, recuado pela esquerda", "padding-left:34px" in compacto
   and "padding-right:34px" not in compacto,
   "o recuo centra o rotulo sobre a linha; do lado errado ele sai torto")

print("\n== PADRAO: so na ULTIMA folha ==")
# Nao da para pedir a `table-footer-group` que apareca so na ultima folha: ele
# repete por definicao. Entao o modo padrao usa outro mecanismo — bloco comum
# no fim do fluxo — e a ausencia da tabela E a prova de que nao vai repetir.
ok("a linha entra", 'class="rubricas"' in ultima)
ok("NAO monta a tabela-pagina", 'class="pagina"' not in ultima,
   "com a tabela, o rodape repetiria em toda folha")
ok("nao repete o rodape em toda folha",
   "table.pagina>tfoot{display:table-footer-group}"
   not in ultima.replace(" ", "").replace("\n", ""))
ok("sai uma vez so", ultima.count('<div class="rubricas"') == 1,
   "%d vezes" % ultima.count('<div class="rubricas"'))
# Sozinha no fim do fluxo, a faixa abriria folha propria — foi o que aconteceu
# com a assinatura (medido: 93% de papel branco). Dentro do grupo `.fim`, que
# ja e `break-inside:avoid`, ela viaja colada as assinaturas.
fim = ultima[ultima.index('<div class="fim">'):]
ok("viaja junto com a assinatura, sem abrir folha sozinha",
   'class="rubricas"' in fim[:fim.index("</div>\n  <div class=\"rod\"")]
   if '</div>\n  <div class="rod"' in fim else 'class="rubricas"' in fim,
   "fora do grupo .fim ela orfana, como a assinatura orfanava")

print("\n== PEDIDO: rodape em TODAS as folhas ==")
ok("o documento vira o corpo de uma tabela-pagina", 'class="pagina"' in com)
ok("a rubrica vira o rodape dessa tabela", '<tfoot><tr><td><div class="rubricas"' in com)
ok("o rodape repete no pe de toda folha",
   "table.pagina>tfoot{display:table-footer-group}" in compacto,
   "sem isso a caixa sai uma vez so, no fim do documento")
ok("NAO usa position:fixed", "position:fixed" not in com[com.index("table.pagina{"):],
   "fixed repete mas nao reserva espaco — foi o que sobrepos o cartao")
ok("a tabela-pagina nao tem aparencia propria", "border-collapse:collapse" in com)
# o <tfoot> da tabela de ITENS nao pode virar rodape de folha junto
ok("so o rodape da tabela-pagina vira rodape de folha",
   "table.pagina>tfoot{display:table-footer-group}" in compacto
   and "}tfoot{display:table-footer-group}" not in compacto,
   "regra solta em 'tfoot' repetiria o VALOR TOTAL dos itens no pe de cada folha")
ok("nao mexe na margem da pagina", "12mm 17mm" not in com and "12mm 14mm" not in com,
   "mexer na margem muda a paginacao de quem so queria uma linha")
# calibrado pelo documento assinado que veio de exemplo, e depois alongado a
# pedido: linha de ~44mm com ~13mm livres acima para escrever
ok("comprimento da linha (~44mm no papel)", "width:165px" in com)
ok("e LINHA, nao retangulo", "border-bottom:1px solid" in com
   and "i{display:block;height:58px;border:1px" not in com,
   "caixa fechada nao foi o pedido: e uma linha para rubricar em cima")
ok("com espaco livre acima da linha", "height:52px" in com,
   "a altura e o espaco de escrever, nao a altura de uma caixa")

print("\n== a tabela do rodape nao pode estragar as quebras ==")
# Dentro de celula de tabela o Chromium IGNORA break-after/break-before. Com 24
# itens, o cartao "Locais de entrega" saia com o titulo numa folha e o conteudo
# na outra — um cartao vazio no pe da pagina. `break-inside` ele respeita.
imp = com[com.index("@media print"):]
ok("cada cartao fica inteiro numa folha",
   ".bloco:not(.tabela){break-inside:avoid}" in imp.replace(" ", ""))
ok("a tabela de ITENS continua fluindo", ".bloco.tabela{break-inside:avoid}" not in imp,
   "marcada como indivisivel, ela deixava 52% da folha em branco")

print("\n== o marcador sobrevive ao rascunho e ao desfazer ==")
js = io.open(os.path.join(PROJ, "frontend", "app.js"), encoding="utf-8").read()
htm = io.open(os.path.join(PROJ, "frontend", "index.html"), encoding="utf-8").read()
ok("o campo existe na tela", 'id="ckRubricas"' in htm)
ok("vai no formulario enviado ao motor", 'rubricas: !!($("ckRubricas")' in js)
ok("marcadores entram na foto (checked, nao value)",
   "_MARCAS_AF" in js and "marcas[id] = e.checked" in js,
   "guardando .value, recuperar o rascunho devolvia a AF e perdia a rubrica")
ok("e sao restaurados", "e.checked = !!v" in js)
# PROPRIEDADE, nao a linha literal: a versao anterior exigia
# `$("ckRubricas").onchange = schedulePreview;` exatamente assim, e quebrou
# quando o manipulador cresceu para abrir o balao — sem nada ter regredido.
_m = re.search(r'\$\("ckRubricas"\)\.onchange\s*=\s*([^\n]+)', js)
ok("mexer no marcador redesenha a previa",
   bool(_m) and "schedulePreview" in _m.group(1),
   (_m.group(1)[:70] if _m else "nao ha manipulador para o marcador"))

print("\n== a ESCOLHA de onde a rubrica sai ==")
ok("o balao existe na tela", 'id="rubPop"' in htm)
ok("oferece as duas folhas", 'data-todas="0"' in htm and 'data-todas="1"' in htm)
ok("o modo mora num interruptor, nao numa variavel", 'id="ckRubTodas"' in htm,
   "numa variavel ele nao entraria na foto do rascunho")
ok("e por isso entra na foto", '"ckRubTodas"' in js and "_MARCAS_AF" in js)
ok("vai no formulario enviado ao motor", "rubricas_todas:" in js)
ok("o motor repassa a escolha", '"rubricas_todas"' in open(
    os.path.join(PROJ, "backend", "engine.py"), encoding="utf-8").read())
# O balao fecha; a pastilha e o unico lugar onde o modo continua visivel.
ok("a pastilha mostra o modo em vigor", 'id="btnRubModo"' in htm
   and "última folha" in js and "todas as folhas" in js)
ok("e o rascunho restaurado repinta a pastilha",
   "pintarRubModo();" in js.split("e.checked = !!v")[1][:400],
   "marcar no braco nao dispara onchange: a pastilha voltaria errada")

print("\n== o total nao pode contradizer os itens ==")
# Caso real: a proposta da PADTEC foi lida com R$ 4.378,86 enquanto a unica
# linha da AF somava R$ 63.311,60. O documento saiu com os dois numeros, um
# embaixo do outro. O aviso ja existia, mas na IMPORTACAO — na hora de gerar ele
# ja tinha sido substituido por outra mensagem na barra de status.
ok("existe a conferencia", "function totalBateComOsItens()" in js)
ok("ela roda ANTES de gerar", "if (!totalBateComOsItens()) return;" in js)
ok("total MAIOR que a soma passa direto", "if (total >= soma - 0.01) return true;" in js,
   "frete e seguro ficam fora da tabela — caso previsto, nao pode incomodar")
ok("total MENOR pergunta antes", "Gerar assim mesmo?" in js)
ok("e a pergunta mostra os dois numeros",
   "Valor total informado" in js and "Soma dos itens" in js)

print("\n== o CSS nao vaza escape de f-string ==")
ok("nenhum '%%' no documento", "%%" not in com)

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

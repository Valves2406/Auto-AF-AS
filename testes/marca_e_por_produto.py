# -*- coding: utf-8 -*-
r"""A marca do app, o modo "por produto" e a associação que sumia do texto.

1. MARCA
   A tela de carregamento e o ícone do executável usam a marca do Auto AF/AS.
   O `.ico` precisa de VÁRIAS resoluções dentro do mesmo arquivo (o Windows
   escolhe conforme o lugar: 16px na barra de tarefas, 256px na visualização
   grande) — uma imagem só, redimensionada na hora, sai borrada nas pequenas.
   E o ícone leva SÓ o símbolo: aos 16px o texto "Auto AF/AS" vira sujeira.

2. POR PRODUTO
   O modo já existia, mas era manual. Reparar que um item entre dez tem 70 dias
   em vez de 15 é justamente o que não acontece lendo a grade — então quando a
   proposta traz valores diferentes, o modo liga sozinho. Com ele ligado, o
   campo do documento deixa de ser a faixa ("12 a 24 meses") e passa a ser a
   lista por item, que é o que serve num documento de compra.

3. ASSOCIAÇÃO
   A frase "Com associação AF-… e CPM-…" sumia quando o número da AF era uma
   SIGLA de projeto ("AS-E-BMW/2026-TR"). A regra que separava identificador
   preenchido de identificador vazio exigia DÍGITOS (`-\d+/`), e uma sigla era
   tratada como campo em branco. O que importa é ter alguma coisa entre o traço
   e a barra.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import engine

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


ASSETS = os.path.join(PROJ, "assets")
WEB = os.path.join(PROJ, "web")

print("== a marca existe e está montada certo ==")
marca = os.path.join(ASSETS, "autoafas_logo.png")
simb = os.path.join(ASSETS, "autoafas_simbolo.png")
ico = os.path.join(ASSETS, "app.ico")
ok("a marca cheia está nos assets", os.path.exists(marca))
ok("o símbolo sozinho também", os.path.exists(simb))
ok("e o ícone do executável", os.path.exists(ico))
try:
    from PIL import Image
    with Image.open(ico) as im:
        medidas = sorted({s[0] for s in im.info.get("sizes", [])} or {im.size[0]})
    ok("o ícone traz várias resoluções", len(medidas) >= 5, str(medidas))
    ok("inclusive 16px (barra de tarefas) e 256px (visualização grande)",
       16 in medidas and 256 in medidas, str(medidas))
    with Image.open(simb) as im:
        ok("o símbolo é quadrado", im.width == im.height, "%dx%d" % im.size)
        ok("e tem fundo transparente", im.mode == "RGBA" and im.getextrema()[3][0] == 0)
except ImportError:                       # sem Pillow, o resto do teste vale
    print("  (Pillow ausente: não dá p/ conferir as resoluções do .ico)")

print("\n== a tela de carregamento usa a marca ==")
html = io.open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
css = io.open(os.path.join(WEB, "app.css"), encoding="utf-8").read()
appy = io.open(os.path.join(PROJ, "app.py"), encoding="utf-8").read()
ok("a splash aponta para a marca", 'src="marca.png"' in html)
# A janela do app é uma janela de navegador: o ícone que o Windows põe na barra
# de tarefas dela vem do FAVICON, não do executável. Apontando a aba para o
# mesmo app.ico, os dois lugares mostram o mesmo desenho — e o .ico traz de 16 a
# 256px dentro, então o Windows escolhe o tamanho em vez de esticar um PNG.
ok("a aba usa o mesmo .ico do executável", 'href="app.ico"' in html)
ok("e o app serve esse arquivo", '"/app.ico"' in appy)
ok("o servidor entrega as duas", '"/marca.png"' in appy and '"/simbolo.png"' in appy)
ok("a marca tem largura relativa, não altura fixa",
   ".splash-marca" in css and "width: min(" in css.split(".splash-marca")[1][:120])
# o título e o "Axia Energia" saíram: a marca já os traz desenhados
ok("não repete o nome em texto ao lado do desenho",
   'class="splash-tit"' not in html and 'class="splash-axia"' not in html)

print("\n== o modo 'por produto' liga sozinho quando os itens divergem ==")
js = io.open(os.path.join(WEB, "app.js"), encoding="utf-8").read()
ok("existe a função que decide", "function ligarPorProdutoSeDiferir()" in js)
ok("o liga/desliga aceita o estado (p/ ligar sem simular clique)",
   "function setPerItemGarantia(v)" in js and "function setPerItemPrazo(v)" in js)
ok("o botão continua alternando", "function togglePerItemGarantia() { setPerItemGarantia(" in js)
ok("é chamada ao ler uma proposta",
   len(re.findall(r"ligarPorProdutoSeDiferir\(\);", js)) >= 2)
ok("só liga com valores DIFERENTES (>1 distinto)",
   'distintos("garantia") > 1' in js and 'distintos("prazo") > 1' in js)
ok("e avisa a pessoa em vez de mudar calado", "liguei o modo" in js)

print("\n== a associação volta ao texto quando o número é uma sigla ==")
BASE = {"fornecedor": "DATACOM Telemática", "fornecedor_fantasia": "DATACOM",
        "valor_total": "902.275,28", "ano": "2026", "modificacao": "TR",
        "revisao": "0", "moeda": "Real", "objeto": "Fornecimento de switches",
        "cenario": "sem", "itens": []}


def finalidade(numero, prefixo="AF-E"):
    return engine.cpm_de_form(dict(BASE, numero=numero, prefixo=prefixo)).get("finalidade", "")


ok("sigla de projeto: AF-E-BMW/2026-TR entra no texto",
   "Com associação AF-E-BMW/2026-TR e CPM-E-BMW/2026-TR." in finalidade("BMW"),
   finalidade("BMW")[-90:])
ok("e numa AS o par é AS + CPS",
   "Com associação AS-E-BMW/2026-TR e CPS-E-BMW/2026-TR." in finalidade("BMW", "AS-E"))
ok("número em dígitos segue funcionando",
   "Com associação AF-E-351/2026-TR e CPM-E-351/2026-TR." in finalidade("351"))
# a regra existe para NÃO imprimir "AF-E-/2026-TR", que é campo em branco
ok("número em branco não vira associação inventada",
   "Com associação" not in finalidade(""), finalidade("")[-60:])

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

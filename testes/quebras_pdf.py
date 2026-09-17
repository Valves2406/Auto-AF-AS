# -*- coding: utf-8 -*-
r"""Quebras de página e campos vazios no PDF.

Caso real (AF de 16 itens, 01/09/2026): a primeira folha saía com 52% em branco
e o documento ocupava 3 páginas em vez de 2.

A causa era `break-inside: avoid` na TABELA. Essa regra não é um pedido, é uma
ordem: se o bloco não couber no que sobrou da página, ele salta INTEIRO para a
próxima e deixa o pé em branco.

Este teste não gera PDF (depende do Edge e é lento) — ele guarda a REGRA: o que
pode ser indivisível e o que tem de fluir.
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


def fonte_render():
    """O código-fonte do renderizador, para checar o que só existe na marcação."""
    return io.open(os.path.join(PROJ, "core", "html_render.py"), encoding="utf-8").read()


def estilo(doc):
    """So a folha de estilo do documento.

    Passar o HTML INTEIRO para tem_regra() custava 2m40s na suite: o logo vai
    embutido em base64 e o regex [^{}]+ atravessa esse paredao de caracteres
    tentando casar seletor. Cortando no <style>, a mesma checagem leva menos de
    um segundo — e ainda evita casar texto que por acaso pareca CSS.
    """
    i = doc.index("<style")
    return doc[doc.index(">", i) + 1: doc.index("</style>", i)]


def tem_regra(css, seletor, prop):
    """O seletor recebe essa propriedade? Vale dentro de LISTA de seletores.

    Duas armadilhas que me pegaram escrevendo este teste:
      1. exigir "seletor {" grudado dá falso negativo em
         ".assin div,.aviso{break-inside:avoid}" — a regra existe, o teste é que
         não sabia ler lista;
      2. capturar o seletor com [^{}]+ arrasta o COMENTÁRIO anterior junto, e aí
         ".sec" nunca casa. Os comentários saem antes.
    """
    limpo = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    for sel_txt, corpo in re.findall(r"([^{}]+)\{([^{}]*)\}", limpo):
        seletores = [x.strip() for x in sel_txt.split(",") if x.strip()]
        if seletores and seletor in seletores and prop.replace(" ", "") in corpo.replace(" ", ""):
            return True
    return False


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


RACK = 'RACK 44U 19" L600XP800XA2100MM COM PORTA TIPO COLMEIA - PRETO'
itens = [{"descricao": RACK, "quantidade": "1", "preco_unit_sem": "5.462,50",
          "preco_total_com": "5.462,50"} for _ in range(16)]
FORM = {"fornecedor": "HOYER Equipamentos Ltda", "valor_total": "87.400,00",
        "numero": "BMW", "ano": "2026", "prefixo": "AF-E", "modificacao": "TR",
        "revisao": "0", "moeda": "Real", "objeto": "Fornecimento de racks",
        "itens": itens, "cenario": "sem"}

print("== AF: o que pode saltar de página ==")
html = engine.montar_preview(dict(FORM))
css_af = estilo(html)
impressao = css_af[css_af.index("@media print"):]

ok("a TABELA flui (não salta inteira)",
   not tem_regra(impressao, "table", "break-inside:avoid"),
   "ainda há 'break-inside:avoid' na tabela — era isso que deixava 52% da folha em branco")
ok("a LINHA da tabela continua indivisível", tem_regra(impressao, "tr", "break-inside:avoid"))
ok("o cabeçalho da tabela repete nas páginas seguintes",
   "display:table-header-group" in impressao)
ok("o título de seção não fica órfão no pé", tem_regra(impressao, ".sec", "break-after:avoid"))
ok("uma assinatura não parte ao meio", tem_regra(impressao, ".assin div", "break-inside:avoid"))
ok("o bloco grande NÃO é mais indivisível",
   not any(tem_regra(impressao, sel, "break-inside:avoid") for sel in (".bloco", "table", ".metagrid")),
   "bloco com 'avoid' volta a empurrar meia folha em branco")

print("\n== CPM: mesma regra ==")
cpm = montar_cpm_html(engine.cpm_de_form(dict(FORM)))
css_cpm = estilo(cpm)
imp_cpm = css_cpm[css_cpm.index("@media print"):]
ok("bloco do CPM flui", not tem_regra(imp_cpm, ".bloco", "break-inside:avoid"))
ok("caixa de campo do CPM segue inteira", tem_regra(imp_cpm, ".grid2>div", "break-inside:avoid"))

print("\n== saldo sem CAPEX ==")
base = {"fornecedor": "HOYER", "valor_total": "5.522.766,02", "numero": "BMW", "ano": "2026",
        "prefixo": "AF-E", "modificacao": "TR", "revisao": "0",
        "moeda": "Dólar Americano", "cotacao": "5,15", "cenario": "sem"}
sem = montar_cpm_html(engine.cpm_de_form(dict(base)))
# o saldo aparece mesmo sem CAPEX — pedido do usuario. A verba ao lado diz
# "nao informado", entao o numero nao fica sem explicacao.
ok("sem CAPEX, o saldo ainda aparece", "cel neg" in sem)
ok("e o documento diz que não foi informado", "não informado" in sem)

com_folga = montar_cpm_html(engine.cpm_de_form(dict(base, capex="30.000.000,00")))
ok("com CAPEX suficiente, saldo positivo e sem vermelho", "cel neg" not in com_folga)
m = re.search(r'Saldo</div><div class="cv">([^<]*)', com_folga)
ok("saldo calculado", m and "1.557.755,00" in m.group(1), m.group(1) if m else "?")

curto = montar_cpm_html(engine.cpm_de_form(dict(base, capex="1.000.000,00")))
ok("CAPEX insuficiente continua marcando vermelho", "cel neg" in curto)

print("\n== campo sem valor ==")
ok("campo vazio do CPM vira travessao", "fv vazio" in sem)
# A AF tinha a mesma falha e ficou de fora do primeiro conserto: "Inscricao
# Estadual" e "Data de emissao" saiam com o rotulo e um branco do lado.
af_vazio = engine.montar_preview(dict(FORM))
ok("campo vazio da AF tambem vira travessao", "fv vazio" in af_vazio)

print("\n== linhas alinhadas ==")
# O que gerou a reclamacao: dentro do MESMO bloco, uma linha ficava lado a lado
# e a seguinte empilhada, porque a decisao era tomada por linha, pelo tamanho do
# rotulo (> 15 caracteres empilhava). Agora o rotulo tem largura fixa, entao os
# valores alinham na vertical e os fios divisorios ficam na mesma altura.
for nome, doc in (("CPM", estilo(cpm)), ("AF", estilo(html))):
    ok(nome + ": rotulo tem COLUNA FIXA", tem_regra(doc, ".fk", "flex:0 0 44%"),
       "sem largura fixa, cada linha alinha o valor num lugar diferente")
    ok(nome + ": acabou a decisao por linha", "rotlongo" not in doc,
       "a regra do rotulo > 15 caracteres deixava o bloco irregular")

print("\n== grades que nao deixam linha pela metade ==")
ok("Orcamento e grade de 3 colunas",
   tem_regra(estilo(cpm), ".orc", "grid-template-columns:repeat(3"),
   "em flex, as 2 celulas da ultima linha esticavam e nada alinhava na vertical")
ok("Condicoes comerciais em coluna unica", tem_regra(estilo(cpm), ".cond-grid", "display:block"),
   "em 2 colunas, um valor curto terminava no meio da folha ao lado de um vazio")
ok("Garantia/prazo/pagamento em coluna unica",
   tem_regra(estilo(html), ".foot.sozinho > div", "display:block"))

# A moldura do Orcamento tem de fechar como retangulo: sem isso sobra um vao
# cinza no lugar da celula que falta. Antes o vao era tapado por uma celula
# VAZIA — que fechava a moldura mas deixava um retangulo em branco no meio do
# documento. Agora quem fecha a fila e a ultima celula, esticada pela sobra.
n_cel = len(re.findall(r'<div class="cel[ "]', cpm))
tem_span = ' sp2"' in cpm or ' sp3"' in cpm
ok("a fila do Orcamento fecha", n_cel % 3 == 0 or tem_span, "%d celulas" % n_cel)
ok("e fecha sem retangulo em branco", '<div class="cel"></div>' not in cpm and
   'class="cel vaga"' not in cpm)

print("\n== faturamento nao parte ao meio ==")
ok("bloco de faturamento e indivisivel", tem_regra(impressao, ".bloco.fat", "break-inside:avoid"),
   "partido, a 2a metade cai na folha seguinte sem titulo e parece outro bloco")
ok("e o bloco recebe mesmo a classe", 'class="bloco locais fat"' in fonte_render(),
   "a regra existe mas ninguem a usa")

print("\n== assinatura nao gera folha so para ela ==")
ok("no papel a assinatura e mais justa que na tela",
   tem_regra(impressao, ".assin div", "margin-top:34px"),
   "com 62px o bloco nao cabia no pe da folha e nascia uma folha 90% em branco")

print("\n== caixas do topo: rotulo EM CIMA do valor ==")
# Medido na largura real do papel (A4 util, 186mm): cada caixa do topo tem
# 201px. Com o rotulo numa coluna fixa de 44%, sobravam 87px para o valor — e o
# CNPJ precisa de 104, o "Originado da Licitacao" de 112. O valor era cortado na
# borda da caixa, e o endereco saia com duas palavras por linha, em cinco linhas.
# Empilhado, o valor usa 207px: nada transborda e o endereco cai para 2 linhas.
css_af = estilo(html)
ok("nas caixas do topo a linha empilha", tem_regra(css_af, ".metagrid .f", "display:block"),
   "lado a lado nessa largura corta o valor na borda da caixa")
ok("o rotulo ocupa a linha inteira", tem_regra(css_af, ".metagrid .fk", "display:block"))
ok("o valor tambem, alinhado a esquerda", tem_regra(css_af, ".metagrid .fv", "text-align:left"))
ok("e pode quebrar em vez de transbordar",
   tem_regra(css_af, ".metagrid .f.nq .fv", "white-space:normal"),
   "com nowrap, um id como CPS-E-BMW/2026-TR sai pela borda")
# a regra de TRES classes vencia a das caixas do topo (duas) e mantinha o
# endereco espremido; ela saiu junto com a classe que a acionava
ok("o caso especial do endereco nao existe mais", ".f.longa.end" not in html,
   "'.f.longa.end' tem 3 classes e vencia '.metagrid .f', que tem 2")
ok("e ninguem mais recebe a classe 'end'", '" end"' not in fonte_render())

print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

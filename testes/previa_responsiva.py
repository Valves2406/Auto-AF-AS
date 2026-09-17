# -*- coding: utf-8 -*-
r"""A prévia na tela: acompanha a largura, e diz AF ou AS conforme o documento.

Três coisas que quebraram juntas e que este arquivo protege.

1. `<meta name="viewport">`
   Sem essa linha o navegador de celular NÃO usa a largura real do aparelho:
   ele finge uma janela de 980px, desenha a página nela e depois encolhe tudo.
   O efeito é que nenhuma regra `@media` dispara — a prévia fica presa no
   desenho de tela larga, com letra de lupa. Medido: com a janela em 380px o
   `clientWidth` continuava dando 980. É uma linha no `<head>`, e sem ela todo
   o resto deste arquivo é decoração.

2. As grades encolhem em degraus
   Orçamento: 3 colunas → 2 (até 760px) → 1 (até 430px).
   As grades de dois campos lado a lado (`.grid2`, `.foot`) e as faixas do topo
   da AF empilham antes de espremer rótulo e valor um contra o outro.
   O cabeçalho (logo · título · número) quebra em duas filas: numa fila só, o
   título saía com UMA PALAVRA POR LINHA.

3. A última linha do Orçamento não tem buraco
   São 5 campos numa grade de 3 colunas: sobra o terço final. Antes entrava ali
   uma célula vazia — um retângulo em branco no meio do documento. Agora a
   última célula ESTICA pelo que sobrou (`sp2`/`sp3`), e o span é limitado
   junto com a grade: um `span 3` numa grade de 2 colunas inventaria uma
   terceira coluna e entortaria a moldura.

E os RÓTULOS DE DENTRO do documento acompanham o tipo: numa AS o que existe é
uma "AS associada" e a "Data da CPS" — não "AF associada"/"Data da CPM". Fora
do documento (abas, botões) "AF/AS" e "CPM/CPS" seguem valendo: ali o par é o
nome da função, não o nome de um documento específico.
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
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


FORM = {"fornecedor": "DIACOM COMERCIO EM TELECOMUNICACOES LTDA",
        "cnpj": "07.238.098/0001-69", "valor_total": "37.480,94",
        "numero": "351", "ano": "2026", "prefixo": "AF-E", "modificacao": "GE",
        "revisao": "0", "moeda": "Real", "objeto": "Fornecimento de cordão óptico.",
        "projeto": "Reposição de estoque", "fornecedor_fantasia": "DIACOM",
        "itens": [{"descricao": "Cordão óptico monofibra", "quantidade": "6",
                   "preco_unit_com": "213,92", "preco_total_com": "1.283,52"}]}

af = engine.montar_preview(dict(FORM))
ass = engine.montar_preview(dict(FORM, prefixo="AS-E"))
cpm = montar_cpm_html(engine.cpm_de_form(dict(FORM)))
cps = montar_cpm_html(engine.cpm_de_form(dict(FORM, prefixo="AS-E")))

print("\n-- a página usa a largura real do aparelho --")
for nome, h in (("AF", af), ("CPM", cpm)):
    ok(nome + ": declara o viewport",
       'name="viewport"' in h and "width=device-width" in h)

print("\n-- as grades encolhem em degraus --")
ok("Orçamento: 3 colunas na tela larga",
   "grid-template-columns:repeat(3,minmax(0,1fr))" in cpm)
ok("Orçamento: 2 colunas até 760px",
   "@media screen and (max-width:760px){.orc{grid-template-columns:repeat(2,minmax(0,1fr))}}" in cpm)
ok("Orçamento: 1 coluna até 430px",
   "@media screen and (max-width:430px){.orc{grid-template-columns:1fr}}" in cpm)
for nome, h in (("AF", af), ("CPM", cpm)):
    ok(nome + ": os campos lado a lado empilham",
       bool(re.search(r"@media screen and \(max-width:640px\)\{\.grid2", h)))
    ok(nome + ": o cabeçalho quebra em duas filas",
       "@media screen and (max-width:560px)" in h and ".top{flex-wrap:wrap" in h)
ok("AF: as faixas do topo empilham",
   "@media screen and (max-width:470px){.metagrid{grid-template-columns:1fr}}" in af)

print("\n-- o fio entre os campos do Orçamento aparece no papel --")
# O fio é BORDA das células, não mais o fundo do container aparecendo por um
# vão de 1px. O vão era coisa PINTADA: com as células em posição fracionária
# (medido: 344,656 -> 345,656), o encaixe nos pixels do dispositivo fechava o
# vão e o fio sumia — em umas colunas sim, noutras não. Borda entra no layout
# e sobrevive ao encaixe. A propriedade continua a mesma: o fio existe e é
# visível; em #eaeff7 (quase branco) ele sumia no papel.
m = re.search(r"\.orc \.cel\{[^}]*border-right:1px solid (#[0-9a-f]{6})", cpm)
ok("o fio entre as células é borda, e é visível",
   bool(m) and m.group(1) == "#c9d2e5", "achei %s" % (m.group(1) if m else "nada"))
ok("e não voltou a ser vão pintado",
   not re.search(r"\.orc\{[^}]*gap:1px", cpm))

print("\n-- a última linha do Orçamento não tem buraco --")
ok("nenhuma célula de preenchimento vazia", 'class="cel vaga"' not in cpm)
ok("a última célula estica pela sobra", ' sp2"' in cpm or ' sp3"' in cpm)
ok("o span é limitado junto com a grade",
   "@media screen and (max-width:760px){.orc .cel.sp3{grid-column:span 2}}" in cpm and
   "@media screen and (max-width:430px){.orc .cel.sp2,.orc .cel.sp3{grid-column:span 1}}" in cpm)
# com moeda estrangeira entra mais um campo (Valor em R$): 6 células, linha cheia
cpm_usd = montar_cpm_html(engine.cpm_de_form(dict(FORM, moeda="Dólar", cotacao="5,40")))
ok("linha cheia não ganha span", ' sp2"' not in cpm_usd and ' sp3"' not in cpm_usd)

print("\n-- a prévia diz QUAL modelo vai ser gerado --")
# A prévia mostra SEMPRE o modelo Visual — o HTML sai idêntico com "Oficial" ou
# com "Visual" escolhido na cortina. Só que a cortina começa em "Oficial", e o
# PDF gerado é o do Excel, paisagem, com outra cara. Quem não reparasse na
# cortina preenchia olhando um documento e recebia outro, sem aviso nenhum.
_html = engine.montar_preview(dict(FORM, pdf_estilo="html"))
_excel = engine.montar_preview(dict(FORM, pdf_estilo="excel"))
ok("a prévia é a mesma nos dois estilos (é sempre o Visual)", _html == _excel)

_idx = io.open(os.path.join(PROJ, "web", "index.html"), encoding="utf-8").read()
_js = io.open(os.path.join(PROJ, "web", "app.js"), encoding="utf-8").read()
_css = io.open(os.path.join(PROJ, "web", "app.css"), encoding="utf-8").read()
ok("existe a etiqueta na barra da AF/AS", 'id="tagModeloAF"' in _idx)
ok("e na barra da CPM/CPS", 'id="tagModeloCPM"' in _idx)
ok("a função que a preenche existe", "function marcarModelo()" in _js)
ok("ela avisa quando o modelo difere da prévia",
   "diferente desta prévia" in _js and 'classList.toggle("difere"' in _js)
ok("e roda na abertura, não só ao trocar a cortina", "marcarModelo();" in _js)
ok("o aviso tem cor própria, no claro e no escuro",
   ".modelo-tag.difere" in _css and "body.dark .modelo-tag.difere" in _css)
# a cortina NÃO redesenha mais a prévia: ela não muda com o estilo
ok("a cortina atualiza a etiqueta, não a prévia",
   'addEventListener("change", marcarModelo)' in _js and
   '$("pdfEstilo").addEventListener("change", schedulePreview)' not in _js)

# O PADRÃO é a primeira <option>: sem `selected`, é ela que o navegador marca.
# Escolha do usuário: o Visual vem selecionado, para que o documento gerado seja
# o mesmo que está na prévia. O Oficial segue a um clique na mesma cortina.
def _primeira_opcao(idsel):
    m = re.search(r'<select id="%s".*?<option value="([^"]+)"' % idsel, _idx, re.S)
    return m.group(1) if m else "(não achei)"


ok("AF/AS abre no Visual", _primeira_opcao("pdfEstilo") == "html",
   _primeira_opcao("pdfEstilo"))
ok("CPM/CPS abre no Visual", _primeira_opcao("cpmEstilo") == "html",
   _primeira_opcao("cpmEstilo"))
ok("e o Oficial continua disponível nas duas",
   _idx.count('<option value="excel">Oficial</option>') == 2)

print("\n-- quebrar dentro da palavra vale SÓ para a descrição --")
# O `th` já esteve nesta regra e foi um tiro no pé: com o cabeçalho podendo
# quebrar dentro da palavra, a largura MÍNIMA da coluna de preço virou UMA
# LETRA — e como essas colunas pedem `width:1%` (encolher até o conteúdo), o
# navegador deu a elas uma letra. "Unitário" saiu escrito na vertical.
ok("só td.desc quebra dentro da palavra", "td.desc{overflow-wrap:anywhere}" in af)
ok("o cabeçalho da tabela NÃO quebra dentro da palavra",
   "td.desc,th{overflow-wrap:anywhere}" not in af and
   "th,td.desc{overflow-wrap:anywhere}" not in af)

print("\n-- dentro do documento, o rótulo segue o tipo --")
for h, doc, coleta in ((cpm, "AF", "CPM"), (cps, "AS", "CPS")):
    ok("%s: diz '%s associada'" % (coleta, doc), ">%s associada<" % doc in h)
    ok("%s: diz 'Data da %s'" % (coleta, coleta), ">Data da %s<" % coleta in h)
    ok("%s: não vaza o rótulo do outro tipo" % coleta,
       ">%s associada<" % ("AS" if doc == "AF" else "AF") not in h)
ok("AF: o rótulo da licitação é neutro e o VALOR é que muda",
   "Originado da Licitação" in af and "CPM-E-351/2026-GE" in af)
ok("AS: o mesmo campo traz a CPS", "CPS-E-351/2026-GE" in ass)

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

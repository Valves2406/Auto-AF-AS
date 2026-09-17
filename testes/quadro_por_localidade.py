# -*- coding: utf-8 -*-
r"""Proposta em QUADRO POR LOCALIDADE: entregas, quantidade, frete e observações.

O caso real: ARTEMIS, proposta 205.2026. Uma tabela de 6 colunas, uma linha por
destino, e o frete cobrado por destino dentro do total de cada linha.

  Localidade / Endereço de Entrega | Qtd. / Descrição | Valor Produto | Frete |
  Total Localidade | Prazo Est. Entrega

Lida pela heurística genérica, cada linha virava um item cuja DESCRIÇÃO era o
endereço de entrega e cujo "unitário com impostos" era o FRETE. Com o cabeçalho
na mão, nada disso precisa ser adivinhado.

Duas armadilhas do cabeçalho, achadas aqui
------------------------------------------
1. A varredura que empilha as linhas de cabeçalho parava na primeira linha com
   "texto + preço" — e a folha traz "TOTAL DOS PRODUTOS (8 ... R$ 38.262,40"
   ANTES da tabela. Parando ali, o cabeçalho verdadeiro nunca era lido. Linha de
   TOTAL não é linha de dados: é o fim deles.
2. O que foi empilhado antes disso virava "cabeçalho": a coluna 0 juntou o
   parágrafo de apresentação e o título "ESPECIFICAÇÃO TÉCNICA ... POR
   LOCALIDADE", e a palavra "localidade" ali fazia a coluna 0 passar por coluna
   de localidade. Cabeçalho SE ESPALHA por colunas; parágrafo fica numa célula.
3. E "Localidade / Endereço de ENTREGA" contém "entrega": depois de casar como
   coluna de localidade, ela caía também na regra de PRAZO DE ENTREGA.

O frete
-------
Vem por destino (R$ 2.500,00 em Anápolis, R$ 1.200,00 em Miguelópolis...) e já
está somado no total de cada linha. Virar item linha a linha contaria o frete
duas vezes. Ele vira UM item — nome, quantidade 1, valor total — e a conta
fecha: 8 x 4.782,80 = 38.262,40, mais 17.718,00, dá os 55.980,40 da folha.
"""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
from core.extrator import ExtratorProposta
from core.modelos import brl_para_float

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


E = ExtratorProposta()

VAZIA = ["", "", "", "", "", ""]


def linha(local, frete, prazo):
    return [local, "01 Conjunto (1 Rack + 1 PDU)", "R$ 4.782,80", frete,
            "R$ %s" % frete.replace("R$ ", ""), prazo]


# a tabela como o pdfplumber devolve: blocos de texto numa célula só, depois o
# cabeçalho de verdade espalhado pelas 6 colunas
TABELA = [
    ["ARTEMIS RACKS & SOLUTIONS SOLUÇÕES DE INFRAESTRUTURA", "", "", "", "", ""],
    VAZIA,
    ["A ARTEMIS RACKS & SOLUTIONS LTDA. submete à apreciação da ELETRONET S.A.",
     "", "", "", "", ""],
    ["ESPECIFICAÇÃO TÉCNICA DO CONJUNTO POR LOCALIDADE", "", "", "", "", ""],
    ["Fornecimento de 01 (um) Conjunto por Localidade composto por:", "", "", "", "", ""],
    # a armadilha: totais impressos ANTES da tabela
    ["TOTAL DOS PRODUTOS (8 CONJUNTOS) R$ 38.262,40 TOTAL DOS FRETES R$ 17.718,00",
     "", "", "", "", ""],
    ["1. QUADRO COMERCIAL E LOGÍSTICO POR LOCALIDADE", "", "", "", "", ""],
    VAZIA,
    ["Localidade / Endereço de Entrega", "Qtd. / Descrição", "Valor Produto",
     "Frete", "Total Localidade", "Prazo Est. Entrega (Fab. 10d + Trânsito)"],
    linha("Anápolis / GO Rod. GO 330 Km 07 - Anápolis/GO",
          "R$ 2.500,00", "14 a 16 dias úteis (4 a 6d trânsito)"),
    linha("Bandeirantes / GO BR-153, km 510 - Ap. de Goiânia/GO",
          "R$ 2.550,00", "14 a 16 dias úteis (4 a 6d trânsito)"),
    linha("Brasília Geral / DF SAPS, Área Especial 1, Lote 1 - Brasília/DF",
          "R$ 2.500,00", "13 a 15 dias úteis (3 a 5d trânsito)"),
    linha("Miguelópolis / SP Torre 123 LT Masc. Morais - Miguelópolis/SP",
          "R$ 1.200,00", "10 a 12 dias úteis (até 2d trânsito)"),
    linha("Porto Colômbia / MG Estrada Furnas - Planura, s/n - Planura/MG",
          "R$ 1.200,00", "14 a 16 dias úteis (4 a 6d trânsito)"),
    ["TOTAL GERAL (8 Localidades)", "8 Conjuntos", "R$ 38.262,40", "R$ 17.718,00",
     "R$ 55.980,40", "10 a 16 dias úteis"],
]

print("== o cabeçalho de verdade é encontrado, apesar do texto solto antes ==")
cols = E._cols_prazo_garantia(TABELA)
ok("coluna da localidade", cols.get("localidade", (None,))[0] == 0, str(cols.get("localidade")))
ok("coluna de qtd/descrição", cols.get("qtd_desc", (None,))[0] == 1, str(cols.get("qtd_desc")))
ok("coluna do valor do produto", cols.get("valor_produto", (None,))[0] == 2,
   str(cols.get("valor_produto")))
ok("coluna do frete", cols.get("frete", (None,))[0] == 3, str(cols.get("frete")))
# "Localidade / Endereço de ENTREGA" contém "entrega" e não pode roubar o prazo
ok("o prazo é a coluna 5, não a do endereço", cols.get("prazo", (None,))[0] == 5,
   str(cols.get("prazo")))
# um parágrafo com a palavra "localidade" não pode virar coluna de localidade
ok("linha de TOTAL antes da tabela não interrompe a varredura",
   not E._parece_linha_de_item(TABELA[5]))
ok("parágrafo numa célula só não entra no cabeçalho",
   E._cols_prazo_garantia(TABELA[:8]) == {})

print("\n== os itens, a quantidade e o prazo de cada destino ==")
itens, entregas = E._quadro_por_localidade(TABELA)
produtos = [i for i in itens if i.descricao != "Frete"]
ok("5 destinos viram 5 itens", len(produtos) == 5, "%d" % len(produtos))
ok("a linha de TOTAL GERAL ficou de fora",
   not any("total" in i.descricao.lower() for i in itens))
if produtos:
    a = produtos[0]
    # "01 Conjunto (1 Rack + 1 PDU)" = Qtd 1, unidade Conjunto, descrição o resto
    ok("quantidade 1", a.quantidade == "1", a.quantidade)
    ok("unidade 'Conjunto'", a.unidade == "Conjunto", a.unidade)
    ok("descrição '(1 Rack + 1 PDU)'", a.descricao == "(1 Rack + 1 PDU)", a.descricao)
    ok("preço do PRODUTO, sem o frete junto", a.preco_unit_com == "4.782,80",
       a.preco_unit_com)
    ok("total da linha = unitário x qtd", a.preco_total_com == "4.782,80",
       a.preco_total_com)
ok("cada destino guarda o SEU prazo",
   produtos[2].prazo.startswith("13 a 15") and produtos[3].prazo.startswith("10 a 12"),
   "%r / %r" % (produtos[2].prazo, produtos[3].prazo))

print("\n== o frete é UM item, com o total somado ==")
fretes = [i for i in itens if i.descricao == "Frete"]
ok("existe um item de frete, e só um", len(fretes) == 1, "%d" % len(fretes))
if fretes:
    f = fretes[0]
    ok("quantidade 1", f.quantidade == "1", f.quantidade)
    # 2.500 + 2.550 + 2.500 + 1.200 + 1.200 = 9.950,00
    ok("valor = soma dos fretes dos destinos", f.preco_total_com == "9.950,00",
       f.preco_total_com)
# e o frete não é contado duas vezes: itens + frete = total dos destinos
soma = sum(brl_para_float(i.preco_total_com) or 0 for i in itens)
ok("a soma não conta o frete duas vezes", abs(soma - (5 * 4782.80 + 9950.0)) < 0.01,
   "%.2f" % soma)

print("\n== os locais de entrega vêm da própria proposta ==")
ok("um por destino", len(entregas) == 5, "%d" % len(entregas))
if entregas:
    ok("nome da localidade", entregas[0]["nome"] == "Anápolis", entregas[0]["nome"])
    ok("endereço inteiro", entregas[0]["endereco"] == "Rod. GO 330 Km 07 - Anápolis/GO",
       entregas[0]["endereco"])
    # o município de verdade está no fim do endereço e nem sempre é o nome da
    # localidade: "Bandeirantes/GO" é entregue em Aparecida de Goiânia
    ok("município sai do fim do endereço", entregas[1]["municipio"] == "Ap. de Goiânia",
       entregas[1]["municipio"])
    ok("e a UF junto", entregas[1]["uf"] == "GO", entregas[1]["uf"])
    # "Porto Colômbia / MG" é entregue em Planura/MG
    ok("localidade e município podem diferir",
       entregas[4]["nome"] == "Porto Colômbia" and entregas[4]["municipio"] == "Planura",
       "%s / %s" % (entregas[4]["nome"], entregas[4]["municipio"]))

print("\n== a filial de faturamento sai da UF de cada entrega ==")
# A nota sai da filial do estado onde a mercadoria entra: entregando em GO, DF,
# MG e SP, faturam-se as quatro. Antes eram escolhidas à mão numa lista de 26.
_fat = E._faturamento_das_ufs(entregas, [])
_ufs = [f.get("uf") for f in _fat]
ok("uma filial por UF de entrega, sem repetir", _ufs == ["GO", "DF", "SP", "MG"], str(_ufs))
ok("e são filiais da Eletronet",
   all("03.052.673" in (f.get("cnpj") or "") for f in _fat),
   str([f.get("cnpj") for f in _fat]))
# o CNPJ escrito na folha manda quando existe; a UF só COMPLETA o que falta
_ja = [{"uf": "GO", "cnpj": "03.052.673/0014-06"}]
_ufs2 = [f.get("uf") for f in E._faturamento_das_ufs(entregas, _ja)]
ok("não repete a filial que já entrou pelo CNPJ da proposta",
   "GO" not in _ufs2 and "DF" in _ufs2, str(_ufs2))
ok("sem entregas, não inventa filial", E._faturamento_das_ufs([], []) == [])

print("\n== o local lido vira o POP do cadastro, com endereço ==")
# A proposta diz só o nome. Preenchido à mão, o campo sairia do cadastro e viria
# completo — sigla, endereço, município. O documento ficava com o faturamento
# detalhado ao lado de um local de entrega pelado.
_completos = E.completar_entregas([
    {"nome": "Guarulhos", "sigla": "", "municipio": "Guarulhos", "uf": "SP", "endereco": ""},
    {"nome": "Taquaril", "sigla": "", "municipio": "Taquaril", "uf": "MG", "endereco": ""},
])
ok("ganhou a sigla do cadastro", all(e["sigla"] for e in _completos),
   str([e["sigla"] for e in _completos]))
ok("e o endereço", all(e["endereco"] for e in _completos),
   str([e["endereco"][:24] for e in _completos]))
# "Taquaril" fica em Belo Horizonte: o município do cadastro corrige o do nome
ok("o município vem do cadastro, não do nome do POP",
   _completos[1]["municipio"] == "Belo Horizonte", _completos[1]["municipio"])

# "Fortaleza" casa com SEIS registros ("Angola Cable - Fortaleza", "Fortaleza"…):
# nome exato manda, senão o parecido escolheria o errado
_fla = E.completar_entregas([{"nome": "Fortaleza", "sigla": "", "municipio": "",
                              "uf": "CE", "endereco": ""}])
ok("nome exato ganha de 'Angola Cable - Fortaleza'",
   "angola" not in _fla[0]["nome"].lower(), _fla[0]["nome"])

# a UF é filtro: há "Paulo Afonso" na BA e "Paulo Afonso III" em AL
_pa = E.completar_entregas([{"nome": "Paulo Afonso", "sigla": "", "municipio": "",
                             "uf": "BA", "endereco": ""}])
ok("a UF impede casar com o POP de outro estado", _pa[0]["uf"] == "BA", _pa[0]["uf"])

# nome que não está no cadastro fica como a proposta escreveu
_novo = E.completar_entregas([{"nome": "Lugar Inexistente ZZ", "sigla": "",
                               "municipio": "Xis", "uf": "SP",
                               "endereco": "Rua da proposta, 1"}])
ok("nome fora do cadastro fica como veio",
   _novo[0]["endereco"] == "Rua da proposta, 1", _novo[0]["endereco"])
ok("lista vazia não quebra", E.completar_entregas([]) == [])

print("\n== a ESPECIFICAÇÃO TÉCNICA vai para as observações ==")
TEXTO = """ESPECIFICAÇÃO TÉCNICA DO CONJUNTO POR LOCALIDADE
Fornecimento de 01 (um) Conjunto por Localidade composto por:
• 01 Rack Indoor 19'' 44U (Alt: 2090mm x Lar: 600mm x Prof: 800mm) com Porta Frontal Perfurada e Sistema
de Aterramento Integrado/Embutido.
• PDU 200A: Disjuntor Geral com distribuição VIA A e VIA B contendo 8x63A, 6x32A e 6x20A. POR
LOCALIDADE!
TOTAL DOS PRODUTOS (8 CONJUNTOS) R$ 38.262,40
1. QUADRO COMERCIAL E LOGÍSTICO POR LOCALIDADE"""
obs = E._especificacao_tecnica(TEXTO)
ok("achou os dois marcadores mais a abertura", len(obs) == 3, "%d: %r" % (len(obs), obs))
ok("remonta o marcador quebrado em duas linhas",
   any("Aterramento Integrado/Embutido" in o and "Rack Indoor" in o for o in obs),
   repr(obs))
ok("e o segundo também", any(o.endswith("POR LOCALIDADE!") for o in obs), repr(obs))
ok("para antes da linha de totais", not any("38.262,40" in o for o in obs), repr(obs))
ok("e antes da próxima seção", not any("QUADRO COMERCIAL" in o for o in obs), repr(obs))

print("\n== e o caminho INTEIRO: proposta -> tela -> documento ==")
# O elo que faltava. O extrator já devolvia a especificação em `observacoes`,
# mas na tela o campo só era LIDO (ao gerar e ao salvar rascunho) — nada nunca
# escrevia nele. O texto era produzido e descartado no caminho, e o quadro de
# observações ficava vazio.
_js = io.open(os.path.join(PROJ, "frontend", "app.js"), encoding="utf-8").read()
ok("existe a função que põe as observações na tela", "function porObservacoes(" in _js)
ok("chamada ao LER uma proposta", "porObservacoes(p.observacoes)" in _js)
ok("e ao IMPORTAR uma AF pronta", "porObservacoes(d.observacoes)" in _js)
ok("não repete o que a pessoa já escreveu", "jaTem.has(txt)" in _js)

# e do formulário para o documento
import html as _html
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
import engine
_OBS = ["Fornecimento de 01 (um) Conjunto por Localidade composto por:",
        "01 Rack Indoor 19'' 44U com Porta Frontal Perfurada",
        "PDU 200A: Disjuntor Geral com distribuição VIA A e VIA B"]
_html_af = engine.montar_preview({
    "fornecedor": "ARTEMIS RACKS & SOLUTIONS LTDA", "valor_total": "55.980,40",
    "numero": "1", "ano": "2026", "prefixo": "AF-E", "moeda": "Real",
    "objeto": "Fornecimento de conjuntos", "observacoes": _OBS,
    "itens": [{"descricao": "(1 Rack + 1 PDU)", "quantidade": "1",
               "preco_unit_com": "4.782,80"}]})
# o documento escapa aspas e acentos: comparar no texto, não no HTML cru
_texto = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", _html_af)))
for _o in _OBS:
    ok("sai no documento: %r" % _o[:34], _o[:40] in _texto)

print("\n== o '•' separa dois campos na mesma linha ==")
pg = E._pagamento("• Forma de Pagamento: 21 DDL • Validade da Proposta: 01 (um) dia.")
ok("a validade não fica grudada no pagamento",
   pg == "O pagamento deve ser efetuado 21 dias após o faturamento", pg)

print("\n== a razão social acaba na forma jurídica ==")
for bruto, esperado in (
        ("A ARTEMIS RACKS & SOLUTIONS LTDA. submete à apreciação da",
         "ARTEMIS RACKS & SOLUTIONS LTDA"),
        ("SEICOM - INDUSTRIA, COMERCIO E SERVICOS", "SEICOM - INDUSTRIA, COMERCIO E SERVICOS"),
        ("Zopone Engenharia e Comércio Ltda", "Zopone Engenharia e Comércio Ltda")):
    lido = E._ate_a_forma_juridica(bruto)
    ok("corta %r" % bruto[:34], lido == esperado, "veio %r" % lido)

print("\n== endereço precisa de número ==")
ok("cabeçalho de tabela não vira endereço",
   E._endereco("Localidade / Endereço de Entrega Valor Produto Frete") == "")
ok("endereço de verdade continua passando",
   E._endereco("Endereço: RUA YASHICA, 535, JD GONÇALVES - Sorocaba - SP")
   == "RUA YASHICA, 535, JD GONÇALVES - Sorocaba - SP")

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

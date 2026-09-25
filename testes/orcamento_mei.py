# -*- coding: utf-8 -*-
r"""Orçamento de MEI, e um nome de arquivo que o navegador recusava.

O ERRO
------
"Failed to read the 'headers' property from 'RequestInit': String contains
non ISO-8859-1 code point." O nome do arquivo ia num cabeçalho HTTP, e
cabeçalho só aceita Latin-1. O arquivo que estourou foi um
"Orçamento_-_Deslocamento_Extra.pdf" cujo "ç" NÃO era o ç: era "c" + cedilha
solta (U+0327), forma que o OneDrive/Mac grava. Idêntico na tela, fora do
Latin-1 — e o fetch morria antes de sair. Travessão "–" e aspas curvas "’"
davam o mesmo erro.

O ORÇAMENTO
-----------
Lido o arquivo, o documento vinha vazio: é de um MEI, cuja razão social a
Receita registra como "<raiz do CNPJ> <NOME DO TITULAR>" — sem LTDA nem S.A.
para a busca pela forma jurídica achar. E a coluna "VALOR UNIT." quebra em
duas linhas na folha, deixando a linha do produto só com o TOTAL.

O QUE ESTE TESTE GUARDA
-----------------------
  • o front nunca põe o nome cru no cabeçalho; o servidor desfaz a codificação
    e junta a cedilha solta de volta no "ç";
  • a razão social de MEI é reconhecida — mas só com a raiz do CNPJ DO
    DOCUMENTO, não qualquer linha que comece com número;
  • "N°: 2026/001" é o número do orçamento, e "ANO: 2026/27" não é;
  • a linha com só o total vira item, com o unitário tirado da conta — e só
    quando a soma bate com o total anunciado.

Os dados abaixo são FICTÍCIOS: o orçamento real traz telefone e e-mail de uma
pessoa, e este repositório é público.
"""
import io
import os
import re
import sys
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

import app
from core.extrator import ExtratorProposta

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


print("== o nome do arquivo não derruba o envio ==")
js = io.open(os.path.join(PROJ, "frontend", "app.js"), encoding="utf-8").read()
crus = re.findall(r'"X-Filename"\s*:\s*[\w.]+\.name', js)
ok("nenhum cabeçalho leva o nome cru", not crus, str(crus))
ok("o nome passa por encodeURIComponent",
   re.search(r'"X-Filename"\s*:\s*encodeURIComponent\(', js) is not None)


class _Falso:
    """Só o que o _upload_tmp lê do Handler."""
    def __init__(self, nome):
        self.headers = {"X-Filename": urllib.parse.quote(nome)}  # = encodeURIComponent


NOME = "Orçamento – Extra’s.pdf"     # c + cedilha solta, travessão, aspas curvas
tmp = app.Handler._upload_tmp(_Falso(NOME), b"%PDF", "teste_mei", "proposta.pdf")
try:
    base = os.path.basename(tmp)
    ok("o servidor devolve o ç inteiro", "Orçamento" in base, base)
    ok("a extensão sobrevive (é ela que escolhe o leitor)", base.endswith(".pdf"), base)
    ok("e o arquivo foi gravado", os.path.getsize(tmp) == 4)
finally:
    os.remove(tmp)

print("\n== orçamento de MEI ==")
# o texto como o pdfplumber o entrega (medido no PDF real, dados trocados)
TEXTO = """12.345.678 MARIA EXEMPLO DA SILVA ORÇAMENTO
CNPJ: 12.345.678/0001-95 N°: 2026/001
Telefone: (00) 00000-0000 Data: 24/09/2026
Goiânia - GO
Emitente: Maria Exemplo da Silva Validade da Proposta: 10 dias
Localidade: Goiânia - GO Condição de Pagamento: À vista / PIX
VALOR
ITEM DESCRIÇÃO DO SERVIÇO QTD TOTAL
UNIT.
R$
01 Deslocamento Extra 1 R$ 300,00
300,00
VALOR TOTAL: R$ 300,00
Observações / Condições:
• Este orçamento é válido pelo período de 10 dias a partir da data de emissão.
12.345.678 Maria Exemplo da Silva
CNPJ: 12.345.678/0001-95
12.345.678 Maria Exemplo da Silva — Contato: (00) 00000-0000 Página 1 de 1
"""
ex = ExtratorProposta()
forn = ex._fornecedor(TEXTO)
ok("a razão social de MEI é o fornecedor", forn == "12.345.678 MARIA EXEMPLO DA SILVA", repr(forn))
ok("sem o título da folha grudado", "ORÇAMENTO" not in forn, repr(forn))

OUTRA_RAIZ = TEXTO.replace("12.345.678 MARIA EXEMPLO DA SILVA ORÇAMENTO", "99.888.777 JOAO DE OUTRO LUGAR") \
                  .replace("12.345.678 Maria", "Maria")
ok("raiz que não é a do CNPJ do documento não vira fornecedor",
   "JOAO" not in ex._fornecedor(OUTRA_RAIZ), repr(ex._fornecedor(OUTRA_RAIZ)))

num = ex._numero_proposta(TEXTO)
ok("N°: 2026/001 é o número", num == "2026/001", repr(num))
ok("ANO: 2026/27 não é número de proposta",
   ex._numero_proposta("Referência\nANO: 2026/27\n") == "")

itens = ex._itens_linha_total(TEXTO, "300,00")
ok("a linha com só o total vira 1 item", len(itens) == 1, str(len(itens)))
if itens:
    it = itens[0]
    ok("com a descrição limpa", it.descricao == "Deslocamento Extra", repr(it.descricao))
    ok("e o unitário tirado da conta", it.preco_unit_sem == "300,00" and it.quantidade == "1",
       "%s x %s" % (it.quantidade, it.preco_unit_sem))
    ok("o total da linha fica", it.preco_total_com == "300,00", repr(it.preco_total_com))

print("\n== a conta decide ==")
DOIS = """01 Deslocamento Extra 1 R$ 300,00
02 Diaria de tecnico 3 R$ 150,00 R$ 450,00
VALOR TOTAL: R$ 750,00
"""
dois = ex._itens_linha_total(DOIS, "750,00")
ok("duas linhas que somam o total: 2 itens", len(dois) == 2, str(len(dois)))
ok("com unitário na linha, vale o da linha",
   len(dois) == 2 and dois[1].preco_unit_sem == "150,00" and dois[1].quantidade == "3")
ok("soma que não bate com o total: nenhum item", ex._itens_linha_total(DOIS, "999,00") == [])
ok("sem total anunciado: nenhum item", ex._itens_linha_total(DOIS, "") == [])
ERRADA = "01 Diaria de tecnico 2 R$ 100,00 R$ 300,00\nVALOR TOTAL: R$ 300,00\n"
ok("linha em que qtd × unitário não dá o total é descartada",
   ex._itens_linha_total(ERRADA, "300,00") == [])

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

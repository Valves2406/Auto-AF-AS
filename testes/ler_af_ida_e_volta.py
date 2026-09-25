# -*- coding: utf-8 -*-
r"""Ler a AF de volta: o que o app escreveu tem de voltar igual.

POR QUE IDA E VOLTA
-------------------
A AF é um documento NOSSO. Sabemos exatamente o que entrou nela, então dá
para conferir a leitura sem gabarito externo nenhum: monta-se uma AF com
dados conhecidos, gera-se o documento pelo próprio app, lê-se de volta e
compara-se campo a campo.

O leitor antigo tratava a AF como proposta de fornecedor — procurava pedaços
de texto soltos — e, medido em 93 AFs reais com PDF e Excel da mesma AF:

    faturamento e locais de entrega   0 de 93 lidos do PDF
    CEP                               o da Eletronet no lugar do fornecedor (51)
    nº da proposta                    o próprio nº da AF (23)
    garantia/prazo/pagamento          só a 1ª linha de um texto de várias
    itens (Excel)                     só as linhas 28-44 — AF de 28 itens voltava com 16
    pagamento (Excel)                 célula B51 fixa, que caía em cima de um item

O leitor novo (core/leitor_af.py) lê pelo DESENHO do documento: título de
seção, rótulo e valor têm estilos diferentes no PDF visual; o modelo Excel
tem rótulos com dois-pontos, notas numeradas e borda em cada célula.

O QUE ESTE TESTE GUARDA
-----------------------
  • PDF visual: TODOS os campos, 18 itens (com impostos e descrição longa que
    quebra linha), 2 e 4 filiais (cartão ao lado e grade), 5 locais,
    observações, garantia/prazo/pagamento de várias linhas;
  • Excel: os mesmos campos pela planilha (itens até o limite do modelo);
  • a conta confere a leitura: soma dos itens = valor total, sem aviso.

Precisa do Edge (PDF visual) e do modelo .xlsm (Excel) — sem eles, a parte
correspondente é pulada, não reprovada.
"""
import io
import os
import re
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)

import logging
logging.disable(logging.CRITICAL)

import engine
from core.gerador import _edge_exe, gerar_af_pdf_html
from core.modelos import brl_para_float, float_para_brl

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome +
          (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ------------------------------------------------------------ a AF de teste --
# Siglas e municípios INVENTADOS: o local volta pelo texto do PDF, sem depender
# do catálogo desta máquina. As filiais são reais (o CNPJ é a identidade).
LOCAIS = [("Estação Teste %d" % i, "TST%d" % i, "Rodovia de Teste %d, km %d - Zona Rural" % (i, 10 * i),
           "Cidade Teste %d" % i, "MG" if i % 2 else "BA") for i in range(1, 6)]
FILIAIS = [("MG", "03.052.673/0002-64"), ("BA", "03.052.673/0020-46"),
           ("RS", "03.052.673/0005-07"), ("PR", "03.052.673/0006-98")]


def item(i):
    unit = 1000 + 37.5 * i
    qtd = (i % 4) + 1
    imp = [{"nome": "IPI", "aliq": "5"}, {"nome": "ICMS", "aliq": "18"}] if i % 3 == 0 else []
    uc = unit * 1.23 if imp else unit
    desc = ("Transponder Muxponder 400G com dois módulos de linha coerentes, "
            "licença de software perpétua e kit de instalação (lote %d)" % i) if i % 5 == 0 \
        else "Módulo óptico QSFP28 100G LR4 - lote %d" % i
    return {"codigo": "TMD400G-SD-%02dA-000" % i, "descricao": desc, "quantidade": str(qtd),
            "preco_unit_sem": float_para_brl(unit), "preco_unit_com": float_para_brl(uc),
            "preco_total_com": float_para_brl(round(uc, 2) * qtd), "impostos": imp}


def formulario(n_itens, n_filiais):
    itens = [item(i) for i in range(1, n_itens + 1)]
    total = sum(brl_para_float(it["preco_total_com"]) for it in itens)
    return {
        "prefixo": "AF-E", "numero": "901", "ano": "2026", "modificacao": "GE", "revisao": "0",
        "data_emissao": "25/09/2026", "data": "18/09/2026",
        "fornecedor": "EMPRESA EXEMPLO DE TELECOMUNICAÇÕES LTDA", "cnpj": "12.345.678/0001-95",
        "insc_est": "123.456.789.110", "cep": "13.086-902",
        "endereco": "Rua Doutor Exemplo Martins, 500, Galpão 3 - Distrito Industrial, Campinas-SP",
        "numero_proposta": "2026-2023 v3, 2026-1979 v4-RJ e 2026-1979 v4-Recife",
        "objeto": "Fornecimento de transponders, módulos ópticos e serviços técnicos de instalação.",
        "moeda": "Real", "valor_total": float_para_brl(total),
        "garantia": "2 anos para produtos LightPad (DWDM); plugáveis de revenda: 1 ano, "
                    "contados a partir da entrega do bem.",
        "prazo_entrega": "Itens 1 a 3 em 15 dias; demais itens em até 45 dias após o recebimento "
                         "do pedido de compras aprovado por ambas as partes.",
        "condicao_pagamento": "O pagamento será realizado em 1x com até 90 dias de carência "
                              "após a emissão da nota fiscal.",
        "itens": itens,
        "faturamentos": [{"uf": uf, "razao_social": "ELETRONET S.A - FILIAL", "cnpj": c,
                          "endereco": "Endereço da filial %s" % uf, "cep": "00.000-000"}
                         for uf, c in FILIAIS[:n_filiais]],
        "entregas": [{"nome": n, "sigla": s, "endereco": e, "municipio": m, "uf": u}
                     for n, s, e, m, u in LOCAIS],
        "observacoes": ["Os serviços de suporte devem ser faturados para o CNPJ da matriz.",
                        "Entrega agendada com 48h de antecedência."],
    }


def conferir(rotulo, form, d, com_extras=True):
    """Campo a campo: o que entrou tem de voltar."""
    ok(rotulo + ": leu", d.get("ok"), str(d.get("erro")))
    if not d.get("ok"):
        return
    ok(rotulo + ": nº da AF", d.get("af_id") == "AF-E-901/2026-GE", repr(d.get("af_id")))
    for campo in ("fornecedor", "cnpj", "insc_est", "cep", "numero_proposta", "objeto",
                  "garantia", "prazo_entrega", "condicao_pagamento"):
        ok("%s: %s" % (rotulo, campo), norm(d.get(campo)) == norm(form[campo]),
           "%r != %r" % (norm(d.get(campo))[:80], norm(form[campo])[:80]))
    ok(rotulo + ": endereço", norm(form["endereco"]).endswith(norm(d.get("endereco"))) and d.get("endereco"),
       repr(d.get("endereco")))
    ok(rotulo + ": data de emissão", d.get("data_emissao") == "25/09/2026", repr(d.get("data_emissao")))
    ok(rotulo + ": valor total", brl_para_float(d.get("valor_total")) == brl_para_float(form["valor_total"]),
       "%s != %s" % (d.get("valor_total"), form["valor_total"]))
    its = d.get("itens") or []
    ok(rotulo + ": %d itens" % len(form["itens"]), len(its) == len(form["itens"]), str(len(its)))
    for a, b in zip(form["itens"], its):
        mesmo = (a["codigo"] == b["codigo"] and norm(a["descricao"]) == norm(b["descricao"])
                 and a["quantidade"] == b["quantidade"]
                 and all(brl_para_float(a[k]) == brl_para_float(b[k])
                         for k in ("preco_unit_sem", "preco_unit_com", "preco_total_com")))
        if not mesmo:
            ok(rotulo + ": item " + a["codigo"], False, "%r / %r" % (b.get("codigo"), b.get("descricao")))
            break
    else:
        ok(rotulo + ": código, descrição, qtd e preços de TODOS os itens", True)
    ok(rotulo + ": sem aviso de soma", not any("soma" in a for a in d.get("avisos", [])),
       str(d.get("avisos")))
    ok(rotulo + ": filiais pelo CNPJ",
       [re.sub(r"\D", "", f.get("cnpj", "")) for f in d.get("faturamentos", [])]
       == [re.sub(r"\D", "", f["cnpj"]) for f in form["faturamentos"]],
       str([f.get("cnpj") for f in d.get("faturamentos", [])]))
    ok(rotulo + ": locais (nome, sigla, município, UF)",
       [(e.get("nome"), e.get("sigla"), e.get("municipio"), e.get("uf")) for e in d.get("entregas", [])]
       == [(e["nome"], e["sigla"], e["municipio"], e["uf"]) for e in form["entregas"]],
       str([(e.get("nome"), e.get("sigla")) for e in d.get("entregas", [])]))
    if com_extras:
        ok(rotulo + ": data da proposta", d.get("data_proposta") == "18/09/2026", repr(d.get("data_proposta")))
        ok(rotulo + ": impostos por item",
           [it.get("impostos") for it in its] == [it["impostos"] for it in form["itens"]],
           str([it.get("impostos") for it in its][:4]))
        ok(rotulo + ": observações", d.get("observacoes") == form["observacoes"], str(d.get("observacoes")))


tmp = tempfile.mkdtemp(prefix="teste_ler_af_")

print("== PDF visual (o que o app gera hoje) ==")
if not _edge_exe():
    print("  (Microsoft Edge não encontrado — parte pulada)")
else:
    for n_fil, nome in ((2, "2 filiais, cartão ao lado"), (4, "4 filiais, em grade")):
        form = formulario(18, n_fil)
        pdf = os.path.join(tmp, "visual_%d.pdf" % n_fil)
        gerar_af_pdf_html(pdf, engine.montar_preview(dict(form)))
        print("  -- %s --" % nome)
        conferir("visual", form, engine.importar_af(pdf))

print("\n== Excel (.xlsx pelo modelo oficial) ==")
from core import gerador
try:
    modelo = gerador.template_para("AF-E")
except Exception:
    modelo = ""
if not (modelo and os.path.exists(modelo)):
    print("  (modelo .xlsm ausente — parte pulada; ele não vai para o repositório)")
else:
    form = formulario(12, 2)                    # o modelo Excel comporta 14 itens
    res = engine.gerar(dict(form, formato="excel", saida=os.path.join(tmp, "af.xlsx")))
    ok("excel: gerou", res.get("ok"), str(res.get("erro")))
    if res.get("ok"):
        conferir("excel", form, engine.importar_af(res["saida"]), com_extras=False)

    # O PDF OFICIAL: o modelo impresso pelo próprio Excel. É o desenho mais
    # difícil de ler — o Excel não quebra linha, e o que passa da célula fica
    # escondido atrás da vizinha (a descrição "(lote 5)" virava a quantidade
    # "25)"; o nº da proposta longo invadia a inscrição estadual).
    print("\n== PDF oficial (modelo impresso pelo Excel) ==")
    if not gerador.EXCEL_COM_DISPONIVEL:
        print("  (Excel indisponível — parte pulada)")
    else:
        res = engine.gerar(dict(form, formato="pdf", pdf_estilo="excel", anexar_proposta=False,
                                saida=os.path.join(tmp, "oficial.pdf")))
        if not res.get("ok") or any("reportlab" in a for a in res.get("avisos", [])):
            print("  (o Excel não exportou o PDF nesta máquina — parte pulada)")
        else:
            conferir("oficial", form, engine.importar_af(res["saida"]), com_extras=False)

print()
print("FALHAS: " + ", ".join(falhas) if falhas else "TUDO OK")
sys.exit(1 if falhas else 0)

"""
engine.py — API do Gerador de AF (chamada direto pelo app desktop em Python).
Funções: dados(), extrair(pdf), preview(form) -> HTML, gerar(form) -> arquivo.
"""

from __future__ import annotations

import dataclasses
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

from core import dados_eletronet as de
from core.extrator import ExtratorProposta
from core.gerador import (gerar_af_excel, gerar_af_pdf,
                          gerar_af_pdf_html, gerar_cpm_excel, gerar_cpm_pdf,
                          alcada_para, alcadas_lista, _af_id, _cpm_de)
from core.html_render import montar_html
from core.log import get_logger
from core.modelos import (
    DadosProposta, ItemAF, MOEDAS_ORDEM, PREFIXOS, MODIFICACOES,
    brl_para_float, float_para_brl, moeda_info, moeda_nome, valor_por_extenso,
)

LOG = get_logger("engine")

# Propostas lidas nesta sessão: caminho -> {texto, extraido}. Serve p/ aprender
# com a correção quando o documento for gerado. Some ao fechar o app, e tudo
# bem: o aprendizado só perde a chance daquela proposta.
_LIDAS: dict[str, dict] = {}

# Instância p/ os helpers de regex (métodos sem estado). A EXTRAÇÃO em si usa
# uma instância NOVA por chamada (o cache de tabelas é por documento — evita
# corrida entre requisições no servidor multi-thread).
_EXTRATOR = ExtratorProposta()


def dados() -> dict:
    return {
        "ok": True,
        "fornecedores": de.catalogo_fornecedores(),
        "faturamento": de.locais_faturamento(),
        "pops": de.pops_entrega(),
        "moedas": list(MOEDAS_ORDEM),
        "prefixos": list(PREFIXOS),
        "modificacoes": list(MODIFICACOES),
        "ocultos": de.ocultos(),
        "alcadas": alcadas_lista(),   # faixas de responsáveis p/ a cortina do CPM/CPS
        "pessoas": de.pessoas(),      # agenda de quem assina (sugestões + extras)
        # versão à vista: depois de trocar o .exe é como se confere, em dois
        # segundos, se a atualização realmente entrou naquela máquina
        "versao": de.VERSAO_APP,
        "pasta_dados": os.path.dirname(de.USER_JSON),
        "dados": de.onde_estao_os_dados(),
    }


def compartilhar_dados(caminho: str) -> dict:
    """Aponta a máquina para um arquivo de cadastros numa pasta de rede — é o que
    faz o setor inteiro enxergar o que qualquer um cadastrar."""
    try:
        return de.usar_dados_em(caminho)
    except Exception as exc:
        LOG.exception("falha ao trocar a pasta de cadastros")
        return {"ok": False, "erro": str(exc)}


def cadastrar(tipo: str, registro: dict) -> dict:
    """Salva um novo fornecedor / local de faturamento / POP de entrega."""
    try:
        de.adicionar_usuario(tipo, registro or {})
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def modelo_cadastro(caminho: str) -> dict:
    """Gera a planilha-modelo (3 abas) p/ cadastro em massa."""
    try:
        de.modelo_cadastro_xlsx(caminho)
        return {"ok": os.path.exists(caminho), "saida": caminho,
                "pasta": os.path.dirname(caminho), "arquivo": os.path.basename(caminho)}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def importar_cadastros(caminho: str) -> dict:
    """Importa fornecedores/faturamento/POPs em massa de uma planilha preenchida.
    Linhas já cadastradas não duplicam (contadas em 'duplicadas')."""
    if not caminho or not os.path.exists(caminho):
        return {"ok": False, "erro": "Arquivo não encontrado."}
    try:
        r = de.importar_cadastros_xlsx(caminho)
        total = r["fornecedor"] + r["faturamento"] + r["pop"]
        if total:
            return {"ok": True, "total": total, **r, "erro": ""}
        msg = ("Todas as linhas já estavam cadastradas — nada foi duplicado."
               if r.get("duplicadas") else "Nenhuma linha válida encontrada na planilha.")
        return {"ok": False, "total": 0, **r, "erro": msg}
    except Exception as exc:
        LOG.exception("falha na importação em massa")
        return {"ok": False, "erro": str(exc)}


def atualizar(tipo: str, id_antigo: dict, dados: dict) -> dict:
    """Edita QUALQUER item da lista — cadastro seu ou item do catálogo oficial.

    O .xlsm nunca é tocado. Para um item do catálogo, a edição é feita ocultando
    a versão do modelo e cadastrando a corrigida no lugar: a lista mostra só a
    sua, e o ↩ na aba Excluir devolve a original quando quiser."""
    try:
        r = de.atualizar_usuario(tipo, id_antigo or {}, dados or {})
        if r.get("atualizados"):
            return {"ok": True, **r, "erro": ""}

        # não era cadastro seu: é item do catálogo → oculta o antigo e grava o novo
        oc = de.remover_usuario(tipo, id_antigo or {})
        if not (oc.get("ocultados") or oc.get("removidos")):
            return {"ok": False, "erro": "Item não encontrado na lista."}
        try:
            de.adicionar_usuario(tipo, dados or {})
        except ValueError as exc:                 # duplicata: desfaz p/ não sumir o item
            de.restaurar_usuario(tipo, id_antigo or {})
            return {"ok": False, "erro": str(exc)}
        return {"ok": True, "atualizados": 1, "do_catalogo": True, "erro": ""}
    except Exception as exc:
        LOG.exception("falha ao editar cadastro")
        return {"ok": False, "erro": str(exc)}


def remover(tipo: str, registro: dict) -> dict:
    """Apaga um cadastro do usuário; item do catálogo é apenas OCULTADO (reversível)."""
    try:
        r = de.remover_usuario(tipo, registro or {})
        n = r.get("removidos", 0) + r.get("ocultados", 0)
        return {"ok": n > 0, **r, "erro": "" if n else "Item não encontrado."}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def padroes() -> dict:
    """Padrões editáveis pelo usuário (texto fixo da finalidade, gestores)."""
    return {"ok": True, "padroes": de.padroes(), "finalidade_modelo": de.PADRAO_FINALIDADE}


def salvar_padroes(novos: dict) -> dict:
    try:
        return {"ok": True, "padroes": de.salvar_padroes(novos or {})}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def salvar_pessoas(lista) -> dict:
    """Grava a AGENDA de assinaturas (papel + nome), que é permanente."""
    try:
        return {"ok": True, "pessoas": de.salvar_pessoas(lista or [])}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def restaurar(tipo: str, registro: dict) -> dict:
    """Desfaz a ocultação de um item do catálogo."""
    try:
        n = de.restaurar_usuario(tipo, registro or {})
        return {"ok": n > 0, "restaurados": n, "erro": "" if n else "Item não estava oculto."}
    except Exception as exc:
        return {"ok": False, "erro": str(exc)}


def extrair(caminho: str) -> dict:
    if not caminho or not os.path.exists(caminho):
        return {"ok": False, "erro": f"Arquivo não encontrado: {caminho}"}
    # Proposta CIENA vem em EXCEL (DDPTool) e gera DOIS documentos: AF (equipamento)
    # e AS (serviço). Detecta e devolve os dois lados; senão, avisa.
    if caminho.lower().endswith((".xlsx", ".xlsm")):
        try:
            from core.extrator_ciena import ler_ciena
            ci = ler_ciena(caminho)
        except Exception as exc:
            LOG.exception("falha ao ler a proposta CIENA (Excel)")
            return {"ok": False, "erro": f"Falha ao ler o Excel: {exc}"}
        if ci:
            forn = next((f for f in de.catalogo_fornecedores()
                         if "CIENA" in (f.get("empresa", "") or "").upper()), None)
            if forn:                                    # dados oficiais da CIENA do catálogo
                ci.update({"fornecedor": forn.get("empresa", ""), "cnpj": forn.get("cnpj", ""),
                           "insc_est": forn.get("insc_est", ""), "endereco": forn.get("endereco", ""),
                           "cep": forn.get("cep", "")})
            ci["caminho_pdf"] = caminho   # a proposta (Excel) fica p/ anexar depois
            # A planilha diz para ONDE vai cada coisa; a nota sai da filial do
            # estado que recebe. A CIENA entra por este caminho próprio e não
            # passava pela regra de faturamento por UF que as outras já usam.
            try:
                ex_uf = ExtratorProposta()
                # a planilha dá o nome do site; o cadastro dá o endereço
                ci["entregas"] = ex_uf.completar_entregas(ci.get("entregas") or [])
                ci["faturamentos"] = ex_uf._faturamento_das_ufs(ci.get("entregas") or [], [])
            except Exception as exc:
                LOG.warning("não consegui casar as filiais da CIENA: %s", exc)
            return ci
        return {"ok": False, "erro": "Excel não reconhecido — esperava proposta CIENA com as abas "
                                     "'Resumo de Preços' e 'Detalhamento de Preços'."}
    try:
        ex = ExtratorProposta()
        d = dataclasses.asdict(ex.extrair(caminho))
    except Exception as exc:
        LOG.exception("falha inesperada ao extrair a proposta")
        return {"ok": False, "erro": f"Falha ao ler a proposta: {exc}"}
    # guarda o texto e o que foi lido: na hora de gerar, comparamos com o que o
    # usuário deixou no formulário e aprendemos com as correções dele.
    # Em memória (rápido) E em %APPDATA%\AutoAF (sobrevive a fechar o app entre
    # ler a proposta e gerar o documento — que é o caso normal, não a exceção).
    texto_lido = getattr(ex, "ultimo_texto", "")
    _LIDAS[os.path.abspath(caminho)] = {"texto": texto_lido, "extraido": dict(d)}
    if len(_LIDAS) > 12:                    # não crescer sem limite numa sessão longa
        _LIDAS.pop(next(iter(_LIDAS)))
    try:
        from core.aprendizado import lembrar_leitura

        lembrar_leitura(caminho, texto_lido, d)
    except Exception as exc:                # guardar é bônus: nunca derruba a leitura
        LOG.warning("não consegui guardar a leitura da proposta: %s", exc)
    d["ok"] = True
    return d


def _parse_af_id(af_id: str) -> dict:
    """De 'AF-E-207/2026-TR' (ou '...-REV3') volta prefixo/número/ano/mod/revisão.

    A modificação é OPCIONAL: documento gerado com "N/A" sai como
    'AF-E-444/2026' e precisa voltar igual ao ser importado."""
    import re
    m = re.match(r"\s*(A[FS]-[A-Za-z0-9]+)-(\d+)/(\d{4})(?:-(?!REV\d)([A-Za-z0-9]+?))?"
                 r"(?:-REV(\d+))?\s*$", af_id or "")
    if not m:
        return {"prefixo": "", "numero": "", "ano": "", "modificacao": "", "revisao": "0"}
    return {"prefixo": m.group(1), "numero": m.group(2), "ano": m.group(3),
            "modificacao": m.group(4) or "N/A", "revisao": m.group(5) or "0"}


def _importar_af_pdf(caminho: str) -> dict:
    """Lê a AF/AS a partir do PDF — o do próprio app (visual) ou o do modelo
    Excel. Quem sabe ler é o core/leitor_af.py: ele conhece o desenho do
    documento, título por título. Aqui só se traduz para o formulário."""
    from core.leitor_af import ler_af_pdf
    try:
        d = ler_af_pdf(caminho)
    except Exception as exc:
        LOG.exception("falha ao ler a AF em PDF")
        return {"ok": False, "erro": f"Não consegui ler o PDF: {exc}"}
    if not d.get("ok"):
        return d
    if not (d.get("af_id") or d.get("fornecedor")):
        return {"ok": False, "erro": "Não encontrei uma AF neste PDF (nem o número da "
                                     "autorização nem o fornecedor)."}
    ident = _parse_af_id(d.get("af_id", ""))
    tipo = "AS" if (ident["prefixo"].startswith("AS")
                    or "SERVI" in (d.get("titulo") or "").upper()) else "AF"
    avisos = list(d.get("avisos") or [])
    # A CONTA CONFERE A LEITURA. Soma dos itens = valor total: se fecha, tudo
    # o que tem preço foi lido; se não fecha, alguém precisa olhar.
    tot = brl_para_float(d.get("valor_total"))
    soma = sum(brl_para_float(it.get("preco_total_com")) or 0 for it in d.get("itens", []))
    if tot and any(it.get("preco_total_com") for it in d.get("itens", [])) and abs(soma - tot) > 0.05:
        avisos.append(f"A soma dos itens ({float_para_brl(soma)}) não fecha com o valor total "
                      f"da AF ({float_para_brl(tot)}) — confira os itens.")
    return {
        "ok": True, "tipo": tipo, "af_id": d.get("af_id", ""), "cpm": d.get("cpm", ""),
        "fornecedor": d.get("fornecedor", ""), "cnpj": d.get("cnpj", ""),
        "insc_est": d.get("insc_est", ""), "endereco": d.get("endereco", ""), "cep": d.get("cep", ""),
        "numero_proposta": d.get("numero_proposta", ""), "data_emissao": d.get("data_emissao", ""),
        "data_proposta": d.get("data_proposta", ""),
        "valor_total": d.get("valor_total", ""), "objeto": d.get("objeto", ""),
        # a CHAVE do catálogo ("Dólar Americano"), não o que está escrito —
        # senão o <select> da tela não marca a opção
        "moeda": moeda_nome(d.get("moeda") or "Real"),
        "garantia": d.get("garantia", ""), "prazo_entrega": d.get("prazo_entrega", ""),
        "condicao_pagamento": d.get("condicao_pagamento", ""),
        "prefixo": ident["prefixo"], "numero": ident["numero"], "ano": ident["ano"],
        "modificacao": ident["modificacao"], "revisao": ident["revisao"],
        "itens": d.get("itens", []), "faturamentos": d.get("faturamentos", []),
        "entregas": d.get("entregas", []), "observacoes": d.get("observacoes", []),
        "avisos": avisos,
    }


def _st(v) -> str:
    """Célula → texto limpo (datas viram dd/mm/aaaa)."""
    import datetime as _dt
    if v is None:
        return ""
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _brl_import(v) -> str:
    """Número US do Excel ("241364.57") → padrão BR ("241.364,57")."""
    s = str(v if v is not None else "").strip()
    if not s or "," in s:
        return s
    try:
        return float_para_brl(float(s))
    except (ValueError, TypeError):
        return s


def _importar_cpm_xlsx(caminho: str) -> dict:
    """Lê o CPM/CPS pela aba 'CPM' (células FIXAS) e devolve os campos da AF
    (fornecedor/valor/prazo…) + os próprios do CPM (finalidade/alçada/…)."""
    import re
    from openpyxl import load_workbook
    wb = load_workbook(caminho, data_only=True)
    if "CPM" not in wb.sheetnames:
        wb.close()
        return {"ok": False, "erro": "Não é um CPM/CPS do app (aba 'CPM' ausente)."}
    ws = wb["CPM"]

    def c(cel):
        return _st(ws[cel].value)

    titulo, cpm_id, af_id = c("A1"), c("I4"), (c("I13") or c("A21"))
    finalidade, justif, conseq = c("A7"), c("A16"), c("A30")
    fantasia, atend, forn = c("C21"), c("A42"), c("A48")
    prazo_e, local, pagto, alcada = c("D51"), c("D52"), c("D53"), c("D54")
    gerente, gg, diretor, cfo, presid = c("D55"), c("D56"), c("D57"), c("D58"), c("D59")
    relacao, prop_raw = c("H48"), c("C62")
    valor, capex = c("E21"), c("I21")
    data_cpm, data_rel = c("I7"), c("I10")
    consultados = []
    for r in range(36, 40):
        nome = c(f"B{r}")
        if not nome:
            continue
        prazo = ""
        mm = re.search(r"—\s*Prazo:\s*(.+)$", nome)
        if mm:
            prazo, nome = mm.group(1).strip(), nome[:mm.start()].strip(" —")
        consultados.append([nome, prazo, _brl_import(c(f"I{r}"))])
    wb.close()

    tipo = "CPS" if "SERVI" in titulo.upper() else "CPM"
    mp = re.search(r"Proposta:\s*(.+)$", prop_raw)
    proposta = mp.group(1).strip() if mp else ""
    cotv = re.search(r"R\$\s*(\d[\d.,]*)", relacao)   # taxa só se houver NÚMERO
    cotacao = cotv.group(1).strip() if cotv else ""
    # O CPM guarda o valor em REAIS (convertido); a moeda do documento é Real, e a
    # cotação/relação cambial indicam de onde veio (ex.: proposta em US$).
    moeda = "Real"
    ident = _parse_af_id(af_id)
    conselho = presid if "conselho" in (alcada or "").lower() else ""
    return {
        "ok": True, "tipo": tipo, "cpm_id": cpm_id, "af_id": af_id, "cpm": cpm_id,
        "fornecedor": forn, "fornecedor_completo": forn, "fornecedor_fantasia": fantasia,
        "cnpj": "", "insc_est": "", "endereco": "", "cep": "",
        "valor_total": _brl_import(valor), "moeda": moeda,
        "objeto": _cpm_base_texto(finalidade) if finalidade else "",
        "finalidade": finalidade, "justificativa": justif, "consequencias": conseq,
        "atendimento": atend, "prazo_entrega": prazo_e, "local_entrega": local,
        "condicao_pagamento": pagto, "forma_pagamento": pagto, "alcada": alcada,
        "gerente": gerente, "gerente_geral": gg, "diretor": diretor, "cfo": cfo,
        "presidencia": presid, "conselho": conselho,
        "relacao_cambial": relacao, "cotacao": cotacao, "capex": _brl_import(capex),
        "data_cpm": data_cpm, "data_relatorio": data_rel, "numero_proposta": proposta,
        "consultados": consultados,
        "prefixo": ident["prefixo"], "numero": ident["numero"], "ano": ident["ano"],
        "modificacao": ident["modificacao"], "revisao": ident["revisao"],
        "itens": [], "faturamentos": [], "entregas": [],
        "avisos": ["CPM/CPS importada — o CPM não lista os itens (só o total); confira na aba CPM."],
    }


def _importar_cpm_pdf(caminho: str) -> dict:
    """Lê o CPM/CPS do PDF (texto renderizado) por rótulos fixos."""
    import re
    import pdfplumber
    try:
        with pdfplumber.open(caminho) as pdf:
            texto = "\n".join((pg.extract_text() or "") for pg in pdf.pages[:2])
    except Exception as exc:
        return {"ok": False, "erro": f"Não consegui ler o PDF do CPM: {exc}"}

    def acha(pat, grp=1):
        m = re.search(pat, texto, re.I)
        return re.sub(r"\s{2,}", " ", m.group(grp)).strip() if m else ""

    cpm_id = acha(r"(CP[MS]-[A-Za-z0-9]+-\d+/\d{4}-[A-Za-z0-9]+(?:-REV\d+)?)")
    af_id = acha(r"(A[FS]-[A-Za-z0-9]+-\d+/\d{4}-[A-Za-z0-9]+(?:-REV\d+)?)")
    tipo = "CPS" if "SERVI" in texto.upper()[:400] else "CPM"
    ident = _parse_af_id(af_id)
    # valor: aparece VÁRIAS vezes (soma/orçamento/fornecedor/recomendação) → pega o
    # mais frequente com >= 1000 ou >= 3 dígitos (ignora cotação tipo "5,02").
    import collections
    cands = re.findall(r"(\d{1,3}(?:\.\d{3})+,\d{2}|\d{3,},\d{2})", texto)
    valor = collections.Counter(cands).most_common(1)[0][0] if cands else \
        acha(r"SOMA DA COMPRA:\s*([\d.]+,\d{2})")
    relacao = acha(r"(1\s*US\$\s*=\s*R\$\s*\d[\d.,]*)")
    cotv = re.search(r"R\$\s*(\d[\d.,]*)", relacao)
    # fornecedor: nome de empresa (…LTDA/S.A.) seguido de um valor; fallbacks robustos
    forn = (acha(r"([A-ZÀ-Ÿ][A-ZÀ-Ÿ0-9 .,&/\-]{5,}?(?:LTDA|S[/.]?A\.?|EIRELI))\s+[\d.]+,\d{2}")
            or acha(r"FORNECEDOR\s+VALOR[^\n]*\n\s*(.+?)\s+R?\$?\s*[\d.]+,\d{2}")
            or _EXTRATOR._fornecedor(texto))
    forn = re.sub(r"^\d+\s+", "", forn).strip(" $.,-")   # tira "1 " e "$" da linha de consultado
    def bloco(pat):   # texto MULTILINHA (DOTALL) limpo
        m = re.search(pat, texto, re.I | re.S)
        return re.sub(r"\s{2,}", " ", m.group(1).replace("\n", " ")).strip() if m else ""

    finalidade = bloco(r"(Aquisi[çc][ãa]o com a finalidade.*?)(?:AF ASSOCIADA|JUSTIFICATIVA DA)")
    # o layout de 2 colunas mistura data/rótulos no meio da finalidade → remove
    finalidade = re.sub(r"\b\d{2}/\d{2}/\d{4}\b|DATA D[OA] (?:CPM|RELAT[ÓO]RIO)|AF ASSOCIADA:?|"
                        r"CP[MS]-[\w/\-]+|AF-[\w/\-]+", " ", finalidade)
    finalidade = re.sub(r"\s{2,}", " ", finalidade).strip(" .") + ("." if finalidade else "")
    justif = bloco(r"JUSTIFICATIVA DA AQUISI[ÇC][ÃA]O\s*(.+?)\s*(?:OR[ÇC]AMENTO|IDENTIFICA[ÇC])")
    conseq = bloco(r"CONSEQU[ÊE]NCIAS.*?AQUISI[ÇC][ÃA]O\s*(.+?)\s*(?:FORNECEDORES CONSULTADOS|OR[ÇC]AMENTO)")

    def aprov(rot):   # "GERENTE: Nome, email@…" → "Nome"
        m = re.search(rot + r":\s*(.+?)(?:,\s*[\w.\-]+@|\n|$)", texto)
        v = m.group(1).strip() if m else ""
        return "" if v in ("0", "-", "") else v
    gerente, gg = aprov(r"GERENTE(?! GERAL)"), aprov(r"GERENTE GERAL")
    diretor, cfo, presid = aprov("DIRETOR"), aprov("CFO"), aprov(r"PRESID[ÊE]NCIA")
    md = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto)
    data_cpm = md.group(1) if md else ""
    alcada = acha(r"ALÇADA[^\n]*?:\s*(.+?)(?:\n|GERENTE:)")
    conselho = presid if "conselho" in alcada.lower() else ""
    consultados = []
    sec = re.search(r"FORNECEDORES CONSULTADOS.*?(?:ATENDIMENTO|RECOMENDA)", texto, re.I | re.S)
    if sec:
        # nome pode ter MINÚSCULA (ex.: "FONNET Comércio de …"); valor com "$" ou "R$"
        for m in re.finditer(r"\d\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 .,&/\-]{4,}?)\s+R?\$?\s*([\d.]+,\d{2})",
                             sec.group(0)):
            consultados.append([m.group(1).strip(" .-"), "", m.group(2)])
    if not consultados and forn and valor:   # single-source: o recomendado é o consultado
        consultados = [[forn, "", valor]]
    return {
        "ok": True, "tipo": tipo, "cpm_id": cpm_id, "af_id": af_id, "cpm": cpm_id,
        "fornecedor": forn, "fornecedor_completo": forn,
        "cnpj": "", "insc_est": "", "endereco": "", "cep": "",
        "valor_total": valor, "moeda": "Real",   # o CPM guarda o valor em reais
        "objeto": _cpm_base_texto(finalidade) if finalidade else "",
        "finalidade": finalidade, "justificativa": justif, "consequencias": conseq,
        "prazo_entrega": acha(r"PRAZO DE ENTREGA\s+(.+?)\n"),
        "condicao_pagamento": acha(r"FORMA DE PAGAMENTO\s+(.+?)\n"),
        "local_entrega": acha(r"LOCAL DE ENTREGA\s+(.+?)\n"),
        "alcada": alcada,
        "gerente": gerente, "gerente_geral": gg, "diretor": diretor, "cfo": cfo,
        "presidencia": presid, "conselho": conselho,
        "relacao_cambial": relacao, "cotacao": cotv.group(1).strip() if cotv else "",
        "data_cpm": data_cpm, "data_relatorio": data_cpm,
        "numero_proposta": acha(r"Proposta:\s*([A-Za-z0-9\-]+)"),
        "prefixo": ident["prefixo"], "numero": ident["numero"], "ano": ident["ano"],
        "modificacao": ident["modificacao"], "revisao": ident["revisao"],
        "consultados": consultados, "itens": [], "faturamentos": [], "entregas": [],
        "avisos": ["CPM/CPS importada do PDF (melhor-esforço) — confira; o Excel é mais fiel."],
    }


def importar_af(caminho: str) -> dict:
    """Caminho INVERSO: lê uma AF/AS/CPM/CPS já gerada (Excel OU o PDF do app) e
    devolve TODAS as informações no formato do formulário, p/ revisar e reexportar.
    Detecta o tipo automaticamente (nada muda de lugar → células/rótulos fixos)."""
    if not caminho or not os.path.exists(caminho):
        return {"ok": False, "erro": f"Arquivo não encontrado: {caminho}"}
    nome = os.path.basename(caminho).upper()
    eh_cpm = nome.startswith(("RTC-CPM", "RTC-CPS", "CPM", "CPS"))
    if caminho.lower().endswith(".pdf"):
        return _importar_cpm_pdf(caminho) if eh_cpm else _importar_af_pdf(caminho)
    if eh_cpm:
        return _importar_cpm_xlsx(caminho)
    # Excel sem nome de CPM: tenta AF/AS; se não tiver 'AF-pg1', tenta CPM.
    try:
        from openpyxl import load_workbook
        nomes = load_workbook(caminho, read_only=True).sheetnames
    except Exception:
        nomes = []
    if "AF-pg1" not in nomes and "CPM" in nomes:
        return _importar_cpm_xlsx(caminho)
    try:
        from core.html_render import ler_af
        d = ler_af(caminho)
    except Exception as exc:
        return {"ok": False,
                "erro": f"Não consegui ler a AF (é um .xlsx/.xlsm gerado pelo app?): {exc}"}

    # Os preços foram gravados como NÚMERO no Excel e voltam em formato US
    # ("180099.59"); reconverte p/ o padrão BR ("180.099,59") do formulário.
    def _brl(v):
        s = str(v if v is not None else "").strip()
        if not s or "," in s:          # vazio ou já em BR
            return s
        try:
            return float_para_brl(float(s))
        except (ValueError, TypeError):
            return s

    ident = _parse_af_id(d.get("af_id", ""))
    itens = [{"codigo": it.get("cod", ""), "descricao": it.get("desc", ""),
              "quantidade": it.get("qtd", ""), "unidade": it.get("un", ""),
              "preco_unit_sem": _brl(it.get("us", "")), "preco_unit_com": _brl(it.get("uc", "")),
              "preco_total_com": _brl(it.get("tot", ""))} for it in d.get("itens", [])]
    faturamentos = [{"razao_social": f.get("razao", ""), "uf": f.get("uf", ""),
                     "cnpj": f.get("cnpj", ""), "endereco": f.get("endereco", ""),
                     "cep": f.get("cep", "")} for f in d.get("faturamentos", [])]
    entregas = [{"nome": e.get("nome", ""), "sigla": e.get("sigla", ""),
                 "endereco": e.get("endereco", ""), "municipio": e.get("municipio", ""),
                 "uf": e.get("uf", "")} for e in d.get("entregas", [])]
    tipo = "AS" if (ident["prefixo"].startswith("AS")
                    or "SERVI" in d.get("titulo", "").upper()) else "AF"
    return {
        "ok": True, "tipo": tipo,
        "af_id": d.get("af_id", ""), "cpm": d.get("cpm", ""),
        "fornecedor": d.get("fornecedor", ""), "cnpj": d.get("cnpj", ""),
        "insc_est": d.get("ie", ""), "endereco": d.get("endereco", ""), "cep": d.get("cep", ""),
        "numero_proposta": d.get("proposta", ""), "data_emissao": d.get("data", ""),
        # U19 (topo) é o total autoritativo — fica ACIMA dos itens, então nunca
        # desce de linha em AF grande; R43 pode virar item quando há muitos itens.
        "valor_total": _brl(d.get("total_topo", "") or d.get("total_forn", "") or d.get("total", "")),
        "objeto": d.get("objeto", ""), "moeda": d.get("moeda", "Real"),
        "garantia": d.get("garantia", ""), "prazo_entrega": d.get("prazo", ""),
        "condicao_pagamento": d.get("pagamento", ""),
        "prefixo": ident["prefixo"], "numero": ident["numero"], "ano": ident["ano"],
        "modificacao": ident["modificacao"], "revisao": ident["revisao"],
        "itens": itens, "faturamentos": faturamentos, "entregas": entregas,
        "avisos": d.get("avisos", []),
    }


def _item_vazio(it: dict) -> bool:
    """Linha em branco da grade não é item.

    A tabela sempre deixa uma linha livre no fim para digitar a próxima — e ela
    ia parar no documento e no Excel como uma linha de trações. Só ficou
    evidente quando o item passou a mostrar imposto: aparecia "IPI 5%" numa
    linha sem código, sem descrição e sem preço. Imposto sozinho não é conteúdo."""
    return not any(str((it or {}).get(k, "")).strip()
                   for k in ("codigo", "descricao", "quantidade",
                             "preco_unit_sem", "preco_unit_com", "preco_total_com"))


def itens_uteis(lista) -> list:
    return [it for it in (lista or []) if it and not _item_vazio(it)]


def _proposta_de(j: dict) -> DadosProposta:
    campos = {f.name for f in dataclasses.fields(DadosProposta)}
    base = {k: v for k, v in (j or {}).items() if k in campos and k != "itens"}
    prop = DadosProposta(**base)
    ic = {f.name for f in dataclasses.fields(ItemAF)}
    prop.itens = [ItemAF(**{k: v for k, v in (it or {}).items() if k in ic})
                  for it in itens_uteis((j or {}).get("itens", []))]
    return prop


def montar_preview(p: dict) -> str:
    prefixo = p.get("prefixo", "AF-E")
    numero = p.get("numero", "") or "___"
    ano, mod = p.get("ano", ""), p.get("modificacao", "")
    rev = p.get("revisao", "")
    moeda = p.get("moeda", "Real")
    mo = moeda_info(moeda)
    valor = brl_para_float(p.get("valor_total", ""))
    titulo = "AUTORIZAÇÃO DE " + ("SERVIÇO - AS" if prefixo.upper().startswith("AS")
                                  else "FORNECIMENTO - AF")

    def _lista(*chaves):
        for ch in chaves:
            v = p.get(ch)
            if isinstance(v, list):
                return [x for x in v if x]
            if isinstance(v, dict):
                return [v]
        return []

    faturamentos = _lista("faturamentos", "faturamento")
    entregas = _lista("entregas", "entrega")
    d = {
        "arquivo": "", "titulo": titulo,
        "af_id": _af_id(prefixo, numero, ano, mod, rev), "cpm": _cpm_de(prefixo, numero, ano, mod, rev),
        # Duas datas distintas: emissão (quando a AF é feita) vai p/ Identificação;
        # data da proposta (quando o fornecedor a emitiu) vai p/ o bloco Fornecedor.
        "data": p.get("data_emissao", ""), "data_proposta": p.get("data", ""),
        "proposta": p.get("numero_proposta", ""),
        "fornecedor": p.get("fornecedor", ""), "endereco": p.get("endereco", ""),
        "cep": p.get("cep", ""), "cnpj": p.get("cnpj", ""), "ie": p.get("insc_est", ""),
        "moeda": moeda,
        "extenso": (valor_por_extenso(valor, mo["sing"], mo["plur"], mo["sub"], mo["sub_pl"]) + ".")
                   if valor is not None else "",
        "objeto": p.get("objeto", ""), "total": valor, "total_topo": "", "total_forn": "",
        "itens": [{"cod": it.get("codigo", ""), "desc": it.get("descricao", ""),
                   "qtd": it.get("quantidade", ""), "un": it.get("unidade", ""),
                   "us": it.get("preco_unit_sem", ""), "uc": it.get("preco_unit_com", ""),
                   "tot": it.get("preco_total_com", ""),
                   "imp": it.get("impostos") or []} for it in itens_uteis(p.get("itens", []))],
        "garantia": p.get("garantia", ""), "prazo": p.get("prazo_entrega", ""),
        "pagamento": p.get("condicao_pagamento", ""),
        "faturamentos": [{"razao": f.get("razao_social", ""), "uf": f.get("uf", ""),
                          "endereco": f.get("endereco", ""), "cep": f.get("cep", ""),
                          "cnpj": f.get("cnpj", "")} for f in faturamentos],
        "entregas": entregas,
        "observacoes": [str(o).strip() for o in (p.get("observacoes") or []) if str(o).strip()],
        # gestores que assinam ESTA AF/AS, além de Eletronet e fornecedor
        "assinantes": [x for x in (p.get("assinantes") or [])
                       if isinstance(x, dict) and str(x.get("nome", "")).strip()],
        # faixa de RUBRICA no pé da folha (opcional): quem confere a AF rubrica
        # cada folha; a assinatura completa continua no fim do documento.
        # `rubricas_todas` escolhe ONDE: sem ela, só a última folha (o padrão);
        # com ela, todas. Só tem efeito quando `rubricas` está marcado.
        "rubricas": bool(p.get("rubricas")),
        "rubricas_todas": bool(p.get("rubricas_todas")),
        "avisos": [],
    }
    return montar_html(d)


# ------------------------------------------------------------ CPM / CPS -----
def _cpm_base_texto(objeto: str) -> str:
    """Tira o 'Fornecimento de ' do objeto p/ encaixar nos textos do CPM.

    Sem objeto devolve VAZIO — nunca "a aquisição". Aquele default produzia
    "Aquisição com a finalidade de realizar a aquisição", que não diz nada e
    ainda assim ia para o documento assinado."""
    import re
    return re.sub(r"^\s*fornecimento\s+de\s+", "", (objeto or ""), flags=re.I).strip()


def _resumo_itens(itens, limite: int = 3) -> str:
    """Objeto deduzido dos ITENS quando o campo veio vazio: melhor descrever o
    que está sendo comprado do que escrever uma frase genérica."""
    import re
    descs = []
    for it in (itens or []):
        d = str((it or {}).get("descricao") or (it or {}).get("codigo") or "").strip()
        d = re.sub(r"\s+", " ", d)
        if not d:
            continue
        d = re.split(r"[;|\n]", d)[0].strip(" .,-")      # 1ª oração: a descrição costuma ser longa
        if len(d) > 64:
            d = d[:61].rstrip() + "…"
        if d.lower() not in [x.lower() for x in descs]:
            descs.append(d)
    if not descs:
        return ""
    mostrados = descs[:limite]
    txt = mostrados[0] if len(mostrados) == 1 else ", ".join(mostrados[:-1]) + " e " + mostrados[-1]
    sobra = len(descs) - len(mostrados)
    return txt + (f" e mais {sobra} item(ns)" if sobra > 0 else "")


def _abre_finalidade(base: str) -> str:
    """Costura o objeto na frase certa. "realizar a modernização da rede" está
    correto; "realizar 10 switches" não — quando o objeto é uma LISTA DE BENS a
    frase tem de ser "para o fornecimento de"."""
    import re
    b = (base or "").strip()
    if not b:
        return ""
    acao = re.match(r"^(a|o|as|os)\s+\S+(ç[ãa]o|mento|agem|tura|ncia)\b", b, flags=re.I)
    return (f"Aquisição com a finalidade de realizar {b}" if acao
            else f"Aquisição para o fornecimento de {b}")


def _fantasia(nome: str) -> str:
    """Nome fantasia = 1ª palavra em MAIÚSCULAS (DATACOM Telemática → DATACOM)."""
    import re
    p = re.split(r"[ /]+", (nome or "").strip())
    return p[0].upper() if p and p[0] else ""


def _cpm_textos(cenario: str, ctx: dict):
    """Textos PADRONIZADOS (finalidade, justificativa, consequências) nos moldes
    dos exemplos da Eletronet, por cenário: 'sem' (estoque, sem cliente), 'com'
    (um cliente/CAPEX) e 'varios' (vários clientes). Partes vazias são omitidas."""
    import re

    def _t(v):
        return str(v or "").strip()
    def _nomes(lst):
        lst = [x for x in lst if x]
        if not lst:
            return ""
        if len(lst) == 1:
            return lst[0]
        return ", ".join(lst[:-1]) + " e " + lst[-1]
    def _seg(c):
        """Trecho de finalidade para UM cliente, com os campos próprios dele."""
        nome = _t(c.get("cliente")) or "o cliente"
        pa, pb = _t(c.get("pop_a")), _t(c.get("pop_b"))
        s = f"o atendimento do cliente {nome}"
        if pa or pb:
            s += f" entre os POPs {pa} a {pb}"
        if _t(c.get("banda")):
            s += f" de capacidade de {_t(c.get('banda'))}"
        if _t(c.get("servico")):
            s += f" do serviço de {_t(c.get('servico'))}"
        if _t(c.get("produtos")):
            s += f", contemplando {_t(c.get('produtos'))}"
        return s
    forn = _t(ctx.get("fornecedor"))
    # Objeto: o que o usuário escreveu; se não escreveu, o que os ITENS dizem.
    # Sem nenhum dos dois o texto não é inventado — sai vazio para ser preenchido.
    base = _t(ctx.get("objeto_base")) or _resumo_itens(ctx.get("itens"))
    # info estruturada por cliente; se não veio, monta 1 a partir dos escalares (compat)
    info = [c for c in (ctx.get("clientes_info") or []) if any(_t(v) for v in c.values())]
    if not info:
        scal = {"cliente": ctx.get("cliente"), "pop_a": ctx.get("pop_a"), "pop_b": ctx.get("pop_b"),
                "banda": ctx.get("banda"), "servico": ctx.get("servico"), "ccs": ctx.get("ccs"),
                "os": ctx.get("os"), "psc": ctx.get("psc"), "produtos": ctx.get("produtos")}
        if any(_t(v) for v in scal.values()):
            info = [scal]
    nomes_lst = [_t(c.get("cliente")) for c in info if _t(c.get("cliente"))]
    # Associação: AF, CPM e o CCS/OS/PSC de CADA cliente (agrupados por tipo).
    # Identificador sem número ("AF-E-/2026-TR") não é associação — é um campo em
    # branco disfarçado, e ia impresso no documento. Só entra o que está completo.
    # O que importa é ter ALGUMA COISA entre o traço e a barra, não ser dígito: o
    # número da AF pode ser uma sigla de projeto ("AS-E-BMW/2026-TR"), e a regra
    # antiga (`-\d+/`) descartava esses como se fossem campo em branco — a frase
    # "Com associação AF-… e CPM-…" sumia do documento inteiro sem explicação.
    _completo = lambda x: bool(re.search(r"-[^-/\s]+/", _t(x)))   # noqa: E731
    assoc = [x for x in (_t(ctx.get("af_id")), _t(ctx.get("cpm_id"))) if _completo(x)]
    assoc += [f"CCS-{_t(c.get('ccs'))}" for c in info if _t(c.get("ccs"))]
    assoc += [f"OS-{_t(c.get('os') or c.get('os_num'))}" for c in info if _t(c.get("os") or c.get("os_num"))]
    assoc += [f"PSC {_t(c.get('psc'))}" for c in info if _t(c.get("psc"))]
    assoc = [x for x in assoc if x]
    if len(assoc) > 1:
        assoc_txt = f" Com associação {', '.join(assoc[:-1])} e {assoc[-1]}."
    elif assoc:
        assoc_txt = f" Com associação {assoc[0]}."
    else:
        assoc_txt = ""
    just_forn = (f" O fornecedor {forn} é neste momento o único fornecedor que atende todos os "
                 f"requisitos, com equipamento homologado na rede Eletronet, justificando assim a "
                 f"escolha desta proposta.") if forn else ""
    if cenario in ("com", "varios") and info:
        if cenario == "varios" and len(info) >= 2:
            segs = [_seg(c) for c in info]                  # um trecho por cliente
            corpo = ("; ".join(segs[:-1]) + "; e " + segs[-1]) if len(segs) > 2 else (segs[0] + "; e " + segs[1])
            fin = f"Aquisição com a finalidade de realizar {corpo}.{just_forn}{assoc_txt}"
            alvo = f"dos clientes {_nomes(nomes_lst)}" if nomes_lst else "dos clientes"
            locs = ""
        else:
            c = info[0]                                     # 1 cliente (cenário 'com')
            fin = f"Aquisição com a finalidade de realizar {_seg(c)}.{just_forn}{assoc_txt}"
            nome = _t(c.get("cliente"))
            pa, pb = _t(c.get("pop_a")), _t(c.get("pop_b"))
            alvo = f"do cliente {nome}" if nome else "do cliente"
            locs = f" nas localidades {pa} a {pb}" if (pa or pb) else ""
        jus = f"Possibilitar o atendimento {alvo}{locs}."
        con = f"Impossibilidade de realizar o atendimento {alvo}."
    else:   # sem cliente (estoque)
        produtos = _t(ctx.get("produtos"))
        # "contempla" só acrescenta quando diz algo além do objeto — repetir a
        # mesma lista em duas frases seguidas é ruído, não informação. A
        # comparação é feita sem o "Fornecimento de", senão "10 switches" e
        # "Fornecimento de 10 switches" passam por textos diferentes.
        contempla = (f" Esta aquisição contempla {produtos}."
                     if produtos and _cpm_base_texto(produtos).lower() != base.lower() else "")
        # O trecho a partir daqui é FIXO e editável em Cadastros → Padrões: só muda
        # quando o usuário quiser (ou quando o cenário tem cliente, que usa o texto
        # de atendimento). {fornecedor} é o único ponto substituído.
        modelo = (de.padroes().get("finalidade_fixa") or "").strip() or de.PADRAO_FINALIDADE
        forn_ok = (" " + modelo.replace("{fornecedor}", forn)) if forn else ""
        abre = _abre_finalidade(base)
        if abre:
            fin = f"{abre}.{contempla}{forn_ok}{assoc_txt}"
            jus = f"Possibilitar {base}." if base[:1].islower() else f"Possibilitar a aquisição de {base}."
            con = f"Impossibilidade de realizar {base}."
        else:
            # Sem objeto e sem itens não há o que afirmar: o campo fica em branco
            # para ser preenchido, em vez de sair uma frase que não diz nada.
            fin = f"{forn_ok.strip()}{assoc_txt}".strip()
            jus = con = ""
    return fin.strip(), jus.strip(), con.strip()


def cpm_de_form(j: dict) -> dict:
    """Monta o dict do CPM/CPS a partir do formulário da AF + campos próprios do
    CPM. TODO campo tem default (derivado da AF) e pode ser editado manualmente."""
    from datetime import datetime
    from core.modelos import ELETRONET
    prefixo = j.get("prefixo", "AF-E")
    numero, ano = j.get("numero", ""), j.get("ano", "")
    mod, rev = j.get("modificacao", ""), j.get("revisao", "0")
    tipo = "CPS" if str(prefixo).upper().startswith("AS") else "CPM"
    valor = j.get("valor_total", "")
    forn = j.get("fornecedor", "")
    forn_full = j.get("fornecedor_completo") or forn
    base = _cpm_base_texto(j.get("objeto", ""))
    hoje = datetime.today().strftime("%d/%m/%Y")
    g = lambda k, d="": (j.get(k) or d)   # noqa: E731  (usa default se vazio)
    # Para os RESPONSÁVEIS o vazio é uma ESCOLHA, não ausência: só cai no padrão
    # por faixa quando a chave nem veio (uso direto da API, sem formulário).
    resp = lambda k, d="": ((j.get(k) or "") if k in j else d)   # noqa: E731
    # Moeda + conversão p/ REAIS: a cotação é o valor de 1 unidade da moeda em R$
    # (1 US$/€/¥ = R$ X). O valor em reais alimenta a ALÇADA (evita erro humano).
    moeda = j.get("moeda", "Real")
    simb = moeda_info(moeda)["simb"]
    eh_real = (simb == "R$")
    valor_f = brl_para_float(valor) or 0.0
    taxa = brl_para_float(j.get("cotacao", "")) or 0.0
    valor_reais_n = valor_f if eh_real else (valor_f * taxa if taxa else 0.0)
    relacao_cambial = "" if eh_real else f"1 {simb} = R$ {float_para_brl(taxa)}"
    rotulo, nomes = alcada_para(valor_reais_n)   # alçada pela FAIXA em R$ (já sem Herivelto)
    # Gestores PADRÃO do usuário (Cadastros → Padrões) substituem os do template,
    # posição a posição — quem não foi personalizado continua vindo da planilha.
    _g = de.padroes().get("gestores") or {}
    nomes = [(_g.get(k) or nomes[i] if i < len(nomes) else _g.get(k, ""))
             for i, k in enumerate(("gerente", "gerente_geral", "diretor", "cfo", "presidencia"))]
    conselho_d = "Conselho de Administração Eletronet" if "conselho" in (rotulo or "").lower() else ""
    cpm_id = _cpm_de(prefixo, numero, ano, mod, rev)
    af_id = _af_id(prefixo, numero, ano, mod, rev)
    # Textos PADRONIZADOS pelo cenário (sem cliente / com cliente / vários).
    cenario = (j.get("cenario") or "sem").lower()
    # Vários clientes: CADA cliente tem seu próprio conjunto de campos (POP/banda/serviço/
    # CCS/OS/PSC/produtos). 'clientes_info' = lista de dicts; 'clientes' = só os nomes.
    def _cli(c):
        return {"cliente": str(c.get("cliente", "")).strip(), "pop_a": str(c.get("pop_a", "")).strip(),
                "pop_b": str(c.get("pop_b", "")).strip(), "banda": str(c.get("banda", "")).strip(),
                "servico": str(c.get("servico", "")).strip(), "ccs": str(c.get("ccs", "")).strip(),
                "os": str(c.get("os", "") or c.get("os_num", "")).strip(), "psc": str(c.get("psc", "")).strip(),
                "produtos": str(c.get("produtos", "")).strip()}
    clientes_info = [_cli(c) for c in (j.get("clientes_info") or []) if any(str(v).strip() for v in c.values())]
    if not clientes_info and str(j.get("cliente", "")).strip():   # compat: cenário antigo (1 cliente escalar)
        clientes_info = [_cli(j)]
    clientes = [c["cliente"] for c in clientes_info if c["cliente"]]
    ctx = {"fornecedor": forn_full, "objeto_base": base, "produtos": g("produtos", j.get("objeto", "")),
           "itens": j.get("itens") or [],      # objeto deduzido dos itens quando não há objeto escrito
           "cpm_id": cpm_id, "af_id": af_id, "cliente": j.get("cliente", ""), "clientes": clientes,
           "clientes_info": clientes_info,
           "pop_a": j.get("pop_a", ""),
           "pop_b": j.get("pop_b", ""), "banda": j.get("banda", ""), "servico": j.get("servico", ""),
           "ccs": j.get("ccs", ""), "os": j.get("os_num", ""), "psc": j.get("psc", "")}
    fin_d, jus_d, con_d = _cpm_textos(cenario, ctx)
    # Local de entrega = os POPs da AF (podem ser vários); senão, a matriz Eletronet.
    entregas = j.get("entregas") or []

    def _loc(e):
        nome = e.get("nome", "")
        sig = f" ({e.get('sigla')})" if e.get("sigla") else ""
        end = f" — {e.get('endereco')}" if e.get("endereco") else ""      # endereço COMPLETO
        mun = (f", {e.get('municipio')}/{e.get('uf')}" if e.get("municipio") else "")
        return (nome + sig + end + mun).strip()
    local_default = ("; ".join(x for x in (_loc(e) for e in entregas) if x)
                     or f'{ELETRONET["endereco"]} - {ELETRONET["bairro"]}')
    return {
        "tipo": tipo, "cpm_id": cpm_id, "af_id": af_id,
        "fornecedor": forn,
        "fornecedor_completo": forn_full,
        "fornecedor_fantasia": g("fornecedor_fantasia", _fantasia(forn)),
        "valor": valor,
        "moeda": j.get("moeda", "Real"),   # LINKADA da AF
        "proposta": j.get("numero_proposta", ""),
        "data_cpm": g("data_cpm", hoje),
        "data_relatorio": g("data_relatorio", g("data_cpm", hoje)),
        "prazo_entrega": g("prazo_entrega", ""),
        "forma_pagamento": g("forma_pagamento", j.get("condicao_pagamento", "")),
        "local_entrega": g("local_entrega", local_default),
        "finalidade": g("finalidade", fin_d),
        "justificativa": g("justificativa", jus_d),
        "consequencias": g("consequencias", con_d),
        "atendimento": g("atendimento", f"Os equipamentos da {forn_full} atendem as especificações técnicas e comerciais solicitadas." if forn_full else ""),
        "alcada": g("alcada", rotulo),
        # RESPONSÁVEIS: se o formulário MANDOU a chave (mesmo VAZIA), respeita —
        # o usuário escolheu uma alçada em que aquele responsável não entra. Antes
        # o `or default` repreenchia pela faixa do VALOR e a escolha de alçada não
        # surtia efeito nenhum (ex.: faixa "Até R$ 3.000" voltava com Diretor+CFO).
        "gerente": resp("gerente", nomes[0]),
        "gerente_geral": resp("gerente_geral", nomes[1]),
        "diretor": resp("diretor", nomes[2]),
        "cfo": resp("cfo", nomes[3]),
        "presidencia": resp("presidencia", nomes[4]),
        "conselho": resp("conselho", conselho_d),
        # quem de fato ASSINA (subconjunto dos responsáveis da alçada). Ausente =
        # todos assinam, que era o comportamento antes desta opção existir.
        "assinam": j.get("assinam"),
        # assinantes EXTRAS (papel + nome) vindos da agenda — além dos cargos fixos
        "extras": [x for x in (j.get("extras") or [])
                   if isinstance(x, dict) and str(x.get("nome", "")).strip()],
        "projeto": g("projeto", ""),      # campo próprio do CPM/CPS (não vem da AF)
        "capex": g("capex", 0), "cotacao": g("cotacao", ""),
        # CAPEX (investimento) ou OPEX (custeio): muda so o NOME da verba no
        # documento — a conta do saldo e a mesma. Aceita so os dois valores
        # previstos, para nao imprimir no documento o que vier do formulario.
        "tipo_verba": ("OPEX" if str(g("tipo_verba", "")).strip().upper() == "OPEX"
                       else "CAPEX"),
        "valor_reais": (float_para_brl(valor_reais_n) if valor_reais_n else ""),
        "relacao_cambial": relacao_cambial,
        # cenário + CAPEX/cliente ecoados p/ o front manter o estado
        "cenario": cenario, "cliente": j.get("cliente", ""), "clientes": clientes,
        "clientes_info": clientes_info, "pop_a": j.get("pop_a", ""),
        "pop_b": j.get("pop_b", ""), "banda": j.get("banda", ""), "servico": j.get("servico", ""),
        "ccs": j.get("ccs", ""), "os_num": j.get("os_num", ""), "psc": j.get("psc", ""),
        "produtos": j.get("produtos", ""),
        "consultados": j.get("consultados") or ([[forn_full, j.get("prazo_entrega", ""), valor]] if forn else []),
    }


def cpm_dados(j: dict) -> dict:
    """Devolve os campos do CPM já preenchidos (defaults da AF), p/ o front exibir
    e o usuário editar antes de gerar."""
    d = cpm_de_form(j or {})
    d["ok"] = True
    return d


def cpm_preview(j: dict) -> str:
    """Prévia HTML do CPM/CPS (mostra como está ficando)."""
    from core.html_render import montar_cpm_html
    return montar_cpm_html(cpm_de_form(j or {}))


def gerar_cpm(j: dict) -> dict:
    saida = j.get("saida", "")
    if not saida:
        return {"ok": False, "erro": "Caminho de saída não informado."}
    if not (j.get("numero") or "").strip():
        return {"ok": False, "erro": "Informe ao menos o número (para o CPM-…)."}
    cpm = cpm_de_form(j)
    # quem foi usado nesta CPM entra na agenda — é assim que a lista de nomes
    # cresce sozinha e a troca de setor depois vira só escolher da lista
    try:
        de.lembrar_pessoas({k: cpm.get(k) for k in
                            ("gerente", "gerente_geral", "diretor", "cfo", "presidencia")})
    except Exception as exc:                      # agenda é conveniência, não pode travar a geração
        LOG.warning("não consegui atualizar a agenda de assinaturas: %s", exc)
    formato = (j.get("formato") or "pdf").lower()
    estilo = (j.get("cpm_estilo") or "excel").lower()   # "excel" (oficial) | "html" (visual)
    # A CPM também sai com a PROPOSTA anexada ao final do PDF, igual à AF.
    anexar = bool(j.get("anexar_proposta", True))
    proposta_pdf = (j.get("caminho_pdf") or "") if anexar else ""
    avisos: list[str] = []
    info: dict = {}
    try:
        if formato == "excel":
            res = gerar_cpm_excel(saida, cpm)   # xlsx não anexa proposta (é planilha)
        elif estilo == "html":
            # "Visual": a prévia HTML do CPM vira o PDF (impressa pelo Edge). Se o
            # Edge falhar, cai no PDF oficial (template via Excel COM).
            from core.html_render import montar_cpm_html
            try:
                res = gerar_af_pdf_html(saida, montar_cpm_html(cpm), proposta_pdf=proposta_pdf)
            except Exception as exc:
                LOG.exception("CPM Visual (Edge) falhou — usando o PDF oficial")
                # o MOTIVO na tela: sem ele a troca de layout é invisível,
                # e não há o que corrigir na próxima vez
                avisos.append("O PDF Visual falhou (%s) — foi gerado o PDF oficial "
                              "(Excel) no lugar." % (exc or type(exc).__name__))
                res = gerar_cpm_pdf(saida, cpm, proposta_pdf=proposta_pdf, info=info)
        else:
            res = gerar_cpm_pdf(saida, cpm, proposta_pdf=proposta_pdf, info=info)
    except Exception as exc:
        LOG.exception("falha ao gerar o CPM")
        return {"ok": False, "erro": str(exc)}
    if info.get("motor") == "xlsx":
        avisos.append("O Excel não pôde exportar o PDF — foi entregue o .xlsx no lugar.")
    if info.get("tinha_proposta") and info.get("proposta_anexada") is False:
        avisos.append("Não consegui anexar a proposta ao PDF — o documento saiu sem o anexo.")
    ok = os.path.exists(res) and os.path.getsize(res) > 0
    return {"ok": ok, "saida": res, "pasta": os.path.dirname(res),
            "arquivo": os.path.basename(res), "formato": formato, "avisos": avisos,
            "erro": "" if ok else "O arquivo não foi criado."}


def _aprender_com_correcao(j: dict) -> list:
    """Se esta AF veio de uma proposta já lida, aprende com o que o usuário
    mudou. Nunca derruba a geração — aprender é bônus."""
    caminho = os.path.abspath(j.get("caminho_pdf") or "")
    try:
        from core.aprendizado import aprender, leitura

        # memória primeiro; se o app foi reaberto entre ler e gerar, o disco tem
        lida = _LIDAS.get(caminho) or leitura(caminho)
        if not lida or not lida.get("texto"):
            return []
        cnpj = j.get("cnpj") or (lida.get("extraido") or {}).get("cnpj", "")
        final = {"valor_total": j.get("valor_total", ""),
                 "numero_proposta": j.get("numero_proposta", ""),
                 "prazo_entrega": j.get("prazo_entrega", ""),
                 "garantia": j.get("garantia", ""),
                 "condicao_pagamento": j.get("condicao_pagamento", "")}
        return aprender(cnpj, lida["texto"], lida["extraido"], final)
    except Exception as exc:
        LOG.warning("não consegui aprender com a correção: %s", exc)
        return []


def gerar(j: dict) -> dict:
    # O front envia o formulário "achatado" (sem embrulho "proposta"); aceitamos
    # as duas formas para não gerar uma AF em branco.
    prop = _proposta_de(j.get("proposta") or j)
    saida = j.get("saida", "")
    if not saida:
        return {"ok": False, "erro": "Caminho de saída não informado."}
    args = (saida, prop, j.get("prefixo", "AF-E"), j.get("numero", ""),
            j.get("ano", ""), j.get("modificacao", ""),
            j.get("data_emissao", ""), j.get("revisao", "0"))
    fat = j.get("faturamentos") or j.get("faturamento") or None   # aceita lista ou único
    ent = j.get("entregas") or j.get("entrega") or None
    formato = (j.get("formato") or "pdf").lower()
    estilo = (j.get("pdf_estilo") or "excel").lower()   # "excel" (oficial) | "html" (visual)
    anexar = bool(j.get("anexar_proposta", True))
    avisos: list[str] = []
    info: dict = {}

    # APRENDE com o que o usuário corrigiu: compara o que foi lido da proposta
    # com o que ele deixou no formulário e guarda o rótulo do campo corrigido.
    aprendido = _aprender_com_correcao(j)
    if aprendido:
        avisos.append("Aprendi a ler deste fornecedor: " + ", ".join(aprendido)
                      + ". Na próxima proposta dele já vem preenchido.")
    try:
        if formato == "excel":
            res = gerar_af_excel(*args, faturamento=fat, entrega=ent)
        elif estilo == "html":
            # "Visual": a prévia HTML vira o PDF (impressa pelo Edge), com a proposta
            # anexada. Se o Edge falhar, cai no PDF oficial via Excel.
            proposta_pdf = (prop.caminho_pdf or "") if anexar else ""
            try:
                res = gerar_af_pdf_html(saida, montar_preview(j), proposta_pdf=proposta_pdf)
            except Exception as exc:
                LOG.exception("PDF Visual (Edge) falhou — usando o PDF oficial")
                # o MOTIVO na tela: sem ele a troca de layout é invisível,
                # e não há o que corrigir na próxima vez
                avisos.append("O PDF Visual falhou (%s) — foi gerado o PDF oficial "
                              "(Excel) no lugar." % (exc or type(exc).__name__))
                res = gerar_af_pdf(*args, faturamento=fat, entrega=ent,
                                   anexar_proposta=anexar, info=info)
        else:
            res = gerar_af_pdf(*args, faturamento=fat, entrega=ent,
                               anexar_proposta=anexar, info=info)
    except Exception as exc:
        LOG.exception("falha ao gerar a AF (%s)", formato)
        return {"ok": False, "erro": str(exc)}
    if info.get("motor") == "reportlab":
        avisos.append("O Excel não pôde exportar o PDF oficial — foi gerado um PDF "
                      "simplificado (reportlab).")
    if info.get("tinha_proposta") and info.get("proposta_anexada") is False:
        avisos.append("Não consegui anexar a proposta ao PDF — o documento saiu sem o anexo.")
    ok = os.path.exists(res) and os.path.getsize(res) > 0
    out = {"ok": ok, "saida": res, "pasta": os.path.dirname(res),
           "arquivo": os.path.basename(res), "formato": formato, "avisos": avisos,
           "erro": "" if ok else "O arquivo não foi criado."}
    if ok and formato != "excel":
        try:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(res)
            out["paginas"] = len(doc)
            doc.close()
        except Exception:
            pass
    return out

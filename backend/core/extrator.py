"""
extrator.py — extrai um DadosProposta de um PDF de proposta comercial.
Calibrado contra as propostas reais (FONNET/SEICOM/NEC/BINÁRIO/PADTEC/DATACOM):
nº da proposta por padrão de fornecedor, valor evitando taxas de câmbio,
fornecedor ignorando a Eletronet. OCR de reserva para propostas escaneadas.
"""

from __future__ import annotations

import os
import re

from .log import get_logger
from .modelos import DadosProposta, ItemAF, brl_para_float, float_para_brl

LOG = get_logger("extrator")

# pdfplumber, pypdfium2 e pytesseract são pesados (~0,5 s juntos) e só servem p/
# LER uma proposta — não p/ abrir o app. Importados SOB DEMANDA → startup rápido.
def _pdfplumber():
    import pdfplumber
    return pdfplumber


def _ocr_libs():
    """(pdfium, pytesseract) ou (None, None) se o OCR de reserva não estiver disponível."""
    try:
        import pypdfium2 as pdfium
        import pytesseract
        return pdfium, pytesseract
    except Exception:
        return None, None

# Docling (opcional, PREFERIDO quando disponível): entrega texto/markdown limpo
# com tabelas e faz OCR próprio (resolve fontes quebradas e PDFs escaneados).
# Desligar com a variável de ambiente GERADORAF_DOCLING=0.
_DOCLING_OFF = os.environ.get("GERADORAF_DOCLING", "1") == "0"
_DOCLING_CONV = None  # None=não testado, False=indisponível, objeto=ok


def _docling():
    global _DOCLING_CONV
    if _DOCLING_OFF:
        return None
    if _DOCLING_CONV is None:
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            # OCR desligado: evita baixar o modelo do RapidOCR (modelscope, bloqueado
            # pela inspeção SSL corporativa). Propostas escaneadas caem no Tesseract.
            opts = PdfPipelineOptions(do_ocr=False)
            _DOCLING_CONV = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
        except Exception:
            _DOCLING_CONV = False
    return _DOCLING_CONV or None


_DOCLING_CACHE: dict[str, str] = {}


def _ler_docling(caminho: str) -> str:
    """Markdown limpo do Docling (texto + tabelas), com cache por arquivo — uma
    conversão serve tanto para os CAMPOS quanto para os ITENS. O Docling
    reconstrói o texto de PDFs com fontes quebradas e estrutura as tabelas,
    melhorando bastante a assertividade frente ao texto nativo corrompido."""
    if caminho in _DOCLING_CACHE:
        return _DOCLING_CACHE[caminho]
    conv = _docling()
    md = ""
    if conv:
        try:
            md = conv.convert(caminho).document.export_to_markdown() or ""
        except Exception:
            md = ""
    _DOCLING_CACHE[caminho] = md
    return md


def _ler_docling_limitado(caminho: str, max_pag: int = 4) -> str:
    """Docling só nas PRIMEIRAS páginas (onde costuma estar a tabela de itens).
    Para PDFs grandes (ex.: NEC com itens em anexo), evita gastar dezenas de
    segundos convertendo o documento inteiro à toa."""
    conv = _docling()
    if not conv:
        return ""
    try:
        import pypdfium2 as pdfium
        src = pdfium.PdfDocument(caminho)
        n = len(src)
        if n <= max_pag:                    # doc pequeno → conversão normal (cacheada)
            src.close()
            return _ler_docling(caminho)
        import os
        import tempfile
        dst = pdfium.PdfDocument.new()
        dst.import_pages(src, list(range(max_pag)))
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.close()
        dst.save(tmp.name)
        dst.close()
        src.close()
        try:
            return conv.convert(tmp.name).document.export_to_markdown() or ""
        finally:
            try:
                os.remove(tmp.name)
            except Exception:
                pass
    except Exception:
        return ""


CNPJ_ELETRONET = "03052673000345"
# RAIZ do CNPJ da Eletronet — os 8 primeiros dígitos, que são os mesmos nas 26
# filiais; só o sufixo de estabelecimento muda.
#
# A comparação TEM de ser pela raiz. Comparando os 14 dígitos contra uma filial
# só, uma proposta que cita outra filial passava pelo filtro e o CNPJ da
# PRÓPRIA ELETRONET virava o do fornecedor na AF. Medido na ARTEMIS 207.2026,
# que lista quatro filiais: saía 03.052.673/0023-99 (Eletronet PA) como
# fornecedor.
#
# E o estrago não parava aí. Com o CNPJ preenchido, a trava que só aceita o
# catálogo "pelo nome" quando não há nome nem CNPJ desligava o reconhecimento
# — então o nome do fornecedor caiu no título da proposta e o CEP virou o da
# filial de Curitiba. Um CNPJ errado, quatro campos errados.
RAIZ_ELETRONET = "03052673"


def _eh_eletronet(cnpj: str) -> bool:
    """O documento é DA Eletronet: ela nunca é a fornecedora de si mesma."""
    return re.sub(r"\D", "", cnpj or "")[:8] == RAIZ_ELETRONET
_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
          "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
          "outubro": 10, "novembro": 11, "dezembro": 12}


# Glifo que a fonte do PDF não mapeia. O pdfplumber escreve o código cru.
_CID = re.compile(r"\(cid:\d+\)")


def _texto_parece_lixo(t: str) -> bool:
    # UM (cid:NN) NÃO CONDENA A FOLHA. Ele aparece sempre que o PDF usa um glifo
    # fora do mapa da fonte — o marcador de uma lista, um ™, um travessão. O
    # resto da folha continua perfeitamente legível.
    #
    # A regra antiga descartava a folha inteira no primeiro (cid: encontrado.
    # Numa proposta da ARTEMIS (207.2026), quatro marcadores de bullet — 36
    # caracteres — derrubaram uma folha de ~2.400 que trazia a data, o número da
    # proposta, a tabela de entregas e a composição financeira. O app leu só a
    # folha 2 e, sem enxergar a linha do desconto, adotou como total o valor
    # BRUTO: R$ 25.431,20 no lugar de R$ 22.379,46. A AF autorizaria pagar
    # R$ 3.051,74 a mais, e nenhum aviso disparava — a folha some calada.
    #
    # A folha só é lixo quando a fonte INTEIRA quebrou, e aí quase todo o
    # conteúdo vira (cid:NN). Por isso a medida é PROPORÇÃO, não presença.
    #
    # O teste de letras abaixo não substitui este: "(cid:127)" tem 3 letras em
    # 10 caracteres, então uma folha 100% quebrada fica em ~30% de letras e
    # passaria folgada pelo corte de 25%. É justamente o caso que este ramo pega.
    cids = _CID.findall(t)
    if cids and sum(len(c) for c in cids) / max(len(t), 1) > 0.20:
        return True
    letras = sum(c.isalpha() for c in t)
    return len(t) > 60 and letras / max(len(t), 1) < 0.25


class ExtratorProposta:
    """Extrai um DadosProposta a partir do caminho de um PDF de proposta."""

    # ---- leitura do texto p/ os CAMPOS: pdfplumber (inline, calibrado) > OCR.
    # A Docling NÃO entra aqui: o markdown dela separa rótulo/valor em linhas
    # diferentes e quebraria os regex de campo. Ela é usada só p/ ITENS (tabelas).
    def _ler_texto(self, caminho: str) -> tuple[str, str]:
        # PASSE ÚNICO: texto E tabelas no MESMO open (o 2º open custa ~100 ms de
        # re-parse; extrair as tabelas com o PDF já aberto custa ~6 ms). As tabelas
        # ficam em cache p/ o _itens_tabelas reaproveitar sem reabrir o arquivo.
        with _pdfplumber().open(caminho) as pdf:
            pgs = pdf.pages
            paginas = [(p.extract_text() or "") for p in pgs]
            # O (cid:NN) que sobrou numa folha aproveitada é ruído visual: sem
            # tirar, a observação da ARTEMIS entraria na AF como
            # "(cid:127) Os prazos de transporte...". Vira espaço, não some a
            # linha — o glifo era um marcador, e a quebra de linha já o supre.
            limpas = [_CID.sub(" ", t) for t in paginas
                      if t.strip() and not _texto_parece_lixo(t)]
            # só vale extrair tabelas se o texto nativo é bom (senão vai p/ docling/ocr)
            if limpas:
                self._tabelas_cache = (caminho, [p.extract_tables() or [] for p in pgs])
                # PALAVRAS E RÉGUAS no mesmo passe. Os leitores por posição
                # (itens e condições do cabeçalho) abriam o arquivo de novo,
                # cada um — três opens do mesmo PDF, e o open é 31% do tempo
                # de uma extração. Aqui sai de graça: o documento já está
                # aberto e decodificado.
                self._folhas_cache = (caminho, [
                    {"palavras": p.extract_words(), "regras": list(p.lines)}
                    for p in pgs])
        if limpas:
            return "\n".join(limpas), "pdf"
        # Texto nativo vazio/corrompido (fontes quebradas): o Docling costuma
        # reconstruir melhor — e mais rápido — que o OCR. Só roda neste caminho ruim.
        LOG.info("texto nativo ruim em %s — tentando Docling", os.path.basename(caminho))
        md = _ler_docling(caminho)
        if md.strip() and not _texto_parece_lixo(md):
            return md, "docling"
        LOG.info("Docling não resolveu — tentando OCR (Tesseract)")
        texto = self._ocr(caminho)
        if texto.strip():
            return texto, "ocr"
        LOG.warning("nenhum método extraiu texto legível de %s", os.path.basename(caminho))
        return "\n".join(paginas), "pdf"

    def _ocr(self, caminho: str, max_paginas: int = 3) -> str:
        pdfium, pytess = _ocr_libs()
        if pdfium is None:
            return ""
        partes = []
        pdf = pdfium.PdfDocument(caminho)
        try:
            for i in range(min(len(pdf), max_paginas)):
                img = pdf[i].render(scale=300 / 72).to_pil()
                partes.append(pytess.image_to_string(img, lang="por+eng", config="--psm 4 --oem 3"))
        finally:
            pdf.close()
        return "\n".join(partes)

    # ---- utilidades -------------------------------------------------------
    @staticmethod
    def _formatar_cnpj(cnpj: str) -> str:
        d = re.sub(r"\D", "", cnpj)
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else cnpj.strip()

    @staticmethod
    def _primeiro(t: str, padroes: list[str], flags=re.I) -> str:
        for p in padroes:
            m = re.search(p, t, flags)
            if m:
                return m.group(1).strip()
        return ""

    # ---- campos -----------------------------------------------------------
    def _data(self, t: str) -> str:
        m = re.search(r"(\d{1,2})\s+de\s+([A-Za-zçÇ]+)\s+de\s+(\d{4})", t, re.I)
        if m and m.group(2).lower() in _MESES:
            return f"{int(m.group(1)):02d}/{_MESES[m.group(2).lower()]:02d}/{m.group(3)}"
        return self._primeiro(t, [r"Data[:\s]*(\d{2}/\d{2}/\d{4})", r"(\d{2}/\d{2}/\d{4})"])

    def _numero_proposta(self, t: str) -> str:
        num = self._primeiro(t, [
            # "Nossa referência: PRPT 5777_26B" → captura o código inteiro, inclusive
            # o trecho após o espaço (tokens que tenham dígito), sem cruzar a linha.
            r"Nossa refer[êe]ncia:\s*([A-Z0-9][\w.\-/]*(?:[ \t]+\w*\d[\w.\-/]*)*)",
            r"Proposta\s*N[ºo°]\s*:?\s*([A-Z]{2,}-[\d.\-/]+)",       # FONNET: FN-20260108-79764
            r"N[úu]mero da Proposta\s*:?\s*([0-9][\w.\-/]+)",        # NEC: 0100103488
            r"Proposta\s+Comercial\s+N[ºo°]\s*:?\s*([\w.\-/]+)",     # SEICOM: 000.071
            r"Proposta\s+Nro\.?\s*:?\s*([\w.\-/]+)",                 # BINÁRIO: 46609B
            r"Proposta\s*(\d{4}-\d{3,4}\s*[vV]\s*\d*)",              # PADTEC: 2026-0607v2
            r"(PRPT\s*\d+[\w]*)",                                    # DATACOM
            # "N.º: BRU-OR-0172/25" no cabeçalho da carta de apresentação
            r"N\.?[ºo°]\s*:\s*([A-Z]{2,}[\w.\-/]*\d[\w.\-/]*)",
            r"Proposta[:\s]+([A-Z0-9][\w.\-/]{2,22})",              # genérico (último)
        ])
        num = re.sub(r"\s{2,}", " ", num).strip(" .:-")
        # Número de proposta SEM dígito nenhum não é número: o padrão genérico
        # lia "REF.: Proposta Comercial" e devolvia "Comercial".
        return num if re.search(r"\d", num) else ""

    # Os rótulos com que um fornecedor ANUNCIA o total. Valor achado por um
    # destes é palavra dele; o resto é dedução nossa, e vale menos.
    # UMA lista só. Antes havia duas cópias — esta e outra dentro de
    # `_valor_total` — e elas saíram de sincronia: o rótulo novo da ARTEMIS foi
    # acrescentado aqui e não lá, e como quem preenche o campo é o
    # `_valor_total`, a correção não teve efeito nenhum. Duas listas que
    # precisam ser iguais acabam diferentes; agora a de baixo é esta mais um
    # padrão, escrito uma vez só.
    _ROTULOS_TOTAL_BASE = [
        r"Valor Total da Solu[çc][ãa]o[:\d \w]*?R?\$?\s*([\d.]+,\d{2})",
        r"Total com impostos[:\s]*R?\$?\s*([\d.]+,\d{2})",
        r"Valor Total\s*:?\s*R?\$?\s*([\d.]+,\d{2})",
        r"Valor Global[:\s]*R?\$?\s*([\d.]+,\d{2})",
        r"Total\s*\+\s*Despesas?\s*:?\s*R?\$?\s*([\d.]+,\d{2})",   # SEICOM
        r"R\$\s*Total\s*:?\s*([\d.]+,\d{2})",                      # BINÁRIO
        r"Total\s+Geral\s*:?\s*R?\$?\s*([\d.]+,\d{2})",
        # "VALOR FINAL LÍQUIDO DA PROPOSTA R$ 22.379,46" (ARTEMIS). É o total
        # DEPOIS do desconto — o que a Eletronet paga. Sem este rótulo o app
        # caía no último recurso e adotava o frete.
        r"VALOR\s+FINAL\s+L[ÍI]QUIDO[^\n]*?R?\$?\s*([\d.]+,\d{2})",
    ]
    # A linha que é SÓ "Total R$ 44.829,12" (Precision) também é anúncio, mas
    # vale só para o `_valor_total_rotulado` — é ela que distingue "anunciado"
    # de "deduzido" na conferência da aritmética. Ancorada na linha inteira de
    # propósito: solta, a palavra casaria com "Comprimento total da fibra" e
    # traria o número de outra frase.
    _ROTULOS_TOTAL = _ROTULOS_TOTAL_BASE + [
        r"(?m)^[ \t]*Total[ \t]*:?[ \t]*R\$[ \t]*([\d.]+,\d{2})[ \t]*$",
    ]

    def _valor_total_rotulado(self, t: str) -> str:
        """Só o total que o fornecedor ANUNCIA com todas as letras."""
        return self._primeiro(t, self._ROTULOS_TOTAL)

    def _valor_total(self, t: str) -> str:
        val = self._primeiro(t, self._ROTULOS_TOTAL_BASE)
        if val:
            return val

        def _f(s):
            return float(s.replace(".", "").replace(",", "."))

        em_total = []
        for ln in t.splitlines():
            baixo = ln.lower()
            if "total" not in baixo:
                continue
            # A PALAVRA "total" NÃO BASTA. "Frete Rodoviário TOTAL Estimado
            # (Fracionado) R$ 6.300,00" é uma PARCELA da proposta, e "Prazo
            # Total" nem é dinheiro. Na ARTEMIS 207.2026 o frete de 6.300,00
            # virava o total de uma proposta de 22.379,46 — o app autorizaria
            # pagar 28% do devido.
            if re.search(r"\b(frete|transporte|transit|prazo|entrega|desconto)\b", baixo):
                continue
            em_total += re.findall(r"(\d{1,3}(?:\.\d{3})*,\d{2})", ln)
        if em_total:
            return max(em_total, key=_f)
        # TARIFA NÃO É TOTAL. "cobrança de R$ 4.378,86 POR DIA" (Padtec) é preço
        # de uma eventualidade, não o valor da proposta — e como era o maior
        # valor com "R$" na folha, virava o total da AF.
        valores = [m.group(1) for m in re.finditer(r"R\$\s*([\d.]+,\d{2})", t)
                   if _f(m.group(1)) >= 100
                   and not re.match(r"\s*(?:por|/|a\s+cada|ao)\s+"
                                    r"(?:dia|hora|m[êe]s|km|quil[ôo]metro|ponto|"
                                    r"evento|trecho|visita|unidade)",
                                    t[m.end():m.end() + 24], re.I)]
        return max(valores, key=_f) if valores else ""

    # A razão social ACABA na forma jurídica. Sem isso, um nome que aparece no
    # meio de uma frase ("A ARTEMIS ... LTDA. submete à apreciação da ...") vem
    # com o resto da frase grudado.
    _FORMA_JURIDICA = re.compile(
        r"\b(S[/.]?A|S\.A\.|LTDA|EIRELI|EPP|ME)\b\.?", re.I)
    _ARTIGO = re.compile(r"^(?:A|O|AS|OS)\s+(?=[A-ZÀ-Ÿ])")

    @classmethod
    def _ate_a_forma_juridica(cls, nome: str) -> str:
        """"A ARTEMIS RACKS & SOLUTIONS LTDA. submete..." -> "ARTEMIS RACKS & SOLUTIONS LTDA." """
        nome = re.sub(r"\s{2,}", " ", (nome or "").strip())
        m = cls._FORMA_JURIDICA.search(nome)
        if m:
            nome = nome[:m.end()].strip()
        return cls._ARTIGO.sub("", nome).strip(" .,:;-")

    def _fornecedor(self, t: str) -> str:
        for m in re.finditer(r"Raz[ãa]o Social[:\s]*([^\n]+)", t, re.I):
            nome = re.split(r"\s+CNPJ", m.group(1), flags=re.I)[0].strip(" .:-")
            if nome and "eletronet" not in nome.lower():
                return nome
        # \b ANTES E DEPOIS da forma jurídica. Sem as fronteiras, e com re.I,
        # "SA" casava DENTRO de palavras comuns: em "PROPOSTA COMERCIAL Nº
        # 207.2026 - REVISADA" o trecho "REVI|SA|DA" satisfazia o padrão e a
        # LINHA DE TÍTULO virava o nome do fornecedor na AF. Como o nome saía
        # preenchido (com lixo), a trava que só consulta o catálogo quando não
        # há nome nem CNPJ desligava o reconhecimento da ARTEMIS.
        for m in re.finditer(r"^([A-ZÀ-Ÿ][\w .,&/-]+?\b(?:S[/.]?A|LTDA|S\.A\.|EIRELI)\b[\w .]*)$",
                             t, re.I | re.M):
            nome = m.group(1).strip()
            if "eletronet" in nome.lower():
                antes = re.split(r"\beletronet\b", nome, flags=re.I)[0].strip(" -.,")
                antes = self._ate_a_forma_juridica(antes)
                if len(antes) >= 4:
                    return antes
                continue
            # Razão social QUEBRADA em 2 linhas (ex.: "SKYLANE OPTICS DO BRASIL
            # SERVICOS DE" + "PESQUISA LTDA"): o regex pega só a linha de baixo.
            # Se o nome tem poucas palavras antes do sufixo E a linha anterior é um
            # fragmento em CAIXA ALTA terminando em preposição, junta as duas.
            palavras = re.sub(r"\b(S[/.]?A|LTDA|S\.A\.|EIRELI)\b.*$", "", nome, flags=re.I).split()
            if len(palavras) <= 2:
                fim_prev = t.rfind("\n", 0, m.start())
                prev = t[t.rfind("\n", 0, fim_prev) + 1: fim_prev].strip() if fim_prev > 0 else ""
                if (prev and prev.isupper() and not re.search(r"[\d:]|eletronet", prev, re.I)
                        and not re.search(r"\b(S[/.]?A|LTDA|EIRELI)\b", prev, re.I)
                        and re.search(r"\b(DE|DO|DA|DOS|DAS|E)$", prev, re.I)):
                    return f"{prev} {nome}".strip()
            return self._ate_a_forma_juridica(nome) or nome
        return ""

    def _cnpj(self, t: str) -> str:
        # Pega TODOS os CNPJs formatados, tira o da Eletronet e prefere a MATRIZ
        # (/0001) — cobre proposta que escreve "CNPJ de faturamento 49.../0001-65".
        achados = re.findall(r"\b(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})\b", t)
        nao_el = [c for c in achados if not _eh_eletronet(c)]
        if nao_el:
            matriz = next((c for c in nao_el if re.sub(r"\D", "", c)[8:12] == "0001"), None)
            return self._formatar_cnpj(matriz or nao_el[0])
        for cnpj in re.findall(r"CNPJ[^\d]{0,20}([\d./-]{14,20})", t):   # reserva: sem pontuação
            if not _eh_eletronet(cnpj):
                return self._formatar_cnpj(cnpj)
        return ""

    def _cep(self, t: str) -> str:
        # CEP de verdade tem hífen (XXXXX-XXX). Exigir o hífen evita pegar
        # fragmentos de CNPJ ("03549807") ou de nº de proposta/data ("20260616").
        # E o contexto antes não pode ser de TELEFONE — "(11) 56429-325" tem o
        # mesmo formato de um CEP.
        def _ok(m) -> bool:
            ctx = t[max(0, m.start() - 16):m.start()].lower()
            if any(p in ctx for p in ("tel", "fone", "fax", ")")):
                return False
            return re.sub(r"\D", "", m.group(1)) != "04719002"

        for m in re.finditer(r"CEP[:\s]*(\d{2}\.?\d{3}-\d{3})", t, re.I):   # 1º: após o rótulo
            if _ok(m):
                return m.group(1)
        for m in re.finditer(r"(?<![\d/.\-])(\d{2}\.?\d{3}-\d{3})(?![\d\-])", t):   # 2º: formato c/ hífen
            if _ok(m):
                return m.group(1)
        for m in re.finditer(r"CEP[:\s]+(\d{8})(?!\d)", t, re.I):   # 3º: rótulo + 8 dígitos
            if m.group(1) != "04719002":
                return f"{m.group(1)[:5]}-{m.group(1)[5:]}"
        return ""

    def _insc_est(self, t: str) -> str:
        m = re.search(r"Inscri[çc][ãa]o Estadual[:\s]*([\d.\-/]{6,20})", t, re.I)
        return m.group(1).strip() if m else ""

    def _endereco(self, t: str) -> str:
        # "Endereço DE ENTREGA" é a coluna dos destinos num quadro por
        # localidade, não o endereço do fornecedor. Sem esta ressalva, o
        # cabeçalho "Localidade / Endereço de Entrega | Valor Produto | Frete"
        # virava o endereço da empresa.
        for m in re.finditer(r"Endere[çc]o(?:\s+Completo)?(?!\s+de\s+Entrega)\s*:?\s*([^\n]+)",
                             t, re.I):
            linha = re.split(r"\s+CNPJ", m.group(1), flags=re.I)[0].strip()
            linha = linha.strip(" -–—,;")   # traco solto antes do CEP
            low = linha.lower()
            # Endereço tem NÚMERO (o do imóvel, o do km ou o CEP). Exigir um
            # dígito é o que separa um endereço de um pedaço de cabeçalho —
            # e sair vazio, para alguém preencher, é melhor que sair errado.
            if not re.search(r"\d", linha):
                continue
            if "verbo divino" not in low and "eletronet" not in low and "egídio" not in low:
                return linha
        return ""

    # ---- proposta organizada em SECOES numeradas --------------------------
    # Muitas propostas vem assim, com titulos numerados e o conteudo embaixo:
    #
    #     3.3 CONDICOES DE PAGAMENTO
    #     > Pagamentos 30 (trinta) dias apos o envio da nota fiscal...
    #     3.5 VALOR
    #     > R$ 13.934,70 (treze mil novecentos e trinta e quatro reais...)
    #
    # As regras campo-a-campo deste arquivo leem UMA linha ("Garantia: 12
    # meses"). Aqui o valor esta na linha SEGUINTE ao titulo e as vezes ocupa
    # varias — por isso garantia e condicao de pagamento saiam vazias mesmo
    # estando escritas com todas as letras na proposta.
    #
    # O sumario e descartado: la os titulos vem seguidos de pontilhado e do
    # numero da pagina, e o "conteudo" seria a lista de outros titulos.
    _TITULO_SECAO = re.compile(
        r"^[ \t]*(\d+(?:\.\d+)*)[.)]?[ \t]+"
        r"([A-ZÀ-Ú][A-ZÀ-Ú0-9 ,;/&()'\-]{3,70}?)[ \t]*$", re.M)

    def _secoes(self, t: str) -> dict:
        """{titulo em MAIUSCULAS: conteudo ate o proximo titulo}."""
        achados = [m for m in self._TITULO_SECAO.finditer(t) if "...." not in m.group(0)]
        out = {}
        for i, m in enumerate(achados):
            fim = achados[i + 1].start() if i + 1 < len(achados) else len(t)
            corpo = t[m.end():fim]
            titulo = re.sub(r"\s{2,}", " ", m.group(2)).strip()
            # o sumario repete os titulos; fica o ULTIMO, que e o do corpo
            out[titulo.upper()] = corpo
        return out

    @staticmethod
    def _limpar_secao(corpo: str, max_linhas: int = 6) -> str:
        """Tira marcadores, rodape e numeracao; junta as linhas numa frase."""
        linhas = []
        for l in corpo.splitlines():
            l = l.strip().lstrip("\u27a2\u2022\u25aa\u25cf\u2192-\u2013 ").strip()
            l = re.sub(r"^\d+[.)]\s*", "", l)          # "1. Fornecimento de..."
            if not l:
                continue
            # rodape que se repete em toda folha da proposta
            if re.search(r"www\.|@|Cep:|CEP:\s*\d|^F:\s*\(|Fax|Fone|^Av\.", l, re.I):
                continue
            linhas.append(l)
            if len(linhas) >= max_linhas:
                break
        return re.sub(r"\s{2,}", " ", " ".join(linhas)).strip(" .;")

    def _da_secao(self, t: str, *nomes: str) -> str:
        """Conteudo da primeira secao cujo titulo contenha um dos nomes."""
        secoes = self._secoes(t)
        for nome in nomes:
            for titulo, corpo in secoes.items():
                if nome in titulo:
                    limpo = self._limpar_secao(corpo)
                    if limpo:
                        return limpo
        return ""

    # "GARANTIA: De acordo com a linha de produto." — rótulo no começo da
    # linha é o fornecedor declarando o campo, e ganha de qualquer frase solta
    # que contenha a palavra. Sem isto, na ALG vencia o rabo de "...o
    # recebimento de mercadorias com embalagens violadas implica na perda de
    # garantia do produto."
    _GARANTIA_ROTULO = re.compile(
        r"(?m)^[ \t]*GARANTIA[ \t]*:[ \t]*([^\n]{3,160})")

    def _garantia(self, t: str) -> str:
        m = self._GARANTIA_ROTULO.search(t or "")
        if m:
            return re.sub(r"\s{2,}", " ", m.group(1)).strip(" .;") + "."
        m = re.search(r"garantia[^\n]{0,60}?\b[ée]\s+de\s+([^\n.;]+)", t, re.I)
        if m:
            return re.sub(r"\s{2,}", " ", m.group(1)).strip()
        m = re.search(r"[Gg]arantia\D{0,40}(\d+\s*(?:anos?|meses|m[êe]s))", t)
        if m:
            return m.group(1).strip()
        de_secao = self._da_secao(t, "GARANTIA")
        if de_secao:
            return de_secao
        # GARANTIA EM CLÁUSULA, sem número: "A garantia para o objeto dessa
        # oferta está sujeita ao prazo previsto no Código Civil, a contar da
        # entrega do bem." As regras acima procuram um número e devolvem vazio —
        # e campo vazio faz parecer que a proposta não fala de garantia.
        # A frase QUEBRA em duas linhas na folha, então a busca atravessa o
        # \n; e a primeira ocorrência da palavra costuma ser o SUMÁRIO
        # ("5 Garantia ......... 7"), que é descartado pelos pontinhos. Por
        # isso percorre todas as ocorrências em vez de parar na primeira.
        for m in re.finditer(r"\bA?\s*garantia\b[^\n]{0,200}?(?:\n[^\n]{0,120}?)?\.", t, re.I):
            frase = re.sub(r"\s+", " ", m.group(0)).strip()
            # URL cortada no ponto de "www." não é cláusula de garantia: quando
            # há link, o que vale é a linha inteira.
            if "http" in frase.lower():
                linha = t[m.start(): t.find("\n", m.start())]
                frase = re.sub(r"\s+", " ", linha).strip()
            if re.search(r"\.{4,}", frase):          # linha de sumário
                continue
            if not re.match(r"^A?\s*garantia\b", frase, re.I):
                continue
            # O TÍTULO da seção fica colado na frase ("Garantia A garantia para
            # o objeto..."), porque na folha ele é a linha de cima. Tira a
            # repetição, mantendo a frase.
            frase = re.sub(r"^garantia\s+(?=[AaOo]\s+garantia\b)", "", frase, flags=re.I)
            return frase
        return ""

    # "Condição" (singular) NÃO casava: o padrão antigo era `Condi[çc][õo]es?`,
    # que cobre "Condições"/"Condicoes" mas exige um "o"/"õ" onde o singular tem
    # "ão". A DATACOM escreve "Condição de pagamento: 30/60/90 dias." — e a forma
    # de pagamento saía vazia numa proposta que a trazia escrita com todas as
    # letras. Agora as quatro grafias entram, e "Forma de pagamento" também.
    _PAGTO_LINHA = re.compile(
        r"(?:condi[çc](?:[õo]es|[ãa]o)|forma)\s+de\s+"
        r"pag(?:amen)?to\.*\s*:\s*([^\n]+)", re.I)
    # Código interno do fornecedor colado na frente da condição: a SEICOM escreve
    # "503 - 30 DDL", onde 503 é o código dela para o prazo. No documento da
    # Eletronet esse número não quer dizer nada.
    _COD_PAGTO = re.compile(r"^\s*\d{1,4}\s*-\s*(?=\S)")
    # Outra coluna começando na mesma linha (a folha tem DUAS colunas lado a
    # lado): "30 DDL TRANSPORTADORA........: 000 - ..." — corta no rótulo seguinte.
    _OUTRA_COLUNA = re.compile(
        r"\s{2,}(?=[A-ZÀ-Ú][A-ZÀ-Ú \t]{4,}\.*\s*:)|\s+(?=[A-ZÀ-Ú]{5,}\.{3,})"
        # o marcador também separa dois campos na mesma linha:
        # "Forma de Pagamento: 21 DDL • Validade da Proposta: 01 (um) dia."
        r"|\s*[•◦▪]\s*")
    # DDL = "dias data líquida": o pagamento vence N dias depois do faturamento.
    # A sigla sozinha não diz isso a quem lê a AF, e o usuário pediu por extenso.
    _DDL = re.compile(r"^(\d{1,3})\s*(?:dd?l|ddl|d\.d\.l\.?)\b\.?$", re.I)
    # "Condição de pagamento: 90 dias." — só o número, sem dizer em quantas
    # parcelas nem a contar de quê. Vira a frase por extenso.
    _PRAZO_SO = re.compile(r"^(?:at[ée]\s+)?(\d{1,3})\s*dias?\.?$", re.I)

    # Marcadores usados nas listas das propostas.
    _MARCA_LISTA = re.compile(r"^\s*[•◦▪·\-–—o]\s+")
    # Onde a seção de especificação acaba: outra seção (numerada ou não) ou uma
    # linha de totais.
    _FIM_SECAO = re.compile(
        r"^\s*(?:\d+\.\s+[A-ZÀ-Ú]|[A-ZÀ-Ú][A-ZÀ-Ú \t&/]{8,}$|TOTAL\b|INVESTIMENTO\b)")
    _TIT_ESPEC = re.compile(
        r"^\s*ESPECIFICA[ÇC][ÃA]O\s+T[ÉE]CNICA[^\n]*$", re.I | re.M)

    def _especificacao_tecnica(self, t: str) -> list[str]:
        """O conteúdo da ESPECIFICAÇÃO TÉCNICA, um item por marcador.

        Cada marcador pode ocupar várias linhas na folha (o texto quebra na
        margem) — a continuação é remontada no marcador a que pertence, senão a
        observação sai cortada no meio de uma frase.
        """
        m = self._TIT_ESPEC.search(t or "")
        if not m:
            return []
        linhas = t[m.end():].splitlines()
        saida: list[str] = []
        for ln in linhas:
            if not ln.strip():
                continue
            if self._FIM_SECAO.match(ln):
                break
            if self._MARCA_LISTA.match(ln):
                saida.append(self._MARCA_LISTA.sub("", ln).strip())
            elif saida:
                saida[-1] = (saida[-1] + " " + ln.strip()).strip()   # continuação
            else:
                saida.append(ln.strip())                            # linha de abertura
        # junta o que quebrou e devolve sem duplicatas, na ordem
        vistos, out = set(), []
        for x in (re.sub(r"\s{2,}", " ", v).strip(" .;") for v in saida):
            if x and x not in vistos:
                vistos.add(x)
                out.append(x)
        return out

    _TIT_CAMBIO = re.compile(r"^[ \t]*(?:\d+(?:\.\d+)*[.)]?[ \t]+)?"
                             r"Varia[çc][ãa]o\s+Cambial[ \t]*$", re.I | re.M)

    def _variacao_cambial(self, t: str) -> str:
        """A cláusula de variação cambial, num parágrafo só.

        Entra nas observações toda vez que existe: a taxa de referência e a
        banda mudam a cada proposta, e é o que decide o valor faturado. Deixar
        isso só no PDF anexo é perder a informação que move o preço.
        """
        m = self._TIT_CAMBIO.search(t or "")
        if not m:
            return ""
        corpo = []
        for ln in t[m.end():].splitlines():
            if not ln.strip():
                if corpo:
                    continue
                continue
            if self._FIM_SECAO.match(ln) or self._TIT_ESPEC.match(ln):
                break
            corpo.append(self._MARCA_LISTA.sub("", ln).strip())
            if len(corpo) >= 18:                 # cláusula longa: corta com bom senso
                break
        texto = re.sub(r"\s{2,}", " ", " ".join(corpo)).strip(" .;")
        if len(texto) < 30:                      # só o título, sem corpo
            return ""
        return "Variação cambial: " + texto

    # Sem rótulo antes: a NEC escreve a condição como FRASE, sob o título
    # "2.4 Forma e Condições de Faturamento e Pagamento" — que não casa com
    # "Condição de pagamento:" nem vira seção reconhecível. A frase, porém, diz
    # tudo: "será pago no prazo de 90 (noventa) dias da emissão da respectiva
    # nota fiscal".
    _PAGTO_FRASE = re.compile(
        r"ser[áa]\s+pago\s+(?:no\s+prazo\s+de\s+|em\s+)(\d{1,3})\s*"
        r"(?:\([^)]*\)\s*)?dias?\s+(?:corridos\s+)?"
        r"d[aoe]s?\s+(emiss[ãa]o|faturamento|entrega)", re.I)
    _ONDE_CONTA = {"emissao": "a emissão da nota fiscal",
                   "faturamento": "o faturamento",
                   "entrega": "a entrega"}

    def _pagamento(self, t: str) -> str:
        """Como se paga. Uma linha ("Pagamento: 30 DDL") ou a secao inteira."""
        m = self._PAGTO_LINHA.search(t)
        if m:
            bruto = self._OUTRA_COLUNA.split(m.group(1))[0]
            bruto = re.sub(r"\s{2,}", " ", bruto).strip(" .;")
            bruto = self._COD_PAGTO.sub("", bruto).strip()
            return self._pagamento_por_extenso(bruto)
        m = self._PAGTO_FRASE.search(t)
        if m:
            n = int(m.group(1))
            onde = self._ONDE_CONTA[self._sem_acento(m.group(2))]
            return ("O pagamento deve ser efetuado %d %s após %s"
                    % (n, "dia" if n == 1 else "dias", onde))
        return self._da_secao(t, "CONDIÇÕES DE PAGAMENTO", "CONDIÇÃO DE PAGAMENTO",
                             "CONDICOES DE PAGAMENTO", "FORMA DE PAGAMENTO", "PAGAMENTO")

    @classmethod
    def _pagamento_por_extenso(cls, v: str) -> str:
        """"30 DDL" vira a frase inteira; o resto passa como está.

        A sigla é do dia a dia de quem compra, não de quem assina a AF — e a AF
        é um documento que sai da empresa. Pedido do usuário.
        """
        v = (v or "").strip()
        m = cls._DDL.match(v)
        if m:
            n = int(m.group(1))
            return ("O pagamento deve ser efetuado %d %s após o faturamento"
                    % (n, "dia" if n == 1 else "dias"))
        # Um número sozinho ("90 dias") é pagamento em UMA parcela com aquele
        # prazo de carência. Parcelado ("30/60/90", "5 PARC.") não cai aqui —
        # tem barra ou a palavra parcela, e passa como está.
        m = cls._PRAZO_SO.match(v)
        if m:
            n = int(m.group(1))
            return ("O pagamento será realizado em 1x com até %d %s de carência"
                    % (n, "dia" if n == 1 else "dias"))
        return v

    # "item 1 - ... item 2 - ..." dentro do bloco de prazo: cada trecho é o
    # prazo de UM item, e não uma frase sobre o pedido inteiro.
    _PRAZO_ITEM = re.compile(r"\bitem\s+0*(\d{1,3})\s*[-–:]\s*", re.I)
    _SO_PRONTA = re.compile(r"^(?:tenho\s+)?(?:todas?\s+as?\s+unidades?\s+)?"
                            r"a?\s*pronta[\s-]*entrega\.?$", re.I)

    def _prazo_por_item(self, t: str) -> dict:
        """{nº do item: prazo} quando o bloco de prazo vem quebrado por item.

        Devolve vazio quando a proposta fala do pedido como um todo — que é o
        caso comum.
        """
        # O bloco é delimitado pelos PRÓPRIOS marcadores, não pelo rótulo: numa
        # folha de duas colunas o rótulo fica centralizado na vertical e cai no
        # meio da lista, deixando o item 1 para trás dele.
        marcas = list(self._PRAZO_ITEM.finditer(t or ""))
        if len(marcas) < 2:
            return {}
        fim = re.search(r"\n\s*(?:Garantia|Observa[çc][õo]es|Validade|Condi[çc])\b",
                        t[marcas[-1].end():], re.I)
        bloco = t[marcas[0].start(): marcas[-1].end() + (fim.start() if fim else 400)]
        m = True
        partes = self._PRAZO_ITEM.split(bloco)
        if len(partes) < 3:                       # não veio quebrado por item
            return {}
        fora = {}
        for i in range(1, len(partes) - 1, 2):
            n = int(partes[i])
            txt = re.sub(r"\s+", " ", partes[i + 1]).strip(" .;,")
            # tira o código do produto repetido no começo do trecho
            txt = re.sub(r"^[A-Z0-9][A-Z0-9\-/() x]{4,}\s*[-–]\s*", "", txt).strip()
            # o RÓTULO da folha cai no meio da lista (coluna centralizada na
            # vertical) e fica pendurado no fim do trecho do item anterior
            txt = re.sub(r"\s*Prazo\s+de\s+Entrega\s*:?\s*$", "", txt, flags=re.I).strip(" .;,")
            if txt:
                fora[n] = txt
        return fora

    def _prazo(self, t: str) -> str:
        # PRONTA-ENTREGA só vale para o documento inteiro se valer para TODOS os
        # itens. Na FONNET, 3 de 10 unidades do item 1 estão prontas e as outras
        # chegam dia 22/09 — dizer "Pronta-entrega" na AF é assumir um
        # compromisso que o fornecedor não deu.
        por_item = self._prazo_por_item(t)
        if por_item:
            if all(self._SO_PRONTA.match(v) for v in por_item.values()):
                return "Pronta-entrega"
            return "; ".join("item %d: %s" % (n, por_item[n]) for n in sorted(por_item))
        # "pronta entrega" / "entrega imediata" (fornecedor já tem o material em estoque)
        if re.search(r"pronta[\s-]*entrega|entrega\s+imediata", t, re.IGNORECASE):
            return "Pronta-entrega"
        m = re.search(r"[Pp]razo de [Ee]ntrega[^\n]{0,30}?(\d+\s*(?:dias|dia|semanas|meses|m[eê]s))", t)
        if m:
            return m.group(1).strip()
        # O prazo pode vir numa FRASE, e não logo depois do rótulo: "O prazo
        # estimado de entrega é de até 90 dias após a assinatura do documento
        # de contratação". Aqui o número está uma oração adiante.
        m = re.search(r"prazo[^\n.]{0,60}?entrega[^\n.]{0,40}?\b(?:at[ée]\s+)?"
                      r"(\d{1,4}\s*(?:dias?|semanas?|meses|m[eê]s|anos?))"
                      r"([^\n.]{0,60})", t, re.I)
        if m:
            # guarda o "após a assinatura..." junto: um prazo sem o marco a
            # partir do qual ele conta não diz quando a entrega vence
            rabo = re.sub(r"\s{2,}", " ", m.group(2)).strip(" ,;")
            if re.match(r"^(?:[úu]teis|corridos)?\s*ap[óo]s\b|^(?:[úu]teis|corridos)\b", rabo, re.I):
                # o marco fecha na primeira alternativa e nunca no meio de uma
                # palavra: "...ou recebiment" não é marco de prazo nenhum
                rabo = re.split(r"\s+ou\s+", rabo, 1)[0].strip(" ,;")
                if len(rabo) > 48:
                    rabo = rabo[:48].rsplit(" ", 1)[0]
                # conjunção pendurada no fim (a alternativa ficou na linha
                # seguinte e o corte por " ou " não chegou a acontecer)
                rabo = re.sub(r"\s+(?:ou|e|,)$", "", rabo).strip(" ,;")
                return re.sub(r"\s{2,}", " ", m.group(1) + " " + rabo).strip(" ,;")
            return m.group(1).strip()
        return ""

    _DUR = re.compile(r"^\s*(\d{1,4})\s*(dias?|semanas?|m[êe]s(?:es)?|anos?)\s*$", re.I)
    _PLURAL = {"dia": "dias", "semana": "semanas", "mes": "meses", "mês": "meses",
               "ano": "anos"}

    @classmethod
    def _resumir_duracoes(cls, valores: list[str]) -> str:
        """Vários prazos viram UM texto — sem esconder que eles diferem.

        A AF tem um campo só, e a proposta pode trazer 15 dias num item e 70 no
        outro. Escolher um seria mentir sobre o outro: o campo passa a dizer a
        FAIXA ("15 a 70 dias"). Cada item continua com o seu, que é o que a grade
        edita e o que vai para o documento linha a linha.
        """
        vistos, soltos = {}, []
        for v in valores:
            v = re.sub(r"\s+", " ", str(v or "")).strip()
            if not v:
                continue
            m = cls._DUR.match(v)
            if not m:
                if v not in soltos:                  # "Pronta-entrega" e afins
                    soltos.append(v)
                continue
            un = cls._PLURAL.get(cls._sem_acento(m.group(2)).lower(), m.group(2).lower())
            vistos.setdefault(un, set()).add(int(m.group(1)))
        if not vistos:
            return soltos[0] if len(soltos) == 1 else ", ".join(soltos)
        if len(vistos) > 1:                          # dias E meses na mesma coluna
            partes = ["%d %s" % (min(n), u) if len(n) == 1 else "%d a %d %s" % (min(n), max(n), u)
                      for u, n in vistos.items()]
            return " / ".join(partes + soltos)
        un, nums = next(iter(vistos.items()))
        if len(nums) == 1:
            n = nums.pop()
            sing = {"dias": "dia", "meses": "mês", "anos": "ano", "semanas": "semana"}
            texto = "%d %s" % (n, sing[un] if n == 1 and un in sing else un)
        else:
            texto = "%d a %d %s" % (min(nums), max(nums), un)
        return " / ".join([texto] + soltos)

    def _objeto(self, t: str, itens: list[ItemAF]) -> str:
        # A SECAO vem primeiro: "Escopo de fornecimento" costuma ser um paragrafo
        # inteiro, e a regra de uma linha so devolvia o comeco dele, cortado no
        # meio da frase.
        obj = self._da_secao(t, "ESCOPO DE FORNECIMENTO", "ESCOPO DO FORNECIMENTO",
                             "OBJETO", "ESCOPO")
        if not obj:
            obj = self._primeiro(t, [r"REF:\s*([^\n]+)",
                                     r"Escopo de Fornecimento\s*[•\-\s]*([^\n]+)",
                                     r"Objeto[:\s]*([^\n]+)"])
        if obj:
            return re.sub(r"\s{2,}", " ", obj).strip()
        # Sem objeto explícito → resumo BREVE e legível: descrições DISTINTAS dos
        # itens (primeiras palavras de cada uma).
        tipos: list[str] = []
        for it in itens:
            desc = re.sub(r"\s+", " ", (it.descricao or it.codigo or "")).strip()
            if not desc:
                continue
            curto = " ".join(desc.split()[:6])
            if curto.lower() not in [x.lower() for x in tipos]:
                tipos.append(curto)
        if not tipos:
            return ""
        txt = "Fornecimento de " + "; ".join(tipos)
        return (txt[:197] + "…") if len(txt) > 200 else txt

    # ---- identificação Part Number × NCM × descrição -----------------------
    @staticmethod
    def _eh_ncm(c: str) -> bool:
        """NCM (código fiscal) tipo 8517.62.59 ou 85176259 — NÃO é Part Number."""
        return bool(re.fullmatch(r"\d{4}\.?\d{2}\.?\d{2}", (c or "").replace(" ", "")))

    @staticmethod
    def _eh_codigo(c: str, desc: str = "") -> bool:
        """Part Number/código: token curto com LETRA e (dígito ou hífen), ex.:
        PRE-QSFP-ER4, TQSFP28-ZRHT. Exclui NCM, preço, percentual e a descrição."""
        c = (c or "").strip()
        if not c or c == desc or ExtratorProposta._eh_ncm(c):
            return False
        if re.search(r"\d[\d.]*,\d{2}", c) or c.endswith("%"):     # preço / percentual
            return False
        tem_letra = bool(re.search(r"[A-Za-z]", c))
        tem_num_hifen = bool(re.search(r"[\d\-]", c))
        return tem_letra and tem_num_hifen and 3 <= len(c) <= 32 and len(c.split()) <= 3

    @staticmethod
    def _eh_preco(c: str) -> bool:
        """Valor monetário '#.###,##' que NÃO é PERCENTUAL de imposto escrito na
        própria célula (ex.: '18,00%')."""
        c = (c or "").strip()
        if not c or "%" in c:
            return False
        low = c.lower()
        if any(t in low for t in ("icms", "ipi", "pis", "cofins", "iss", "aliq", "alíq")):
            return False
        # A célula tem de SER o número, não apenas contê-lo. Enquanto bastava
        # conter, a frase "Valor Global da Proposta com Impostos: R$ 902.275,28"
        # era um preço válido — e a linha de fecho da proposta virava um produto,
        # dobrando a soma dos itens. O espaço que o pdfplumber enfia no meio do
        # número ("R$ 5 .462,50") sai antes de conferir: era por causa dele que a
        # regra tinha ficado frouxa.
        nu = re.sub(r"\s+", "", c)
        nu = re.sub(r"^(R\$|US\$|CN¥|COL\$|CLP\$|\$U|Bs|S/|[€₲$])", "", nu)
        return bool(re.fullmatch(r"-?[\d.]*\d,\d{2}", nu))

    @staticmethod
    def _cols_imposto_tabela(linhas: list[list[str]]) -> set[int]:
        """Acha as colunas de IMPOSTO pelo CABEÇALHO (ex.: '% ICMS', '% IPI'). É o
        caso em que a célula de dados é só o número ('9,75') e o '%' está no título
        — sem isso, a alíquota era confundida com preço. Colunas com 'Preço/Valor/
        Total/Unitário' nunca são imposto, mesmo citando 'sem ICMS e sem IPI'."""
        for row in linhas:
            junto = " ".join(row).lower()
            if not any(k in junto for k in ("icms", "ipi", "alíq", "aliq", "%")):
                continue                          # não é a linha de cabeçalho de impostos
            cols = set()
            for j, h in enumerate(row):
                hl = (h or "").lower()
                if any(t in hl for t in ("preç", "prec", "valor", "total", "unit")):
                    continue                      # coluna de preço/valor — nunca imposto
                if "%" in hl or any(t in hl for t in ("icms", "ipi", "pis", "cofins", "iss", "alíq", "aliq")):
                    cols.add(j)
            if cols:
                return cols
        return set()

    # Quanto tempo, e em que unidade. O cabecalho diz a unidade entre
    # parenteses — "(dias)", "(meses)" — e a celula traz so o numero.
    _UNID_COL = ((r"\(\s*dias?\s*\)", "dias"), (r"\(\s*m[êe]s(?:es)?\s*\)", "meses"),
                 (r"\(\s*anos?\s*\)", "anos"), (r"\(\s*semanas?\s*\)", "semanas"))

    @classmethod
    def _cols_prazo_garantia(cls, linhas: list[list[str]]) -> dict:
        """Acha as colunas de CÓDIGO, PRAZO DE ENTREGA e GARANTIA pelo cabeçalho.

        O cabeçalho de tabela larga vem PARTIDO em várias linhas — na DATACOM a
        coluna do prazo tem "Prazo" numa linha, "Entrega" na seguinte e "(dias)"
        mais abaixo. Olhar linha a linha (como `_cols_imposto_tabela` faz) não
        enxerga nenhuma delas inteira. Aqui as linhas de cabeçalho são EMPILHADAS
        por coluna, e a busca acontece no texto empilhado.

        Cabeçalho = tudo antes da primeira linha que vira item.
        Devolve {"codigo": (col, ""), "prazo": (col, unidade), ...}.

        O código é achado assim porque a heurística não dava conta: ela exige
        uma LETRA no token (boa para "PRE-QSFP-ER4") e o código da DATACOM é só
        dígito e ponto ("800.5304"). Cabeçalho é informação, não chute. Cuidado
        com os vizinhos: "Código Finame" e "Classif. Fiscal" (o NCM) NÃO são o
        código do produto.
        """
        cab: list[str] = []
        for cels in linhas:
            if cls._parece_linha_de_item(cels):
                break                              # começaram os dados
            # Cabeçalho SE ESPALHA por colunas; parágrafo fica numa célula só.
            # Sem esta linha, o texto de apresentação da folha entrava no
            # cabeçalho e a palavra "localidade" de um título fazia a coluna 0
            # passar por coluna de localidade.
            if sum(1 for c in cels if c) < 2:
                continue
            for j, c in enumerate(cels):
                while len(cab) <= j:
                    cab.append("")
                if c:
                    cab[j] += " " + c
        achado = {}
        for j, titulo in enumerate(cab):
            t = cls._sem_acento(titulo).lower()
            if ("codigo" in t and "finame" not in t and "fiscal" not in t
                    and "classif" not in t and "ncm" not in t and "codigo" not in achado):
                achado["codigo"] = (j, "")
                continue
            # Colunas do QUADRO POR LOCALIDADE (uma linha por destino).
            casou = False
            for chave, precisa, proibe in (
                    ("localidade", ("localidade",), ()),
                    ("qtd_desc", ("qtd", "descri"), ()),
                    ("valor_produto", ("valor", "produto"), ()),
                    ("frete", ("frete",), ()),
                    ("total_local", ("total",), ("geral",))):
                if (chave not in achado and all(p in t for p in precisa)
                        and not any(p in t for p in proibe)):
                    achado[chave] = (j, "")
                    casou = True
                    break
            # Coluna já classificada não é reclassificada: "Localidade / Endereço
            # de ENTREGA" contém a palavra "entrega" e, sem este `continue`, caía
            # também na regra de PRAZO DE ENTREGA — o prazo passava a ser lido da
            # coluna do endereço.
            if casou:
                continue
            if "prazo" not in t and "garantia" not in t and "entrega" not in t:
                continue
            unidade = ""
            for padrao, nome in cls._UNID_COL:
                if re.search(padrao, titulo, re.I):
                    unidade = nome
                    break
            # "Prazo de Garantia" tem as DUAS palavras: garantia decide.
            qual = "garantia" if "garantia" in t else ("prazo" if "entrega" in t or "prazo" in t else "")
            if qual and qual not in achado:
                achado[qual] = (j, unidade or ("meses" if qual == "garantia" else "dias"))
        return achado

    @staticmethod
    def _parece_linha_de_item(cels: list[str]) -> bool:
        """Tem preço e texto? Então os dados já começaram — o cabeçalho acabou."""
        junto = " ".join(cels).lower()
        if "descri" in junto or "qtde" in junto or "qtd." in junto:
            return False                           # ainda é cabeçalho
        # Linha de TOTAL não é linha de dados — é o fim deles. Sem isto, um
        # "TOTAL DOS PRODUTOS ... R$ 38.262,40" impresso ANTES da tabela parava
        # a varredura, e o cabeçalho de verdade, mais abaixo, nunca era lido.
        if ExtratorProposta._LINHA_FECHO.search(junto):
            return False
        tem_preco = any(re.search(r"\d[\d.]*,\d{2}", c or "") for c in cels)
        tem_texto = any(len(re.findall(r"[A-Za-zÀ-ÿ]{3,}", c or "")) >= 2 for c in cels)
        return tem_preco and tem_texto

    @staticmethod
    def _dur_da_celula(cel: str, unidade: str) -> str:
        """'15' + 'dias' -> '15 dias'. Célula que já traz a unidade vem como está."""
        c = re.sub(r"\s+", " ", str(cel or "")).strip()
        if not c or c in "-–—":
            return ""
        # DINHEIRO não é prazo. Na linha de licença, desalinhada, "900,00" caía
        # na coluna do prazo e virava "900 dias".
        if re.search(r"\d[\d.]*,\d{2}", c) or "$" in c:
            return ""
        if re.search(r"[A-Za-zÀ-ÿ]", c):            # já escrito ("15 dias", "imediata")
            return c
        n = re.fullmatch(r"0*(\d{1,4})(?:[.,]0+)?", c)
        if not n:
            return ""
        num = n.group(1)
        # prazo de entrega em ANOS ou garantia de séculos é erro de leitura
        teto = {"dias": 999, "semanas": 260, "meses": 240, "anos": 20}.get(unidade, 999)
        if int(num) > teto:
            return ""
        # singular quando é 1: "1 mês", não "1 meses"
        un = unidade
        if num == "1":
            un = {"dias": "dia", "meses": "mês", "anos": "ano", "semanas": "semana"}.get(un, un)
        return f"{num} {un}".strip()

    def _separar_codigo(self, meio: str) -> tuple[str, str]:
        """De 'PRE-QSFP-ER4 8517.62.59 QSFP+, 1310nm...' devolve
        ('PRE-QSFP-ER4', 'QSFP+, 1310nm...') — tira Part Number e NCM do início."""
        toks = meio.split()
        cod = ""
        if toks and self._eh_codigo(toks[0]):
            cod, toks = toks[0], toks[1:]
        if toks and self._eh_ncm(toks[0]):                # descarta NCM logo após
            toks = toks[1:]
        return cod, " ".join(toks).strip()

    # Valor em reais SEMPRE termina em ",dd". Ancorar no centavo é o que faz o
    # espaço que o PDF às vezes enfia no meio do número ("R$ 5 .462,50",
    # "R$ 9 48,69") deixar de partir a captura na metade.
    _DIN = r"([\d][\d .,]*?,\d{2})"
    # Linha de tabela com NCM: nº · descrição · unidade · NCM(8) · qtd · unit ·
    # total · prazo · endereço de entrega. O NCM de 8 dígitos entre a unidade e
    # a quantidade é uma âncora forte: praticamente não há como outra coisa
    # cair nesse formato por acaso.
    _LINHA_NCM = re.compile(
        r"^\s*(\d{1,3})\s+(.+?)\s+([A-Z]{1,4})\s+(\d{8})\s+([\d.,]+)\s+"
        r"R\$\s*" + _DIN + r"\s+R\$\s*" + _DIN + r"\s+(\d{1,4})\b\s*(.*)$")

    # Linha de ORÇAMENTO (SEICOM e afins), toda numa linha de texto:
    #   ITEM MATERIAL DESCRIÇÃO QTD U.M. UNIT %DESC C/DESC %ICMS %IPI VLR-IPI TOTAL PRAZO
    #   001 BTRMT2004 BASTIDOR 44U ... 1,000 PC 4.650,0000 0,0 4.650,000 12,00 7,50 809,36 5.459,36 5
    # A âncora é o par QUANTIDADE + UNIDADE ("1,000 PC"): número com vírgula
    # seguido de sigla curta e, logo depois, uma fila de números. É o que separa
    # a DESCRIÇÃO — texto livre, cheia de números e barras ("6X20A/6X32A/8X63A")
    # — do resto, sem depender de onde cada coluna começa na folha.
    _NUM_ORC = r"\d[\d.]*,\d+"
    # Ancorado no FIM da linha, não na contagem de colunas: cada revisão da
    # proposta tem um conjunto diferente de impostos entre o unitário e o total.
    # O que não muda é que o total é o último valor em dinheiro e o prazo, quando
    # existe, é o inteiro solto depois dele.
    _LINHA_ORCAMENTO = re.compile(
        r"^[ \t]*(\d{1,3})[ \t]+"                     # ITEM
        r"([A-Z0-9][A-Z0-9\-./]{2,19})[ \t]+"          # MATERIAL (código)
        r"(.+?)[ \t]+"                                 # DESCRIÇÃO
        r"(" + _NUM_ORC + r")[ \t]+([A-Z]{1,3})[ \t]+"  # QTD + U.M. (âncora)
        r"(" + _NUM_ORC + r"(?:[ \t]+[\d.,]+){1,8})"    # unitário + os impostos
        r"[ \t]*$", re.M)

    def _itens_orcamento(self, t: str) -> list[ItemAF]:
        """Itens de proposta em forma de ORÇAMENTO, lidos do TEXTO.

        Vale a pena existir mesmo havendo leitor de tabela: quando a folha não
        tem fios entre as linhas, o pdfplumber funde os produtos todos numa
        célula só e o leitor de tabela devolve as linhas de TOTAL no lugar deles.
        """
        linhas = t.splitlines()
        itens = []
        for m in self._LINHA_ORCAMENTO.finditer(t):
            desc = re.sub(r"\s{2,}", " ", m.group(3)).strip()
            if not self._eh_descricao_de_item(desc):
                continue
            # A DESCRIÇÃO CONTINUA na linha de baixo quando não coube: o
            # "(EBDEN0001/STECK)" do PDU é uma linha à parte na folha e aparece
            # junto na AF pronta. Continuação = linha seguinte sem número de
            # item e sem valor.
            n_linha = t[:m.start()].count("\n")
            if n_linha + 1 < len(linhas):
                prox = linhas[n_linha + 1].strip()
                if (prox and not re.match(r"^\d{1,3}\s", prox)
                        and not re.search(r"\d[\d.]*,\d{2}", prox)
                        and self._eh_descricao_de_item(prox) and len(prox) <= 60):
                    desc = (desc + " " + prox).strip()
            qtd = m.group(4)
            if re.fullmatch(r"\d+,0+", qtd):        # "1,000" é 1, não 1 milésimo
                qtd = qtd.split(",")[0]
            # a fila de valores: o TOTAL é o último em dinheiro; o PRAZO, o
            # inteiro solto depois dele
            fila = m.group(6).split()
            prazo_txt = ""
            if fila and re.fullmatch(r"\d{1,4}", fila[-1]):
                prazo_txt = fila.pop()
            dinheiros = [x for x in fila if re.fullmatch(r"\d[\d.]*,\d{2,4}", x)]
            if len(dinheiros) < 2:
                continue                           # sem unitário e total não é item
            # O unitário desta coluna é SEM imposto: 5.200,00 + 390,00 de IPI
            # = 6.498,38 (com o ICMS de 7%), que é o total da linha. Guardado
            # como "com impostos" apareceria no documento sem fechar com o
            # total ao lado.
            sem = self._duas_casas(self._limpar_dinheiro(dinheiros[0]))
            total = self._limpar_dinheiro(dinheiros[-1])
            com = self._unit_do_total(total, qtd)
            itens.append(ItemAF(
                codigo=m.group(2), descricao=desc, quantidade=qtd,
                unidade=m.group(5), preco_unit_sem=sem, preco_unit_com=com,
                preco_total_com=total,
                prazo=self._dur_da_celula(prazo_txt, "dias")))
        return itens

    @staticmethod
    def _duas_casas(v: str) -> str:
        """"4.650,0000" -> "4.650,00". Quatro casas é precisão de sistema do
        fornecedor; dinheiro no documento tem duas."""
        n = brl_para_float(v)
        return float_para_brl(n) if n is not None else v

    @classmethod
    def _unit_do_total(cls, total: str, qtd: str) -> str:
        """Unitário COM impostos = total da linha ÷ quantidade."""
        t, q = brl_para_float(total), brl_para_float(qtd)
        return float_para_brl(t / q) if (t is not None and q) else ""

    @staticmethod
    def _limpar_dinheiro(v: str) -> str:
        """Tira o espaço que o PDF enfia no meio do número.

        O pdfplumber devolve "R$ 5 .462,50" e "R$ 9 48,69" — o espaço vem da
        posição do texto na página, não do número. A conta até funcionava (o
        conversor ignora o espaço), mas o texto ia CRU para o formulário e para
        o documento, e "9 48,69" num campo de preço parece erro de digitação.
        """
        v = re.sub(r"\s+", "", str(v or "").strip())
        return v.lstrip("R$").strip()

    # Uma linha da tabela de COMPOSIÇÃO FINANCEIRA: rótulo à esquerda, um valor
    # em reais à direita, e nada mais. O sinal de menos pode vir antes do "R$"
    # ("- R$ 3.051,74", como a ARTEMIS escreve o desconto) ou depois dele.
    _LINHA_COMPOSICAO = re.compile(
        r"(?m)^[ \t]*(?P<desc>[^\n\d][^\n]*?)[ \t]+"
        r"(?P<sinal>-[ \t]*)?R\$[ \t]*(?P<sinal2>-[ \t]*)?"
        r"(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})[ \t]*$")

    def _itens_composicao(self, t: str, total: str) -> list[ItemAF]:
        """Itens de uma tabela "Composição financeira", com a CONTA decidindo.

        Este formato (ARTEMIS) não tem quantidade nem preço unitário: é uma
        lista de PARCELAS — produtos, frete, desconto — e, no meio delas, dois
        valores que NÃO são parcelas e sim resultados:

            Produtos ......................  R$ 19.131,20   <- parcela
            Frete .........................  R$  6.300,00   <- parcela
            Investimento Bruto Global .....  R$ 25.431,20   <- SUBTOTAL
            Desconto Especial (12%) ....... -R$  3.051,74   <- parcela (negativa)
            VALOR FINAL LÍQUIDO ...........  R$ 22.379,46   <- TOTAL

        Distinguir parcela de resultado por palavra-chave seria adivinhação —
        cada fornecedor batiza o subtotal de um jeito. A ARITMÉTICA não: um
        valor que é igual à soma do que veio antes é resultado, não parcela.
        É o mesmo oráculo que o resto do extrator já usa.

        Só devolve itens quando a soma deles BATE com o total anunciado. Sem
        isso, devolve vazio: um item inventado é pior do que item nenhum,
        porque vira dinheiro na AF.
        """
        if not total:
            return []
        alvo = brl_para_float(total)
        if not alvo:
            return []

        crus = []
        for m in self._LINHA_COMPOSICAO.finditer(t):
            desc = re.sub(r"\s{2,}", " ", m.group("desc")).strip(" .:-—")
            if len(desc) < 3:
                continue
            v = brl_para_float(m.group("val"))
            if m.group("sinal") or m.group("sinal2"):
                v = -v
            crus.append((desc, v))
        if len(crus) < 2:
            return []

        mantidos, soma = [], 0.0
        for desc, v in crus:
            # resultado, não parcela: já é o que temos somado até aqui
            if mantidos and abs(v - soma) < 0.01:
                continue
            # o total anunciado encerra a tabela
            if abs(v - alvo) < 0.01 and mantidos:
                break
            mantidos.append((desc, v))
            soma += v

        if not mantidos or abs(soma - alvo) >= 0.01:
            return []          # a conta não fecha: não arrisca

        itens = []
        for desc, v in mantidos:
            it = ItemAF()
            it.descricao = desc
            it.preco_total_com = float_para_brl(v)
            itens.append(it)
        return itens

    def _itens_com_ncm(self, t: str) -> list[ItemAF]:
        """Itens de proposta cuja tabela tem NCM e ENDEREÇO DE ENTREGA na MESMA
        linha do produto.

        Sem isto, o endereço vinha grudado e virava a descrição do item — a AF
        saía com "Rodovia GO 330 Km 07" no lugar de "RACK 44U 19"". O endereço é
        separado e descartado daqui: local de entrega é escolhido no formulário,
        a partir do cadastro, não copiado de um pedaço de texto quebrado.
        """
        itens: list[ItemAF] = []
        for ln in t.splitlines():
            m = self._LINHA_NCM.match(ln)
            if not m:
                continue
            _n, desc, unid, _ncm, qtd, unit, total, _dias, _end = m.groups()
            # Nesta tabela NÃO há coluna de código (as colunas são ITEM ·
            # SOLICITAÇÃO · DESCRIÇÃO · UNID · NCM · QT · …), então o texto
            # inteiro é a descrição. Passar por _separar_codigo arrancava
            # "PDU3U" para o campo Código e deixava a descrição começando em
            # '19-21" 200A 2 VIAS' — o produto perdia o nome. O NCM também não
            # serve de código: é classificação fiscal, não part number.
            itens.append(ItemAF(codigo="", descricao=desc.strip(), quantidade=qtd, unidade=unid,
                                preco_unit_sem=self._limpar_dinheiro(unit), preco_unit_com="",
                                preco_total_com=self._limpar_dinheiro(total)))
        return itens

    # Quantos PRECOS diferentes o documento tem. E o sinal mais barato de que
    # existe (ou nao) uma tabela de itens: uma tabela de N itens traz pelo menos
    # N precos. Proposta de preco fechado — servico cotado num numero so — tem
    # um valor e mais nada.
    _DINHEIRO_DOC = re.compile(r"\d{1,3}(?:\.\d{3})+,\d{2}|\b\d+,\d{2}\b")
    _MIN_PRECOS_TABELA = 3

    def _pode_ter_tabela(self, t: str) -> bool:
        """Vale a pena gastar o Docling procurando itens neste documento?

        Medido nas propostas reais: a de preco fechado (Zopone, SE Araraquara)
        tem 1 preco no documento inteiro e o Docling gastava 22s para achar zero
        item. A PADTEC — onde ele comprovadamente encontra os itens que o regex
        perde — tem 4. O corte em 3 separa os dois casos com folga.
        """
        return len(set(self._DINHEIRO_DOC.findall(t))) >= self._MIN_PRECOS_TABELA

    # Quantidade escrita por extenso no comeco do escopo: "02 (dois) kits...".
    _QTD_ESCOPO = re.compile(r"^\D{0,24}?\b0*(\d{1,3})\s*\((?:um|uma|dois|duas|tr[êe]s|quatro|"
                             r"cinco|seis|sete|oito|nove|dez|onze|doze|quinze|vinte|trinta)\b",
                             re.I)

    def _item_do_escopo(self, texto: str, objeto: str, valor_total: str):
        """Uma linha de item a partir do ESCOPO, para proposta de preco fechado.

        A proposta de servico cotado num numero so nao tem tabela de itens — mas
        a AF precisa de pelo menos uma linha dizendo o que esta sendo comprado, e
        isso esta escrito no escopo de fornecimento com todas as letras:

            3.1 ESCOPO DE FORNECIMENTO
            1. Fornecimento de 02 (dois) kits certificados de aterramento...
            3.5 VALOR
            > R$ 13.934,70

        A quantidade sai do proprio texto ("02 (dois)"); o unitario e o total
        dividido por ela — conta, nao chute. Sem quantidade escrita, fica 1.
        """
        desc = (objeto or "").strip()
        if not desc or not valor_total:
            return None
        total = brl_para_float(valor_total)
        if total is None or total <= 0:
            return None
        m = self._QTD_ESCOPO.match(desc)
        qtd = int(m.group(1)) if m and int(m.group(1)) > 0 else 1
        unit = total / qtd
        return ItemAF(codigo="", descricao=desc, quantidade=str(qtd), unidade="",
                      preco_unit_sem=float_para_brl(unit),
                      preco_unit_com=float_para_brl(unit),
                      preco_total_com=float_para_brl(total))

    def _confere_soma(self, itens: list[ItemAF], t: str) -> bool:
        """A soma dos itens bate com o SUBTOTAL/TOTAL declarado na proposta?

        É a prova de que o corte das colunas está certo. Sem ela eu estaria
        confiando num regex escrito a partir de UMA proposta; com ela, o
        resultado só é aceito quando a própria proposta confirma."""
        if not itens:
            return False
        soma = sum(brl_para_float(it.preco_total_com) or 0 for it in itens)
        if soma <= 0:
            return False
        declarados = [brl_para_float(v) for v in
                      re.findall(r"(?:SUBTOTAL|TOTAL)\s*R?\$?\s*([\d][\d .,]*?,\d{2})", t, re.I)]
        return any(d and abs(d - soma) < 0.01 for d in declarados)

    def _itens(self, t: str) -> list[ItemAF]:
        """Melhor-esforço: descrição seguida de uma linha com qtd e preços R$.
        Tabelas embaralhadas retornam vazio (o usuário preenche na grade)."""
        # 1º a tabela com NCM, e SÓ se a soma fechar com o total declarado.
        com_ncm = self._itens_com_ncm(t)
        if com_ncm and self._confere_soma(com_ncm, t):
            LOG.info("itens lidos pela tabela com NCM: %d (soma confere com a proposta)", len(com_ncm))
            return com_ncm
        itens: list[ItemAF] = []
        linhas = t.splitlines()
        for i, ln in enumerate(linhas):
            m = re.match(r"\s*(\d{1,2})\s+(.+?)\s+(\d+)\s+R\$\s*([\d.]+,\d{2}).*?R\$\s*([\d.]+,\d{2})\s+R\$\s*([\d.]+,\d{2})\s*$", ln)
            if m:
                cod, desc = self._separar_codigo(m.group(2).strip())
                itens.append(ItemAF(codigo=cod, descricao=desc, quantidade=m.group(3),
                                    preco_unit_sem=m.group(4), preco_unit_com=m.group(5),
                                    preco_total_com=m.group(6)))
        return itens

    def _item_de_celulas(self, cels: list[str], cols_imposto: set = frozenset(),
                         cols_pg: dict | None = None) -> ItemAF | None:
        """Monta um ItemAF de UMA linha de tabela (heurística por colunas:
        descrição = célula textual mais longa; Part Number = token código-like
        que NÃO é NCM; preços = células '#.###,##', menos as colunas de imposto).
        Serve p/ tabelas do pdfplumber e markdown do docling. None = não é item."""
        if len(cels) < 3 or all(set(c) <= set("-: ") for c in cels):   # vazia/separador
            return None
        # Pula as colunas de imposto detectadas pelo cabeçalho (ex.: % ICMS, % IPI),
        # senão a alíquota '9,75' entrava no lugar do preço.
        precos = [c for j, c in enumerate(cels) if j not in cols_imposto and self._eh_preco(c)]
        desc = max((c for c in cels if re.search(r"[A-Za-zÀ-ÿ]{3,}", c)), key=len, default="")
        if not precos or not desc or not self._eh_descricao_de_item(desc):
            return None
        di = cels.index(desc)
        # Qtd vem DEPOIS da descrição (evita pegar a coluna "Item"=1,2,3…).
        # As colunas de prazo/garantia também são inteiros curtos e vêm depois da
        # descrição: sem excluí-las, "15" (dias) podia ser lido como quantidade.
        cols_pg = cols_pg or {}
        fora = set(cols_imposto) | {j for j, _ in cols_pg.values()}
        qtd = next((c for j, c in enumerate(cels)
                    if j > di and j not in fora and re.fullmatch(r"\d{1,4}", c)), "")
        # CÓDIGO: a coluna dita pelo cabeçalho manda; a heurística é a reserva.
        cod = ""
        if "codigo" in cols_pg:
            j = cols_pg["codigo"][0]
            bruto = cels[j].strip() if j < len(cels) else ""
            # na linha de licença a descrição ocupa a coluna do código: não vale
            if bruto and bruto != desc and not self._eh_preco(bruto):
                cod = bruto
        if not cod:
            # Part Number vem ANTES da descrição (cai p/ qualquer um se não achar).
            cod = next((c for j, c in enumerate(cels) if j < di and self._eh_codigo(c, desc)),
                       next((c for c in cels if self._eh_codigo(c, desc)), ""))
        # LICENÇA não tem código de produto na proposta — e "Licença <equipamento>"
        # é o suficiente para saber do que se trata (regra do usuário).
        if not cod and re.match(r"\s*licen[çc]as?\b", desc, re.I):
            cod = "LICENÇA"
        # Linha-RESUMO (ex.: Padtec "2xTM2400G", "Equipamentos" carregando o total
        # geral): sem qtd, sem código e descrição de 1 palavra → não é item.
        if not qtd and not cod and len(desc.split()) <= 1:
            return None
        # 3 preços = [unit s/imp, unit c/imp, total]; 2 = [unit c/imp, total]; 1 = [total]
        if len(precos) >= 3:
            us, uc = precos[0], precos[1]
        elif len(precos) == 2:
            us, uc = "", precos[0]
        else:
            us, uc = "", ""
        # prazo e garantia PRÓPRIOS do item, quando a tabela os traz em coluna
        def _pg(qual):
            if qual not in cols_pg:
                return ""
            j, unidade = cols_pg[qual]
            return self._dur_da_celula(cels[j], unidade) if j < len(cels) else ""

        # o pdfplumber devolve "R$ 1 47.717,52": o "R$ " e o espaço enfiado no
        # meio do número iam crus para o campo de preço do documento
        us, uc = self._limpar_dinheiro(us), self._limpar_dinheiro(uc)
        tot = self._limpar_dinheiro(precos[-1])
        qtd, us, uc = self._conferir_pela_conta(qtd, us, uc, tot, cels)
        return ItemAF(codigo=cod, descricao=desc, quantidade=qtd, preco_unit_sem=us,
                      preco_unit_com=uc, preco_total_com=tot,
                      prazo=_pg("prazo"), garantia=_pg("garantia"))

    @staticmethod
    def _conferir_pela_conta(qtd: str, us: str, uc: str, tot: str, cels: list) -> tuple:
        """Quantidade x unitário tem de dar o total. Quando não dá, a conta manda.

        Linha de sub-tabela (licenças, serviços) entra na grade da tabela grande
        deslocada, e a coluna que o leitor toma por "Qtde" é outra coisa — na
        DATACOM era a alíquota de ISS: quantidade 2 no lugar de 6, com 6 x 900,00
        = 5.400,00 impresso na própria linha. AF com quantidade errada é pedido
        errado, então: se `total / unitário` dá um inteiro exato e a quantidade
        lida não fecha, vale o inteiro.

        Numa linha assim os OUTROS números também estão fora de lugar, então o
        "sem impostos" é reeleito: o maior preço abaixo do unitário com impostos
        (na licença, 882,00 — e não os 18,00 do valor do ISS).
        """
        u = brl_para_float(uc)
        t = brl_para_float(tot)
        # "UNITÁRIO" QUE É TOTAL: a tabela traz unitário e total nas colunas de
        # sem-imposto e com-imposto, e a leitura por posição toma o 2º preço por
        # unitário. `us x qtd == uc` prova que não é: unitário vezes quantidade
        # não pode dar outro unitário. O unitário com impostos sai do total.
        n0 = brl_para_float(qtd)
        s0 = brl_para_float(us)
        if u and t and n0 and s0 and abs(s0 * n0 - u) <= max(0.01, 0.001 * u) \
                and abs(u - t) > 0.01:
            uc = float_para_brl(t / n0)
            u = t / n0
        if not u or not t:
            return qtd, us, uc
        n = t / u
        inteiro = round(n)
        if inteiro < 1 or abs(n - inteiro) > 0.005:      # não fecha redondo: não mexe
            return qtd, us, uc
        lido = brl_para_float(qtd)
        if lido and abs(lido - inteiro) < 0.005:
            return qtd, us, uc                           # já estava certo
        # a linha INTEIRA, inclusive as colunas que o cabeçalho da tabela grande
        # chama de imposto: numa sub-tabela deslocada é lá que o preço foi parar
        melhor = [p for p in (brl_para_float(x) for x in cels
                              if re.search(r"\d[\d.]*,\d{2}", str(x or "")))
                  if p is not None and 0 < p < u]
        novo_us = float_para_brl(max(melhor)) if melhor else ""
        return str(inteiro), novo_us, uc

    # Linha de FECHO da tabela, não produto: "Total de Produtos 2: R$ 513.721,61",
    # "Valor Global da Proposta com Impostos: R$ 902.275,28", "Subtotal".
    # Olhar só a palavra "total" deixava passar "Valor Global" e "Valor da
    # Proposta" — e o fecho entrava como item, somando a proposta inteira de novo.
    # "TOTAIS" no PLURAL escapava: `\btotal\b` não casa "TOTAIS". Foi assim que
    # "TOTAIS DO ORÇAMENTO :" e "ICMS INCLUSO ... TOTAIS DA PÁGINA 1 :" viraram
    # produtos numa proposta de 2 itens.
    _LINHA_FECHO = re.compile(
        r"\b(?:sub)?tota(?:l|is)\b|\bvalor\s+(?:global|total|da\s+proposta)\b"
        r"|\bdescri[çc][ãa]o\b|\bpre[çc]o\s+total\b", re.I)

    @classmethod
    def _eh_descricao_de_item(cls, desc: str) -> bool:
        return not cls._LINHA_FECHO.search(desc or "")

    # "01 Conjunto (1 Rack + 1 PDU)" -> qtd 1, unidade "Conjunto",
    # descrição "(1 Rack + 1 PDU)". A unidade é a palavra que vem colada no
    # número; o que sobra é o produto.
    _QTD_UNID_DESC = re.compile(
        r"^\s*0*(\d{1,4})\s+([A-Za-zÀ-ÿ]+)\s*(.*)$", re.S)
    # "Anápolis / GO Rod. GO 330 Km 07 - Anápolis/GO"
    _LOCAL_UF_END = re.compile(r"^\s*(.+?)\s*/\s*([A-Z]{2})\s+(.+)$", re.S)
    # o município de verdade está no fim do endereço ("- Ap. de Goiânia/GO"),
    # e nem sempre é igual ao nome da localidade ("Porto Colômbia" fica em Planura)
    _MUN_UF_FIM = re.compile(r"[-,]\s*([^-,/]{2,40}?)\s*/\s*([A-Z]{2})\s*$")

    def _quadro_por_localidade(self, linhas: list[list[str]]) -> tuple:
        """Tabela com uma linha por DESTINO: itens, entregas e o frete somado.

        Devolve (itens, entregas). Lista vazia quando a tabela não é deste tipo —
        o que se reconhece pelo cabeçalho ter, ao mesmo tempo, uma coluna de
        LOCALIDADE e uma de FRETE.
        """
        cols = self._cols_prazo_garantia(linhas)
        if "localidade" not in cols or "frete" not in cols:
            return [], []
        cl = cols["localidade"][0]
        cq = cols.get("qtd_desc", (None,))[0]
        cv = cols.get("valor_produto", (None,))[0]
        cf = cols["frete"][0]
        cp = cols.get("prazo", (None,))[0]

        itens, entregas, frete_total = [], [], 0.0
        for cels in linhas:
            if cl >= len(cels):
                continue
            local = re.sub(r"\s+", " ", cels[cl] or "").strip()
            if not local or not self._eh_descricao_de_item(local):
                continue                       # cabeçalho e a linha de TOTAL GERAL
            valor = self._limpar_dinheiro(cels[cv]) if cv is not None and cv < len(cels) else ""
            if not brl_para_float(valor):
                continue                       # sem preço não é linha de destino

            qtd, unidade, desc = "1", "", local
            if cq is not None and cq < len(cels):
                m = self._QTD_UNID_DESC.match(re.sub(r"\s+", " ", cels[cq] or "").strip())
                if m:
                    qtd, unidade = m.group(1), m.group(2)
                    desc = m.group(3).strip() or unidade

            n_qtd = brl_para_float(qtd) or 1
            itens.append(ItemAF(
                descricao=desc, quantidade=qtd, unidade=unidade,
                preco_unit_com=valor,
                preco_total_com=float_para_brl((brl_para_float(valor) or 0) * n_qtd),
                prazo=(re.sub(r"\s+", " ", cels[cp]).strip()
                       if cp is not None and cp < len(cels) and cels[cp] else "")))

            if cf < len(cels):
                frete_total += brl_para_float(self._limpar_dinheiro(cels[cf])) or 0.0
            ent = self._entrega_da_celula(local)
            if ent:
                entregas.append(ent)

        # FRETE como UM item: nome, quantidade 1 e o valor total. Somar o frete
        # dentro do total de cada destino faria a conta contar o frete duas vezes.
        if frete_total > 0:
            itens.append(ItemAF(descricao="Frete", quantidade="1",
                                preco_unit_com=float_para_brl(frete_total),
                                preco_total_com=float_para_brl(frete_total)))
        return itens, entregas

    @classmethod
    def _entrega_da_celula(cls, texto: str) -> dict | None:
        """"Anápolis / GO Rod. GO 330 Km 07 - Anápolis/GO" -> local de entrega."""
        m = cls._LOCAL_UF_END.match(texto or "")
        if not m:
            return None
        nome, uf, endereco = m.group(1).strip(), m.group(2), m.group(3).strip()
        mun = cls._MUN_UF_FIM.search(endereco)
        return {"nome": nome, "sigla": "",
                "municipio": mun.group(1).strip() if mun else nome,
                "uf": mun.group(2) if mun else uf, "endereco": endereco}

    def _itens_de_tabela(self, linhas: list[list[str]]) -> list[ItemAF]:
        """Constrói os itens de UMA tabela: detecta as colunas de imposto pelo
        cabeçalho e aplica em todas as linhas de dados."""
        # QUADRO POR LOCALIDADE tem colunas próprias (endereço de entrega, frete
        # por destino) que a heurística lê como descrição e preço. O cabeçalho
        # diz o que é cada uma — quando ele existe, ele manda.
        quadro, entregas = self._quadro_por_localidade(linhas)
        if quadro:
            self._entregas_lidas = (getattr(self, "_entregas_lidas", []) or []) + entregas
            return quadro
        cols_imp = self._cols_imposto_tabela(linhas)
        cols_pg = self._cols_prazo_garantia(linhas)
        out = []
        for cels in linhas:
            it = self._item_de_celulas(cels, cols_imp, cols_pg)
            if it:
                out.append(it)
        return out

    # Vãos MEDIDOS nesta folha: pedaços da mesma palavra ficam a 0,0-0,1pt e um
    # espaço de verdade a ~1,0pt. O corte em 0,5pt remonta "IM PO RTADO" sem
    # colar "POWER FILTER". Acima de 8pt já é outra coluna.
    _VAO_COLADO = 0.5
    _VAO_COLUNA = 8.0

    @classmethod
    def _juntar_palavras(cls, ws: list) -> str:
        """Remonta o texto respeitando o vão: sem espaço quando a fonte partiu."""
        if not ws:
            return ""
        out = [ws[0]["text"]]
        for a, b in zip(ws, ws[1:]):
            out.append(("" if (b["x0"] - a["x1"]) < cls._VAO_COLADO else " ") + b["text"])
        return re.sub(r"\s{2,}", " ", "".join(out)).strip()

    @staticmethod
    def _linhas_por_posicao(palavras: list) -> list:
        """As linhas da folha, reconstruídas: agrupa por Y, ordena por X."""
        linhas = {}
        for w in palavras:
            linhas.setdefault(round(w["top"] / 4), []).append(w)
        return [sorted(linhas[k], key=lambda w: w["x0"]) for k in sorted(linhas)]

    def _folhas(self, caminho: str) -> list:
        """Palavras e réguas de cada página, do cache do passe único.

        Chamado por fora (nos testes, ou num método usado isoladamente) não há
        cache: abre o arquivo. Dentro de uma extração, o `_ler_texto` já
        encheu o cache e aqui não se toca no disco.
        """
        cache = getattr(self, "_folhas_cache", None)
        if cache and cache[0] == caminho:
            return cache[1]
        folhas = []
        try:
            with _pdfplumber().open(caminho) as pdf:
                folhas = [{"palavras": p.extract_words(), "regras": list(p.lines)}
                          for p in pdf.pages]
        except Exception:
            LOG.exception("falha ao ler as páginas de %s", os.path.basename(caminho))
        self._folhas_cache = (caminho, folhas)
        return folhas

    @staticmethod
    def _bordas_desenhadas(regras, topo: float, base: float) -> list:
        """As divisórias que a folha DESENHA, quando desenha.

        A planilha da NEC não tem grade fechada — `extract_tables()` não acha
        tabela nenhuma —, mas traça as verticais que separam as colunas. Ler
        por elas é melhor do que deduzir a coluna pelo vão entre as palavras:
        na linha do meio do cabeçalho, "Unit Price R$" e "Total Price R$" ficam
        a 3pt uma da outra, menos que um vão de coluna, e as duas colunas de
        preço viravam uma só.

        Só vale se houver traço suficiente para ser uma tabela (4 verticais);
        abaixo disso é moldura de página, e o vão entre palavras decide.
        """
        xs = sorted({round(l["x0"], 1) for l in (regras or [])
                     if abs(l["x0"] - l["x1"]) < 1                 # é vertical
                     and l["bottom"] > topo and l["top"] < base})   # cruza o cabeçalho
        return ([0.0] + xs + [1e9]) if len(xs) >= 4 else []

    @staticmethod
    def _coluna_de(w: dict, bordas: list):
        """Em qual coluna cai a palavra (pelo MEIO dela, não pela ponta)."""
        meio = (w["x0"] + w["x1"]) / 2
        for j in range(len(bordas) - 1):
            if bordas[j] <= meio < bordas[j + 1]:
                return j
        return None

    @classmethod
    def _texto_empilhado(cls, ws: list) -> str:
        """Junta palavras que vêm de LINHAS diferentes da mesma célula.

        Não dá para usar `_juntar_palavras` direto: ela decide o espaço pelo
        vão em X, e comparar o X de uma palavra da 1ª linha com o da 2ª não
        quer dizer nada. Junta-se cada linha por vez, e as linhas entre si com
        um espaço — é assim que "Net Sales" + "Unit Price R$" vira o nome
        inteiro da coluna.
        """
        porlinha = {}
        for w in ws:
            porlinha.setdefault(round(w["top"] / 4), []).append(w)
        return " ".join(
            cls._juntar_palavras(sorted(porlinha[k], key=lambda w: w["x0"]))
            for k in sorted(porlinha)).strip()

    def _faixa_do_cabecalho(self, linhas: list, cab: list) -> list:
        """As linhas que formam o cabeçalho, não só aquela onde ele foi achado.

        O cabeçalho desta folha tem três alturas: os rótulos ("Description",
        "Qty"), o grupo de cada preço ("Net Sales", "Sales With Tax") e o tipo
        do valor ("Unit Price R$"). Sem as três, nenhuma coluna se chama
        "Unit" e todos os itens caem fora na última conferência do leitor.

        Vizinhança em Y, e nunca uma linha com dinheiro: cabeçalho não tem
        preço, item tem. É o que impede o primeiro item de ser lido como parte
        do cabeçalho quando ele vem colado.
        """
        tops = [w["top"] for w in cab]
        topo, base = min(tops), max(tops)
        faixa = []
        for ws in linhas:
            t = min(w["top"] for w in ws)
            if min(abs(t - topo), abs(t - base)) > 8:
                continue
            if ws is not cab and re.search(r"\d[\d.]*,\d{2}", self._juntar_palavras(ws)):
                continue                       # isso é item, não cabeçalho
            faixa.append(ws)
        return faixa or [cab]

    # Os rótulos do cabeçalho de condições da ALG e o campo da AF que cada um
    # alimenta. A busca é por PEDAÇO do rótulo porque ele quebra em duas
    # palavras na folha ("CONDIÇÃO" / "PGTO").
    _COND_CABECALHO = (("condi", "pagamento"), ("pgto", "pagamento"),
                       ("prazo", "prazo"), ("entrega", "prazo"),
                       ("frete", "frete"))

    def _condicoes_no_cabecalho(self, caminho: str) -> dict:
        """Prazo, pagamento e frete da tabelinha de condições do topo da folha.

        Tabela sem grade, com os valores logo abaixo dos rótulos e alinhados
        pelo mesmo x. Ler por posição é o que aguenta valor de várias palavras
        ("45 dias úteis"); por espaços, "45" e "dias úteis" cairiam em campos
        diferentes.
        """
        achado: dict = {}
        try:
            for folha in self._folhas(caminho)[:2]:   # é sempre no topo
                linhas = self._linhas_por_posicao(folha["palavras"])
                for i, ws in enumerate(linhas[:-1]):
                    junto = self._juntar_palavras(ws).lower()
                    if not ("cliente" in junto and
                            ("pgto" in junto or "pagamento" in junto)):
                        continue
                    # cada RÓTULO abre uma coluna; a fronteira é o meio do
                    # caminho até o rótulo seguinte
                    cols = []
                    for w in ws:
                        alvo = next((c for p, c in self._COND_CABECALHO
                                     if p in w["text"].lower()), None)
                        if cols and alvo and cols[-1][1] == alvo:
                            continue          # "CONDIÇÃO" e "PGTO" são a mesma
                        cols.append((w["x0"], alvo))
                    # A palavra pertence ao ÚLTIMO rótulo que começa
                    # antes dela. Pelo meio da palavra não dá: "Alves"
                    # (fim do nome do contato) é larga e seu centro cruzava
                    # a fronteira, entrando no campo de pagamento.
                    valores = {}
                    for w in linhas[i + 1]:
                        dono = None
                        for x, alvo in cols:
                            if x <= w["x0"] + 2:
                                dono = alvo
                            else:
                                break
                        if dono:
                            valores.setdefault(dono, []).append(w)
                    for alvo, ws_col in valores.items():
                        txt = self._juntar_palavras(
                            sorted(ws_col, key=lambda w: w["x0"])).strip(" -:")
                        if txt:
                            achado[alvo] = txt
                    if achado:
                        return achado
        except Exception:
            LOG.exception("falha ao ler as condições do cabeçalho")
        return achado

    def _itens_planilha_posicionada(self, caminho: str) -> tuple:
        """Planilha de preços sem fios, lida pela posição (NEC/Nokia).

        Devolve (itens, valor_total). Vazio quando a folha não é deste tipo —
        o que se reconhece pelo cabeçalho ter, na mesma linha, "Description" e
        uma coluna de quantidade.
        """
        itens, total = [], ""
        try:
            for folha in self._folhas(caminho):
                linhas = self._linhas_por_posicao(folha["palavras"])
                cab = next((ws for ws in linhas
                            if self._eh_cabecalho_de_itens(
                                self._juntar_palavras(ws))), None)
                if not cab:
                    continue
                tops = [w["top"] for w in cab]
                bordas = self._bordas_desenhadas(folha["regras"],
                                                 min(tops) - 6, max(tops) + 6)
                novos, tot = self._ler_planilha(linhas, cab, bordas)
                itens += novos
                total = tot or total
        except Exception:
            LOG.exception("falha ao ler a planilha de preços posicionada")
            return [], ""
        return itens, total

    # O cabeçalho da tabela de itens, nos dois idiomas em que ele aparece:
    # "Description ... Qty" (NEC, Nokia) e "Descrição ... Qtde" (ALG). Exige o
    # PAR descrição+quantidade: a palavra "descrição" sozinha aparece em
    # parágrafo de texto corrido e faria o leitor tentar ler prosa como tabela.
    _CAB_DESC = re.compile(r"\bDescription\b|\bDescri[çc][ãa]o\b", re.I)
    _CAB_QTD = re.compile(r"\bQ\s?ty\b|\bQtde?\b|\bQuantidade\b", re.I)

    @classmethod
    def _eh_cabecalho_de_itens(cls, junto: str) -> bool:
        return bool(cls._CAB_DESC.search(junto) and cls._CAB_QTD.search(junto))

    def _ler_planilha(self, linhas: list, cab: list, bordas: list = None) -> tuple:
        """Uma folha da planilha: usa o cabeçalho para saber o que é cada coluna.

        `bordas` são as divisórias que a folha desenha, quando desenha. Sem
        elas, as colunas saem do vão entre as palavras do cabeçalho — como
        sempre foi, e como continua sendo nas folhas sem traço nenhum.
        """
        faixa = self._faixa_do_cabecalho(linhas, cab)
        if bordas:
            # o cabeçalho INTEIRO empilhado dentro de cada coluna desenhada
            celulas = [[] for _ in range(len(bordas) - 1)]
            for ws in faixa:
                for w in ws:
                    j = self._coluna_de(w, bordas)
                    if j is not None:
                        celulas[j].append(w)
            nomes = [self._texto_empilhado(c) for c in celulas]
        else:
            # as palavras do cabeçalho viram COLUNAS pelo vão entre elas
            grupos, atual = [], [cab[0]]
            for a, b in zip(cab, cab[1:]):
                if (b["x0"] - a["x1"]) > self._VAO_COLUNA:
                    grupos.append(atual)
                    atual = []
                atual.append(b)
            grupos.append(atual)
            nomes = [self._juntar_palavras(g) for g in grupos]
            xs = [g[0]["x0"] for g in grupos]
            # fronteira: meio do caminho entre o início de uma coluna e o da seguinte
            bordas = [0.0] + [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)] + [1e9]

        def campo(d, *chaves):
            for c in chaves:
                for nome, val in d.items():
                    if c.lower() in nome.lower() and val:
                        return val
            return ""

        # A FAIXA DA COLUNA "DESCRIÇÃO". É ela que diz se uma linha solta é
        # continuação do nome do produto ou já é outra coisa na folha.
        faixa_desc = None
        for j, nome_col in enumerate(nomes):
            if self._CAB_DESC.search(nome_col or ""):
                faixa_desc = (bordas[j], bordas[j + 1])
                break

        itens, total = [], ""
        ultimo_i, continuando = -1, False
        for ws in linhas:
            if any(ws is f for f in faixa):
                continue
            junto = self._juntar_palavras(ws)
            m = re.search(r"Valor\s*Total\s*R?\$?\s*([\d.]+,\d{2})", junto, re.I)
            if m:
                total = m.group(1)
                continue
            # CONTINUAÇÃO DA DESCRIÇÃO: na ALG o nome do produto vem nas linhas
            # ABAIXO da linha do item ("RI-42-19-600-600-AC -" em cima, "Rack
            # Indoor 19\" 42U Larg." embaixo). Sem juntar, a AF sai com o código
            # no lugar do nome. Só entra linha SEM dinheiro e SEM código — isto
            # é, texto solto; o próximo item tem os dois e encerra a costura.
            comeca_na_descricao = bool(
                faixa_desc and ws and faixa_desc[0] <= ws[0]["x0"] < faixa_desc[1])
            if (continuando and ultimo_i >= 0 and junto and comeca_na_descricao
                    and not re.search(r"\d[\d.]*,\d{2}", junto)
                    and not re.match(r"[A-Z0-9][A-Z0-9\-./]{3,19}\s", junto)
                    and len(junto) < 90):
                it = itens[ultimo_i]
                it.descricao = (it.descricao + " " + junto).strip()
                continue
            celulas = [[] for _ in nomes]
            for w in ws:
                meio = (w["x0"] + w["x1"]) / 2
                for j in range(len(nomes)):
                    if bordas[j] <= meio < bordas[j + 1]:
                        celulas[j].append(w)
                        break
            d = dict(zip(nomes, (self._juntar_palavras(c) for c in celulas)))
            # LINHA DE PRODUTO: ou tem número de item hierárquico (NEC: "1.4"),
            # ou tem um código de produto (ALG: "35020060099"). Sem nenhum dos
            # dois é linha de texto que caiu dentro da faixa da tabela.
            num_item = (campo(d, "Item") or "").strip()
            cod_prod = (campo(d, "Código Fabricante", "Codigo Fabricante",
                              "Código NEC", "Código", "Codigo") or "").strip()
            por_numero = bool(re.fullmatch(r"\d+\.\d+", num_item))
            # CÓDIGO DE PRODUTO TEM DÍGITO. "ELETRONET" e "RECEBIMENTO" são
            # palavras de cabeçalho e de cláusula que caíram na faixa da
            # tabela; "35020060099" e "RI-42-19-600-600-AC" são código.
            por_codigo = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9\-./]{3,19}", cod_prod)
                              and re.search(r"\d", cod_prod))
            if not por_numero and not por_codigo:
                continue
            # DESCRIÇÃO LARGA invade a coluna de quantidade: a quantidade é o
            # último pedaço, o resto volta para a descrição.
            desc, qtd = campo(d, "Description", "Descri"), ""
            bruto = ""
            for nome, val in d.items():
                if self._CAB_QTD.search(nome):
                    bruto = (val or "").strip()
                    break
            if re.fullmatch(r"\d{1,5}", bruto):
                qtd = bruto
            elif bruto:
                mm = re.search(r"(.*?)\s*(\d{1,5})\s*$", bruto)
                desc = (desc + " " + (mm.group(1) if mm else bruto)).strip()
                qtd = mm.group(2) if mm else ""
            # "Unit" (NEC) ou "Preço Final" (ALG): é a mesma coluna — o preço
            # de UMA unidade já com imposto.
            unit = self._limpar_dinheiro(self._preco(d, "Unit")
                                         or self._preco(d, "Pre.o Final"))
            tot = self._limpar_dinheiro(self._preco(d, "Total"))
            if not desc or not (unit or tot):
                continue
            # Qualificada só pelo código, a linha precisa de um TOTAL que seja
            # dinheiro: nas duas intrusas dessa folha, a coluna do total trazia
            # nome de consultor e texto de cláusula.
            if por_codigo and not por_numero and not tot:
                continue
            # POR QUAL FILIAL o pedido é faturado. A NEC muda de CNPJ conforme
            # a natureza da operação, e quem diz qual é a própria planilha.
            fat = campo(d, "cnpj de faturamento", "cnpj")
            if fat and self._CNPJ_SOLTO.search(fat):
                self._cnpj_faturamento = self._CNPJ_SOLTO.search(fat).group(0)
            itens.append(ItemAF(
                codigo=campo(d, "Código Fabricante", "Codigo Fabricante",
                             "Código NEC", "Código", "Codigo"),
                descricao=re.sub(r"\s{2,}", " ", desc).strip(),
                quantidade=qtd, preco_unit_com=unit, preco_total_com=tot))
            ultimo_i = len(itens) - 1
            continuando = True
        return itens, total

    _CNPJ_SOLTO = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4,5}-\d{2}")

    def _filiais_do_fornecedor(self, caminho: str) -> dict:
        """{CNPJ: dados} das filiais que a proposta lista para faturamento.

        A tabela "Dados para faturamento" é desenhada como uma coluna por
        filial; o pdfplumber devolve cada coluna como uma tabelinha de uma
        coluna só, na ordem: rótulos primeiro, depois uma por filial. Casando
        os rótulos com os valores linha a linha, cada filial sai inteira — em
        vez do endereço picotado que o texto corrido produz.
        """
        filiais = {}
        try:
            with _pdfplumber().open(caminho) as pdf:
                for pg in pdf.pages:
                    cols = [[" ".join((c or "").split()) for linha in t for c in linha]
                            for t in (pg.extract_tables() or [])]
                    if len(cols) < 2:
                        continue
                    rot = [r.lower() for r in cols[0]]
                    if not any("cnpj" in r for r in rot):
                        continue               # não é a tabela de faturamento
                    for col in cols[1:]:
                        if len(col) != len(rot):
                            continue           # coluna truncada: não dá para casar
                        d = dict(zip(rot, col))

                        def pega(*chaves):
                            for k, v in d.items():
                                if any(c in k for c in chaves) and v:
                                    return v
                            return ""

                        bruto = pega("cnpj")
                        m = self._CNPJ_SOLTO.search(bruto or "")
                        if not m:
                            continue
                        end = pega("endere")
                        # "9.662-030": a própria proposta escreve o CEP de São
                        # Bernardo sem o zero da frente. Exigir dois dígitos
                        # deixava o campo vazio, e sobrava na tela o CEP que a
                        # varredura de texto havia pescado de OUTRA filial.
                        cep = re.search(r"\b\d{1,2}\.?\d{3}-?\d{3}\b", end or "")
                        filiais[m.group(0)] = {
                            "rotulo": pega("dados da"),
                            "insc_est": pega("estadual"),
                            "endereco": re.sub(r"\s*CEP\s*[\d.\-]+\s*$", "", end or "").strip(" ,;"),
                            "cep": cep.group(0) if cep else "",
                        }
        except Exception:
            LOG.exception("falha ao ler a tabela de filiais do fornecedor")
        return filiais

    def _aplicar_filial(self, d, caminho: str) -> str:
        """Troca os dados do fornecedor pelos da filial que a planilha indica.

        Devolve o rótulo da filial (p/ avisar na tela) ou "".
        """
        alvo = getattr(self, "_cnpj_faturamento", "")
        if not alvo:
            return ""
        filiais = self._filiais_do_fornecedor(caminho)
        f = filiais.get(alvo)
        if not f:
            return ""
        d.cnpj = alvo
        d.insc_est = f["insc_est"] or d.insc_est
        d.endereco = f["endereco"] or d.endereco
        d.cep = f["cep"] or d.cep
        return f["rotulo"] or alvo

    @staticmethod
    def _preco(d: dict, papel: str) -> str:
        r"""O preço COM imposto, entre os três que a planilha traz.

        A folha repete o mesmo item em "Net Sales" (líquido), "Sales Without
        Tax" e "Sales With Tax". A AF se faz pelo valor com imposto — é o que a
        Eletronet paga, e é o que fecha com o "Valor Total R$" impresso no pé
        da planilha. Pegando a primeira coluna com "Unit" no nome, vinha a
        líquida: 136.201,62 no lugar de 153.466,62.

        "Without Tax" não casa com `with\s*tax` porque entre "with" e "tax" vem
        "out" — não é preciso excluí-la à parte.
        """
        candidatas = [n for n in d if re.search(papel, n, re.I) and d[n].strip()]
        if not candidatas:
            return ""
        com_imposto = [n for n in candidatas if re.search(r"with\s*tax", n, re.I)]
        return d[(com_imposto or candidatas)[0]]

    def _itens_tabelas(self, caminho: str) -> list[ItemAF]:
        """Tabelas NATIVAS do pdfplumber (rápido, sem ML) — alternativa ao Docling
        quando o regex linha-a-linha não acha itens. Vale só p/ PDFs digitais.
        Reaproveita as tabelas já lidas no _ler_texto (passe único); só reabre o
        PDF se for chamado por fora, sem cache."""
        itens: list[ItemAF] = []
        cache = getattr(self, "_tabelas_cache", None)
        try:
            if cache and cache[0] == caminho:
                paginas = cache[1]                                  # sem 2º open
            else:
                with _pdfplumber().open(caminho) as pdf:
                    paginas = [p.extract_tables() or [] for p in pdf.pages]
            for tabs in paginas:
                for tb in tabs:
                    linhas = [[re.sub(r"\s+", " ", (c or "")).strip() for c in row] for row in tb]
                    itens += self._itens_de_tabela(linhas)
        except Exception:
            pass
        return itens

    def _itens_md(self, md: str) -> list[ItemAF]:
        """Itens das TABELAS markdown do docling. Agrupa as linhas de cada tabela
        (separadas por linhas em branco) p/ achar as colunas de imposto no cabeçalho."""
        itens: list[ItemAF] = []
        bloco: list[list[str]] = []
        for ln in md.splitlines():
            if ln.count("|") < 3:
                if bloco:
                    itens += self._itens_de_tabela(bloco)
                    bloco = []
                continue
            bloco.append([c.strip() for c in ln.strip().strip("|").split("|")])
        if bloco:
            itens += self._itens_de_tabela(bloco)
        return itens

    # ---- ponto de entrada -------------------------------------------------
    # --------------------------------------------- catálogo como dicionário --
    # Genéricas demais p/ identificar alguém: aparecem em meia dúzia de razões
    # sociais e casariam com o fornecedor errado.
    _PALAVRAS_VAGAS = {
        "comercio", "comercial", "distribuidora", "distribuicao", "telecomunicacoes",
        "telecom", "equipamentos", "eletronicos", "eletronica", "servicos", "sistemas",
        "tecnologia", "industria", "solucoes", "produtos", "brasil", "importacao",
        # as mesmas palavras em INGLÊS: metade dos fornecedores do setor escreve
        # o nome assim, e "solutions" chegou a casar ARTEMIS numa proposta da
        # Precision Solutions — as duas têm a palavra no nome
        "solutions", "systems", "technology", "technologies", "communications",
        "networks", "services", "products", "group", "company", "international",
        "industries", "electronics", "engineering", "trading", "latin", "america",
        "america", "global", "digital", "telecommunications",
        "exportacao", "engenharia", "materiais", "suprimentos", "informatica", "ltda",
        "eireli", "epp", "me", "sociedade", "anonima", "participacoes", "holding",
        # preposições e palavras de formulário: "PLP - PRODUTOS PARA LINHAS
        # PREFORMADOS" casava com o "Para:" do cabeçalho da proposta.
        "para", "para", "com", "sem", "dos", "das", "por", "sob", "sobre", "entre",
        "proposta", "comercial", "cliente", "fornecedor", "empresa", "grupo", "nome",
        "total", "valor", "item", "itens", "geral", "data", "prazo",
    }

    @staticmethod
    def _sem_acento(t: str) -> str:
        import unicodedata
        return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()

    def identificar_do_catalogo(self, texto: str, com_confianca: bool = False):
        """Acha no TEXTO da proposta um fornecedor JÁ CADASTRADO e devolve o
        registro oficial dele (ou None). Com `com_confianca`, devolve também
        COMO foi identificado: "cnpj" (identidade exata) ou "nome" (indício).

        Ordem invertida de propósito. Antes era: adivinhar o nome por regex e só
        então casar com o catálogo — se a regex falhasse (layout novo, nome sem
        o rótulo "Razão Social"), o cadastro nunca era usado, mesmo com o CNPJ
        impresso na proposta. Agora o catálogo é o dicionário: procura-se nele.

        1º pelo CNPJ (14 dígitos, identidade exata);
        2º por uma palavra distintiva do apelido/razão social.
        Vale para os fornecedores do .xlsm E para os que o usuário cadastrou."""
        from .dados_eletronet import catalogo_fornecedores

        try:
            catalogo = catalogo_fornecedores()
        except Exception as exc:                      # catálogo indisponível não derruba a leitura
            LOG.warning("não consegui consultar o catálogo: %s", exc)
            return None

        digitos = re.sub(r"\D", "", texto)
        for f in catalogo:
            cnpj = re.sub(r"\D", "", str(f.get("cnpj", "")))
            if len(cnpj) == 14 and cnpj in digitos:
                LOG.info("fornecedor identificado pelo CNPJ do catálogo: %s", f.get("empresa"))
                return (f, "cnpj") if com_confianca else f

        # Palavra INTEIRA e com 5+ letras: como substring, "para" casava dentro de
        # "preparado"; com 4 letras, casava com o "Para:" do cabeçalho.
        alvo = self._sem_acento(texto)
        palavras_texto = set(re.findall(r"[a-z0-9]{5,}", alvo))
        # PESO = quantas palavras distintivas batem (desempate pela mais longa).
        # Contar evidências é melhor que medir uma só: "Precision Solutions" bate
        # duas palavras numa proposta dela, e a ARTEMIS bateria só "solutions".
        pesos = []
        for f in catalogo:
            achadas = set()
            for campo in (f.get("apelido", ""), f.get("empresa", "")):
                for palavra in re.findall(r"[a-z0-9]{5,}", self._sem_acento(campo)):
                    if palavra in self._PALAVRAS_VAGAS or palavra not in palavras_texto:
                        continue
                    achadas.add(palavra)
            if achadas:
                pesos.append(((len(achadas), max(len(p) for p in achadas)), f))
        if not pesos:
            return (None, "") if com_confianca else None
        pesos.sort(key=lambda x: x[0], reverse=True)
        # EMPATE NÃO ESCOLHE: com dois fornecedores no mesmo peso o nome não
        # identifica ninguém. Melhor o app dizer que não reconheceu do que
        # imprimir o fornecedor errado numa AF que vai ser assinada.
        if len(pesos) > 1 and pesos[0][0] == pesos[1][0]:
            LOG.info("nome não identifica: %s e %s empatam",
                     pesos[0][1].get("empresa"), pesos[1][1].get("empresa"))
            return (None, "") if com_confianca else None
        melhor = pesos[0][1]
        LOG.info("fornecedor identificado pelo nome do catálogo: %s", melhor.get("empresa"))
        return (melhor, "nome") if com_confianca else melhor

    def extrair(self, caminho: str) -> DadosProposta:
        import time
        t0 = time.perf_counter()
        d = DadosProposta(arquivo=os.path.basename(caminho), caminho_pdf=os.path.abspath(caminho))
        try:
            texto, metodo = self._ler_texto(caminho)
        except Exception as exc:
            LOG.exception("erro ao abrir o PDF %s", os.path.basename(caminho))
            d.avisos.append(f"Erro ao abrir o PDF: {exc}")
            return d

        d.usou_ocr = (metodo == "ocr")
        if metodo == "ocr":
            d.avisos.append("Proposta lida por OCR — confira os campos com atenção.")
        elif metodo == "docling":
            d.avisos.append("Proposta lida via Docling (texto reconstruído) — confira os campos.")
        if not texto.strip():
            d.avisos.append("Não foi possível extrair texto da proposta.")
            return d

        d.fornecedor = self._fornecedor(texto)
        d.cnpj = self._cnpj(texto)
        d.endereco = self._endereco(texto)
        d.cep = self._cep(texto)
        d.insc_est = self._insc_est(texto)

        # Fornecedor JÁ CADASTRADO reconhecido no texto: os dados oficiais dele
        # valem mais do que o que se conseguiu raspar do PDF.
        #
        # Dois níveis de confiança, e a diferença importa. O CNPJ é IDENTIDADE:
        # 14 dígitos que só pertencem a uma empresa, então manda. O nome é só
        # INDÍCIO — numa proposta da NILKO a palavra "Fênix" aparecia (o projeto
        # Fênix), e casava com o fornecedor "FÊNIX Sistemas de Energia". Por isso
        # o nome só vale quando não se descobriu nem nome nem CNPJ na proposta:
        # aí não há o que atropelar, e é o caso que o usuário mais sofre.
        conhecido, como = self.identificar_do_catalogo(texto, com_confianca=True)
        if conhecido and como == "nome" and (d.fornecedor or d.cnpj):
            conhecido = None                       # já havia dado próprio: não sobrescreve
        if conhecido:
            d.fornecedor = conhecido.get("empresa") or d.fornecedor
            d.cnpj = conhecido.get("cnpj") or d.cnpj
            d.endereco = conhecido.get("endereco") or d.endereco
            d.cep = conhecido.get("cep") or d.cep
            d.insc_est = conhecido.get("insc_est") or d.insc_est
            if conhecido.get("garantia") and not d.garantia:
                d.garantia = conhecido["garantia"]
            d.avisos.append(f"Fornecedor reconhecido no cadastro pelo {'CNPJ' if como == 'cnpj' else 'nome'}"
                            f": {d.fornecedor}."
                            + ("" if como == "cnpj" else " Confira — o nome é só um indício."))

        # guarda o texto p/ aprender depois, quando o usuário gerar o documento
        self.ultimo_texto = texto
        d.numero_proposta = self._numero_proposta(texto)
        d.data = self._data(texto)
        d.valor_total = self._valor_total(texto)
        # `or` e não `=`: algumas linhas acima a garantia pode ter vindo do
        # CADASTRO do fornecedor, e a atribuição direta a apagava quando a
        # proposta não trazia a frase da regra.
        d.garantia = self._garantia(texto) or d.garantia
        d.prazo_entrega = self._prazo(texto) or d.prazo_entrega
        if not getattr(d, "condicao_pagamento", ""):
            d.condicao_pagamento = self._pagamento(texto)
        # CONDIÇÕES NA TABELINHA DO TOPO (ALG): "CONDIÇÃO PGTO 30 dias",
        # "PRAZO ENTREGA 45 dias úteis". Não estão em frase, então nenhuma das
        # regras de texto corrido as acha — e a AF saía sem prazo e sem
        # pagamento, dois campos que a proposta declara com todas as letras.
        if caminho.lower().endswith(".pdf") and not (d.prazo_entrega
                                                     and d.condicao_pagamento):
            cond = self._condicoes_no_cabecalho(caminho)
            if cond.get("prazo") and not d.prazo_entrega:
                d.prazo_entrega = cond["prazo"]
            if cond.get("pagamento") and not d.condicao_pagamento:
                d.condicao_pagamento = self._pagamento_por_extenso(cond["pagamento"])

        # LIÇÕES: o que este fornecedor já ensinou em correções anteriores vale
        # mais que a regra genérica — foi você quem disse onde estava o certo.
        # Tem de vir DEPOIS de todos os campos acima: aplicado antes, a regra
        # genérica rodava em seguida e sobrescrevia o que havia sido aprendido.
        if d.cnpj:
            try:
                from .aprendizado import aplicar as _aplicar_licoes

                aprendido = _aplicar_licoes(d.cnpj, texto)
                usados = []
                for campo, valor in aprendido.items():
                    if getattr(d, campo, "") != valor:
                        setattr(d, campo, valor)
                        usados.append(campo.replace("_", " "))
                if usados:
                    d.avisos.append("Preenchido pelo que este fornecedor já ensinou: "
                                    + ", ".join(usados) + ".")
            except Exception as exc:          # aprendizado é conveniência, não pode derrubar a leitura
                LOG.warning("não consegui aplicar as lições: %s", exc)
        # Itens: 1º o regex de linha (rápido). Mas em muitas propostas (ex.: FONNET)
        # a descrição fica numa linha SEPARADA do código, e o regex perde a
        # descrição — nesse caso as TABELAS nativas (que preservam as colunas) são
        # melhores. Trocamos pela tabela quando ela traz mais itens COM descrição.
        d.itens = self._itens(texto)
        # ORÇAMENTO de uma linha por produto: tentado ANTES das tabelas porque
        # nesse formato o leitor de tabela devolve as linhas de total no lugar
        # dos produtos (o pdfplumber funde os itens quando não há fios).
        if not d.itens:
            d.itens = self._itens_orcamento(texto)
        # TABELA DE COMPOSIÇÃO (ARTEMIS): sem quantidade nem unitário, só
        # parcelas. Vem por último porque é a leitura mais pobre — e só entrega
        # alguma coisa quando a soma das parcelas bate com o total anunciado.
        if not d.itens:
            d.itens = self._itens_composicao(texto, d.valor_total)

        def _com_desc(its):
            return sum(1 for it in its if (it.descricao or "").strip())

        def _com_preco(its):
            return sum(1 for it in its if any((getattr(it, k, "") or "").strip()
                       for k in ("preco_total_com", "preco_unit_com", "preco_unit_sem")))

        def _qual(its):
            # "bons" = têm DESCRIÇÃO e PREÇO; desempate pela quantidade de itens.
            bons = sum(1 for it in its if (it.descricao or "").strip() and any(
                (getattr(it, k, "") or "").strip() for k in ("preco_total_com", "preco_unit_com", "preco_unit_sem")))
            return (bons, len(its))

        def _fraco(its):    # falta descrição ou preço em algum item (ou está vazio)
            return (not its) or _com_desc(its) < len(its) or _com_preco(its) < len(its)

        # Tabelas nativas (rápido) quando o regex de linha perde descrição/preço.
        if metodo == "pdf" and _fraco(d.itens):
            tab = self._itens_tabelas(caminho)
            if tab and _qual(tab) > _qual(d.itens):
                d.itens = tab
                d.avisos.append("Itens lidos da tabela do PDF — confira quantidades e preços.")
        # Itens/valores num ANEXO (ex.: NEC, "descrito no Anexo II"): o Docling só
        # gastaria ~30 s p/ achar 0 itens — avisa e segue (não roda p/ itens).
        itens_em_anexo = bool(re.search(r"(descrit|constante|consta|relacionad|conforme)[^\n]{0,40}anexo",
                                        texto, re.I))
        # ASSERTIVIDADE (acerto > velocidade, escolha do usuário): usa o Docling
        # quando os ITENS ficam FRACOS (sem descrição/preço) — onde ele comprova-
        # damente ajuda (ex.: PADTEC). Quando roda, aproveita o markdown p/ preencher
        # campos VAZIOS de brinde (custo zero). NÃO dispara só por faltar campo: em
        # propostas de anexo/escaneadas (NEC, CIENA) o Docling não acha o dado e
        # gastaria 10-70 s à toa.
        # Sem precos suficientes no texto nao ha tabela de itens para achar: o
        # Docling gastaria dezenas de segundos para devolver zero.
        sem_tabela = not self._pode_ter_tabela(texto)
        if sem_tabela and not d.itens:
            LOG.info("proposta de preço fechado (%d preço(s) no texto) — Docling dispensado",
                     len(set(self._DINHEIRO_DOC.findall(texto))))
        # O POSICIONAL PRIMEIRO. Mesma tabela, leitura determinística, traz o
        # código do produto e não custa os segundos de carregar o modelo do
        # Docling. Só quando ele não achar cabeçalho de tabela é que o Docling
        # entra.
        if _fraco(d.itens) and caminho.lower().endswith(".pdf"):
            pos, tot_pos = self._itens_planilha_posicionada(caminho)
            if pos and _qual(pos) > _qual(d.itens):
                d.itens = pos
                if tot_pos:
                    d.valor_total = tot_pos
                d.avisos.append(
                    "%d itens lidos pela posição na folha (a tabela não tem "
                    "linhas de grade) — confira." % len(pos))
                rotulo = self._aplicar_filial(d, caminho)
                if rotulo:
                    d.avisos.append(
                        "Faturamento pela %s (%s), como indicado na planilha de preços."
                        % (rotulo, d.cnpj))
        if _fraco(d.itens) and not itens_em_anexo and not sem_tabela:
            md = _ler_docling(caminho) if metodo != "pdf" else _ler_docling_limitado(caminho)
            if md and md.strip():
                dg = self._itens_md(md)
                if dg and _qual(dg) > _qual(d.itens):
                    d.itens = dg
                    d.avisos.append("Itens extraídos via Docling — confira quantidades e preços.")
                antes = (d.fornecedor, d.cnpj, d.valor_total, d.cep, d.insc_est,
                         d.numero_proposta, d.garantia, d.prazo_entrega, d.endereco)
                d.fornecedor = d.fornecedor or self._fornecedor(md)   # só preenche vazios
                d.cnpj = d.cnpj or self._cnpj(md)
                d.valor_total = d.valor_total or self._valor_total(md)
                d.cep = d.cep or self._cep(md)
                d.insc_est = d.insc_est or self._insc_est(md)
                d.numero_proposta = d.numero_proposta or self._numero_proposta(md)
                d.garantia = d.garantia or self._garantia(md)
                d.prazo_entrega = d.prazo_entrega or self._prazo(md)
                d.endereco = d.endereco or self._endereco(md)
                depois = (d.fornecedor, d.cnpj, d.valor_total, d.cep, d.insc_est,
                          d.numero_proposta, d.garantia, d.prazo_entrega, d.endereco)
                if depois != antes:
                    d.avisos.append("Alguns campos foram completados via Docling (mais assertivo) — confira.")
        # PLANILHA DE PREÇOS SEM FIOS (NEC/Nokia): não há tabela para o pdfplumber
        # achar e o texto sai coluna a coluna. Só a posição das palavras resolve.
        if not d.itens and caminho.lower().endswith(".pdf"):
            pos, tot_pos = self._itens_planilha_posicionada(caminho)
            if pos:
                d.itens = pos
                if tot_pos:
                    d.valor_total = tot_pos
                d.avisos.append(
                    "%d itens vieram da planilha de preços do anexo (lida pela "
                    "posição na folha, porque a tabela não tem linhas de grade) "
                    "— confira." % len(pos))
                # A planilha diz por qual FILIAL o pedido é faturado; sem isso
                # a AF sai com o CNPJ da matriz e um endereço remendado.
                rotulo = self._aplicar_filial(d, caminho)
                if rotulo:
                    d.avisos.append(
                        "Faturamento pela %s (%s), como indicado na planilha de preços."
                        % (rotulo, d.cnpj))

        if not d.itens and itens_em_anexo:
            d.avisos.append("Os itens parecem estar num anexo da proposta — adicione-os manualmente na grade.")
        # PRAZO POR ITEM escrito em texto ("item 1 - ... item 2 - ..."): cada
        # trecho vai para o seu item, pela ordem em que eles foram lidos.
        por_item = self._prazo_por_item(texto)
        if por_item and d.itens:
            for n, txt in por_item.items():
                if 1 <= n <= len(d.itens) and not d.itens[n - 1].prazo:
                    d.itens[n - 1].prazo = txt

        d.objeto = self._objeto(texto, d.itens)
        # A quem a proposta foi endereçada: muitas trazem a filial da Eletronet
        # no cabeçalho, e repetir isso à mão numa lista de 26 é trabalho que a
        # folha já fez.
        # ESPECIFICAÇÃO TÉCNICA -> observações. Quando a descrição do item é curta
        # ("(1 Rack + 1 PDU)"), é ela que diz o que está sendo comprado.
        if not d.observacoes:
            d.observacoes = self._especificacao_tecnica(texto)
        # VARIAÇÃO CAMBIAL entra SEMPRE que existir: a banda muda de proposta
        # para proposta (esta usa dólar de referência R$ 5,4174 numa banda de
        # R$ 5,26 a R$ 5,56) e é o que define quanto será efetivamente pago.
        cambio = self._variacao_cambial(texto)
        if cambio and cambio not in d.observacoes:
            d.observacoes.append(cambio)

        # ROTAS na descrição dos itens ("Rota Guarulhos (SP) - Barreiro (MG)"):
        # em proposta de serviço as pontas da rota SÃO os locais de atendimento.
        if not d.entregas and not getattr(self, "_entregas_lidas", None):
            rotas = self._entregas_das_rotas(d.itens)
            if rotas:
                d.entregas = rotas
                d.avisos.append("%d local(is) vieram das rotas descritas nos itens "
                                "— confira." % len(rotas))

        # Locais de entrega que a própria proposta lista (quadro por localidade).
        lidas = getattr(self, "_entregas_lidas", None)
        if lidas and not d.entregas:
            vistos, unicas = set(), []
            for e in lidas:                       # a tabela repete o cabeçalho por folha
                ch = (e.get("nome", ""), e.get("endereco", ""))
                if ch not in vistos:
                    vistos.add(ch)
                    unicas.append(e)
            d.entregas = unicas
            d.avisos.append("%d local(is) de entrega vieram da proposta — confira."
                            % len(unicas))
        # BLOCOS POR LOCALIDADE ("PA - GUAMÁ" / "Entrega: ..."): a proposta já
        # enumera os locais, um por bloco. Vem depois das outras leituras
        # porque é a mais específica — só entra se nada antes achou nada.
        if not d.entregas:
            blocos = self._entregas_rotuladas(texto)
            if blocos:
                d.entregas = blocos
                d.avisos.append(
                    "%d local(is) de entrega vieram dos blocos da proposta "
                    "(%s) — confira."
                    % (len(blocos), ", ".join(b["nome"] for b in blocos[:4])))
        if not d.faturamentos:
            d.faturamentos = self._faturamento_da_proposta(texto, d.cnpj)
            if d.faturamentos:
                d.avisos.append(
                    "Faturamento da proposta: %s — confira."
                    % ", ".join("%s (%s)" % (f.get("uf", ""), f.get("cnpj", ""))
                                for f in d.faturamentos))
        # O local lido da proposta é só um nome; o cadastro tem o endereço.
        d.entregas = self.completar_entregas(d.entregas)

        # A nota sai da filial do estado onde a mercadoria entra: entregando em
        # GO, DF, MG e SP, faturam-se as quatro.
        por_uf = self._faturamento_das_ufs(d.entregas, d.faturamentos)
        if por_uf:
            d.faturamentos = list(d.faturamentos) + por_uf
            d.avisos.append("Faturamento por UF de entrega: %s — confira."
                            % ", ".join(f.get("uf", "") for f in por_uf))

        # PRAZO e GARANTIA em COLUNA da tabela: as regras de texto corrido não
        # acham nada (não há "garantia é de 24 meses" escrito em lugar nenhum),
        # mas os itens já vieram com o seu. O documento herda o resumo deles.
        for campo, chave in (("prazo_entrega", "prazo"), ("garantia", "garantia")):
            if getattr(d, campo, ""):
                continue
            resumo = self._resumir_duracoes([getattr(it, chave, "") for it in d.itens])
            if resumo:
                setattr(d, campo, resumo)
                if " a " in resumo or " / " in resumo:
                    d.avisos.append(
                        "%s difere entre os itens (%s) — o campo traz a faixa e cada "
                        "item guarda o seu." % (
                            "Prazo de entrega" if campo == "prazo_entrega" else "Garantia",
                            resumo))

        # Preco fechado: sem tabela de itens, mas com escopo e valor. A AF precisa
        # de uma linha dizendo o que esta sendo comprado — e o escopo diz.
        if not d.itens and not itens_em_anexo and sem_tabela:
            item = self._item_do_escopo(texto, d.objeto, d.valor_total)
            if item:
                d.itens = [item]
                d.avisos.append("Proposta de preço fechado: montei um item com o escopo "
                                "de fornecimento e o valor da proposta — confira a "
                                "quantidade e a descrição.")

        if not d.fornecedor:
            d.avisos.append("Fornecedor não identificado — preencha manualmente.")
        if not d.valor_total:
            d.avisos.append("Valor total não identificado — confira na proposta.")
        self._tirar_linhas_de_grupo(d)
        self._frete_como_item(d, texto)
        self._avisar_divergencia_total(d)
        LOG.info("extração de %s: método=%s, %d item(ns), %.2fs",
                 d.arquivo, metodo, len(d.itens), time.perf_counter() - t0)
        return d

    @staticmethod
    def _unitario(it: ItemAF):
        """Valor unitário do item; se não houver, deduz total ÷ quantidade."""
        unit = brl_para_float(it.preco_unit_com) or brl_para_float(it.preco_unit_sem)
        if unit is not None:
            return unit
        tot, qtd = brl_para_float(it.preco_total_com), brl_para_float(it.quantidade)
        return (tot / qtd) if (tot is not None and qtd) else None

    # Frete cobrado FORA da tabela de itens: "FRETE.....: CIF - VALOR: 7.000,00",
    # "TOTAL + DESPESAS : 13.256,44". É a explicação mais comum para a soma dos
    # itens não bater com o total da proposta.
    _FRETE = re.compile(r"\bfrete\b[^\n]{0,40}?valor\s*:?\s*(\d[\d.]*,\d{2})", re.I)
    # No bloco de totais da ALG a linha é só "Frete R$ 520,00" — sem a palavra
    # "valor" que o padrão acima exige. Ancorada na linha inteira de propósito:
    # solta, "frete" casaria com a cláusula que explica a modalidade CIF.
    _FRETE_LINHA = re.compile(
        r"(?m)^[ \t]*Frete[ \t]*:?[ \t]*R\$?[ \t]*(\d[\d.]*,\d{2})[ \t]*$", re.I)

    def _valor_frete(self, t: str) -> float | None:
        m = self._FRETE.search(t or "") or self._FRETE_LINHA.search(t or "")
        return brl_para_float(m.group(1)) if m else None

    def _faturamento_da_proposta(self, texto: str, cnpj_forn: str) -> list[dict]:
        """TODAS as filiais da Eletronet que a proposta nomeia, casadas pelo CNPJ.

        Só CNPJ: é identidade (14 dígitos são de um estabelecimento só), enquanto
        nome e cidade são indício e casariam a filial errada. O CNPJ do próprio
        FORNECEDOR também está na folha — fica de fora pela comparação direta.

        TODAS, no plural, e isso já foi um defeito: a função devolvia no
        `return` de dentro do laço, ou seja, parava na PRIMEIRA que encontrasse.
        A ARTEMIS 207.2026 lista quatro (PA, PR, BA e RS), uma por localidade de
        entrega, e a AF saía com uma só — a que viesse antes no catálogo, que
        nem é a primeira do documento.

        A ordem de saída é a ORDEM DA PROPOSTA, não a do catálogo: o documento
        agrupa entrega e faturamento por localidade, e manter a sequência deixa
        as duas listas na mesma ordem para quem for conferir.
        """
        try:
            from .dados_eletronet import locais_faturamento
            locais = locais_faturamento()
        except Exception as exc:                 # catálogo é conveniência, não trava
            LOG.warning("não consegui ler os locais de faturamento: %s", exc)
            return []
        so_num = lambda x: re.sub(r"\D", "", str(x or ""))     # noqa: E731
        # ordem de APARIÇÃO, sem repetir
        vistos, ordem = set(), []
        for m in re.finditer(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}", texto or ""):
            n = so_num(m.group(0))
            if n not in vistos:
                vistos.add(n)
                ordem.append(n)
        alvo = so_num(cnpj_forn)
        por_cnpj = {so_num(l.get("cnpj")): l for l in locais if l.get("cnpj")}
        achados = []
        for n in ordem:
            if n == alvo or n not in por_cnpj:
                continue
            loc = por_cnpj[n]
            achados.append(dict(loc))
            LOG.info("faturamento identificado na proposta: %s (%s)",
                     loc.get("uf"), loc.get("cnpj"))
        return achados

    # Cabeçalho de bloco por localidade: "PA - GUAMÁ", "RS - PASSO FUNDO".
    _CAB_LOCALIDADE = re.compile(
        r"^[ \t]*([A-Z]{2})[ \t]*[-–][ \t]*([A-ZÀ-Ÿ0-9][A-ZÀ-Ÿ0-9 .'/\-]{1,48})[ \t]*$")
    # "Entrega: Avenida Perimetral, 33 - Guamá - Belém/PA"
    _LINHA_ENTREGA = re.compile(r"^[ \t]*Entrega[ \t]*:[ \t]*(.+?)[ \t]*$", re.I)
    # o fim do endereço costuma ser "Município/UF"
    _FIM_MUNICIPIO_UF = re.compile(r"([A-Za-zÀ-ÿ.'\- ]{2,40})/([A-Z]{2})[ \t]*$")

    # conectivos que ficam em minúscula num nome próprio em português
    _MINUSCULAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "em"}

    @classmethod
    def _nome_proprio(cls, t: str) -> str:
        """"FOZ DO IGUAÇU" -> "Foz do Iguaçu".

        O `.title()` sozinho devolve "Foz Do Iguaçu": ele não sabe que "do" é
        conectivo. Aqui o catálogo ainda corrigiria (ele casa sem acento e sem
        caixa), mas quando o POP não está cadastrado é ESTE nome que vai para a
        AF — e sai torto.
        """
        palavras = " ".join(str(t or "").split()).lower().split(" ")
        return " ".join(p if i and p in cls._MINUSCULAS else p.capitalize()
                        for i, p in enumerate(palavras))

    def _entregas_rotuladas(self, texto: str) -> list[dict]:
        """Locais de entrega que a proposta LISTA, um bloco por localidade.

        A ARTEMIS 207.2026 escreve assim, e traz tudo pronto:

            PA - GUAMÁ
            Entrega: Avenida Perimetral, 33 - Guamá - Belém/PA
            ELETRONET S.A - FILIAL | CNPJ: ... | UF: PA
            Faturamento: ...

        O NOME vem do cabeçalho do bloco (a localidade), não do endereço: é ele
        que casa com o POP do cadastro — "Guamá", "Foz do Iguaçu", "Barreiras",
        "Passo Fundo". O endereço e o município ficam como estão escritos, e
        `completar_entregas` depois troca pelo registro do cadastro quando
        reconhecer o POP, preenchendo a sigla.

        Sem isto a AF saía com ZERO locais numa proposta que os enumera — e
        preencher quatro endereços à mão é justamente o trabalho que o app
        existe para evitar.
        """
        achados, cab = [], None
        for linha in (texto or "").splitlines():
            m = self._CAB_LOCALIDADE.match(linha)
            if m:
                cab = (m.group(1), self._nome_proprio(m.group(2)))
                continue
            m = self._LINHA_ENTREGA.match(linha)
            if not m:
                continue
            end = " ".join(m.group(1).split())
            uf, nome = (cab or ("", ""))
            mun = ""
            mm = self._FIM_MUNICIPIO_UF.search(end)
            if mm:
                mun = mm.group(1).strip(" -")
                uf = uf or mm.group(2)
            if not nome:
                nome = mun
            if nome:
                achados.append({"nome": nome, "sigla": "", "endereco": end,
                                "municipio": mun, "uf": uf})
            cab = None            # cada cabeçalho serve a UMA entrega
        return achados

    # "Guarulhos (SP)", "Barreiro (MG)" — uma ponta do serviço.
    _CIDADE_UF = re.compile(r"([A-ZÀ-Ú][A-Za-zÀ-ÿ.'\- ]{2,30}?)\s*\(\s*([A-Z]{2})\s*\)")

    def _entregas_das_rotas(self, itens: list) -> list[dict]:
        """Locais de entrega escritos na descrição dos itens, em forma de rota.

        Estreita de propósito: só descrição que fala de ROTA ou TRECHO. Um
        "Cidade (UF)" solto aparece em endereço de fornecedor, em razão social e
        em rodapé, e viraria destino de entrega onde não há entrega nenhuma.
        """
        vistos, out = set(), []
        for it in itens or []:
            desc = getattr(it, "descricao", "") or ""
            if not re.search(r"\brotas?\b|\btrechos?\b", desc, re.I):
                continue
            for nome, uf in self._CIDADE_UF.findall(desc):
                nome = re.sub(r"\s{2,}", " ", nome).strip(" .-–—")
                # "Rota Guarulhos" -> a palavra Rota não faz parte do nome
                nome = re.sub(r"^(?:rota|trecho|de|para|até)\s+", "", nome, flags=re.I).strip()
                if len(nome) < 3 or nome.lower() in ("total", "valor"):
                    continue
                chave = (nome.lower(), uf)
                if chave in vistos:
                    continue
                vistos.add(chave)
                out.append({"nome": nome, "sigla": "", "municipio": nome,
                            "uf": uf, "endereco": ""})
        return out

    def completar_entregas(self, entregas: list) -> list[dict]:
        """Troca o local lido da proposta pelo registro do cadastro de POPs.

        A proposta diz "Fortaleza"; o cadastro sabe que é o POP FLA, na Av.
        Presidente Costa e Silva, 4677, em Fortaleza/CE. Preenchido à mão o
        campo sairia assim — lido da proposta, saía só o nome.

        O que a proposta trouxe NÃO é descartado: vira o valor de partida, e o
        cadastro só preenche o que falta (o endereço, a sigla, o município).
        """
        if not entregas:
            return entregas
        try:
            from .dados_eletronet import pops_entrega
            pops = pops_entrega()
        except Exception as exc:               # cadastro é conveniência, não trava
            LOG.warning("não consegui ler o cadastro de POPs: %s", exc)
            return entregas

        def chave(t):
            return re.sub(r"[^a-z0-9]+", " ", self._sem_acento(str(t or "")).lower()).strip()

        out = []
        for e in entregas:
            nome, uf = chave(e.get("nome")), str(e.get("uf", "")).strip().upper()
            if not nome:
                out.append(e)
                continue
            # UF da proposta é filtro: "Paulo Afonso" (BA) e "Paulo Afonso III"
            # (AL) são lugares diferentes
            candidatos = [p for p in pops
                          if not uf or str(p.get("uf", "")).strip().upper() == uf]
            exatos = [p for p in candidatos
                      if chave(p.get("nome")) == nome or chave(p.get("sigla")) == nome]
            if not exatos:
                # parecido só resolve quando é ÚNICO: "Fortaleza" casa com seis
                # registros, incluindo "Angola Cable - Fortaleza"
                perto = [p for p in candidatos if nome in chave(p.get("nome"))]
                exatos = perto if len(perto) == 1 else []
            if not exatos:
                out.append(e)                  # não está no cadastro: fica como veio
                continue
            # entre dois certos, o que tem ENDEREÇO — completar é o objetivo
            exatos.sort(key=lambda p: (bool(str(p.get("endereco", "")).strip()),
                                       bool(str(p.get("sigla", "")).strip())), reverse=True)
            achado = exatos[0]
            juntos = dict(e)
            for campo in ("nome", "sigla", "municipio", "uf", "endereco"):
                if str(achado.get(campo, "")).strip():
                    juntos[campo] = achado[campo]
            out.append(juntos)
        return out

    def _faturamento_das_ufs(self, entregas: list, ja_tem: list) -> list[dict]:
        """Uma filial da Eletronet por UF de entrega, na ordem em que aparecem.

        A nota sai da filial do estado onde a mercadoria entra: entregando em
        GO, DF, MG e SP, fatura-se pelas quatro. `ja_tem` são as filiais que já
        entraram por outro caminho (o CNPJ escrito na proposta) — elas não são
        repetidas nem substituídas.
        """
        ufs = []
        for e in entregas or []:
            uf = str((e or {}).get("uf", "")).strip().upper()
            if len(uf) == 2 and uf not in ufs:
                ufs.append(uf)
        if not ufs:
            return []
        try:
            from .dados_eletronet import locais_faturamento
            locais = locais_faturamento()
        except Exception as exc:
            LOG.warning("não consegui ler os locais de faturamento: %s", exc)
            return []
        tinha = {str(f.get("uf", "")).strip().upper() for f in (ja_tem or [])}
        out = []
        for uf in ufs:
            if uf in tinha:
                continue
            # UF com mais de uma filial no catálogo (PA e ES têm duas): fica a
            # primeira, e o aviso pede conferência.
            loc = next((f for f in locais
                        if str(f.get("uf", "")).strip().upper() == uf), None)
            if loc:
                out.append(dict(loc))
                tinha.add(uf)
        return out

    def _frete_como_item(self, d: DadosProposta, texto: str) -> None:
        """O frete cobrado FORA da tabela vira um item, quando a conta pede.

        Só entra se `soma dos itens + frete` fechar com o total da proposta:
        numa proposta em que o frete já está no preço de cada linha, o item
        acrescentado contaria o frete duas vezes.
        """
        if not d.itens or any((i.descricao or "").strip().lower() == "frete"
                              for i in d.itens):
            return
        frete = self._valor_frete(texto)
        total = brl_para_float(d.valor_total)
        if not frete or not total:
            return
        soma = 0.0
        for it in d.itens:
            v = brl_para_float(it.preco_total_com)
            if v is None:
                unit, qtd = self._unitario(it), brl_para_float(it.quantidade)
                v = (unit * qtd) if (unit is not None and qtd) else None
            if v is None:
                return                       # sem a soma não dá para provar nada
            soma += v
        if abs((soma + frete) - total) > max(0.01 * total, 1.0):
            return                           # a conta não fecha: não é este o caso
        d.itens.append(ItemAF(descricao="Frete", quantidade="1",
                              preco_unit_com=float_para_brl(frete),
                              preco_total_com=float_para_brl(frete)))
        d.avisos.append("O frete (R$ %s) estava fora da tabela e entrou como item — "
                        "agora os itens somam o total da proposta."
                        % float_para_brl(frete))

    def _tirar_linhas_de_grupo(self, d: DadosProposta) -> None:
        """Tira da lista os SUBTOTAIS que vieram com cara de produto.

        Na Padtec a linha "Equipamentos -" não tem quantidade nem código e o
        total dela é a soma das linhas de baixo — um subtotal de seção. Entrando
        na lista, a soma dos itens dava o DOBRO da proposta.

        A regra de NOME não pega (a linha se chama "Equipamentos"); quem pega é
        a conta. Sem quantidade e sem código, porque um produto de verdade tem
        pelo menos um dos dois.

        POR QUE NÃO BASTA "a soma de todas as outras"
        ---------------------------------------------
        Era assim que esta função funcionava, e ela só enxergava UM subtotal,
        aquele que cobria a tabela inteira. A Padtec 2026-2023 tem DOIS, cada um
        cobrindo só a sua seção:

            Equipamentos -                  573.711,44   <- cobre as 2 de baixo
              Duplo Muxponder 400G   x5     565.628,22
              Unidade de Ventilação  x5       8.083,23
            Licenças e Software -             1.020,41   <- cobre a de baixo
              Licença interface DWDM x10      1.020,41

        Nenhum dos dois é "a soma de todas as outras", então os dois passavam e
        a soma dava 1.149.463,71 para uma proposta de 574.731,85 — o dobro.

        Agora a varredura é por SEÇÃO: o subtotal cobre a sequência de linhas
        vizinhas até onde o próximo subtotal começa. Vale para baixo e para
        cima, porque há tabela que põe o subtotal no fim do grupo.

        E o ORÁCULO fecha a regra: só remove se o que sobrar bater com o total
        anunciado. Sem isso, "linha sem quantidade cuja conta casa" tiraria um
        produto de verdade da AF — e item que some é pior que item a mais,
        porque ninguém percebe a falta.
        """
        if len(d.itens) < 3:                 # com 2, "a soma das outras" é o outro
            return
        totais = [brl_para_float(i.preco_total_com) for i in d.itens]
        if any(v is None for v in totais):
            return

        def sem_identidade(it) -> bool:
            """Produto de verdade costuma ter quantidade OU código."""
            return not (it.quantidade or "").strip() and not (it.codigo or "").strip()

        # CANDIDATO é quem a CONTA acusa, não quem "parece" subtotal.
        # A linha "Licenças e Software de Gerência -" da Padtec traz quantidade
        # 1 e mesmo assim é subtotal: exigir "sem quantidade" a deixava passar,
        # e aí sobrava 1.020,41 contado duas vezes — o oráculo então recusava a
        # remoção do outro subtotal também, e nada era corrigido.
        n = len(d.itens)
        candidatos: set[int] = set()
        for i in range(n):
            for passo in (1, -1):            # a seção pode estar abaixo ou acima
                acc = 0.0
                j = i + passo
                while 0 <= j < n:
                    acc += totais[j]
                    if abs(totais[i] - acc) <= max(0.01, 0.001 * abs(acc)):
                        candidatos.add(i)
                        break
                    j += passo
                if i in candidatos:
                    break
        if not candidatos:
            return

        # ORÁCULO: sem o total anunciado não há como conferir, e aí não se mexe.
        alvo = brl_para_float(d.valor_total) if d.valor_total else None
        if alvo is None:
            return

        def fecha(conjunto) -> bool:
            if not conjunto or len(conjunto) >= n:
                return False
            sobra = sum(v for k, v in enumerate(totais) if k not in conjunto)
            return abs(sobra - alvo) <= max(0.02, 0.001 * abs(alvo))

        # QUAIS candidatos remover, de fato. Não dá para remover todos: na
        # Padtec o último produto (1.020,41) espelha o subtotal logo acima dele
        # e entra na lista de candidatos sem ser subtotal. Tirando os três, a
        # conta não fecha; tirando só o "sem quantidade", também não. O certo
        # ali é {Equipamentos, Licenças} — e quem sabe disso é a conta.
        #
        # Então prova-se combinação por combinação, das MENORES para as
        # maiores: remover de menos é mais seguro do que remover demais, e a
        # primeira que bate com o total anunciado é a resposta. São poucos
        # candidatos; o teto existe só para o caso patológico.
        import itertools
        ordenados = sorted(candidatos,
                           key=lambda i: (not sem_identidade(d.itens[i]), i))
        if len(ordenados) > 12:
            return
        remover = None
        for tamanho in range(1, len(ordenados) + 1):
            for comb in itertools.combinations(ordenados, tamanho):
                if fecha(set(comb)):
                    remover = set(comb)
                    break
            if remover:
                break
        if not remover:
            return

        nomes = [(d.itens[k].descricao or "")[:34] for k in sorted(remover)]
        d.itens = [it for k, it in enumerate(d.itens) if k not in remover]
        d.avisos.append(
            "%s saiu da lista: era subtotal de seção (o valor é a soma das "
            "linhas do grupo), não produto. Agora os itens somam o total."
            % ("; ".join(repr(x) for x in nomes)))

    def _avisar_divergencia_total(self, d: DadosProposta):
        """Soma os totais dos itens e compara com o valor total da proposta —
        avisa se divergir (tolerância de 1% ou R$ 1,00)."""
        soma = 0.0
        achou = False
        for it in d.itens:
            v = brl_para_float(it.preco_total_com)
            if v is None:
                unit, qtd = self._unitario(it), brl_para_float(it.quantidade)
                v = (unit * qtd) if (unit is not None and qtd) else None
            if v is not None:
                soma += v
                achou = True
        total = brl_para_float(d.valor_total)
        # SEM TOTAL NENHUM e com itens que somam: a soma É o total. Acontece
        # quando a proposta escreve o total só dentro da tabela, sem "R$" e sem
        # rótulo (Padtec Furnas-Brasília) — antes a AF saía com o valor vazio.
        if achou and soma and not total:
            d.valor_total = float_para_brl(soma)
            # o aviso de "não identificado" foi escrito lá atrás e acabou de
            # deixar de ser verdade — dois recados sobre o mesmo campo, um
            # deles falso, fazem a pessoa parar de ler os avisos
            d.avisos[:] = [a for a in d.avisos
                           if "Valor total não identificado" not in a]
            d.avisos.append(
                "O valor total não vem anunciado na proposta; usei a soma dos "
                "itens (R$ %s) — confira." % float_para_brl(soma))
            return
        if achou and total and abs(soma - total) > max(0.01 * total, 1.0):
            # DIVERGÊNCIA COM EXPLICAÇÃO: quando a diferença é exatamente o frete
            # cobrado fora da tabela, dizer isso. Aviso sem motivo faz duvidar do
            # documento inteiro — e aqui não há nada errado: o total da proposta
            # inclui uma despesa que não é linha de produto.
            frete = self._valor_frete(getattr(self, "ultimo_texto", "") or "")
            if frete and abs((soma + frete) - total) <= max(0.01 * total, 1.0):
                d.avisos.append(
                    f"A soma dos itens (R$ {float_para_brl(soma)}) mais o frete "
                    f"(R$ {float_para_brl(frete)}) fecha com o total da proposta "
                    f"(R$ {float_para_brl(total)}) — o frete é cobrado fora da tabela.")
                return
            texto = getattr(self, "ultimo_texto", "") or ""

            # O IPI cobrado em linha à parte (DIACOM): os itens saem com ICMS e
            # o total soma o IPI depois. Nada errado — mas o aviso precisa
            # dizer isso, senão faz duvidar do documento inteiro.
            mi = re.search(r"Valor\s+IPI\s*:?\s*R?\$?\s*([\d.]+,\d{2})", texto, re.I)
            ipi = brl_para_float(mi.group(1)) if mi else None
            if ipi and abs((soma + ipi) - total) <= max(0.01 * total, 1.0):
                d.avisos.append(
                    f"A soma dos itens (R$ {float_para_brl(soma)}) mais o IPI "
                    f"(R$ {float_para_brl(ipi)}) fecha com o total da proposta "
                    f"(R$ {float_para_brl(total)}) — o IPI é cobrado em linha "
                    f"separada, fora do preço dos itens.")
                return

            rotulado = self._valor_total_rotulado(texto)
            if rotulado:
                # PREFIXO QUE FECHA: se os N primeiros itens dão exatamente o
                # total anunciado, os de baixo não são do fornecimento — são
                # opcionais de tabela (adicional noturno, visita extra). Deixá-
                # los na AF cobra do cliente o que ele não pediu.
                parcial = 0.0
                for k, it in enumerate(d.itens, 1):
                    v = brl_para_float(it.preco_total_com)
                    if v is None:
                        u, q = self._unitario(it), brl_para_float(it.quantidade)
                        v = (u * q) if (u is not None and q) else 0.0
                    parcial += v or 0.0
                    if k < len(d.itens) and abs(parcial - total) <= 0.01:
                        fora = d.itens[k:]
                        d.itens = d.itens[:k]
                        d.avisos.append(
                            "%d item(ns) saíram da lista: os %d primeiros já somam "
                            "exatamente o total anunciado (R$ %s), então o resto é "
                            "preço opcional de tabela — %s."
                            % (len(fora), k, float_para_brl(total),
                               "; ".join((i.descricao or "")[:28] for i in fora[:4])))
                        return
                d.avisos.append(
                    f"⚠ Soma dos itens (R$ {float_para_brl(soma)}) difere do valor total "
                    f"da proposta (R$ {float_para_brl(total)}).")
                return

            # NÃO TROCAR O NÚMERO DO FORNECEDOR. Cheguei a fazer isto aqui —
            # adotar a soma quando o total não vinha de um rótulo conhecido —
            # e a suíte derrubou, com razão: "sem rótulo" não é "não
            # anunciado", é "anunciado de um jeito que eu não reconheço". A
            # lista de rótulos é incompleta por natureza (não reconhecia o
            # "Total R$ 44.829,12" da Precision), e o preço do engano é uma AF
            # cobrando a mais. Divergência sem explicação vira alerta.
            d.avisos.append(
                f"⚠ Soma dos itens (R$ {float_para_brl(soma)}) difere do valor total "
                f"da proposta (R$ {float_para_brl(total)}).")

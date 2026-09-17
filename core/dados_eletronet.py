"""
dados_eletronet.py — listas de apoio lidas do template oficial empacotado
(`assets/modelo_af.xlsm`): catálogo de fornecedores, filiais de faturamento e
POPs de entrega. Para atualizar, basta trocar o .xlsm.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import unicodedata
from functools import lru_cache

from openpyxl import load_workbook

from .log import get_logger

LOG = get_logger("dados")

from .caminhos import recurso, dado          # separa empacotado × gravável (.exe)

ASSETS = recurso("assets")
MODELO_XLSM = os.path.join(ASSETS, "modelo_af.xlsm")
MODELO_AS_XLSM = os.path.join(ASSETS, "modelo_as.xlsm")
MODELO_CPM = os.path.join(ASSETS, "modelo_cpm.xlsx")   # Coleta de Preços (CPM/CPS)
LOGO = os.path.join(ASSETS, "eletronet_logo.jpeg")

# Cadastros feitos pelo usuário (POPs, locais de entrega, fornecedores, agenda)
# ficam num JSON — NUNCA gravamos no .xlsm oficial. São lidos a cada chamada e
# mesclados ao catálogo do template.
RAIZ = dado()                              # ao lado do .exe (ou a pasta do projeto)

# Nome do arquivo que, colocado AO LADO do executável, faz o cadastro ser da
# EQUIPE: todo mundo que rodar aquele .exe grava e lê nele. Pensado para o .exe
# numa pasta de rede — sem configurar nada em cada máquina.
ARQ_EQUIPE = "cadastro-da-equipe.json"


# ===========================================================================
# ONDE ESTÃO OS CADASTROS — configuração da MÁQUINA (não do cadastro)
#
# Este arquivinho fica sempre em %APPDATA%\AutoAF e guarda uma coisa só: para
# qual arquivo de cadastros esta máquina deve olhar. Ele não pode morar dentro
# do próprio dados_usuario.json, porque é ele que diz onde o dados_usuario.json
# está. É o que permite o setor inteiro trabalhar sobre a MESMA base numa pasta
# de rede: quem cadastra um POP cadastra para todos.
# ===========================================================================
def _pasta_perfil() -> str:
    pasta = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AutoAF")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _arquivo_config() -> str:
    return os.path.join(_pasta_perfil(), "config.json")


def _config() -> dict:
    try:
        with open(_arquivo_config(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        LOG.warning("config.json ilegível: %s", exc)
        return {}


def _arquivo_dados() -> str:
    r"""Onde ficam os cadastros do usuário.

    Em %APPDATA%\AutoAF, e NÃO ao lado do executável: um .exe "onefile" não
    guarda nada dentro de si (ele se descompacta num temporário que é apagado ao
    fechar), então o app precisa de um lugar fixo. Guardando no perfil do
    usuário, o executável pode ser movido, copiado ou substituído à vontade que
    os cadastros continuam sendo encontrados.

    Na 1ª execução, um dados_usuario.json que esteja ao lado do app (formato
    antigo) é TRAZIDO para cá — ninguém perde o que já cadastrou.

    Para uma equipe compartilhar os mesmos cadastros, aponte a variável de
    ambiente GERADORAF_DADOS para um arquivo na pasta de rede.
    """
    escolhido = os.environ.get("GERADORAF_DADOS") or _config().get("dados")
    if escolhido:
        return escolhido

    # CADASTRO DA EQUIPE POR COLOCAÇÃO: um arquivo com este nome AO LADO do
    # executável vale para todo mundo que rodar aquele executável. É o caso de
    # deixar o .exe numa pasta de rede: sem esta regra, o antigo
    # "dados_usuario.json" ao lado do app era COPIADO para o perfil de cada um
    # na primeira execução — e a partir dali cada máquina seguia com a sua
    # cópia, divergindo em silêncio. Aqui o arquivo é usado no lugar, não
    # copiado, e não precisa configurar máquina por máquina.
    equipe = dado(ARQ_EQUIPE)
    if os.path.exists(equipe):
        try:
            with open(equipe, "r+", encoding="utf-8"):      # exige poder ESCREVER
                pass
            return equipe
        except OSError as exc:
            LOG.warning("%s existe mas está somente-leitura (%s) — usando o perfil local",
                        ARQ_EQUIPE, exc)

    antigo = dado("dados_usuario.json")
    try:
        pasta = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AutoAF")
        os.makedirs(pasta, exist_ok=True)
        alvo = os.path.join(pasta, "dados_usuario.json")
        if not os.path.exists(alvo) and os.path.exists(antigo):
            shutil.copyfile(antigo, alvo)                     # migração, uma vez só
            if os.path.exists(antigo + ".bak"):
                shutil.copyfile(antigo + ".bak", alvo + ".bak")
            LOG.info("cadastros migrados p/ %s", alvo)
        return alvo
    except OSError as exc:            # perfil sem permissão: segue no modo antigo
        LOG.warning("não consegui usar a pasta do usuário (%s) — mantendo %s", exc, antigo)
        return antigo


USER_JSON = _arquivo_dados()
_CHAVE = {"fornecedor": "fornecedores", "fornecedores": "fornecedores",
          "faturamento": "faturamento", "pop": "pops", "pops": "pops", "entrega": "pops"}


def onde_estao_os_dados() -> dict:
    """Para a tela: qual arquivo está em uso e se ele é compartilhado."""
    por_ambiente = bool(os.environ.get("GERADORAF_DADOS"))
    por_colocacao = os.path.basename(USER_JSON) == ARQ_EQUIPE
    return {"arquivo": USER_JSON, "pasta": os.path.dirname(USER_JSON),
            "compartilhado": bool(_config().get("dados")) or por_ambiente or por_colocacao,
            "por_ambiente": por_ambiente,          # variável de ambiente manda: a tela não muda
            "por_colocacao": por_colocacao,        # veio do arquivo ao lado do .exe
            "arquivo_equipe": ARQ_EQUIPE,
            "padrao": os.path.join(_pasta_perfil(), "dados_usuario.json")}


def usar_dados_em(caminho: str) -> dict:
    """Aponta ESTA máquina para outro arquivo de cadastros (pasta de rede).

    Se o arquivo de destino ainda não existe, o que já está cadastrado aqui é
    COPIADO para lá — quem configura primeiro semeia a base da equipe em vez de
    começar do zero. Se já existe, nada é sobrescrito: a máquina passa a ler o
    que a equipe construiu.
    """
    global USER_JSON
    caminho = str(caminho or "").strip()
    if not caminho:                                    # voltar ao arquivo local
        cfg = _config()
        cfg.pop("dados", None)
        _gravar_config(cfg)
        USER_JSON = _arquivo_dados()
        LOG.info("cadastros de volta ao perfil local: %s", USER_JSON)
        return {"ok": True, **onde_estao_os_dados()}

    if os.path.isdir(caminho):
        # Apontaram para a PASTA. Qual arquivo dentro dela?
        # Se o cadastro da equipe já está lá, é ELE — senão a pessoa criaria um
        # segundo arquivo ao lado do primeiro, veria o cadastro vazio e o setor
        # ficaria dividido em dois grupos sem ninguém perceber.
        # Não havendo nenhum, cria o da equipe: assim a pasta serve tanto para
        # quem aponta pela tela quanto para quem roda o .exe de dentro dela.
        pasta_alvo = caminho
        for nome in (ARQ_EQUIPE, "dados_usuario.json"):
            if os.path.exists(os.path.join(pasta_alvo, nome)):
                caminho = os.path.join(pasta_alvo, nome)
                break
        else:
            caminho = os.path.join(pasta_alvo, ARQ_EQUIPE)
    pasta = os.path.dirname(os.path.abspath(caminho))
    if not os.path.isdir(pasta):
        return {"ok": False, "erro": f"A pasta não existe ou não está acessível: {pasta}"}
    novo = not os.path.exists(caminho)
    try:
        if novo:
            if os.path.exists(USER_JSON):
                shutil.copyfile(USER_JSON, caminho)    # semeia com o que já existe aqui
            else:
                with open(caminho, "w", encoding="utf-8") as f:
                    json.dump({}, f)
        else:                                          # já existe: só confere que dá p/ escrever
            with open(caminho, "r+", encoding="utf-8"):
                pass
    except OSError as exc:
        return {"ok": False, "erro": f"Sem acesso de escrita a {caminho}: {exc}"}

    cfg = _config()
    cfg["dados"] = caminho
    _gravar_config(cfg)
    USER_JSON = caminho
    LOG.info("cadastros compartilhados em %s (%s)", caminho, "criado" if novo else "já existia")
    return {"ok": True, "criado": novo, **onde_estao_os_dados()}


def _gravar_config(cfg: dict):
    alvo = _arquivo_config()
    tmp = f"{alvo}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, alvo)


def _usuario() -> dict:
    """Lê os cadastros do usuário; se o JSON estiver corrompido (crash/sync do
    OneDrive no meio da escrita), cai no backup .bak em vez de perder tudo."""
    for caminho in (USER_JSON, USER_JSON + ".bak"):
        try:
            with open(caminho, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                if caminho.endswith(".bak"):
                    LOG.warning("dados_usuario.json ilegível — usando o backup .bak")
                return d
        except FileNotFoundError:
            continue
        except Exception as exc:
            LOG.warning("falha ao ler %s: %s", os.path.basename(caminho), exc)
    return {}


# Campos identificadores por tipo, p/ casar o registro a remover/deduplicar.
_IDS = {"fornecedores": ("empresa", "apelido", "cnpj"),
        "faturamento": ("razao_social", "uf", "cnpj"),
        "pops": ("nome", "sigla", "municipio")}

# ===========================================================================
# IDENTIDADE QUE SOBREVIVE A UMA ATUALIZAÇÃO
#
# O catálogo base viaja DENTRO do executável; os cadastros do usuário ficam em
# %APPDATA%. Quando sai uma versão nova, o base muda e o do usuário não — e é aí
# que aparecia o estrago: o usuário corrigia "Gravatai 3", a versão nova
# escrevia "Gravataí 3" (com acento), o "ocultos" casava por texto exato, não
# reconhecia mais o item, e o POP voltava DUPLICADO. O mesmo valia para item
# ocultado, que ressuscitava sozinho.
#
# A saída é comparar por uma identidade que não depende da grafia:
#   • CNPJ (só dígitos) para fornecedor e faturamento;
#   • SIGLA do POP (sem acento, sem pontuação) para os locais de entrega.
# E, quando não há identidade forte, comparar o texto SEM acento e sem caixa.
# ===========================================================================
_IDENT_FORTE = {"fornecedores": "cnpj", "faturamento": "cnpj", "pops": "sigla"}


def _norm_id(v) -> str:
    """Reduz um valor à sua forma comparável: sem acento, sem caixa, sem
    pontuação. CNPJ vira só os dígitos; "GTI-TRI" e "gti tri" viram "gtitri"."""
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _chave_forte(chave: str, reg: dict) -> str:
    """A identidade estável do registro, ou "" se ele não tiver uma."""
    campo = _IDENT_FORTE.get(chave)
    if not campo:
        return ""
    v = _norm_id((reg or {}).get(campo))
    return v if len(v) >= 3 else ""        # sigla/CNPJ curto demais não identifica nada


# ===========================================================================
# VERSÃO DO APP E DO ARQUIVO DE DADOS
#
# O arquivo do usuário sobrevive à troca do executável — é justamente por isso
# que ele precisa dizer de que versão veio. Sem esse carimbo, uma versão futura
# que mude o formato de um campo não teria como saber se já converteu aquele
# arquivo, e converteria duas vezes (ou nenhuma).
#
# Regra ao lançar uma versão:
#   • mudou só o código/catálogo? mexa em VERSAO_APP e pronto;
#   • mudou o FORMATO do dados_usuario.json? suba ESQUEMA_DADOS e escreva o
#     passo correspondente em _MIGRACOES.
# ===========================================================================
VERSAO_APP = "0.7"
ESQUEMA_DADOS = 2


def _mig_2_licoes_saneadas(d: dict) -> str:
    """1 → 2: as lições da versão antiga eram fatias de 42 caracteres cortadas
    no meio da palavra e faziam o app preencher campo errado. Saem todas; o app
    reaprende sozinho na próxima correção."""
    licoes_ = d.get("licoes") or {}
    n = sum(len(v) for forn in licoes_.values() for v in (forn or {}).values())
    if not n:
        return ""
    d["licoes"] = {}
    return f"{n} lição(ões) de leitura antigas descartadas (serão reaprendidas)"


# esquema alvo -> (descrição, função)
_MIGRACOES = {
    2: ("lições de leitura no formato novo", _mig_2_licoes_saneadas),
}


def migrar() -> dict:
    """Põe o arquivo do usuário no esquema atual. Roda na abertura do app.

    Antes de qualquer conversão guarda uma cópia carimbada com o esquema de
    origem — se uma versão nova fizer besteira, o arquivo anterior continua ali,
    inteiro, e não escondido atrás do .bak rotativo.
    """
    d = _usuario()
    if not d:                                   # instalação nova: só carimba
        with _editando() as (novo, alvo):
            novo["versao"] = ESQUEMA_DADOS
            novo["versao_app"] = VERSAO_APP
            alvo["salvar"] = True
        return {"de": ESQUEMA_DADOS, "para": ESQUEMA_DADOS, "passos": []}

    de_ = int(d.get("versao") or 1)
    if de_ >= ESQUEMA_DADOS and d.get("versao_app") == VERSAO_APP:
        return {"de": de_, "para": de_, "passos": []}

    if de_ < ESQUEMA_DADOS and os.path.exists(USER_JSON):
        copia = f"{USER_JSON}.esquema{de_}"
        try:
            if not os.path.exists(copia):
                shutil.copyfile(USER_JSON, copia)
                LOG.info("cópia de segurança antes de migrar: %s", os.path.basename(copia))
        except OSError as exc:
            LOG.warning("não consegui copiar antes de migrar: %s", exc)

    passos = []
    with _editando() as (dados, alvo):
        atual = int(dados.get("versao") or 1)
        for alvo_v in sorted(_MIGRACOES):
            if atual < alvo_v:
                rotulo, func = _MIGRACOES[alvo_v]
                try:
                    detalhe = func(dados) or rotulo
                    passos.append(f"v{alvo_v}: {detalhe}")
                except Exception as exc:        # um passo ruim não pode travar o app
                    LOG.exception("falha na migração para v%s", alvo_v)
                    passos.append(f"v{alvo_v}: FALHOU ({exc})")
                atual = alvo_v
        dados["versao"] = ESQUEMA_DADOS
        dados["versao_app"] = VERSAO_APP
        alvo["salvar"] = True
    if passos:
        LOG.info("dados migrados %s -> %s: %s", de_, ESQUEMA_DADOS, "; ".join(passos))
    return {"de": de_, "para": ESQUEMA_DADOS, "passos": passos}


@contextlib.contextmanager
def _editando():
    """Abre os cadastros para edição COM TRAVA entre processos e relendo o arquivo
    DENTRO dela; grava ao sair do bloco.

    Sem isso, com o app aberto em duas máquinas (pasta compartilhada) o padrão
    ler→modificar→gravar perdia atualização: A lê, B lê, A grava, B grava — e o
    cadastro de A some silenciosamente. Reler dentro da trava garante que a
    modificação parte sempre da versão mais recente."""
    from .trava import travar
    with travar(USER_JSON):
        d = _usuario()
        alvo = {"salvar": False}
        yield d, alvo
        if alvo["salvar"]:
            _salvar(d)


def _salvar(d: dict):
    """Grava o JSON de forma ATÔMICA (temp + os.replace) e guarda um .bak da
    versão anterior — um crash ou sync do OneDrive no meio da escrita não
    corrompe mais os cadastros do usuário. O temp leva o PID no nome porque, com
    dois processos gravando, um `.tmp` fixo era sobrescrito pelo outro."""
    tmp = f"{USER_JSON}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(USER_JSON):
        try:
            shutil.copyfile(USER_JSON, USER_JSON + ".bak")
        except Exception as exc:
            LOG.warning("não consegui criar o backup .bak: %s", exc)
    os.replace(tmp, USER_JSON)


def _ja_existe(chave: str, registro: dict, existentes: list[dict]) -> bool:
    """True se um registro com os MESMOS identificadores (campos não vazios do
    novo cadastro) já está na lista — evita cadastro/importação em duplicidade."""
    ids = [k for k in _IDS.get(chave, ()) if str(registro.get(k, "")).strip()]
    return bool(ids) and any(_casa(e, registro, ids) for e in existentes)


def _visiveis(chave: str) -> list[dict]:
    """Lista mesclada (catálogo + usuário) VISÍVEL — itens ocultados ficam de
    fora, então re-cadastrar um item que foi ocultado continua permitido."""
    return {"fornecedores": catalogo_fornecedores,
            "faturamento": locais_faturamento,
            "pops": pops_entrega}[chave]()


def adicionar_usuario(tipo: str, registro: dict) -> dict:
    """Acrescenta um cadastro (fornecedor / faturamento / pop) ao JSON lateral.
    Recusa duplicata exata do que já está visível no catálogo ou nos cadastros."""
    chave = _CHAVE.get((tipo or "").lower())
    if not chave:
        raise ValueError(f"tipo de cadastro inválido: {tipo!r}")
    registro = {k: (str(v).strip() if v is not None else "") for k, v in (registro or {}).items()}
    registro["origem"] = "usuario"
    with _editando() as (d, alvo):
        # a checagem de duplicata TAMBÉM entra na trava: fora dela, dois apps
        # cadastrando o mesmo fornecedor passavam os dois pela verificação.
        if _ja_existe(chave, registro, _visiveis(chave)):
            raise ValueError("Este cadastro já existe (mesmo nome/identificadores) — nada foi salvo.")
        d.setdefault(chave, []).append(registro)
        alvo["salvar"] = True
    LOG.info("cadastro adicionado em %s: %s", chave,
             registro.get("empresa") or registro.get("razao_social") or registro.get("nome") or "?")
    return d


def _ambiguas(lista: list, chave: str) -> set:
    """Identidades fortes que NÃO identificam nada, por aparecerem mais de uma vez.

    No catálogo real a sigla "BHE" está em quatro POPs diferentes (e SDR, RJO,
    CTA, ALM em dois cada). Usar a sigla como identidade nesses casos faria
    ocultar um deles esconder os quatro, e corrigir um apagar os outros três.
    Onde a sigla não distingue, a comparação volta a ser campo a campo."""
    vistos, repetidas = set(), set()
    for e in lista:
        k = _chave_forte(chave, e)
        if not k:
            continue
        if k in vistos:
            repetidas.add(k)
        vistos.add(k)
    return repetidas


def _casa(e: dict, registro: dict, ids, chave: str = "", ambiguas=frozenset()) -> bool:
    """São o mesmo cadastro?

    Primeiro pela identidade forte (CNPJ / sigla): ela não muda quando alguém
    corrige um acento. Só vale quando a identidade é ÚNICA na lista — sigla
    repetida não identifica ninguém. Sem identidade forte utilizável, compara
    campo a campo, sem acento e sem caixa, senão "Tucuruí" e "Tucurui" passam
    por cadastros diferentes."""
    if chave:
        a, b = _chave_forte(chave, e), _chave_forte(chave, registro)
        if a and b and a not in ambiguas and b not in ambiguas:
            return a == b
    return bool(ids) and all(_norm_id(e.get(k)) == _norm_id(registro.get(k)) for k in ids)


def _preferir_usuario(out: list, chave: str) -> list:
    """Quando um cadastro do usuário e um do catálogo são o MESMO item, fica o
    do usuário.

    É o que torna a atualização segura sem depender do "ocultos": corrigir um
    POP é, na prática, dizer "a minha versão vale mais que a de fábrica" — e
    isso continua verdade quando o catálogo de fábrica muda de grafia na versão
    seguinte. Sem isto o item voltava duplicado a cada atualização."""
    meus = [e for e in out if e.get("origem") == "usuario"]
    if not meus:
        return out
    ambig = _ambiguas(out, chave)
    ids = _IDS.get(chave, ())
    return [e for e in out
            if e.get("origem") == "usuario"
            or not any(_casa(e, m, ids, chave, ambig) for m in meus)]


def _ocultar(out: list, chave: str) -> list:
    """Tira da lista os itens DO CATÁLOGO que o usuário escolheu ocultar.

    Só o catálogo: um cadastro do próprio usuário nunca é escondido por esta
    lista. Sem essa checagem, CORRIGIR um item oficial ficava impossível —
    ocultar a versão velha e recadastrar a certa com os mesmos identificadores
    (é o caso de uma filial que muda de endereço mas mantém o CNPJ) escondia
    as duas de uma vez. `adicionar_usuario` já permite recadastrar o que foi
    ocultado; aqui é o outro lado da mesma regra."""
    ocs = _usuario().get("ocultos", {}).get(chave, [])
    if not ocs:
        return out
    full = _IDS.get(chave, ())
    ambig = _ambiguas(out, chave)
    return [e for e in out
            if e.get("origem") == "usuario"
            or not any(_casa(e, o, [k for k in full if str(o.get(k, "")).strip()], chave, ambig)
                       for o in ocs)]


# ---------------------------------------------------------------- padrões --
# Textos e gestores que o usuário pode ajustar UMA vez e valem p/ todo CPM novo.
# Ficam no mesmo dados_usuario.json (chave "padroes"), então acompanham o app.
PADRAO_FINALIDADE = ("O fornecedor {fornecedor} atende os requisitos técnicos "
                     "homologados na rede Eletronet.")


def padroes() -> dict:
    """Padrões do usuário (texto fixo da finalidade, gestores da alçada)."""
    return _usuario().get("padroes", {})


def salvar_padroes(novos: dict) -> dict:
    """Grava os padrões (mescla com o que já existe). Usa a MESMA trava dos
    cadastros — dois apps abertos não se sobrescrevem.

    A mescla entra um nível nos dicionários (ex.: "gestores"): quem manda só
    o Diretor não apaga o CFO que já estava gravado."""
    with _editando() as (d, alvo):
        atual = d.setdefault("padroes", {})
        for k, v in (novos or {}).items():
            if v is None:
                continue
            if isinstance(v, dict) and isinstance(atual.get(k), dict):
                atual[k].update(v)
            else:
                atual[k] = v
        alvo["salvar"] = True
    LOG.info("padrões atualizados: %s", list((novos or {}).keys()))
    return padroes()


def pessoas() -> list:
    """AGENDA de quem assina: [{"papel": "Gerente de Engenharia", "nome": "..."}].

    Fica gravada no dados_usuario.json, então sobrevive a fechar o app. Serve
    para (a) sugerir nomes nos campos da alçada — trocar de setor vira escolher
    da lista em vez de redigitar — e (b) entrar como assinante EXTRA no CPM/CPS.
    """
    return [p for p in (padroes().get("pessoas") or []) if isinstance(p, dict) and p.get("nome")]


def salvar_pessoas(lista) -> list:
    """Substitui a agenda inteira (o front manda a lista já editada)."""
    limpa, vistos = [], set()
    for p in (lista or []):
        nome = str((p or {}).get("nome", "")).strip()
        papel = str((p or {}).get("papel", "")).strip()
        chave = (papel.lower(), nome.lower())
        if not nome or chave in vistos:          # sem nome não é pessoa; sem repetir
            continue
        vistos.add(chave)
        limpa.append({"papel": papel, "nome": nome})
    salvar_padroes({"pessoas": limpa})
    LOG.info("agenda de assinaturas: %d pessoa(s)", len(limpa))
    return limpa


def lembrar_pessoas(gestores: dict) -> None:
    """Guarda na agenda os nomes que o usuário acabou de usar na alçada.

    É o que dá a "lista de todos que eu já tinha deixado lá": o cadastro se
    monta sozinho conforme os documentos vão sendo feitos."""
    rotulos = {"gerente": "Gerente", "gerente_geral": "Gerente Geral", "diretor": "Diretor",
               "cfo": "CFO", "presidencia": "Presidência", "conselho": "Conselho de Administração"}
    atual = pessoas()
    tem = {(p["papel"].lower(), p["nome"].lower()) for p in atual}
    novos = []
    for chave, nome in (gestores or {}).items():
        nome = str(nome or "").strip()
        papel = rotulos.get(chave, str(chave).replace("_", " ").title())
        if nome and (papel.lower(), nome.lower()) not in tem:
            novos.append({"papel": papel, "nome": nome})
            tem.add((papel.lower(), nome.lower()))
    if novos:
        salvar_padroes({"pessoas": atual + novos})


def ocultos() -> dict:
    """Itens do catálogo ocultados pelo usuário (para exibir/restaurar)."""
    return _usuario().get("ocultos", {})


def remover_usuario(tipo: str, registro: dict) -> dict:
    """Apaga um cadastro do usuário; se for item do CATÁLOGO (não cadastrado por
    aqui), apenas OCULTA (reversível) — o .xlsm nunca é tocado.
    Devolve {'removidos': n, 'ocultados': n}."""
    chave = _CHAVE.get((tipo or "").lower())
    if not chave:
        raise ValueError(f"tipo de cadastro inválido: {tipo!r}")
    registro = registro or {}
    ids = [k for k in _IDS.get(chave, ()) if str(registro.get(k, "")).strip()]
    if not ids:
        return {"removidos": 0, "ocultados": 0}
    with _editando() as (d, alvo):
        lst = d.get(chave, [])
        restantes = [e for e in lst if not _casa(e, registro, ids)]
        removidos = len(lst) - len(restantes)
        if removidos:                               # era cadastro do usuário → apaga
            d[chave] = restantes
            alvo["salvar"] = True
            return {"removidos": removidos, "ocultados": 0}
        # é do catálogo → oculta (sem mexer no .xlsm)
        ocs = d.setdefault("ocultos", {}).setdefault(chave, [])
        reg_id = {k: str(registro.get(k, "")).strip() for k in ids}
        if not any(_casa(o, reg_id, ids) for o in ocs):
            ocs.append(reg_id)
            alvo["salvar"] = True
    return {"removidos": 0, "ocultados": 1}


def atualizar_usuario(tipo: str, id_antigo: dict, novo: dict) -> dict:
    """Edita um cadastro DO USUÁRIO: casa pelo registro antigo (ids) e substitui
    pelos valores novos. Só edita cadastros do usuário — o catálogo do .xlsm é
    read-only (pode só ser ocultado). Devolve {'atualizados': n}."""
    chave = _CHAVE.get((tipo or "").lower())
    if not chave:
        raise ValueError(f"tipo de cadastro inválido: {tipo!r}")
    id_antigo = id_antigo or {}
    ids = [k for k in _IDS.get(chave, ()) if str(id_antigo.get(k, "")).strip()]
    if not ids:
        return {"atualizados": 0}
    novo = {k: (str(v).strip() if v is not None else "") for k, v in (novo or {}).items()}
    novo["origem"] = "usuario"
    with _editando() as (d, alvo):
        lst = d.get(chave, [])
        for i, e in enumerate(lst):
            if _casa(e, id_antigo, ids):
                lst[i] = novo
                alvo["salvar"] = True
                LOG.info("cadastro atualizado em %s: %s", chave,
                         novo.get("empresa") or novo.get("razao_social") or novo.get("nome") or "?")
                return {"atualizados": 1}
    return {"atualizados": 0}


def restaurar_usuario(tipo: str, registro: dict) -> int:
    """Desfaz a ocultação de um item do catálogo. Devolve quantos restaurados."""
    chave = _CHAVE.get((tipo or "").lower())
    if not chave:
        raise ValueError(f"tipo de cadastro inválido: {tipo!r}")
    registro = registro or {}
    ids = [k for k in _IDS.get(chave, ()) if str(registro.get(k, "")).strip()]
    with _editando() as (d, alvo):
        ocs = d.get("ocultos", {}).get(chave, [])
        rest = [o for o in ocs if not _casa(o, registro, ids)]
        n = len(ocs) - len(rest)
        if n:
            d["ocultos"][chave] = rest
            alvo["salvar"] = True
    return n


def template_para(prefixo: str) -> str:
    if (prefixo or "").upper().startswith("AS") and os.path.exists(MODELO_AS_XLSM):
        return MODELO_AS_XLSM
    return MODELO_XLSM


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


@lru_cache(maxsize=1)
def _wb():
    return load_workbook(MODELO_XLSM, data_only=True)


# Cada catálogo = base lida do template (cacheada) + cadastros do usuário
# (lidos a cada chamada, p/ que um novo cadastro apareça sem reiniciar o app).
def _campos(modelo: dict, reg: dict) -> dict:
    return {k: _txt(reg.get(k, modelo.get(k, ""))) for k in modelo} | {
        "origem": reg.get("origem", "usuario")}


@lru_cache(maxsize=1)
def _fornecedores_base() -> list[dict]:
    ws = _wb()["dados_base"]
    out = []
    for r in range(3, ws.max_row + 1):
        apelido, empresa = _txt(ws.cell(r, 1).value), _txt(ws.cell(r, 2).value)
        if not apelido and not empresa:
            continue
        out.append({
            "apelido": apelido, "empresa": empresa,
            "endereco": _txt(ws.cell(r, 3).value), "cep": _txt(ws.cell(r, 4).value),
            "cnpj": _txt(ws.cell(r, 5).value), "insc_est": _txt(ws.cell(r, 6).value),
            "garantia": _txt(ws.cell(r, 8).value), "origem": "catalogo",
        })
    return out


def catalogo_fornecedores() -> list[dict]:
    modelo = {"apelido": "", "empresa": "", "endereco": "", "cep": "", "cnpj": "",
              "insc_est": "", "garantia": ""}
    out = list(_fornecedores_base()) + [_campos(modelo, f) for f in _usuario().get("fornecedores", [])]
    out.sort(key=lambda d: (d.get("apelido") or d.get("empresa") or "").upper())
    return _ocultar(_preferir_usuario(out, "fornecedores"), "fornecedores")


@lru_cache(maxsize=1)
def _faturamento_base() -> list[dict]:
    ws = _wb()["locais"]
    out = []
    for r in range(2, ws.max_row + 1):
        uf, razao = _txt(ws.cell(r, 1).value), _txt(ws.cell(r, 2).value)
        if not uf and not razao:
            continue
        out.append({
            "uf": uf, "razao_social": razao,
            "cnpj": _txt(ws.cell(r, 3).value), "endereco": _txt(ws.cell(r, 4).value),
            "cep": _txt(ws.cell(r, 5).value), "cnpj2": _txt(ws.cell(r, 6).value),
            "insc_est": _txt(ws.cell(r, 7).value), "insc_mun": _txt(ws.cell(r, 8).value),
            "origem": "catalogo",
        })
    return out


def locais_faturamento() -> list[dict]:
    modelo = {"uf": "", "razao_social": "", "cnpj": "", "endereco": "", "cep": "",
              "cnpj2": "", "insc_est": "", "insc_mun": ""}
    out = list(_faturamento_base()) + [_campos(modelo, f) for f in _usuario().get("faturamento", [])]
    return _ocultar(_preferir_usuario(out, "faturamento"), "faturamento")


@lru_cache(maxsize=1)
def _pops_base() -> list[dict]:
    ws = _wb()["POPs"]
    out = []
    for r in range(2, ws.max_row + 1):
        nome, sigla = _txt(ws.cell(r, 1).value), _txt(ws.cell(r, 2).value)
        if not nome and not sigla:
            continue
        out.append({
            "nome": nome, "sigla": sigla,
            "endereco": _txt(ws.cell(r, 3).value), "municipio": _txt(ws.cell(r, 4).value),
            "uf": _txt(ws.cell(r, 5).value), "maps": _txt(ws.cell(r, 6).value),
            "latitude": _txt(ws.cell(r, 7).value), "longitude": _txt(ws.cell(r, 8).value),
            "cedente": _txt(ws.cell(r, 9).value), "origem": "catalogo",
        })
    return out


def pops_entrega() -> list[dict]:
    modelo = {"nome": "", "sigla": "", "endereco": "", "municipio": "", "uf": "",
              "maps": "", "latitude": "", "longitude": "", "cedente": ""}
    out = list(_pops_base()) + [_campos(modelo, p) for p in _usuario().get("pops", [])]
    out.sort(key=lambda d: (d.get("nome") or "").upper())
    return _ocultar(_preferir_usuario(out, "pops"), "pops")


# ============================ IMPORTAÇÃO EM MASSA ============================
# Esquema (ordem + rótulo) de cada tipo — usado no modelo Excel e na importação.
CAMPOS_CAD = {
    "fornecedor": [("apelido", "Apelido"), ("empresa", "Empresa (razão social)"),
                   ("cnpj", "CNPJ"), ("insc_est", "Inscrição Estadual"),
                   ("endereco", "Endereço"), ("cep", "CEP"), ("garantia", "Garantia padrão")],
    "faturamento": [("uf", "UF"), ("razao_social", "Razão social"), ("cnpj", "CNPJ"),
                    ("cnpj2", "CNPJ 2"), ("endereco", "Endereço"), ("cep", "CEP"),
                    ("insc_est", "Inscrição Estadual"), ("insc_mun", "Inscrição Municipal")],
    "pop": [("nome", "Nome da estação"), ("sigla", "Sigla"), ("endereco", "Endereço"),
            ("municipio", "Município"), ("uf", "UF"), ("maps", "Link Google Maps"),
            ("latitude", "Latitude"), ("longitude", "Longitude"), ("cedente", "Cedente")],
}
# Nome da aba (minúsculo) → tipo. Aceita variações comuns.
_ABA_TIPO = {"fornecedores": "fornecedor", "fornecedor": "fornecedor",
             "faturamento": "faturamento", "faturamentos": "faturamento", "locais": "faturamento",
             "pops": "pop", "pop": "pop", "entrega": "pop", "entregas": "pop"}
# Campo mínimo p/ a linha valer (senão é ignorada).
_OBRIG_CAD = {"fornecedor": ("empresa", "apelido"), "faturamento": ("razao_social",), "pop": ("nome",)}


def modelo_cadastro_xlsx(caminho: str) -> str:
    """Gera uma planilha SIMPLES (3 abas: Fornecedores · Faturamento · POPs) com os
    cabeçalhos certos + 1 linha de exemplo, p/ o usuário preencher e importar."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    exemplo = {
        "fornecedor": {"apelido": "FONNET", "empresa": "FONNET COMÉRCIO DE EQUIP. LTDA",
                       "cnpj": "11.035.558/0001-29", "insc_est": "ISENTO",
                       "endereco": "Rua Exemplo, 100 - Centro, Cidade-UF", "cep": "00000-000",
                       "garantia": "12 meses"},
        "faturamento": {"uf": "SP", "razao_social": "ELETRONET S.A - FILIAL",
                        "cnpj": "03.052.673/0001-45", "cnpj2": "",
                        "endereco": "Av. Exemplo, 200 - Cidade-UF", "cep": "00000-000",
                        "insc_est": "", "insc_mun": ""},
        "pop": {"nome": "POP Eletronet Exemplo", "sigla": "EXP", "endereco": "Rua do POP, 1",
                "municipio": "Cidade", "uf": "UF", "maps": "", "latitude": "", "longitude": "",
                "cedente": ""},
    }
    wb = Workbook()
    wb.remove(wb.active)
    for aba, tipo in (("Fornecedores", "fornecedor"), ("Faturamento", "faturamento"), ("POPs", "pop")):
        ws = wb.create_sheet(aba)
        for c, (chave, rot) in enumerate(CAMPOS_CAD[tipo], 1):
            cell = ws.cell(1, c, rot)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1B1FE6")
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[cell.column_letter].width = max(16, len(rot) + 3)
            ws.cell(2, c, exemplo[tipo].get(chave, ""))     # linha 2 = exemplo (some ao importar)
        ws.freeze_panes = "A2"
    wb.save(caminho)
    return caminho


def _eh_exemplo(reg: dict, tipo: str) -> bool:
    """Detecta a linha de exemplo do modelo (p/ não cadastrá-la sem querer)."""
    if tipo == "fornecedor":
        return reg.get("apelido") == "FONNET" and "FONNET COMÉRCIO DE EQUIP" in reg.get("empresa", "")
    if tipo == "faturamento":
        return reg.get("endereco", "").startswith("Av. Exemplo, 200")
    return reg.get("nome") == "POP Eletronet Exemplo"


def importar_cadastros_xlsx(caminho: str) -> dict:
    """Lê a planilha (abas Fornecedores/Faturamento/POPs) e cadastra TODAS as linhas
    de uma vez (uma única gravação no JSON). Casa as colunas pelo RÓTULO do cabeçalho;
    se não achar, usa a posição. A linha de exemplo do modelo é ignorada e linhas já
    cadastradas (mesmos identificadores) NÃO duplicam — importar 2× é inofensivo."""
    from openpyxl import load_workbook
    wb = load_workbook(caminho, data_only=True, read_only=True)
    res = {"fornecedor": 0, "faturamento": 0, "pop": 0,
           "ignoradas": 0, "duplicadas": 0, "erros": []}
    lotes: dict = {}
    base = {chave: _visiveis(chave) for chave in ("fornecedores", "faturamento", "pops")}
    try:
        for ws in wb.worksheets:
            tipo = _ABA_TIPO.get((ws.title or "").strip().lower())
            if not tipo:
                continue
            cols = CAMPOS_CAD[tipo]
            linhas = list(ws.iter_rows(values_only=True))
            if len(linhas) < 2:
                continue
            cab = [_txt(x).strip().lower() for x in linhas[0]]
            idx = {}                                        # campo → índice da coluna
            for i, (chave, rot) in enumerate(cols):
                alvo = rot.strip().lower()
                j = next((k for k, h in enumerate(cab) if h in (alvo, chave)), None)
                idx[chave] = j if j is not None else (i if i < max(len(cab), 1) else None)
            for row in linhas[1:]:
                reg = {chave: (_txt(row[idx[chave]]) if (idx[chave] is not None and idx[chave] < len(row)) else "")
                       for chave, _ in cols}
                if not any(reg.values()) or _eh_exemplo(reg, tipo):
                    continue
                if not any(reg.get(k) for k in _OBRIG_CAD[tipo]):
                    res["ignoradas"] += 1
                    continue
                chave = _CHAVE[tipo]
                # duplicidade: contra o catálogo/cadastros E contra o próprio lote
                if _ja_existe(chave, reg, base[chave] + lotes.get(chave, [])):
                    res["duplicadas"] += 1
                    continue
                reg["origem"] = "usuario"
                lotes.setdefault(chave, []).append(reg)
                res[tipo] += 1
    finally:
        wb.close()
    if any(lotes.values()):                                 # grava tudo de uma vez
        with _editando() as (d, alvo):                      # trava: não perde o que outro app gravou
            for chave, regs in lotes.items():
                d.setdefault(chave, []).extend(regs)
            alvo["salvar"] = True
    LOG.info("importação em massa: %s", {k: v for k, v in res.items() if k != "erros"})
    return res

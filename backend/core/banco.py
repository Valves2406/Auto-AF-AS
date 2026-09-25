r"""
banco.py — os CADASTROS da equipe num banco na nuvem (Supabase).

O que vai para o banco é SÓ isto: fornecedores, filiais de faturamento e POPs
de entrega — dados de consulta que o setor inteiro usa para preencher a AF.
AF, AS e propostas NUNCA passam por aqui.

Por que a API HTTPS e não o driver do Postgres
----------------------------------------------
A porta do Postgres (5432) costuma estar fechada na rede da empresa; a 443 não.
E a API não pede biblioteca nova no executável: é urllib puro.

Se a internet cair
------------------
Toda leitura boa vira uma CÓPIA LOCAL (%APPDATA%\AutoAF\banco_cache.json). Sem
conexão, o app segue com a cópia; sem cópia, com o catálogo do modelo .xlsm,
como sempre foi. GRAVAR é que exige conexão: um cadastro não fica "pendente"
numa máquina, divergindo das outras em silêncio.

Depois de uma falha, o app passa um minuto sem perguntar ao banco — senão cada
lista da tela esperaria o tempo-limite inteiro e a aba travaria.

Onde fica a configuração (endereço + chave publicável)
------------------------------------------------------
1. variáveis GERADORAF_BANCO_URL e GERADORAF_BANCO_CHAVE;
2. %APPDATA%\AutoAF\config.json, chave "banco";
3. um banco.json ao lado do executável ou na pasta do setor. Achado ali, é
   copiado para o config.json: a máquina continua sabendo do banco mesmo com a
   pasta de rede fora do ar.

A chave publicável só lê, inclui e altera — apagar não existe para ela, e cada
alteração fica guardada num histórico que a API não enxerga (as regras estão no
próprio banco). Mesmo assim ela NUNCA vai para o repositório, que é público.

Fica desligado com GERADORAF_SEM_BANCO=1 (os testes) e quando GERADORAF_DADOS
aponta um arquivo de cadastros específico: quem escolheu um arquivo à mão quer
aquele arquivo.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from .log import get_logger

LOG = get_logger("banco")

TABELAS = ("fornecedores", "faturamento", "pops")
ARQ_BANCO = "banco.json"
TEMPO_LIMITE = 8           # segundos por requisição
VALIDADE = 180             # segundos que uma leitura vale antes de perguntar de novo
ESPERA_APOS_FALHA = 60     # segundos sem tentar depois de uma falha


class Indisponivel(Exception):
    """Sem conexão, ou o banco não aceitou a chave: não dá para falar com ele."""


class Recusado(Exception):
    """O banco respondeu e recusou o pedido (dado inválido, regra de acesso)."""


_trava = threading.Lock()
_memoria: dict[str, tuple[float, list]] = {}      # tabela -> (quando, linhas)
_estado = {"online": None, "erro": "", "falhou_em": 0.0}
_cfg = {"lida": False, "valor": None}


# ------------------------------------------------------------ configuração --
def _pasta_perfil() -> str:
    pasta = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "AutoAF")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _ler_json(caminho: str) -> dict:
    try:
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except Exception as exc:
        LOG.warning("%s ilegível: %s", os.path.basename(caminho), exc)
        return {}


def _gravar_json(caminho: str, d: dict):
    tmp = f"{caminho}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def _valida(cfg) -> dict | None:
    cfg = cfg if isinstance(cfg, dict) else {}
    url = str(cfg.get("url") or "").strip().rstrip("/")
    chave = str(cfg.get("chave") or "").strip()
    # http só na própria máquina (o banco de mentira dos testes)
    ok = url.startswith("https://") or url.startswith(("http://127.0.0.1", "http://localhost"))
    return {"url": url, "chave": chave} if ok and chave else None


def desligado() -> bool:
    return bool(os.environ.get("GERADORAF_SEM_BANCO") or os.environ.get("GERADORAF_DADOS"))


def _rodando_teste() -> bool:
    """Um script da pasta testes/ nunca acha o banco de verdade sozinho: o
    config.json desta máquina aponta para ele, e um teste que cadastra "POP DA
    EQUIPE" gravaria lixo no cadastro do setor. Só vale o banco que o próprio
    teste der pelas variáveis de ambiente."""
    script = os.path.normcase(os.path.abspath(sys.argv[0] if sys.argv and sys.argv[0] else ""))
    return "testes" in script.split(os.sep)


def _pastas_da_equipe() -> list[str]:
    """Onde um banco.json da equipe pode estar: ao lado do app e na pasta do setor."""
    pastas = []
    try:
        from .caminhos import dado
        pastas.append(os.path.dirname(dado(ARQ_BANCO)))
    except Exception:
        pass
    try:
        from .atualizador import pasta_do_setor
        p = pasta_do_setor()
        if p:
            pastas.append(p)
    except Exception:
        pass
    return pastas


def _guardar_na_maquina(cfg: dict):
    arq = os.path.join(_pasta_perfil(), "config.json")
    atual = _ler_json(arq)
    atual["banco"] = {"url": cfg["url"], "chave": cfg["chave"]}
    _gravar_json(arq, atual)


def configuracao() -> dict | None:
    """{"url", "chave"} do banco em uso, ou None (sem banco: vale o arquivo)."""
    if desligado():
        return None
    if _cfg["lida"]:
        return _cfg["valor"]
    cfg = _valida({"url": os.environ.get("GERADORAF_BANCO_URL"),
                   "chave": os.environ.get("GERADORAF_BANCO_CHAVE")})
    if not cfg and _rodando_teste():
        _cfg.update(lida=True, valor=None)
        return None
    if not cfg:
        cfg = _valida(_ler_json(os.path.join(_pasta_perfil(), "config.json")).get("banco"))
    if not cfg:
        for pasta in _pastas_da_equipe():
            achado = _valida(_ler_json(os.path.join(pasta, ARQ_BANCO)))
            if achado:
                cfg = achado
                try:
                    _guardar_na_maquina(achado)
                except OSError as exc:
                    LOG.warning("não consegui guardar a configuração do banco: %s", exc)
                LOG.info("banco da equipe configurado a partir de %s", pasta)
                break
    _cfg.update(lida=True, valor=cfg)
    return cfg


def configurar(url: str, chave: str) -> dict:
    """Liga ESTA máquina ao banco (grava no config.json do perfil)."""
    cfg = _valida({"url": url, "chave": chave})
    if not cfg:
        raise ValueError("Endereço (https://...) e chave do banco são obrigatórios.")
    _guardar_na_maquina(cfg)
    _cfg.update(lida=True, valor=cfg)
    esquecer()
    return cfg


# ---------------------------------------------------------------- conversa --
def _falhou(motivo: str):
    with _trava:
        _estado.update(online=False, erro=motivo, falhou_em=time.monotonic())
    LOG.warning("banco indisponível: %s", motivo)


def _mensagem(corpo: str) -> tuple[str, str]:
    try:
        d = json.loads(corpo)
        return str(d.get("code") or ""), str(d.get("message") or corpo)
    except Exception:
        return "", corpo


def _pedir(metodo: str, caminho: str, corpo=None, cabecalhos: dict | None = None):
    cfg = configuracao()
    if not cfg:
        raise Indisponivel("banco não configurado")
    dados = None if corpo is None else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(cfg["url"] + "/rest/v1/" + caminho, data=dados, method=metodo)
    req.add_header("apikey", cfg["chave"])
    req.add_header("Authorization", "Bearer " + cfg["chave"])
    req.add_header("Accept", "application/json")
    if dados is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in (cabecalhos or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
            texto = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:          # respondeu, mas com erro
        codigo, msg = _mensagem(exc.read().decode("utf-8", "replace")[:500])
        if exc.code in (401, 403) and codigo != "42501":
            _falhou("o banco recusou a chave de acesso (HTTP %d)" % exc.code)
            raise Indisponivel("o banco recusou a chave de acesso") from exc
        if exc.code >= 500 or exc.code == 404:
            _falhou("HTTP %d: %s" % (exc.code, msg))
            raise Indisponivel("o banco não respondeu direito (HTTP %d)" % exc.code) from exc
        if codigo == "23514":                      # check: nome/razão social vazio
            raise Recusado("Falta o nome (ou a razão social) — nada foi salvo.") from exc
        if codigo == "42501":                      # regra de acesso
            raise Recusado("O banco não permite esta operação.") from exc
        raise Recusado("O banco recusou: " + msg) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _falhou(str(getattr(exc, "reason", "") or exc))
        raise Indisponivel("sem conexão com o banco") from exc
    with _trava:
        _estado.update(online=True, erro="", falhou_em=0.0)
    return json.loads(texto) if texto.strip() else None


# ------------------------------------------------------------ cópia local --
def _arq_copia() -> str:
    return os.path.join(_pasta_perfil(), "banco_cache.json")


def _gravar_copia(tabela: str, linhas: list):
    cfg = configuracao() or {}
    with _trava:
        try:
            d = _ler_json(_arq_copia())
            if d.get("projeto") != cfg.get("url"):
                d = {"projeto": cfg.get("url"), "tabelas": {}}
            d.setdefault("tabelas", {})[tabela] = {
                "em": datetime.now().isoformat(timespec="seconds"), "linhas": linhas}
            _gravar_json(_arq_copia(), d)
        except OSError as exc:
            LOG.warning("não consegui guardar a cópia local do banco: %s", exc)


def _ler_copia(tabela: str) -> tuple[list, str] | None:
    cfg = configuracao() or {}
    d = _ler_json(_arq_copia())
    if d.get("projeto") != cfg.get("url"):
        return None
    t = (d.get("tabelas") or {}).get(tabela)
    if not isinstance(t, dict) or not isinstance(t.get("linhas"), list):
        return None
    return t["linhas"], str(t.get("em") or "")


# ---------------------------------------------------------------- leituras --
def linhas(tabela: str) -> list[dict]:
    """Todas as linhas da tabela, ocultas inclusive, na ordem em que entraram.

    Levanta Indisponivel só quando não há banco NEM cópia local."""
    if tabela not in TABELAS:
        raise ValueError(f"tabela desconhecida: {tabela!r}")
    agora = time.monotonic()
    with _trava:
        guardado = _memoria.get(tabela)
        if guardado and agora - guardado[0] < VALIDADE:
            return guardado[1]
        pode_tentar = not _estado["falhou_em"] or agora - _estado["falhou_em"] >= ESPERA_APOS_FALHA
    if pode_tentar:
        try:
            # o banco entrega até 1000 linhas por pedido; os cadastros têm centenas
            achadas = _pedir("GET", f"{tabela}?select=*&order=id.asc")
            if isinstance(achadas, list):
                with _trava:
                    _memoria[tabela] = (time.monotonic(), achadas)
                _gravar_copia(tabela, achadas)
                return achadas
        except Indisponivel:
            pass
    copia = _ler_copia(tabela)
    if copia is None:
        raise Indisponivel(_estado["erro"] or "sem conexão com o banco")
    with _trava:
        # vale só até a próxima tentativa, não os três minutos inteiros
        _memoria[tabela] = (time.monotonic() - VALIDADE + ESPERA_APOS_FALHA, copia[0])
    return copia[0]


def esquecer(tabela: str | None = None):
    """Joga fora a leitura em memória: a próxima pergunta vai ao banco."""
    # (a espera depois de uma falha continua valendo: sem conexão, a cópia
    # responde na hora em vez de cada lista esperar o tempo-limite)
    with _trava:
        if tabela:
            _memoria.pop(tabela, None)
        else:
            _memoria.clear()


# -------------------------------------------------------------- gravações --
def incluir(tabela: str, registros: list[dict]) -> list[dict]:
    if tabela not in TABELAS:
        raise ValueError(f"tabela desconhecida: {tabela!r}")
    if not registros:
        return []
    try:
        return _pedir("POST", tabela, registros, {"Prefer": "return=representation"}) or []
    finally:
        esquecer(tabela)


def alterar(tabela: str, ids, campos: dict) -> list[dict]:
    """Altera as linhas de id em `ids` (um id ou uma lista deles)."""
    if tabela not in TABELAS:
        raise ValueError(f"tabela desconhecida: {tabela!r}")
    ids = [int(i) for i in (ids if isinstance(ids, (list, tuple, set)) else [ids])]
    if not ids:
        return []
    try:
        feitas = _pedir("PATCH", f"{tabela}?id=in.({','.join(map(str, ids))})", campos,
                        {"Prefer": "return=representation"}) or []
    finally:
        esquecer(tabela)
    if not feitas:
        raise Recusado("O item não está mais no banco como estava — recarregue a lista e tente de novo.")
    return feitas


def estado() -> dict:
    """Para a tela: há banco? está respondendo? de quando é a cópia em uso?"""
    cfg = configuracao()
    if not cfg:
        return {"configurado": False}
    copias = _ler_json(_arq_copia()).get("tabelas") or {}
    em = sorted(str(t.get("em") or "") for t in copias.values() if isinstance(t, dict))
    return {"configurado": True, "online": _estado["online"], "erro": _estado["erro"],
            "copia_em": em[0] if em else "",
            "projeto": cfg["url"].split("//", 1)[-1].split(".", 1)[0]}

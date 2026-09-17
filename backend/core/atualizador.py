r"""
atualizador.py — o programa novo chega sozinho na máquina de todo mundo.

O problema
----------
Hoje, para atualizar o setor, alguém compila, manda o .exe por e-mail ou
pendrive e cada pessoa substitui o seu. Quem não substituiu fica para trás em
silêncio: gera AF com a leitura antiga e ninguém percebe até sair errado.

Como funciona
-------------
Uma PASTA DO SETOR guarda a versão oficial: o executável e um `versao.json`
dizendo qual é. Cada máquina roda uma CÓPIA LOCAL — é ela que abre rápido e
continua funcionando se a rede cair. Ao abrir, o app compara a sua versão com a
publicada; sendo mais nova, copia, troca e reabre já atualizado.

Publicar é só chamar `publicar()` apontando o .exe novo: quem faz isso de uma
máquina atualiza todas as outras na próxima vez que abrirem. Vale nos dois
sentidos — não existe "máquina que manda".

Por que trocar um .exe em uso dá trabalho
-----------------------------------------
O Windows não deixa SOBRESCREVER um executável que está rodando, mas deixa
RENOMEAR. Então a troca é: renomeia o que está rodando para `.antigo`, põe o
novo no lugar, abre o novo e sai. Na abertura seguinte o `.antigo` é apagado.

O que este módulo NUNCA faz
---------------------------
* Travar a abertura. Pasta fora do ar, sem permissão, arquivo pela metade: o
  app abre na versão que já tem. Atualizar é conveniência; trabalhar é o
  objetivo.
* Trocar no meio do trabalho. A verificação é só na abertura — ninguém perde
  uma AF pela metade porque o programa resolveu se atualizar.
* Confiar num arquivo truncado. O tamanho publicado é conferido antes da troca;
  cópia interrompida pela rede é descartada.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

from .caminhos import EMPACOTADO
from .log import get_logger

LOG = get_logger(__name__)

ARQ_VERSAO = "versao.json"
SUFIXO_ANTIGO = ".antigo"
SUFIXO_NOVO = ".novo"


# --------------------------------------------------------------- versões ---
def _partes(v: str) -> tuple:
    """"0.10" > "0.9": compara número a número, não texto.

    Em texto "0.10" < "0.9", e a atualização nunca aconteceria depois da nona.
    """
    out = []
    for p in str(v or "0").replace("-", ".").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def mais_nova(publicada: str, atual: str) -> bool:
    return _partes(publicada) > _partes(atual)


# ----------------------------------------------------------------- pasta ---
def pasta_do_setor() -> str:
    """Onde está a versão oficial. Vazio = atualização automática desligada.

    Ordem: a variável de ambiente manda; senão o que a máquina escolheu; senão
    a PASTA DO CADASTRO compartilhado, que é onde o setor já se encontra.
    """
    da_vez = os.environ.get("GERADORAF_ATUALIZACAO")
    if da_vez:
        return da_vez
    try:
        from .dados_eletronet import _config, onde_estao_os_dados

        escolhida = (_config() or {}).get("atualizacao")
        if escolhida:
            return escolhida
        onde = onde_estao_os_dados()
        if onde.get("compartilhado"):
            return onde.get("pasta") or ""
    except Exception as exc:                 # nunca derruba a abertura
        LOG.warning("não consegui descobrir a pasta de atualização: %s", exc)
    return ""


def versao_publicada(pasta: str) -> dict:
    """O que o `versao.json` da pasta diz. Vazio quando não há nada publicado."""
    if not pasta:
        return {}
    try:
        caminho = os.path.join(pasta, ARQ_VERSAO)
        if not os.path.exists(caminho):
            return {}
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception as exc:
        LOG.warning("versao.json ilegível em %s: %s", pasta, exc)
        return {}


# -------------------------------------------------------------- publicar ---
def publicar(exe: str, pasta: str, versao: str) -> dict:
    """Põe este executável como a versão oficial do setor.

    Copia para um nome temporário e só então renomeia: se a rede cair no meio,
    ninguém pega um executável pela metade — o antigo continua valendo.
    """
    if not (exe and os.path.exists(exe)):
        return {"ok": False, "erro": "Executável não encontrado: %s" % exe}
    if not pasta:
        return {"ok": False, "erro": "Pasta do setor não informada."}
    try:
        os.makedirs(pasta, exist_ok=True)
        nome = os.path.basename(exe)
        destino = os.path.join(pasta, nome)
        temporario = destino + SUFIXO_NOVO
        shutil.copy2(exe, temporario)
        if os.path.getsize(temporario) != os.path.getsize(exe):
            os.remove(temporario)
            return {"ok": False, "erro": "A cópia saiu incompleta — nada foi publicado."}
        os.replace(temporario, destino)      # troca atômica
        with open(os.path.join(pasta, ARQ_VERSAO), "w", encoding="utf-8") as f:
            json.dump({"versao": versao, "arquivo": nome,
                       "tamanho": os.path.getsize(destino)}, f, ensure_ascii=False)
        LOG.info("versão %s publicada em %s", versao, pasta)
        return {"ok": True, "versao": versao, "pasta": pasta, "arquivo": nome}
    except Exception as exc:
        LOG.exception("falha ao publicar a versão")
        return {"ok": False, "erro": str(exc)}


# -------------------------------------------------------------- verificar --
def ha_atualizacao(versao_atual: str, pasta: str = "") -> dict:
    """Tem versão nova na pasta do setor? Só olha, não mexe em nada."""
    pasta = pasta or pasta_do_setor()
    pub = versao_publicada(pasta)
    if not pub.get("versao"):
        return {"tem": False}
    origem = os.path.join(pasta, pub.get("arquivo") or "")
    if not os.path.exists(origem):
        LOG.warning("versao.json aponta para um arquivo que não está lá: %s", origem)
        return {"tem": False}
    # tamanho confere? cópia interrompida pela rede não vale como versão
    esperado = pub.get("tamanho")
    if esperado and os.path.getsize(origem) != esperado:
        LOG.warning("o executável publicado está incompleto (%s de %s bytes)",
                    os.path.getsize(origem), esperado)
        return {"tem": False}
    return {"tem": mais_nova(pub["versao"], versao_atual),
            "versao": pub["versao"], "origem": origem, "pasta": pasta}


# ---------------------------------------------------------------- aplicar --
def _apagar(caminho: str) -> None:
    """Remove arquivo OU pasta, sem reclamar se não der.

    Tem de aceitar os dois: se um diretório ocupar o nome que a troca precisa,
    os.remove levanta PermissionError e o log enche de traceback num caminho
    que já está sendo tratado.
    """
    if not os.path.exists(caminho):
        return
    try:
        if os.path.isdir(caminho):
            shutil.rmtree(caminho, ignore_errors=True)
        else:
            os.remove(caminho)
    except OSError:
        pass


def limpar_antigo(exe: str) -> None:
    """Apaga o executável da versão anterior, deixado pela troca da última vez."""
    velho = exe + SUFIXO_ANTIGO
    if os.path.exists(velho):
        try:
            os.remove(velho)
            LOG.info("versão anterior removida")
        except OSError:
            pass                              # ainda em uso: sai na próxima


def aplicar(origem: str, exe: str) -> dict:
    """Troca o executável em uso pelo publicado.

    O Windows não deixa sobrescrever um .exe rodando, mas deixa RENOMEAR: o que
    está em uso vira `.antigo`, o novo entra no lugar. Dando errado em qualquer
    ponto, o antigo volta — é melhor continuar na versão velha do que ficar sem
    programa nenhum.
    """
    novo = exe + SUFIXO_NOVO
    velho = exe + SUFIXO_ANTIGO
    try:
        _apagar(novo)                         # sobra de uma tentativa anterior
        shutil.copy2(origem, novo)
        if os.path.getsize(novo) != os.path.getsize(origem):
            _apagar(novo)
            return {"ok": False, "erro": "Cópia incompleta — a versão atual foi mantida."}
        if os.path.exists(velho):
            os.remove(velho)
        os.rename(exe, velho)                 # libera o nome sem apagar nada
        try:
            os.rename(novo, exe)
        except OSError:
            os.rename(velho, exe)             # desfaz: melhor a versão velha que nenhuma
            raise
        return {"ok": True, "antigo": velho}
    except Exception as exc:
        LOG.exception("falha ao trocar o executável")
        _apagar(novo)
        return {"ok": False, "erro": str(exc)}


def reabrir(exe: str) -> None:
    """Abre a versão nova e deixa esta sair."""
    try:
        subprocess.Popen([exe], cwd=os.path.dirname(exe) or None, close_fds=True)
    except Exception as exc:
        LOG.exception("não consegui reabrir o app atualizado: %s", exc)


def atualizar_na_abertura(versao_atual: str) -> dict:
    """Ponto de entrada: chamado uma vez, na abertura.

    Devolve {"trocou": True} quando o app deve fechar para o novo assumir.
    Qualquer tropeço devolve trocou=False e o app segue normalmente — nunca
    impedir alguém de trabalhar por causa de uma atualização.
    """
    if not EMPACOTADO:                        # rodando pelo fonte: não há o que trocar
        return {"trocou": False, "motivo": "rodando pelo código-fonte"}
    exe = os.path.abspath(sys.executable)
    limpar_antigo(exe)
    try:
        info = ha_atualizacao(versao_atual)
    except Exception as exc:
        LOG.warning("não consegui verificar atualização: %s", exc)
        return {"trocou": False, "motivo": str(exc)}
    if not info.get("tem"):
        return {"trocou": False, "motivo": "já está na versão mais nova"}
    LOG.info("versão %s publicada (esta é a %s) — atualizando",
             info["versao"], versao_atual)
    r = aplicar(info["origem"], exe)
    if not r.get("ok"):
        return {"trocou": False, "motivo": r.get("erro", "")}
    reabrir(exe)
    return {"trocou": True, "versao": info["versao"]}

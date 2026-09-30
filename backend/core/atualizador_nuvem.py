r"""
atualizador_nuvem.py — a versão nova chega pela INTERNET, como num app de loja.

Como funciona para quem usa
---------------------------
1. Ao abrir, o app pergunta ao Supabase se há versão nova (um arquivinho de
   poucos bytes, o `versao.json`). Não atrasa a abertura: é em segundo plano.
2. Havendo, BAIXA em segundo plano enquanto a pessoa trabalha, para uma pasta
   própria (%LOCALAPPDATA%\AutoAF\atualizacao).
3. Confere a assinatura (SHA-256) de cada parte e do arquivo inteiro. Qualquer
   diferença: joga fora e tenta de novo na próxima abertura.
4. A troca acontece na PRÓXIMA ABERTURA (ou no botão "Reiniciar agora") — nunca
   no meio do trabalho. Sem internet, abre na versão que já tem.

Por que em partes
-----------------
O plano grátis do Supabase aceita até 50 MB por arquivo, e o .exe tem ~65 MB.
Publica-se em partes de 40 MB; o app baixa as partes, confere cada uma e junta.
Parte já baixada e conferida não é baixada de novo se a conexão cair no meio.

Segurança
---------
O espaço `versoes` é PRIVADO (o .exe leva os modelos com o catálogo da
empresa). A chave do app só BAIXA um arquivo cujo nome já conhece — não lista,
não envia, não apaga. Publicar exige a chave SECRETA (service_role), que fica
só na máquina de quem publica (variável SUPABASE_SECRET_KEY) — nunca no .exe,
nunca no repositório. O `versao.json` é enviado POR ÚLTIMO: ninguém vê uma
versão anunciada cujas partes ainda não chegaram.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime

from .log import get_logger

LOG = get_logger("atualizador_nuvem")

BUCKET = "versoes"
MANIFESTO = "versao.json"
TAM_PARTE = 40 * 1024 * 1024        # abaixo dos 50 MB por arquivo do plano grátis
TEMPO_LIMITE = 60                   # por parte (40 MB numa conexão lenta)
_PARTE_OK = re.compile(r"^[0-9][0-9A-Za-z.\-]*/parte-\d{1,3}\.bin$")   # sem "../"

_estado = {"baixando": False, "pronta": "", "erro": "", "versao_publicada": ""}
_trava = threading.Lock()


# ------------------------------------------------------------- utilidades --
def _partes_versao(v: str) -> tuple:
    out = []
    for p in str(v or "0").replace("-", ".").split("."):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def mais_nova(publicada: str, atual: str) -> bool:
    return _partes_versao(publicada) > _partes_versao(atual)


def _sha256_arquivo(caminho: str) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def pasta_local() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    p = os.path.join(base, "AutoAF", "atualizacao")
    os.makedirs(p, exist_ok=True)
    return p


def _cfg():
    from . import banco
    return banco.configuracao()


def _url(caminho: str, cfg: dict, baixar: bool = True) -> str:
    rota = "object/authenticated" if baixar else "object"
    return f"{cfg['url']}/storage/v1/{rota}/{BUCKET}/{caminho}"


def _get(caminho: str, cfg: dict, destino: str | None = None):
    """Baixa um arquivo do espaço. Com `destino`, grava em disco aos pedaços e
    devolve None; sem, devolve os bytes. Arquivo que não existe → FileNotFoundError."""
    req = urllib.request.Request(_url(caminho, cfg))
    req.add_header("apikey", cfg["chave"])
    req.add_header("Authorization", "Bearer " + cfg["chave"])
    try:
        with urllib.request.urlopen(req, timeout=TEMPO_LIMITE) as r:
            if destino is None:
                return r.read()
            with open(destino, "wb") as f:
                for bloco in iter(lambda: r.read(1024 * 1024), b""):
                    f.write(bloco)
            return None
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", "replace")
        # o Storage responde "não existe" como HTTP 400 com not_found no corpo
        if exc.code == 404 or "not_found" in corpo or "NoSuchKey" in corpo:
            raise FileNotFoundError(caminho) from exc
        raise


# ------------------------------------------------------ o que foi publicado --
def manifesto(cfg: dict | None = None) -> dict:
    """O `versao.json` publicado. Vazio quando não há nada publicado."""
    cfg = cfg or _cfg()
    if not cfg:
        return {}
    try:
        d = json.loads(_get(MANIFESTO, cfg).decode("utf-8"))
    except FileNotFoundError:
        return {}
    return d if isinstance(d, dict) else {}


def _manifesto_valido(m: dict) -> str:
    """'' se o manifesto é são; senão, o motivo. Nada de caminho fora da pasta
    da versão, nada de parte sem assinatura."""
    if not m.get("versao") or not re.fullmatch(r"[0-9][0-9A-Za-z.\-]*", str(m["versao"])):
        return "versão inválida"
    partes = m.get("partes")
    if not isinstance(partes, list) or not partes:
        return "sem partes"
    for p in partes:
        if not isinstance(p, dict) or not _PARTE_OK.match(str(p.get("nome", ""))):
            return "nome de parte inválido"
        if not str(p["nome"]).startswith(str(m["versao"]) + "/"):
            return "parte fora da pasta da versão"
        if not re.fullmatch(r"[0-9a-f]{64}", str(p.get("sha256", ""))) or not isinstance(p.get("tamanho"), int):
            return "parte sem assinatura"
    if not re.fullmatch(r"[0-9a-f]{64}", str(m.get("sha256", ""))) or not isinstance(m.get("tamanho"), int):
        return "arquivo sem assinatura"
    if sum(p["tamanho"] for p in partes) != m["tamanho"]:
        return "as partes não somam o tamanho do arquivo"
    return ""


# ------------------------------------------------------------------ baixar --
def _pasta_versao(versao: str) -> str:
    p = os.path.join(pasta_local(), versao)
    os.makedirs(p, exist_ok=True)
    return p


def pronta(versao_atual: str) -> dict:
    """A versão já baixada e conferida, se for mais nova que a atual."""
    arq = os.path.join(pasta_local(), "pronta.json")
    try:
        with open(arq, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    exe = d.get("exe") or ""
    if not (mais_nova(d.get("versao", ""), versao_atual) and os.path.exists(exe)):
        return {}
    if os.path.getsize(exe) != d.get("tamanho") or _sha256_arquivo(exe) != d.get("sha256"):
        LOG.warning("a versão baixada não confere mais — será baixada de novo")
        return {}
    return d


def baixar(versao_atual: str, cfg: dict | None = None) -> dict:
    """Confere o que foi publicado e, sendo mais novo, baixa e confere.
    Devolve {"pronta": versao} | {"nada": motivo} | {"erro": motivo}."""
    cfg = cfg or _cfg()
    if not cfg:
        return {"nada": "sem banco configurado"}
    try:
        m = manifesto(cfg)
    except Exception as exc:
        return {"erro": f"sem conexão com as versões ({exc})"}
    with _trava:
        _estado["versao_publicada"] = str(m.get("versao") or "")
    if not m:
        return {"nada": "nenhuma versão publicada"}
    if not mais_nova(str(m.get("versao")), versao_atual):
        return {"nada": "já está na versão mais nova"}
    motivo = _manifesto_valido(m)
    if motivo:
        LOG.warning("versao.json recusado: %s", motivo)
        return {"erro": f"publicação inválida ({motivo})"}
    ja = pronta(versao_atual)
    if ja and ja.get("versao") == m["versao"] and ja.get("sha256") == m["sha256"]:
        return {"pronta": m["versao"]}

    pasta = _pasta_versao(m["versao"])
    caminhos = []
    for i, p in enumerate(m["partes"], 1):
        local = os.path.join(pasta, f"parte-{i}.bin")
        caminhos.append(local)
        if os.path.exists(local) and os.path.getsize(local) == p["tamanho"] \
                and _sha256_arquivo(local) == p["sha256"]:
            continue                                   # já veio e confere: não baixa de novo
        tmp = local + ".baixando"
        try:
            _get(p["nome"], cfg, destino=tmp)
        except Exception as exc:
            _apagar(tmp)
            return {"erro": f"a parte {i} não chegou ({exc})"}
        if os.path.getsize(tmp) != p["tamanho"] or _sha256_arquivo(tmp) != p["sha256"]:
            _apagar(tmp)
            LOG.warning("parte %d da versão %s não confere — descartada", i, m["versao"])
            return {"erro": f"a parte {i} chegou diferente do publicado — tento de novo na próxima abertura"}
        os.replace(tmp, local)

    exe = os.path.join(pasta, str(m.get("arquivo") or "Auto AF-AS.exe"))
    tmp = exe + ".juntando"
    with open(tmp, "wb") as saida:
        for c in caminhos:
            with open(c, "rb") as f:
                for bloco in iter(lambda: f.read(1024 * 1024), b""):
                    saida.write(bloco)
    if os.path.getsize(tmp) != m["tamanho"] or _sha256_arquivo(tmp) != m["sha256"]:
        _apagar(tmp)
        return {"erro": "o arquivo montado não confere com o publicado"}
    os.replace(tmp, exe)
    for c in caminhos:                                 # já juntou: as partes saem
        _apagar(c)
    with open(os.path.join(pasta_local(), "pronta.json"), "w", encoding="utf-8") as f:
        json.dump({"versao": m["versao"], "exe": exe, "sha256": m["sha256"], "tamanho": m["tamanho"],
                   "baixada_em": datetime.now().isoformat(timespec="seconds"),
                   "notas": m.get("notas", "")}, f, ensure_ascii=False)
    LOG.info("versão %s baixada e conferida — entra na próxima abertura", m["versao"])
    return {"pronta": m["versao"]}


def _apagar(caminho: str):
    try:
        if os.path.exists(caminho):
            os.remove(caminho)
    except OSError:
        pass


def em_segundo_plano(versao_atual: str):
    """Chamado numa thread ao abrir: baixa sem atrasar ninguém."""
    with _trava:
        if _estado["baixando"]:
            return
        _estado.update(baixando=True, erro="")
    try:
        r = baixar(versao_atual)
        with _trava:
            _estado.update(pronta=r.get("pronta", ""), erro=r.get("erro", ""))
        if r.get("erro"):
            LOG.warning("atualização pela internet: %s", r["erro"])
    except Exception as exc:                            # nunca derruba o app
        LOG.exception("falha ao baixar a atualização")
        with _trava:
            _estado["erro"] = str(exc)
    finally:
        with _trava:
            _estado["baixando"] = False


def estado(versao_atual: str) -> dict:
    """Para a tela: há versão baixada esperando a próxima abertura?"""
    with _trava:
        e = dict(_estado)
    if not e["pronta"]:
        p = pronta(versao_atual)
        e["pronta"] = p.get("versao", "")
    return e


# ------------------------------------------------------------------ aplicar --
def aplicar_pronta(versao_atual: str, exe: str, reabrir: bool = True) -> dict:
    """Na ABERTURA: havendo versão baixada e conferida, mais nova que esta,
    troca o executável e reabre. Mesma troca da pasta do setor (renomear o .exe
    em uso, pôr o novo no lugar, desfazer se der errado)."""
    p = pronta(versao_atual)
    if not p:
        limpar(versao_atual)
        return {"trocou": False}
    from .atualizador import aplicar, reabrir as _reabrir
    r = aplicar(p["exe"], exe)
    if not r.get("ok"):
        return {"trocou": False, "motivo": r.get("erro", "")}
    LOG.info("versão %s instalada a partir da internet", p["versao"])
    if reabrir:
        _reabrir(exe)
    return {"trocou": True, "versao": p["versao"]}


def limpar(versao_atual: str):
    """Tira o que já não serve: versões baixadas iguais ou mais velhas que a atual."""
    base = pasta_local()
    try:
        with open(os.path.join(base, "pronta.json"), encoding="utf-8") as f:
            d = json.load(f)
        if not mais_nova(d.get("versao", ""), versao_atual):
            _apagar(os.path.join(base, "pronta.json"))
    except (FileNotFoundError, ValueError, OSError):
        pass
    for nome in os.listdir(base):
        cam = os.path.join(base, nome)
        if os.path.isdir(cam) and not mais_nova(nome, versao_atual):
            for arq in os.listdir(cam):
                _apagar(os.path.join(cam, arq))
            try:
                os.rmdir(cam)
            except OSError:
                pass


# ----------------------------------------------------------------- publicar --
def publicar(exe: str, versao: str, url: str, chave_secreta: str, notas: str = "",
             tam_parte: int = TAM_PARTE, manter: int = 2) -> dict:
    """Envia a versão em partes e, POR ÚLTIMO, o versao.json que a anuncia.
    Usa a chave SECRETA — só quem publica a tem. Apaga do espaço as versões
    além das `manter` mais novas (o plano grátis tem 1 GB)."""
    if not (exe and os.path.exists(exe)):
        return {"ok": False, "erro": f"Executável não encontrado: {exe}"}
    if not re.fullmatch(r"[0-9][0-9A-Za-z.\-]*", versao or ""):
        return {"ok": False, "erro": f"Versão inválida: {versao!r}"}
    cfg = {"url": url.rstrip("/"), "chave": chave_secreta}

    def enviar(caminho, dados, tipo="application/octet-stream"):
        req = urllib.request.Request(_url(caminho, cfg, baixar=False), data=dados, method="POST")
        req.add_header("apikey", chave_secreta)
        req.add_header("Authorization", "Bearer " + chave_secreta)
        req.add_header("Content-Type", tipo)
        req.add_header("x-upsert", "true")
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()

    partes = []
    try:
        with open(exe, "rb") as f:
            i = 0
            while True:
                dados = f.read(tam_parte)
                if not dados:
                    break
                i += 1
                nome = f"{versao}/parte-{i}.bin"
                enviar(nome, dados)
                partes.append({"nome": nome, "tamanho": len(dados), "sha256": hashlib.sha256(dados).hexdigest()})
        m = {"versao": versao, "arquivo": os.path.basename(exe), "tamanho": os.path.getsize(exe),
             "sha256": _sha256_arquivo(exe), "partes": partes, "notas": notas,
             "publicado_em": datetime.now().isoformat(timespec="seconds")}
        if _manifesto_valido(m):
            return {"ok": False, "erro": "manifesto inválido: " + _manifesto_valido(m)}
        enviar(MANIFESTO, json.dumps(m, ensure_ascii=False, indent=2).encode("utf-8"), "application/json")
    except urllib.error.HTTPError as exc:
        # nada foi anunciado: o versao.json só sobe depois de todas as partes
        return {"ok": False, "erro": f"o Supabase recusou o envio (HTTP {exc.code}) — confira a chave "
                                     "secreta (SUPABASE_SECRET_KEY). Nenhuma máquina viu esta versão."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "erro": f"sem conexão ({exc}). Nenhuma máquina viu esta versão — publique de novo."}
    removidas = _podar(cfg, versao, manter)
    return {"ok": True, "versao": versao, "partes": len(partes), "tamanho": m["tamanho"],
            "sha256": m["sha256"], "removidas": removidas}


def _podar(cfg: dict, atual: str, manter: int) -> list:
    """Apaga as pastas de versões antigas (fica a atual e a anterior)."""
    def pedir(metodo, rota, corpo):
        req = urllib.request.Request(f"{cfg['url']}/storage/v1/{rota}", method=metodo,
                                     data=json.dumps(corpo).encode("utf-8"))
        req.add_header("apikey", cfg["chave"])
        req.add_header("Authorization", "Bearer " + cfg["chave"])
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8") or "null")
    try:
        itens = pedir("POST", f"object/list/{BUCKET}", {"prefix": "", "limit": 1000}) or []
        versoes = sorted({i["name"] for i in itens if i.get("id") is None and i.get("name")},
                         key=_partes_versao, reverse=True)      # pastas vêm sem id
        velhas = [v for v in versoes[manter:] if v != atual]
        apagar = []
        for v in velhas:
            conteudo = pedir("POST", f"object/list/{BUCKET}", {"prefix": v + "/", "limit": 1000}) or []
            apagar += [f"{v}/{c['name']}" for c in conteudo if c.get("name")]
        if apagar:
            pedir("DELETE", f"object/{BUCKET}", {"prefixes": apagar})
        return velhas
    except Exception as exc:                           # podar é arrumação, não pode falhar a publicação
        LOG.warning("não consegui apagar as versões antigas: %s", exc)
        return []

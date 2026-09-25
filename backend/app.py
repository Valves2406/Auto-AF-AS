"""
app.py — Gerador de AF (desktop). Janela = Edge em modo --app; servidor local
em Python puro (http.server, sem dependências). Backend = engine.py.

Rodar:  python app.py
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import engine
from core.dados_eletronet import LOGO
from core.log import get_logger

LOG = get_logger("app")

from core.caminhos import recurso, dado

WEB = recurso("frontend")
# Saída organizada: uma pasta "saída gerador" com 8 subpastas por tipo × formato.
SAIDA_BASE = dado("saída gerador")     # documentos do usuário: junto do .exe
_SUBPASTAS = ["AF-excel", "AF-pdf", "AS-excel", "AS-pdf",
              "CPM-excel", "CPM-pdf", "CPS-excel", "CPS-pdf"]
SAIDAS = SAIDA_BASE   # compat: /api/modelo_cadastro e afins usam a base


# ------------------------------------------------------------ preparação ----
# Boa parte do custo do app é PREGUIÇOSO: pdfplumber/openpyxl/pypdfium2 só são
# importados na 1ª vez que são usados, e o catálogo/template .xlsm podem estar
# como placeholder do OneDrive (precisam ser baixados). Isso caía todo em cima
# da PRIMEIRA ação do usuário. Aqui isso é feito ANTES, com a tela de carregamento
# mostrando o progresso — depois o uso é fluido.
_PASSOS = [
    ("catalogo", "Carregando catálogo (fornecedores, filiais e POPs)"),
    ("planilha", "Preparando leitura de planilhas"),
    ("pdf", "Preparando leitura de PDF"),
    ("documento", "Preparando montagem de documentos"),
]
_PREP = {"passo": "", "feitos": [], "total": len(_PASSOS), "pronto": False, "erro": ""}
_PREP_LOCK = threading.Lock()


def _marcar(chave: str):
    with _PREP_LOCK:
        if chave not in _PREP["feitos"]:
            _PREP["feitos"].append(chave)
        _PREP["passo"] = chave


def preparar():
    """Aquece tudo que é caro e preguiçoso. Best-effort: se um passo falhar, o app
    continua — só perde o ganho de velocidade daquele passo."""
    t0 = time.time()
    try:
        _marcar("catalogo")
        engine.dados()                       # lê o .xlsm (hidrata se for placeholder OneDrive)

        # Atualização: o arquivo do usuário sobreviveu à troca do executável,
        # então é aqui que ele é posto no formato da versão que acabou de abrir.
        try:
            from core.dados_eletronet import migrar
            r = migrar()
            if r.get("passos"):
                LOG.info("dados atualizados: %s", "; ".join(r["passos"]))
        except Exception as exc:
            LOG.warning("não consegui migrar os dados do usuário: %s", exc)

        # Banco da equipe: o que o arquivo de cadastros desta máquina tem e o
        # banco ainda não, vai — uma vez por arquivo (depois ele fica carimbado).
        try:
            from core.dados_eletronet import levar_para_o_banco
            if levar_para_o_banco().get("incluidos"):
                engine.dados()               # as listas já com o que acabou de entrar
        except Exception as exc:
            LOG.warning("não consegui levar os cadastros para o banco: %s", exc)

        # Varre as lições aprendidas e descarta as que não passam nas regras
        # atuais — a versão antiga guardava pedaços de prosa que preenchiam o
        # campo errado. Roda uma vez por abertura e é barato (dezenas de itens).
        try:
            from core.aprendizado import sanear
            sanear()
        except Exception as exc:
            LOG.warning("não consegui sanear as lições: %s", exc)

        _marcar("planilha")
        import openpyxl                      # noqa: F401
        from openpyxl import load_workbook   # noqa: F401
        # toca os templates p/ o OneDrive hidratar e o SO cachear o arquivo
        for nome in ("modelo_af.xlsm", "modelo_as.xlsm", "modelo_cpm.xlsx"):
            p = recurso("frontend", "imagens", nome)
            try:
                if os.path.exists(p):
                    with open(p, "rb") as f:
                        f.read()
            except OSError:
                pass

        _marcar("pdf")
        import pdfplumber                    # noqa: F401
        try:
            import pypdfium2                 # noqa: F401
        except ImportError:
            pass

        _marcar("documento")
        # 1ª montagem de prévia: compila os regex e embute o logo em base64
        engine.montar_preview({"fornecedor": "", "valor_total": "0,00", "moeda": "Real",
                               "prefixo": "AF-E", "numero": "0", "ano": "2026", "itens": []})
    except Exception as exc:                 # nunca deixa o app travado na tela
        with _PREP_LOCK:
            _PREP["erro"] = str(exc)
        LOG.warning("preparação incompleta: %s", exc)
    finally:
        with _PREP_LOCK:
            _PREP["pronto"] = True
        LOG.info("preparação concluída em %.1fs", time.time() - t0)


def _garantir_saidas():
    os.makedirs(SAIDA_BASE, exist_ok=True)
    for s in _SUBPASTAS:
        os.makedirs(os.path.join(SAIDA_BASE, s), exist_ok=True)


def _subpasta_de(nome: str):
    """Subpasta certa (AF-excel, CPS-pdf, …) a partir do NOME do arquivo.
    Arquivos que não são AF/AS/CPM/CPS (ex.: Modelo_Cadastros) → None."""
    n = os.path.basename(nome).upper()
    fmt = "pdf" if n.lower().endswith(".pdf") else "excel"
    doc = ("CPS" if n.startswith("RTC-CPS") or n.startswith("CPS")
           else "CPM" if n.startswith("RTC-CPM") or n.startswith("CPM")
           else "AS" if n.startswith("AS-") or n.startswith("AS ")
           else "AF" if n.startswith("AF-") or n.startswith("AF ")
           else None)
    return f"{doc}-{fmt}" if doc else None


def _caminho_saida(nome: str) -> str:
    """Caminho final do arquivo dentro da subpasta correta (criando-a)."""
    _garantir_saidas()
    sub = _subpasta_de(nome)
    pasta = os.path.join(SAIDA_BASE, sub) if sub else SAIDA_BASE
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, nome)


def _migrar_saidas():
    """Organiza a saída: move AF/AS/CPM/CPS p/ as 8 subpastas e leva o resto (ex.:
    Modelo_Cadastros) da pasta antiga 'saidas' p/ a raiz de 'saída gerador'.
    Best-effort (arquivos abertos/travados são pulados). Idempotente."""
    import shutil
    _garantir_saidas()
    velha = dado("saidas")
    for src in (velha, SAIDA_BASE):
        if not os.path.isdir(src):
            continue
        for nome in os.listdir(src):
            p = os.path.join(src, nome)
            if not os.path.isfile(p):
                continue
            sub = _subpasta_de(nome)
            if sub:
                dst = os.path.join(SAIDA_BASE, sub, nome)
            elif src == velha:                # "outro" arquivo na pasta antiga → base
                dst = os.path.join(SAIDA_BASE, nome)
            else:
                continue                      # já está na base, sem subpasta → fica
            if os.path.abspath(p) == os.path.abspath(dst):
                continue
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                shutil.move(p, dst)
            except Exception:
                pass
    try:                                      # remove a pasta antiga se ficou vazia
        if os.path.isdir(velha) and not os.listdir(velha):
            os.rmdir(velha)
    except Exception:
        pass


_migrar_saidas()   # organiza a saída já na subida do app

_CTYPE = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "application/javascript; charset=utf-8"}
MAX_UPLOAD = 150 * 1024 * 1024   # 150 MB — nenhuma proposta legítima chega perto disso

# Ciclo de vida: o processo lançador do Edge encerra logo após abrir a janela,
# então não dá p/ usar .wait(). A página manda um "ping" periódico; enquanto
# houver ping o app fica vivo, e ao fechar a janela (pagehide) avisa /api/fechar.
_estado = {"ping": 0.0, "ativo": False, "fechar": False}
# Uma janela fechando NÃO pode derrubar o servidor das outras: cada aba/janela
# manda seu id no ping e só encerramos quando a última avisa que saiu.
_clientes: dict[str, float] = {}
_CLI_LOCK = threading.Lock()


def _visto(cli: str):
    if cli:
        with _CLI_LOCK:
            _clientes[cli] = time.time()


def _saiu(cli: str) -> bool:
    """Marca a saída do cliente; devolve True se não sobrou ninguém."""
    with _CLI_LOCK:
        _clientes.pop(cli, None)
        vivos = [c for c, t in _clientes.items() if time.time() - t < 90]
        return not vivos


def _sanitize(nome: str) -> str:
    # NFC: nome vindo do OneDrive/Mac traz "c" + cedilha solta (U+0327); sem
    # isto a cedilha caía no filtro e "Orçamento" virava "Orcamento".
    nome = unicodedata.normalize("NFC", nome or "AF")
    nome = "".join(c for c in nome if c.isalnum() or c in "._- ").strip()
    return nome or "AF"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype, extra=None):
        data = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        self._send(200, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        _estado["ping"] = time.time(); _estado["ativo"] = True
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path == "/logo.jpeg":
            with open(LOGO, "rb") as f:
                return self._send(200, f.read(), "image/jpeg")
        if path == "/logo.png":
            # versão da UI: fundo transparente + marca na cor da marca (o JPEG
            # original segue sendo o usado nos DOCUMENTOS). Cai no JPEG se faltar.
            p = recurso("frontend", "imagens", "eletronet_logo_ui.png")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), "image/png")
            with open(LOGO, "rb") as f:
                return self._send(200, f.read(), "image/jpeg")
        if path == "/app.ico":
            # o ícone da aba e da barra de tarefas é o mesmo do executável.
            # Resolve por recurso(), não por dirname(LOGO): LOGO é o JPEG dos
            # DOCUMENTOS e mora em backend/modelos/, enquanto a marca da tela
            # está em frontend/imagens/. Amarrar um ao outro era o que deixava
            # o ícone e a faixa quebrados.
            p = recurso("frontend", "imagens", "app.ico")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), "image/x-icon")
            return self._send(404, b"", "image/x-icon")
        if path in ("/marca.svg", "/marca.png", "/simbolo.svg", "/simbolo.png"):
            # Marca do Auto AF/AS. A rota serve pelo PRÓPRIO nome do arquivo —
            # antes havia um de-para para nomes internos ("autoafas_logo.png"),
            # e trocar o conjunto de imagens exigia lembrar de mexer aqui
            # também. Agora o nome da rota é o nome do arquivo.
            #
            # O SVG é o que vale: vetor, nítido em qualquer tela e em qualquer
            # zoom. O PNG fica como reserva.
            arq = path.lstrip("/")
            p = recurso("frontend", "imagens", arq)
            tipo = "image/svg+xml" if arq.endswith(".svg") else "image/png"
            if os.path.exists(p):
                with open(p, "rb") as f:
                    return self._send(200, f.read(), tipo)
            return self._send(404, b"", tipo)
        if path == "/api/preparar":
            # progresso da preparação, p/ a tela de carregamento
            with _PREP_LOCK:
                est = dict(_PREP, passos=[{"chave": k, "rotulo": r} for k, r in _PASSOS])
            return self._send(200, json.dumps(est).encode(), "application/json; charset=utf-8")
        if path.lstrip("/") in ("app.css", "app.js"):
            return self._static(path.lstrip("/"))
        # Fonte da marca (DM Sans) empacotada: a janela é o Edge em modo --app e
        # não há garantia de internet, então a fonte NÃO pode vir do Google.
        if path.startswith("/fontes/") and path.endswith(".woff2"):
            nome = os.path.basename(path)          # só o nome: nada de subir pastas
            alvo = os.path.join(WEB, "fontes", nome)
            if os.path.exists(alvo):
                with open(alvo, "rb") as f:
                    return self._send(200, f.read(), "font/woff2")
        self._send(404, "não encontrado", "text/plain; charset=utf-8")

    def _static(self, nome):
        p = os.path.join(WEB, nome)
        if not os.path.exists(p):
            return self._send(404, "404", "text/plain")
        ext = os.path.splitext(nome)[1]
        with open(p, "rb") as f:
            self._send(200, f.read(), _CTYPE.get(ext, "application/octet-stream"))

    def _upload_tmp(self, raw: bytes, prefixo: str, nome_padrao: str) -> str:
        """Grava o corpo do upload num arquivo temporário com o nome saneado."""
        # o front manda o nome com encodeURIComponent (cabeçalho só aceita Latin-1)
        fn = _sanitize(urllib.parse.unquote(self.headers.get("X-Filename", "") or nome_padrao))
        tmp = os.path.join(tempfile.gettempdir(), f"{prefixo}_{uuid.uuid4().hex}_{fn}")
        with open(tmp, "wb") as f:
            f.write(raw)
        return tmp

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        ln = int(self.headers.get("Content-Length", 0) or 0)
        if ln > MAX_UPLOAD:
            return self._json({"ok": False,
                               "erro": f"Arquivo acima do limite ({MAX_UPLOAD // (1024 * 1024)} MB)."})
        raw = self.rfile.read(ln) if ln else b""
        _estado["ping"] = time.time(); _estado["ativo"] = True
        try:
            if path == "/api/ping":
                _visto(self.headers.get("X-Cliente", ""))
                self._json({"ok": True})
            elif path == "/api/fechar":          # janela foi fechada (sendBeacon)
                cli = self.headers.get("X-Cliente", "") or (json.loads(raw or b"{}") or {}).get("cli", "")
                # só encerra o servidor quando a ÚLTIMA janela sai
                if _saiu(cli):
                    _estado["fechar"] = True
                self._json({"ok": True})
            elif path == "/api/dados":
                self._json(engine.dados())
            elif path == "/api/padroes":
                self._json(engine.padroes())
            elif path == "/api/salvar_padroes":
                self._json(engine.salvar_padroes(json.loads(raw or b"{}")))
            elif path == "/api/salvar_pessoas":
                self._json(engine.salvar_pessoas(json.loads(raw or b"{}").get("pessoas")))
            elif path == "/api/cadastrar":
                j = json.loads(raw or b"{}")
                self._json(engine.cadastrar(j.get("tipo", ""), j.get("dados", {})))
            elif path == "/api/modelo_cadastro":     # planilha-modelo p/ cadastro em massa
                caminho = os.path.join(SAIDAS, "Modelo_Cadastros_em_Massa.xlsx")
                res = engine.modelo_cadastro(caminho)
                if res.get("ok"):
                    try:
                        os.startfile(caminho)  # noqa — abre no Excel p/ preencher
                    except Exception:
                        pass
                self._json(res)
            elif path == "/api/importar_cadastros":  # importa a planilha preenchida
                tmp = self._upload_tmp(raw, "geradoraf_cad", "cadastros.xlsx")
                try:
                    self._json(engine.importar_cadastros(tmp))
                finally:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            elif path == "/api/atualizar":       # editar um cadastro do usuário
                j = json.loads(raw or b"{}")
                self._json(engine.atualizar(j.get("tipo", ""), j.get("id", {}), j.get("dados", {})))
            elif path == "/api/remover":
                j = json.loads(raw or b"{}")
                self._json(engine.remover(j.get("tipo", ""), j.get("dados", {})))
            elif path == "/api/restaurar":
                j = json.loads(raw or b"{}")
                self._json(engine.restaurar(j.get("tipo", ""), j.get("dados", {})))
            elif path == "/api/extrair":
                tmp = self._upload_tmp(raw, "geradoraf", "proposta.pdf")
                self._json(engine.extrair(tmp))
            elif path == "/api/importar_af":     # caminho inverso: lê uma AF pronta
                tmp = self._upload_tmp(raw, "geradoraf_af", "af.xlsx")
                self._json(engine.importar_af(tmp))
            elif path == "/api/preview":
                html = engine.montar_preview(json.loads(raw or b"{}"))
                self._send(200, html, "text/html; charset=utf-8")
            elif path == "/api/gerar":
                j = json.loads(raw or b"{}")
                ext = ".xlsx" if j.get("formato") == "excel" else ".pdf"
                j["saida"] = _caminho_saida(_sanitize(j.get("nome_arquivo", "AF")) + ext)
                self._json(engine.gerar(j))
            elif path == "/api/cpm_dados":       # CPM/CPS preenchido a partir da AF
                self._json(engine.cpm_dados(json.loads(raw or b"{}")))
            elif path == "/api/cpm_preview":
                self._send(200, engine.cpm_preview(json.loads(raw or b"{}")), "text/html; charset=utf-8")
            elif path == "/api/gerar_cpm":
                j = json.loads(raw or b"{}")
                ext = ".xlsx" if j.get("formato") == "excel" else ".pdf"
                j["saida"] = _caminho_saida(_sanitize(j.get("nome_arquivo", "CPM")) + ext)
                self._json(engine.gerar_cpm(j))
            elif path == "/api/compartilhar":     # cadastros numa pasta de rede
                j = json.loads(raw or b"{}") if raw else {}
                self._json(engine.compartilhar_dados(j.get("caminho", "")))
            elif path == "/api/abrir":
                j = json.loads(raw or b"{}") if raw else {}
                alvo = j.get("pasta") or SAIDA_BASE
                # segurança: só abre dentro da árvore de saída
                if not os.path.abspath(alvo).startswith(os.path.abspath(SAIDA_BASE)):
                    alvo = SAIDA_BASE
                if not os.path.isdir(alvo):
                    alvo = SAIDA_BASE
                try:
                    os.startfile(alvo)  # noqa
                except Exception:
                    pass
                self._json({"ok": True, "pasta": alvo})
            else:
                self._send(404, "{}", "application/json")
        except Exception as exc:
            import traceback
            LOG.exception("erro na rota %s", path)   # p/ diagnóstico (ver core/log.py)
            self._json({"ok": False, "erro": str(exc), "trace": traceback.format_exc()[-600:]})


# ===========================================================================
# A JANELA — qualquer navegador, começando pelo que a pessoa escolheu.
#
# Antes só havia Edge. Numa máquina sem Edge (ou de quem usa outro navegador) o
# app caía no `webbrowser.open`, que abre uma ABA no meio das outras: sem janela
# própria, sem tamanho definido, e fácil de fechar por engano junto com o resto.
#
# Agora a ordem é: o navegador PADRÃO do Windows primeiro — é o que a pessoa
# escolheu — e, se ele não estiver na lista ou não for encontrado, os principais
# na ordem em que aparecem aqui. `GERADORAF_NAVEGADOR=chrome` força um deles.
#
# Nos navegadores da família Chromium (Edge, Chrome, Brave, Vivaldi, Opera) a
# janela abre em modo `--app`: sem abas nem barra de endereço, com cara de
# programa. O Firefox não tem esse modo; lá abre uma janela normal, que funciona
# igual — o app é a mesma página.
# ===========================================================================
_PF = os.environ.get("ProgramFiles", r"C:\Program Files")
_PF86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
_LOCAL = os.environ.get("LOCALAPPDATA", "")

# chave -> (nome para o log, tipo, caminhos possiveis)
NAVEGADORES = {
    "edge": ("Microsoft Edge", "chromium", [
        os.path.join(_PF86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(_PF, r"Microsoft\Edge\Application\msedge.exe")]),
    "chrome": ("Google Chrome", "chromium", [
        os.path.join(_PF, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(_PF86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(_LOCAL, r"Google\Chrome\Application\chrome.exe")]),
    "brave": ("Brave", "chromium", [
        os.path.join(_PF, r"BraveSoftware\Brave-Browser\Application\brave.exe"),
        os.path.join(_PF86, r"BraveSoftware\Brave-Browser\Application\brave.exe")]),
    "vivaldi": ("Vivaldi", "chromium", [
        os.path.join(_LOCAL, r"Vivaldi\Application\vivaldi.exe"),
        os.path.join(_PF, r"Vivaldi\Application\vivaldi.exe")]),
    "opera": ("Opera", "chromium", [
        os.path.join(_LOCAL, r"Programs\Opera\opera.exe"),
        os.path.join(_PF, r"Opera\opera.exe")]),
    "firefox": ("Mozilla Firefox", "firefox", [
        os.path.join(_PF, r"Mozilla Firefox\firefox.exe"),
        os.path.join(_PF86, r"Mozilla Firefox\firefox.exe")]),
}
# ordem de tentativa quando nao da para saber o padrao
ORDEM = ("edge", "chrome", "firefox", "brave", "vivaldi", "opera")

# o que o Windows guarda como "programa que abre http"
_PROGID = {"MSEdgeHTM": "edge", "MSEdgeDHTML": "edge", "AppXq0fevzme2pys62n3e0fbqa7peapykr8v": "edge",
           "ChromeHTML": "chrome", "BraveHTML": "brave", "BraveFile": "brave",
           "VivaldiHTM": "vivaldi", "OperaStable": "opera", "Opera.HTML": "opera",
           "FirefoxURL": "firefox"}


def _padrao_do_windows():
    """Qual navegador esta marcado como padrao? None se nao der para saber."""
    try:
        import winreg
        chave = (r"Software\Microsoft\Windows\Shell\Associations"
                 r"\UrlAssociations\http\UserChoice")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
            progid = str(winreg.QueryValueEx(k, "ProgId")[0])
        for pref, nav in _PROGID.items():
            if progid.startswith(pref):
                return nav
        LOG.info("navegador padrao desconhecido (ProgId %s)", progid)
    except Exception as exc:            # sem registro, sem permissao, outro SO
        LOG.info("nao consegui ler o navegador padrao: %s", exc)
    return None


def _caminho(nav):
    for c in NAVEGADORES[nav][2]:
        if c and os.path.exists(c):
            return c
    return None


def _abrir(nav, caminho, url):
    """Abre a janela. Chromium em modo app; Firefox em janela nova."""
    nome, tipo, _ = NAVEGADORES[nav]
    if tipo == "chromium":
        # Perfil por INSTALACAO (hash da pasta do app), nao fixo. Com um caminho
        # unico p/ todos, abrir uma segunda copia (ex.: o .exe com o app ja
        # rodando pelo codigo-fonte) fazia o navegador apenas repassar a URL para
        # a instancia existente e o lancador saia na hora — a nova janela nunca
        # pingava e o servidor se encerrava sozinho. Chavear pela pasta (e nao
        # pela porta/PID) evita criar um perfil novo — dezenas de MB — a cada
        # abertura.
        chave = hashlib.md5((nav + dado()).encode("utf-8", "replace")).hexdigest()[:8]
        perfil = os.path.join(tempfile.gettempdir(), "geradoraf_%s_%s" % (nav, chave))
        args = [caminho, "--app=" + url, "--user-data-dir=" + perfil,
                "--no-first-run", "--no-default-browser-check", "--window-size=1440,940"]
    else:
        args = [caminho, "-new-window", url]
    LOG.info("abrindo a janela no %s", nome)
    return subprocess.Popen(args)


def _lancar_navegador(url: str):
    escolhido = (os.environ.get("GERADORAF_NAVEGADOR") or "").strip().lower()
    tentar = []
    if escolhido in NAVEGADORES:
        tentar.append(escolhido)
    padrao = _padrao_do_windows()
    if padrao and padrao not in tentar:
        tentar.append(padrao)            # o que a pessoa escolheu vem primeiro
    tentar += [n for n in ORDEM if n not in tentar]

    for nav in tentar:
        caminho = _caminho(nav)
        if not caminho:
            continue
        try:
            return _abrir(nav, caminho, url)
        except Exception as exc:         # instalado mas nao abriu: tenta o proximo
            LOG.warning("nao consegui abrir o %s: %s", NAVEGADORES[nav][0], exc)
    return None


def main():
    # ATUALIZAÇÃO AUTOMÁTICA — antes de tudo. Se alguém publicou uma versão nova
    # na pasta do setor, esta máquina troca e reabre já atualizada. Tem de ser
    # aqui, antes do servidor e da janela: depois a pessoa começou a trabalhar, e
    # fechar o programa embaixo dela é pior que ficar uma versão atrás.
    # Qualquer tropeço (pasta fora do ar, sem permissão, cópia pela metade) abre
    # normalmente na versão que já está na máquina.
    try:
        from core.atualizador import atualizar_na_abertura
        from core.dados_eletronet import VERSAO_APP

        if atualizar_na_abertura(VERSAO_APP).get("trocou"):
            LOG.info("versão nova assumiu — esta instância vai sair")
            return
    except Exception as exc:
        LOG.warning("atualização automática não pôde ser verificada: %s", exc)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    # Aquece TUDO que é caro/preguiçoso (catálogo, openpyxl, pdfplumber, prévia)
    # em paralelo com a abertura do Edge. A tela de carregamento acompanha por
    # /api/preparar e só libera a interface quando termina — assim a lentidão não
    # cai em cima da primeira ação do usuário.
    threading.Thread(target=preparar, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"Gerador de AF rodando em {url}  (saídas em {SAIDAS})")
    LOG.info("sessão iniciada em %s (saídas em %s)", url, SAIDAS)

    if not _lancar_navegador(url):
        import webbrowser
        webbrowser.open(url)

    # Mantém o app vivo enquanto a janela estiver aberta. NÃO usamos edge.wait()
    # porque o processo lançador do Edge sai assim que abre a janela (e mataria o
    # servidor antes da página carregar). Em vez disso seguimos o heartbeat:
    #  • a janela demora a abrir → espera até 60s pela 1ª chamada;
    #  • aberta → fica viva enquanto pingar (limite 90s p/ aguentar aba em 2º plano);
    #  • fechada → /api/fechar (sendBeacon) encerra na hora.
    inicio = time.time()
    try:
        while not _estado["fechar"]:
            time.sleep(2)
            if not _estado["ativo"]:
                if time.time() - inicio > 60:
                    break
            elif time.time() - _estado["ping"] > 90:
                break
    except KeyboardInterrupt:
        pass
    httpd.shutdown()


if __name__ == "__main__":
    main()

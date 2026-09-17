# -*- coding: utf-8 -*-
r"""A janela do app abre em qualquer navegador, começando pelo favorito.

Antes só havia Edge. Numa máquina sem Edge — ou de quem usa outro navegador — o
app caía no `webbrowser.open`, que abre uma ABA no meio das outras: sem janela
própria, sem tamanho definido e fácil de fechar por engano junto com o resto.

A ordem agora é: o navegador PADRÃO do Windows primeiro (é o que a pessoa
escolheu) e, se ele não estiver instalado ou não for conhecido, os principais na
ordem da lista. `GERADORAF_NAVEGADOR=chrome` força um deles.

Nos navegadores da família Chromium a janela abre em modo `--app`: sem abas nem
barra de endereço. O Firefox não tem esse modo — lá abre uma janela normal, que
funciona igual, porque o app é a mesma página.

Nada aqui abre janela de verdade: o lançador é trocado por um dublê que só
anota o que teria sido chamado.
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, "backend"))
sys.path.insert(0, PROJ)
import app

falhas = []


def ok(nome, cond, extra=""):
    print(("  OK   " if cond else "  FALHA") + " " + nome + (("   " + extra) if extra and not cond else ""))
    if not cond:
        falhas.append(nome)


chamadas = []


class Duble:
    def __init__(self, args, **k):
        chamadas.append(args)


app.subprocess.Popen = Duble
_caminho_real = app._caminho


def lancar(padrao=None, forcado=None, instalados=()):
    chamadas.clear()
    app._padrao_do_windows = lambda: padrao
    app._caminho = lambda n: ("C:/x/%s.exe" % n) if n in instalados else None
    if forcado:
        os.environ["GERADORAF_NAVEGADOR"] = forcado
    else:
        os.environ.pop("GERADORAF_NAVEGADOR", None)
    r = app._lancar_navegador("http://127.0.0.1:9/")
    if not chamadas:
        return None, None, r
    args = chamadas[0]
    exe = os.path.basename(args[0]).replace(".exe", "")
    modo = "app" if any(str(x).startswith("--app=") for x in args) else "janela"
    return exe, modo, r


TODOS = ("edge", "chrome", "firefox", "brave", "vivaldi", "opera")

print("== o favorito da pessoa vem primeiro ==")
for padrao in TODOS:
    exe, modo, _ = lancar(padrao=padrao, instalados=TODOS)
    ok("padrao %-8s abre o %s" % (padrao, padrao), exe == padrao, str(exe))

print("\n== Chromium abre em modo app; Firefox em janela ==")
for nav in ("edge", "chrome", "brave", "vivaldi", "opera"):
    _, modo, _ = lancar(padrao=nav, instalados=TODOS)
    ok("%-8s em modo app (sem abas nem barra)" % nav, modo == "app", str(modo))
_, modo, _ = lancar(padrao="firefox", instalados=TODOS)
ok("firefox  em janela normal", modo == "janela",
   "o Firefox nao tem modo --app; forcar isso abriria uma janela quebrada")

print("\n== quando o favorito nao serve ==")
exe, _, _ = lancar(padrao="chrome", instalados=("edge",))
ok("favorito ausente cai no proximo instalado", exe == "edge", str(exe))
exe, _, _ = lancar(padrao=None, instalados=("firefox",))
ok("padrao desconhecido usa o que houver", exe == "firefox", str(exe))
exe, modo, r = lancar(padrao="edge", instalados=())
ok("sem navegador nenhum, devolve nada", exe is None and r is None,
   "quem chama cai no webbrowser.open, que ainda abre a pagina")

print("\n== a variavel de ambiente manda ==")
exe, _, _ = lancar(padrao="edge", forcado="firefox", instalados=TODOS)
ok("GERADORAF_NAVEGADOR passa na frente do padrao", exe == "firefox", str(exe))
exe, _, _ = lancar(padrao="edge", forcado="navegador-que-nao-existe", instalados=TODOS)
ok("valor invalido e ignorado, nao quebra", exe == "edge", str(exe))

print("\n== perfil separado por navegador e por instalacao ==")
# Sem perfil proprio, abrir uma 2a copia fazia o navegador so repassar a URL para
# a instancia existente: o lancador saia na hora, a janela nova nunca pingava e o
# servidor se encerrava sozinho.
chamadas.clear()
lancar(padrao="edge", instalados=TODOS)
perf_edge = [x for x in chamadas[0] if str(x).startswith("--user-data-dir=")]
chamadas.clear()
lancar(padrao="chrome", instalados=TODOS)
perf_chrome = [x for x in chamadas[0] if str(x).startswith("--user-data-dir=")]
ok("cada navegador tem seu perfil", perf_edge and perf_chrome and perf_edge != perf_chrome,
   "%s vs %s" % (perf_edge, perf_chrome))
ok("o perfil nao e recriado a cada abertura", "geradoraf_" in (perf_edge[0] if perf_edge else ""),
   "perfil por porta ou PID criaria dezenas de MB por abertura")

print("\n== a lista cobre os navegadores principais ==")
ok("os seis estao previstos", set(app.NAVEGADORES) == set(TODOS), str(sorted(app.NAVEGADORES)))
ok("cada um tem pelo menos um caminho previsto",
   all(v[2] for v in app.NAVEGADORES.values()))
ok("o registro do Windows e consultado", "UrlAssociations" in io.open(
   os.path.join(PROJ, "backend", "app.py"), encoding="utf-8").read())
ok("ler o registro nunca derruba o app", "except Exception as exc:" in io.open(
   os.path.join(PROJ, "backend", "app.py"), encoding="utf-8").read()[
       io.open(os.path.join(PROJ, "backend", "app.py"), encoding="utf-8").read().index("_padrao_do_windows"):])

app._caminho = _caminho_real
print("\n%s" % ("TUDO OK" if not falhas else "FALHAS (%d): %s" % (len(falhas), ", ".join(falhas))))
sys.exit(1 if falhas else 0)

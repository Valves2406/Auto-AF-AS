"""
trava.py — trava de arquivo ENTRE PROCESSOS (multiacesso).

Por que existe: o `dados_usuario.json` fica na pasta do projeto, que é
compartilhada (OneDrive). Se duas pessoas rodarem o app ao mesmo tempo, o padrão
"ler → modificar → gravar" faz o último a gravar APAGAR o cadastro do outro, sem
erro nenhum. A gravação já era atômica (temp + os.replace), o que protege contra
arquivo corrompido por crash — mas atomicidade NÃO resolve perda de atualização.

Implementação: um arquivo-trava criado com O_CREAT|O_EXCL (operação atômica no
sistema de arquivos). Quem consegue criar, tem a trava. Inclui:
  • espera com timeout (não trava a interface para sempre);
  • recuperação de trava ÓRFÃ (processo morto sem liberar) por idade;
  • o PID e o horário ficam gravados dentro, p/ diagnóstico.
"""

from __future__ import annotations

import contextlib
import os
import time

from .log import get_logger

LOG = get_logger("trava")

TIMEOUT = 10.0        # s esperando a vez
IDADE_ORFA = 60.0     # s: trava mais velha que isso é considerada abandonada
_INTERVALO = 0.05


@contextlib.contextmanager
def travar(caminho: str, timeout: float = TIMEOUT):
    """Segura a trava de `caminho` (cria `<caminho>.lock`) enquanto o bloco roda.

    Se não conseguir dentro do timeout, segue MESMO ASSIM avisando no log: é
    melhor gravar com risco baixo do que travar o app do usuário — o pior caso
    volta a ser o comportamento antigo, não uma regressão."""
    lock = caminho + ".lock"
    inicio = time.time()
    fd = None
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
            break
        except FileExistsError:
            # trava órfã? (processo morreu sem liberar)
            try:
                if time.time() - os.path.getmtime(lock) > IDADE_ORFA:
                    LOG.warning("trava órfã removida: %s", lock)
                    os.unlink(lock)
                    continue
            except OSError:
                pass
            if time.time() - inicio > timeout:
                LOG.warning("timeout esperando a trava %s — seguindo sem ela", lock)
                break
            time.sleep(_INTERVALO)
        except OSError as exc:            # pasta read-only, etc. → não trava o app
            LOG.warning("não consegui criar a trava (%s) — seguindo sem ela", exc)
            break
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
                os.unlink(lock)
            except OSError:
                pass

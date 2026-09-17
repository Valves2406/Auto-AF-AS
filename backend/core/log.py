"""
log.py — logger único do Gerador de AF.

NÃO cria arquivo de log. O app roda a partir da área de trabalho das pessoas, e
um `geradoraf.log` nascendo ao lado do executável é sujeira na área de trabalho
de todo o setor.

As chamadas LOG.info/LOG.exception continuam espalhadas pelo código e continuam
funcionando — o registro vai para o console (que, num .exe com `console=False`,
simplesmente não tem para onde ir). Quando for preciso diagnosticar alguma
coisa, a gravação em arquivo se liga por variável de ambiente:

    set GERADORAF_LOG=C:\temp\autoaf.log

Aí sim o arquivo é criado, rotativo (512 KB × 3) — e só naquela execução, na
máquina de quem está investigando.

Uso:  from .log import get_logger
      LOG = get_logger("gerador")     # vira "geradoraf.gerador" no registro
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

# Só grava em arquivo se PEDIREM. Sem a variável, LOG_PATH é "" e nenhum
# arquivo é criado — nem vazio, nem rotacionado.
LOG_PATH = os.environ.get("GERADORAF_LOG") or ""


def get_logger(nome: str = "") -> logging.Logger:
    base = logging.getLogger("geradoraf")
    if not base.handlers:                     # configura uma única vez
        base.setLevel(logging.INFO)
        base.propagate = False
        fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s — %(message)s",
                                "%d/%m/%Y %H:%M:%S")
        if LOG_PATH:                          # só quando GERADORAF_LOG foi definida
            try:
                fh = RotatingFileHandler(LOG_PATH, maxBytes=512 * 1024, backupCount=3,
                                         encoding="utf-8")
                fh.setFormatter(fmt)
                base.addHandler(fh)
            except Exception:                 # sem permissão de escrita → só console
                pass
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        base.addHandler(sh)
    return logging.getLogger(f"geradoraf.{nome}") if nome else base

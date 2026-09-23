"""Dispara o worker local fora do processo HTTP."""

from __future__ import annotations

import os
import subprocess
import sys

from api import settings


def iniciar_worker() -> None:
    """Inicia um consumidor dos lotes pendentes sem bloquear a resposta web.

    O próprio worker usa `FOR UPDATE SKIP LOCKED`, então disparos concorrentes
    não processam o mesmo lote duas vezes.
    """
    if settings.banco_eh_de_teste(settings.database_url()):
        return
    kwargs = {
        "cwd": settings.RAIZ,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen([sys.executable, "-m", "maintenance.prospeccao.worker"], **kwargs)

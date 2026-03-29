from __future__ import annotations

import builtins
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)


def _make_auto_input():
    counters: dict[str, int] = {}

    def auto_input(prompt: str = "") -> str:
        text = str(prompt or "")
        norm = " ".join(text.lower().split())
        counters[norm] = counters.get(norm, 0) + 1

        if "escolha o numero do laudo" in norm or "escolha o número do laudo" in norm:
            return "N"
        if "nome do laudo" in norm:
            return f"Laudo_WEB_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if "descricao (enter para pular)" in norm or "descrição (enter para pular)" in norm:
            return "Execucao automatizada via frontend."
        if "perito responsavel" in norm or "perito responsável" in norm:
            return "Frontend Next"

        if "continuar com proxima imagem" in norm or "continuar com próxima imagem" in norm:
            return "S"

        if "g — gravidade" in norm or "g - gravidade" in norm:
            return "3"
        if "u — urgencia" in norm or "u — urgência" in norm or "u - urgencia" in norm:
            return "3"
        if "t — tendencia" in norm or "t — tendência" in norm or "t - tendencia" in norm:
            return "3"
        if "risco (" in norm:
            return "Medio"

        if "origem (endogena/exogena/natural/funcional)" in norm or "origem (endógena/exógena/natural/funcional)" in norm:
            return "Endogena"
        if "natureza (vicio construtivo/avaria/decrepitude)" in norm or "natureza (vício construtivo/avaria/decrepitude)" in norm:
            return "Vicio Construtivo"

        if "[enter]" in norm:
            return ""
        if "opcao" in norm or "opção" in norm or "escolha [1-5]" in norm:
            return "1"
        if "fonte [1-4]" in norm:
            return "1"
        if "quantidade de resultados" in norm:
            return "5"

        # Prompt curto genérico em menus.
        if norm.endswith(">") or norm == ">":
            return "1" if counters[norm] > 1 else ""

        return ""

    return auto_input


def main() -> int:
    builtins.input = _make_auto_input()
    print(f"[{datetime.now().isoformat()}] Runner analise_img iniciado.")
    print(f"Projeto: {ROOT}")

    from main import CerebroEngenharia
    from analise_imagem import AnalisadorImagem

    app = CerebroEngenharia()
    analisador = AnalisadorImagem(
        db_manager=app.db,
        ai_engine=app.ai,
    )

    processadas = analisador.processar_lote()
    print(f"[{datetime.now().isoformat()}] Runner concluido. Imagens processadas: {processadas}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[{datetime.now().isoformat()}] Erro no runner: {exc}")
        traceback.print_exc()
        raise SystemExit(1)

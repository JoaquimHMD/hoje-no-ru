"""Estimativa da fila do RU Trindade a partir da transmissão pública do Eduplay.

Pega um quadro do mosaico de câmeras (https://eduplay.rnp.br/app/tv/fila-ru-trindade),
conta as pessoas em cada câmera com um detector (YOLO) e grava docs/fila.json.
Só os números são gravados: nenhuma imagem das câmeras é salva ou publicada.

Uso:  python fila.py            (grava docs/fila.json)
      python fila.py --debug X  (também salva em X.jpg o quadro com as detecções, para calibrar)
Requer: pip install opencv-python-headless ultralytics
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
from ultralytics import YOLO

SAIDA = Path(__file__).parent / "docs" / "fila.json"
FUSO = ZoneInfo("America/Sao_Paulo")
PAGINA = "https://eduplay.rnp.br/app/tv/fila-ru-trindade"
API = "https://eduplay.rnp.br/api/v1/tvs/fila-ru-trindade"
CABECALHOS = {"User-Agent": "Mozilla/5.0 (cardapio-ru)"}

# O vídeo é um mosaico 3x3; cada câmera ocupa uma célula (linha, coluna).
# "fila": a qual fila a câmera pertence ("frente", "tras") ou None se não mostra fila.
CAMERAS = [
    {"id": 1, "nome": "Câmera 1 · entrada da frente", "celula": (0, 0), "fila": "frente"},
    {"id": 2, "nome": "Câmera 2 · rampa de trás", "celula": (0, 1), "fila": "tras"},
    {"id": 3, "nome": "Câmera 3 · rampa de trás", "celula": (0, 2), "fila": "tras"},
    {"id": 4, "nome": "Câmera 4 · entrada de trás", "celula": (1, 0), "fila": "tras"},
    {"id": 5, "nome": "Rua", "celula": (1, 1), "fila": None},
    {"id": 6, "nome": "Câmera 3 · calçada de trás", "celula": (1, 2), "fila": "tras"},
    {"id": 7, "nome": "Câmera 4 · bicicletário", "celula": (2, 0), "fila": None},
]

# Pessoas visíveis -> tamanho da fila. Valores provisórios, a calibrar no horário de pico.
NIVEIS = [(2, "sem fila"), (8, "pequena"), (18, "média"), (10**9, "grande")]


def nivel(pessoas: int) -> str:
    return next(nome for limite, nome in NIVEIS if pessoas <= limite)


def abrir(url: str) -> tuple[str, bytes]:
    req = urllib.request.Request(url, headers=CABECALHOS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read()


def capturar_quadro():
    _, corpo = abrir(API)
    info = json.loads(corpo)["mediaInfo"]
    if not info.get("live"):
        raise RuntimeError("a transmissão não está ao vivo")
    base, lista = abrir(info["src"])
    variantes = re.findall(r"RESOLUTION=\d+x(\d+).*?\n(\S+)", lista.decode())
    url = urllib.parse.urljoin(base, max(variantes, key=lambda v: int(v[0]))[1]) if variantes else base
    video = cv2.VideoCapture(url)
    quadro = None
    for _ in range(5):  # descarta os primeiros quadros, que podem vir incompletos
        ok, q = video.read()
        if ok:
            quadro = q
    video.release()
    if quadro is None:
        raise RuntimeError("não consegui ler o vídeo")
    return quadro


def contar(quadro, debug: str | None = None) -> list[dict]:
    modelo = YOLO("yolo11s.pt")
    alt, larg = quadro.shape[0] // 3, quadro.shape[1] // 3
    resultado = []
    for cam in CAMERAS:
        lin, col = cam["celula"]
        y, x = lin * alt, col * larg
        recorte = quadro[y:y + alt, x:x + larg]
        # Amplia o recorte: as pessoas são pequenas na imagem original.
        det = modelo.predict(recorte, classes=[0], conf=0.25, imgsz=960, verbose=False)[0]
        pessoas = len(det.boxes)
        resultado.append({"id": cam["id"], "nome": cam["nome"], "fila": cam["fila"], "pessoas": pessoas})
        if debug:
            for x1, y1, x2, y2 in det.boxes.xyxy.int().tolist():
                cv2.rectangle(quadro, (x + x1, y + y1), (x + x2, y + y2), (0, 255, 0), 2)
            cv2.putText(quadro, f"cam {cam['id']}: {pessoas}", (x + 8, y + alt - 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    if debug:
        cv2.imwrite(debug + ".jpg", quadro)
    return resultado


def main() -> int:
    debug = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--debug" else None
    agora = dt.datetime.now(FUSO).isoformat(timespec="seconds")
    saida = {"atualizado": agora, "ao_vivo": PAGINA, "filas": {}, "cameras": []}
    try:
        saida["cameras"] = contar(capturar_quadro(), debug)
    except Exception as e:
        saida["erro"] = str(e)
        print(f"[fila] erro: {e}", file=sys.stderr)
    try:  # nível da leitura anterior, para o alerta só disparar quando a fila *fica* grande
        anteriores = json.loads(SAIDA.read_text(encoding="utf-8")).get("filas", {})
    except (OSError, ValueError):
        anteriores = {}
    for nome in ("frente", "tras"):
        cams = [c for c in saida["cameras"] if c["fila"] == nome]
        if cams:
            total = sum(c["pessoas"] for c in cams)
            saida["filas"][nome] = {"pessoas": total, "nivel": nivel(total),
                                    "nivel_anterior": anteriores.get(nome, {}).get("nivel")}
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in saida["cameras"]:
        print(f"[fila] câmera {c['id']} ({c['nome']}): {c['pessoas']} pessoas")
    return 1 if "erro" in saida else 0


if __name__ == "__main__":
    sys.exit(main())

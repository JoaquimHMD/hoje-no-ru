"""Avisa o cardápio do dia (e a fila, se houver leitura recente) no celular.

Canais de envio, cada um ligado por variáveis de ambiente:
  ntfy (https://ntfy.sh): notificação para quem assinar o canal no app ntfy.
      NTFY_CANAL        nome do canal, ex.: ru-ufsc-trindade
      NTFY_TOKEN        (opcional) token de uma conta ntfy, se o canal for reservado
      PAGINA_URL        (opcional) endereço da página, aberto ao tocar na notificação
  WhatsApp via CallMeBot (opcional, só para o seu próprio número):
      WHATSAPP_NUMERO   seu número com código do país
      CALLMEBOT_CHAVE   a chave que o CallMeBot mandou para você

Uso:  python avisar.py            cardápio de hoje
      python avisar.py --semana   cardápio de hoje + resto da semana
      python avisar.py --fila     só manda se alguma fila estiver "grande"
      (acrescente --mostrar para ver a mensagem sem enviar)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

DOCS = Path(__file__).parent / "docs"
FUSO = ZoneInfo("America/Sao_Paulo")
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
NOMES_FILA = {"frente": "Fila da frente", "tras": "Fila de trás"}
VALIDADE_FILA_MIN = 20


def ler(nome: str) -> dict:
    try:
        return json.loads((DOCS / nome).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def principal(itens: list[dict]) -> str:
    carnes = [i["texto"] for i in itens if i["rotulo"].lower().startswith("carne")]
    return " / ".join(carnes) if carnes else itens[0]["texto"]


def fila_recente(agora: dt.datetime) -> dict:
    fila = ler("fila.json")
    try:
        idade = agora - dt.datetime.fromisoformat(fila["atualizado"])
    except (KeyError, ValueError):
        return {}
    if fila.get("erro") or idade > dt.timedelta(minutes=VALIDADE_FILA_MIN):
        return {}
    return fila.get("filas", {})


def texto_fila(filas: dict) -> str:
    return "\n".join(f"{NOMES_FILA.get(k, k)}: {v['nivel']}" for k, v in filas.items())


def mensagem_cardapio(agora: dt.datetime, semana: bool) -> tuple[str, str]:
    hoje = agora.date()
    rus = ler("cardapio.json").get("rus", {})
    partes = []
    for ru in rus.values():
        dia = ru["dias"].get(hoje.isoformat())
        if not dia:
            partes.append(f"*{ru['nome']}*: sem cardápio publicado para hoje")
            continue
        linhas = [f"*{ru['nome']}*: {principal(dia['itens'])}"]
        linhas += [f"• {i['rotulo']}: {i['texto']}" for i in dia["itens"]
                   if not i["rotulo"].lower().startswith("carne") and i["rotulo"] != "Aviso"]
        partes.append("\n".join(linhas))
    filas = fila_recente(agora)
    if filas:
        partes.append("*Fila agora (Trindade)*\n" + texto_fila(filas))
    if semana:
        fim = hoje + dt.timedelta(days=6 - hoje.weekday())
        for ru in rus.values():
            linhas = [
                f"• {DIAS[dt.date.fromisoformat(iso).weekday()][:3]}: {principal(d['itens'])}"
                for iso, d in sorted(ru["dias"].items()) if hoje.isoformat() < iso <= fim.isoformat()
            ]
            if linhas:
                partes.append(f"*Resto da semana · {ru['nome']}*\n" + "\n".join(linhas))
    return f"RU hoje · {DIAS[hoje.weekday()]}, {hoje:%d/%m}", "\n\n".join(partes)


def enviar_ntfy(titulo: str, corpo: str, urgente: bool) -> bool:
    canal = os.environ.get("NTFY_CANAL")
    if not canal:
        return False
    dados = {"topic": canal, "title": titulo, "message": corpo.replace("*", ""),
             "tags": ["warning"] if urgente else ["fork_and_knife"],
             "priority": 4 if urgente else 3}
    if os.environ.get("PAGINA_URL"):
        dados["click"] = os.environ["PAGINA_URL"]
    cab = {"User-Agent": "cardapio-ru", "Content-Type": "application/json"}
    if os.environ.get("NTFY_TOKEN"):
        cab["Authorization"] = "Bearer " + os.environ["NTFY_TOKEN"]
    servidor = os.environ.get("NTFY_SERVIDOR", "https://ntfy.sh")
    req = urllib.request.Request(servidor, data=json.dumps(dados).encode(), headers=cab)
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"[avisar] ntfy respondeu {r.status}")
    return True


def enviar_whatsapp(titulo: str, corpo: str) -> bool:
    numero, chave = os.environ.get("WHATSAPP_NUMERO"), os.environ.get("CALLMEBOT_CHAVE")
    if not numero or not chave:
        return False
    consulta = urllib.parse.urlencode({"phone": numero, "text": f"*{titulo}*\n\n{corpo}", "apikey": chave})
    req = urllib.request.Request("https://api.callmebot.com/whatsapp.php?" + consulta,
                                 headers={"User-Agent": "cardapio-ru"})
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"[avisar] CallMeBot respondeu {r.status}")
    return True


def main() -> int:
    args = set(sys.argv[1:])
    agora = dt.datetime.now(FUSO)
    if "--fila" in args:
        filas = fila_recente(agora)
        if not any(v["nivel"] == "grande" and v.get("nivel_anterior") != "grande" for v in filas.values()):
            print("[avisar] nenhuma fila ficou grande agora; nada enviado")
            return 0
        titulo, corpo = "Fila no RU Trindade agora", texto_fila(filas)
    else:
        titulo, corpo = mensagem_cardapio(agora, "--semana" in args)
    if "--mostrar" in args:
        print(titulo + "\n\n" + corpo)
        return 0
    enviados = [enviar_ntfy(titulo, corpo, "--fila" in args), enviar_whatsapp(titulo, corpo)]
    if not any(enviados):
        raise SystemExit("Nenhum canal configurado: defina NTFY_CANAL (ou use --mostrar).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

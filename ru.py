"""Cardápio do RU da UFSC (Trindade e CCA).

Baixa os PDFs semanais publicados em ru.ufsc.br, extrai o cardápio de cada dia
e gera, na pasta docs/:
  - cardapio.json      (dados usados pela página)
  - ru-trindade.ics    (calendário para assinar no Google Agenda)
  - ru-cca.ics

Uso:  python ru.py
Requer o programa `pdftotext` (pacote poppler-utils).
"""
from __future__ import annotations

import datetime as dt
import gzip
import html
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

SAIDA = Path(__file__).parent / "docs"
FUSO = ZoneInfo("America/Sao_Paulo")
DIAS_DE_HISTORICO = 60
PDFS_POR_PAGINA = 3  # quantos PDFs mais recentes ler de cada ponta da lista

RUS = {
    "trindade": {"nome": "RU Trindade", "pagina": "https://ru.ufsc.br/ru/"},
    "cca": {"nome": "RU CCA", "pagina": "https://ru.ufsc.br/cca-2/"},
}

DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


# ---------------------------------------------------------------- download

def baixar(url: str) -> bytes:
    url = urllib.parse.quote(url, safe=":/?=&%")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cardapio-ru)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dados = r.read()
    if dados[:2] == b"\x1f\x8b":  # o site às vezes responde compactado mesmo sem pedirmos
        dados = gzip.decompress(dados)
    return dados


def links_de_pdf(pagina: str) -> list[str]:
    """PDFs de cardápio da página, na ordem em que aparecem (sem o café da manhã)."""
    texto = baixar(pagina).decode("utf-8", "replace")
    achados = re.findall(r'<a [^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', texto, flags=re.I | re.S)
    urls: list[str] = []
    for url, rotulo in achados:
        url = html.unescape(url)
        if "docs.google.com" in url:
            continue
        if re.search(r"caf[eé]", urllib.parse.unquote(url) + " " + rotulo, flags=re.I):
            continue
        if url not in urls:
            urls.append(url)
    return urls


def texto_do_pdf(dados: bytes) -> str:
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = Path(pasta) / "cardapio.pdf"
        arquivo.write_bytes(dados)
        r = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-layout", str(arquivo), "-"],
            capture_output=True, timeout=60,
        )
    return r.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- utilidades

def limpar(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" /")


def ler_data(s: str) -> dt.date | None:
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", s)
    if m:
        d, mes, a = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.search(r"\b(\d{1,2})-([a-zç]{3})-(\d{2,4})\b", s, flags=re.I)
        if not m or m[2].lower() not in MESES:
            return None
        d, mes, a = int(m[1]), MESES.index(m[2].lower()) + 1, int(m[3])
    if a < 100:
        a += 2000
    try:
        return dt.date(a, mes, d)
    except ValueError:
        return None


# ---------------------------------------------------------------- Trindade

RE_DIA_T = re.compile(r"^\s*((?:SEGUNDA|TERÇA|QUARTA|QUINTA|SEXTA)-FEIRA|SÁBADO|DOMINGO)\b")
RE_DATA_T = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}-[a-zç]{3}-\d{2,4})", flags=re.I)
RE_FIM_T = re.compile(r"prepara[çc][õo]es e ingredientes|lista de ingredientes|sujeito a altera", flags=re.I)
RE_ROTULO = re.compile(r"^([A-Za-zÀ-ú][A-Za-zÀ-ú ]{2,24}):\s*(.*)$")


def extrair_trindade(texto: str) -> dict[str, list[dict]]:
    blocos: list[list[str]] = []
    for linha in texto.splitlines():
        if RE_FIM_T.search(linha):
            break
        if RE_DIA_T.match(linha):
            blocos.append([])
        if blocos:
            blocos[-1].append(linha)

    dias: dict[str, list[dict]] = {}
    for bloco in blocos:
        data = None
        itens: list[dict] = []
        for linha in bloco:
            linha = RE_DIA_T.sub("", linha, count=1)
            m = RE_DATA_T.match(linha)
            if m:
                data = data or ler_data(m[1])
                linha = linha[m.end():]
            linha = linha.strip()
            if not linha:
                continue
            m = RE_ROTULO.match(linha)
            if m:
                valor = re.sub(r"\s{3,}", ", ", m[2])
                itens.append({"rotulo": limpar(m[1]).capitalize(), "texto": limpar(valor)})
            elif not itens:
                itens.append({"rotulo": "Base", "texto": limpar(linha)})
            elif re.match(r"(molho|vinagrete)", linha, flags=re.I):
                partes = re.split(r"\s{3,}", linha)
                itens.append({"rotulo": "Molho", "texto": limpar(partes[0])})
                if len(partes) > 1:  # formato antigo: sobremesa na mesma linha
                    itens.append({"rotulo": "Sobremesa", "texto": limpar(partes[1])})
            else:  # continuação da linha anterior
                itens[-1]["texto"] = limpar(itens[-1]["texto"] + " " + linha)
        if data and itens:
            dias[data.isoformat()] = itens
    return dias


# ---------------------------------------------------------------- CCA

RE_DIA_C = re.compile(r"(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)\s*-?\s*feira", flags=re.I)
RE_DIA_DATA_C = re.compile(
    r"(segunda|ter[çc]a|quarta|quinta|sexta|s[áa]bado|domingo)(?:\s*-?\s*feira)?\s*[-–—]\s*(\d{1,2}/\d{1,2}/\d{2,4})",
    flags=re.I,
)
SECOES_C = ["saladas", "acompanhamentos", "carne", "sobremesa"]


def pedacos(linha: str) -> list[tuple[int, str]]:
    """Trechos de uma linha separados por 2+ espaços, com a coluna onde começam."""
    return [(m.start(), m.group().strip()) for m in re.finditer(r"\S+(?: \S+)*", linha)]


def indice_dia(nome: str) -> int:
    nome = nome.lower().replace("terca", "terça").replace("sabado", "sábado")
    return DIAS_SEMANA.index(nome)


def extrair_cca(texto: str) -> dict[str, list[dict]]:
    pagina1 = texto.split("\f")[0]
    linhas = pagina1.splitlines()

    # Colunas: posições onde começa cada "Saladas" na linha de seção.
    colunas: list[int] = []
    for linha in linhas:
        ps = pedacos(linha)
        if len(ps) >= 2 and all(t.lower() == "saladas" for _, t in ps):
            colunas = [p for p, _ in ps]
            break
    if not colunas:
        return {}

    def coluna_de(pos: int) -> int:
        return min(range(len(colunas)), key=lambda i: abs(colunas[i] - pos))

    # Dia da semana de cada coluna (pelo cabeçalho; senão, segunda em diante).
    semana = list(range(len(colunas)))
    vistos: dict[int, int] = {}
    for linha in linhas:
        for m in RE_DIA_C.finditer(linha):
            vistos.setdefault(coluna_de(m.start()), indice_dia(m[1]))
    if len(vistos) == len(colunas):
        semana = [vistos[i] for i in range(len(colunas))]

    # Datas: o cabeçalho ("Cardápio de 09 a 13/11/2026") e a lista de ingredientes
    # ("Segunda feira - 09/11/2026") apontam para a segunda-feira da semana. Os PDFs
    # às vezes trazem datas digitadas erradas, então vale a segunda mais votada.
    votos: list[dt.date] = []
    m = re.search(r"card[áa]pio de .*?(\d{1,2}/\d{1,2}/\d{2,4})", pagina1, flags=re.I)
    fim = ler_data(m[1]) if m else None
    if fim:
        votos.append(fim - dt.timedelta(days=fim.weekday()))
    for m in RE_DIA_DATA_C.finditer(texto):
        d = ler_data(m[2])
        if d:
            votos.append(d - dt.timedelta(days=indice_dia(m[1])))
    if not votos:
        return {}
    segunda = max(set(votos), key=votos.count)

    celulas: list[dict[str, list[str]]] = [{s: [] for s in ["aviso"] + SECOES_C} for _ in colunas]
    secao = None
    for linha in linhas:
        ps = pedacos(linha)
        if not ps or re.search(r"nutricionista|sujeito", linha, flags=re.I):
            continue
        nomes = [t.lower() for _, t in ps]
        comum = max(set(nomes), key=nomes.count)
        if comum in SECOES_C and nomes.count(comum) >= 2:
            secao = comum
            for pos, t in ps:  # ex.: "FERIADO" na coluna de um dia sem cardápio
                if t.lower() != comum:
                    celulas[coluna_de(pos)]["aviso"].append(t)
            continue
        if secao is None:
            continue
        for pos, t in ps:
            celulas[coluna_de(pos)][secao].append(t)

    dias: dict[str, list[dict]] = {}
    for i, cel in enumerate(celulas):
        data = segunda + dt.timedelta(days=semana[i])
        itens = [
            {"rotulo": s.capitalize(), "texto": ", ".join(cel[s])}
            for s in ["aviso"] + SECOES_C if cel[s]
        ]
        if itens:
            dias[data.isoformat()] = itens
    return dias


EXTRATORES = {"trindade": extrair_trindade, "cca": extrair_cca}


# ---------------------------------------------------------------- saídas

def prato_principal(itens: list[dict]) -> str:
    carnes = [i["texto"] for i in itens if i["rotulo"].lower().startswith("carne")]
    return " / ".join(carnes) if carnes else itens[0]["texto"]


def ics_escapar(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_dobrar(linha: str) -> str:
    """Quebra linhas em 75 bytes, como o formato iCalendar exige."""
    partes, atual = [], ""
    for ch in linha:
        if len((atual + ch).encode()) > 73:
            partes.append(atual)
            atual = " " + ch
        else:
            atual += ch
    partes.append(atual)
    return "\r\n".join(partes)


def gerar_ics(chave: str, ru: dict, agora: dt.datetime) -> str:
    carimbo = agora.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    linhas = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//cardapio-ru-ufsc//PT-BR",
        "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{ru['nome']} (cardápio)",
        "X-WR-TIMEZONE:America/Sao_Paulo", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    ]
    for iso, dia in sorted(ru["dias"].items()):
        data = dt.date.fromisoformat(iso)
        descricao = "\n".join(f"{i['rotulo']}: {i['texto']}" for i in dia["itens"])
        descricao += f"\n\nPDF: {dia['pdf']}"
        linhas += [
            "BEGIN:VEVENT",
            f"UID:{chave}-{iso}@cardapio-ru-ufsc",
            f"DTSTAMP:{carimbo}",
            f"DTSTART;VALUE=DATE:{data:%Y%m%d}",
            f"DTEND;VALUE=DATE:{data + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{ics_escapar(ru['nome'] + ': ' + prato_principal(dia['itens']))}",
            f"DESCRIPTION:{ics_escapar(descricao)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(ics_dobrar(l) for l in linhas) + "\r\n"


def main() -> int:
    agora = dt.datetime.now(FUSO)
    SAIDA.mkdir(exist_ok=True)
    arquivo_json = SAIDA / "cardapio.json"
    try:
        dados = json.loads(arquivo_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dados = {"rus": {}}

    falhas = 0
    for chave, cfg in RUS.items():
        ru = dados["rus"].setdefault(chave, {"dias": {}})
        ru.update(nome=cfg["nome"], pagina=cfg["pagina"])
        try:
            urls = links_de_pdf(cfg["pagina"])
        except Exception as e:  # site fora do ar: mantém o que já tínhamos
            print(f"[{chave}] não consegui abrir {cfg['pagina']}: {e}", file=sys.stderr)
            falhas += 1
            continue
        # A lista pode estar em ordem crescente ou decrescente: lê as duas pontas.
        candidatos = list(dict.fromkeys(urls[:PDFS_POR_PAGINA] + urls[-PDFS_POR_PAGINA:]))
        novos = 0
        for url in candidatos:
            try:
                dias = EXTRATORES[chave](texto_do_pdf(baixar(url)))
            except Exception as e:
                print(f"[{chave}] erro em {url}: {e}", file=sys.stderr)
                continue
            if not dias:
                print(f"[{chave}] não entendi o formato de {url}", file=sys.stderr)
                continue
            for iso, itens in dias.items():
                ru["dias"][iso] = {"itens": itens, "pdf": url}
                novos += 1
        if not novos:
            falhas += 1
        limite = (agora.date() - dt.timedelta(days=DIAS_DE_HISTORICO)).isoformat()
        ru["dias"] = {k: v for k, v in sorted(ru["dias"].items()) if k >= limite}
        ultimo = max(ru["dias"], default="-")
        print(f"[{chave}] {novos} dias lidos; cardápio até {ultimo}")
        (SAIDA / f"ru-{chave}.ics").write_text(gerar_ics(chave, ru, agora), encoding="utf-8", newline="")

    dados["atualizado"] = agora.isoformat(timespec="minutes")
    arquivo_json.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if falhas == len(RUS) else 0


if __name__ == "__main__":
    sys.exit(main())

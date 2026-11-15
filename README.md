# Hoje no RU (UFSC)

Cardápio do RU da Trindade e do CCA e fila do RU Trindade, sem precisar abrir o PDF.
Projeto não oficial.

- **Página:** cardápio de hoje, próximos dias e fila (`docs/index.html`)
- **Google Agenda:** um evento por dia com o prato (`docs/ru-trindade.ics`, `docs/ru-cca.ics`)
- **Notificação no celular:** aviso diário pelo app [ntfy](https://ntfy.sh)

## Como funciona

| Arquivo | O que faz |
|---|---|
| `ru.py` | Baixa os PDFs de ru.ufsc.br e gera `docs/cardapio.json` e os calendários |
| `fila.py` | Lê a transmissão pública das câmeras, conta pessoas e gera `docs/fila.json` (não salva imagens) |
| `avisar.py` | Envia o cardápio do dia e o alerta de fila pelo ntfy (WhatsApp opcional) |
| `.github/workflows/` | Rodam os três sozinhos no GitHub |

## Colocar no ar

1. Crie um repositório **público** no GitHub e envie estes arquivos.
2. Em *Settings → Pages*, escolha *Deploy from a branch*, branch `main`, pasta `/docs`.
3. Em *Settings → Secrets and variables → Actions → Variables*, crie `NTFY_CANAL` com o nome do canal (ex.: `ru-ufsc-trindade`).
4. Em *Actions*, rode "Atualizar cardápio" uma vez para conferir.

## Receber as notificações

1. Instale o app **ntfy** (Android ou iPhone).
2. Toque em "+" e assine o canal com o mesmo nome do passo 3 acima.

Qualquer pessoa que souber o nome do canal também consegue publicar nele.

## Pendências

- Calibrar os limites de fila (`NIVEIS` em `fila.py`) num dia de semana, no horário de pico.
  Depois disso, crie a variável `ALERTA_FILA` com o valor `sim` para ligar o alerta.
- Confirmar que a transmissão das câmeras abre a partir dos servidores do GitHub.

## Rodar no seu computador

```bash
python ru.py
python avisar.py --mostrar
pip install -r requirements-fila.txt
python fila.py
python -m http.server 8765 --directory docs
```

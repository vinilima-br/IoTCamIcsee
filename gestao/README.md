# Gestão de pessoas e acessos (Portaria)

Módulo de **cadastro e gerenciamento de pessoas do reconhecimento facial**:
unidades, moradores, visitantes/prestadores, veículos, encomendas e histórico
de acessos. Desenvolvido pelo **André** dentro do projeto do Vini.

## Quem mexe no quê

O André é colaborador de **todo o projeto**: pode mexer na gestão (`gestao/`) e também
no resto (`app/`, `ferramentas/`, `.bat`, etc.) quando precisar. A gestão continua morando
nesta pasta. Nunca vão para o Git: `config.py` (senhas) e `dados/`.

## Como trabalhar

1. Crie uma branch a partir da `main` (ex.: `gestao-visitantes`). **Não envie direto na `main`**:
   os PCs instalados se atualizam sozinhos pela `main`.
2. Faça as mudanças (a gestão fica em `gestao/`; o resto do projeto também pode ser alterado).
3. Mudou a tela (`gestao/ui/src`)? Rode `npm install` (1ª vez) e `npm run build` dentro de
   `gestao/ui` e **envie também o `gestao/ui/dist`**: os PCs não têm Node, usam a tela já compilada.
4. Abra um Pull Request para a `main`. O GitHub confere se o Python compila e o Vini aprova.

## Como ela roda

- **Dentro do painel (o normal):** o `app/servidor.py` chama `gestao/api/embutido.py`, que sobe
  esta API na porta `GESTAO_PORTA` (padrão **8000**) **no mesmo processo** do painel. Ela usa as
  câmeras, as sessões e o reconhecimento facial que o painel já abriu (não abre câmera de novo).
  Abre pela aba **Facial → Gestão de pessoas e acessos**. Login: o mesmo do painel (no próprio PC
  entra direto; de outro aparelho, só depois de entrar no painel com a senha).
- **Isolada (para desenvolver):** `gestao\PORTARIA.bat` abre só a gestão numa janela própria.
  Ela mesma abre as câmeras, então **feche o painel antes** (o .bat avisa).
- **Para a guarita sem internet:** `gestao\BUILD_PORTARIA.bat` gera o `Portaria.exe` (PyInstaller).

## Estrutura

```
gestao/
  api/            FastAPI + SQLite (banco em dados/gestao/portaria.db, fora do Git)
    main.py         rotas /api/... e a tela
    models.py       tabelas (unidades, pessoas, veículos, visitantes, encomendas, logs)
    schemas.py      validação dos dados
    database.py     conexão SQLite
    camera_bridge.py  ponte com o sistema de câmeras (ver "Contrato" abaixo)
    embutido.py     sobe a gestão dentro do painel + login compartilhado
  ui/             React + Vite + Tailwind (src/ = código, dist/ = compilado, vai pro Git)
  desktop_app.py  janela do modo isolado
  PORTARIA.bat    abre o modo isolado
  BUILD_PORTARIA.bat  gera o .exe
```

## Contrato com o sistema de câmeras (não mudar do lado de lá)

A `camera_bridge.py` usa estas peças do `app/servidor.py`. Se precisar de outra coisa, peça na Issue.

- `CAMERAS[cid]` (`proximo_jpeg`, `espectadores`, `cond`, `frame`, `urls`, `status()`), `ORDEM`
- `PTZS[cid].mover()/parar()`, `XMS[cid]`, `_toca_em(cids, alaw, nome)`, `PASTA_TTS`
- `RECS[cid]._registra` (eventos do reconhecimento), `MOTOR_ROSTO` (banco de rostos), `ALERTAS_CAM`
- `lentes.le()`, `gravador.acha_ffmpeg()`, `gerar_voz.gerar_detalhado()`

Fotos cadastradas aqui viram rostos em `rostos/pessoas/` com o nome `PESSOA-<id>-<nome>`
ou `VISITANTE-<id>-<nome>`.

## Não vai pro Git

`config.py` (senhas), `dados/` (banco da gestão em `dados/gestao/`, fotos, snapshots), `gestao/ui/node_modules/`.

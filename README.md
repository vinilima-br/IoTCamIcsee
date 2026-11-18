# Central de Câmeras (IoTCamIcsee)

Painel para câmeras Wi-Fi iCSee/Xiongmai e Elsys num PC Windows: vídeo ao vivo,
áudio (ouvir e falar), PTZ, gravação, cartão SD, alertas da câmera, IA de
pessoas e reconhecimento facial.

## Instalar num PC

1. Baixe o [`bootstrap.bat`](https://github.com/vinilima-br/IoTCamIcsee/raw/main/bootstrap.bat)
   (pode ficar em Downloads mesmo) e dê dois cliques.
2. Ele instala tudo em `C:\CentralCameras`: baixa o projeto, um Python próprio
   (pasta `python`, não precisa ter Python no PC) e as dependências, cria o
   atalho **Central de Cameras** na Área de Trabalho e abre a Central.
   Leva poucos minutos e mostra cada etapa; o registro fica em
   `C:\CentralCameras\instalacao.log`.
3. Adicione as câmeras pela janela do painel (botão **➕ Câmeras**).

O PC precisa estar na mesma rede das câmeras. Os PCs instalados se atualizam
sozinhos pelo GitHub (⚙ Config → "Atualizar sozinho").

## Pastas

- raiz — só o que se clica: `PAINEL.bat` (abre a Central), `INSTALAR.bat`, `bootstrap.bat`
- `app/` — todo o código do sistema
- `ferramentas/` — diagnóstico e configuração de câmeras
- `dev/` — só para o PC de desenvolvimento (não vai no ZIP dos PCs)
- `docs/GUIA_COMPLETO.md` — guia completo, protocolo e solução de problemas

`config.py` (senhas e IPs) nunca vai para o GitHub: cada PC tem o seu,
criado a partir do `config_exemplo.py`.

## Sistema administrativo de portaria

O painel local fica em `portaria_ui/` e a API FastAPI/SQLite em `portaria_api/`.
O banco e as imagens ficam em `data/`; esses dados locais não são versionados.
O frontend usa apenas dependências instaladas pelo npm e é servido pelo backend
em `127.0.0.1:8000`, sem CDN ou acesso externo durante a operação.

Para desenvolver:

1. Prepare o Python portátil, instale os pacotes de `requirements.txt` e
   `portaria_api/requirements.txt`.
2. Em `portaria_ui/`, execute `npm install` e `npm run build`.
3. Execute `python desktop_app.py` ou clique em `PORTARIA.bat`.

`PORTARIA.bat` procura `python/python.exe` e também aceita o layout legado
`python/tools/python.exe`. Para criar o pacote Windows com PyInstaller, execute
`BUILD_PORTARIA.bat` na máquina de preparo e distribua toda a pasta
`dist/Portaria/`. A instalação do computador da guarita não instala pacotes nem
acessa a internet.

### Ponte com o IoTCamIcsee

O stream MJPEG reutiliza `app/servidor.py` (`Camera.proximo_jpeg` e os
contadores de espectadores); o PTZ chama `PTZS[cid].mover()`/`parar()`; a
escuta usa o RTSP convertido pelo FFmpeg e a fala encaminha áudio G.711 A-law
para `XMS[cid].falar()`. A ponte reutiliza uma sessão `sessao_xm.py` já ativa ou
inicia o serviço de sessão local no processo da Portaria. Os reconhecedores
`rosto_servidor.Reconhecedor`
persistem os eventos faciais em `data/portaria.db`, salvam snapshots e
publicam no WebSocket; fotos de pessoas e visitantes atualizam o banco de
embeddings `rostos/pessoas/`.

A ponte só inicia quando `config.py` existe na raiz e contém câmeras
configuradas. Ele não deve ser distribuído com senhas. Copie a configuração de
exemplo para a raiz, revise IPs/credenciais na máquina de preparo e configure
as câmeras na instalação local. Sem o arquivo ou sem câmeras, os módulos
administrativos continuam disponíveis e o painel exibe o motivo da
indisponibilidade da integração. Modelos ONNX já estão em `modelos/`; áudio ao
vivo das câmeras também exige o FFmpeg usado pelo sistema existente.

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

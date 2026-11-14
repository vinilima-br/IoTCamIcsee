# Central de Câmeras — Guia completo

Como o sistema funciona, como usar e, principalmente, **o caminho certo para colocar uma câmera nova** sem repetir os tropeços que tivemos.

Situação em 09/11/2026: 3 câmeras funcionando no mini PC (Windows, Celeron N5105, 8 GB).

| Câmera | Modelo | IP | Vídeo | Som/luz/alarme (porta 34567) |
|---|---|---|---|---|
| cam1 | Elsys ESC-WY3F | 192.168.3.119 | RTSP direto | — |
| cam2 | iCSee X6S (XM232_X6S-WEQ-H) | 192.168.3.67 | ONVIF → RTSP | sim, fala no modo `sub` |
| cam3 | iCSee X6E (XM535_X6E-WEQ) | 192.168.3.2 | ONVIF → RTSP | sim |

---

## 1. Mapa da pasta

O que vai para os PCs (o ZIP do GitHub) é só o app. `dev\` e `docs\`
ficam **só no GitHub e no PC de desenvolvimento** (`export-ignore` no
`.gitattributes`).

```
IoTCamIcsee\
  PAINEL.bat             <- ABRE A CENTRAL (o atalho da Área de Trabalho aponta aqui)
  INSTALAR.bat           <- instala Python + dependências + atalho e abre a Central
  bootstrap.bat          <- PC novo: baixa do GitHub e instala (sem Git)
  requirements.txt  README.md
  config.py              <- IPs e senhas DESTE PC (nasce do app\config_exemplo.py; nunca vai pro GitHub)
  app\                   <- TODO o código
     servidor.py         <- o sistema (Flask, porta 5050)
     janela.py  icone.ico   <- a janela própria (pywebview) e o ícone
     sessao_xm.py        <- dona da sessão 34567 (porta 5051)
     camera_xm.py  cliente_xm.py  elsys_xm.py   <- protocolo XM / iCSee / Elsys RSA
     cameras_cfg.py      <- menu ➕ Câmeras
     onvif_rtsp.py  ptz.py  lentes.py  gravador.py  sd_xm.py
     detector_pessoas.py <- IA de pessoas
     rosto_servidor.py  rostos_ia.py   <- reconhecimento facial
     biblioteca_sons.py  gerar_voz.py  <- sons e texto -> voz
     atualizador.py      <- atualização automática pelo GitHub
     config_exemplo.py   <- modelo do config.py
     templates\painel.html   <- a página
     INICIAR.bat         <- sobe o servidor sem janela própria (painel no navegador)
     INICIAR_SESSAO.bat  <- sessão das câmeras (o PAINEL.bat abre sozinho)
     CRIAR_ATALHO.bat    <- refaz o atalho "Central de Cameras"
     _python.bat         <- acha o Python do PC (usado pelos outros .bat)
  ferramentas\           <- diagnóstico e configuração de câmeras
     provisionar.py  recupera_conta.py  verifica_camera.py
     diag_fala.py  diag_luz_alerta.py  diag_sd.py  converter_sd.py  diag_bloqueio.py
     rosto_cadastro.py   <- cadastra rosto por linha de comando (aceita FOTOS)
     terminar_atualizacao.py  criar_atalho.ps1   <- usados pelo sistema
     obsoletos.txt       <- arquivos que saíram do projeto (o atualizador tira dos PCs)
  modelos\               <- yolov8n + YuNet + SFace (.onnx)
  sons\                  <- só os sons padrão vêm do GitHub; o resto é de cada PC
  dev\                   <- SÓ no PC de desenvolvimento
     ENVIAR_PARA_GITHUB.bat   <- manda as mudanças (os PCs se atualizam sozinhos)
     laboratorio\comando_voz.py
  docs\GUIA_COMPLETO.md  <- este guia

Gerados em cada PC, na pasta do projeto (não vão pro GitHub): config.py,
sessao_estado.json, xm_*.json, alertas_modo.json, lentes_deteccao.json,
ptz_inverter.json, rostos\, logs\, fotos\, gravacoes\, sd_baixados\, janela_dados\.
```

As ferramentas continuam rodando da pasta do projeto, igual antes:
`python ferramentas\diag_fala.py 192.168.3.XX`. Para rodar um módulo do
sistema na mão: `python app\servidor.py` (ou `app\INICIAR.bat`).

Tirou um arquivo do projeto? Apague no PC de dev **e** ponha o caminho em
`ferramentas\obsoletos.txt` — senão ele continua parado nos PCs instalados
(a atualização só copia, nunca apaga).

Os scripts de teste antigos (etapas, Vosk/Whisper, organizar_pasta etc.)
saíram em 13/11/2026; continuam no histórico do git se precisar consultar.

---

## 2. Instalar do zero (outro PC ou depois de formatar)

1. Baixe só o `bootstrap.bat` do GitHub numa pasta (ex.: `C:\Central`) e dê dois cliques.
   Ele baixa o projeto, instala o Python (se faltar), as dependências e cria o atalho.
2. O PC precisa estar na **mesma rede das câmeras** (aqui: 192.168.3.x).
3. As câmeras entram pela janela do painel (botão **➕ Câmeras**).
4. Das próximas vezes: atalho **Central de Cameras** na Área de Trabalho.
5. No celular, na mesma rede: `http://IP-DO-PC:5050`.

Para desligar: **feche a janela** do painel (faz logout limpo nas câmeras).
Com o `INICIAR.bat`, **Ctrl+C** na janela do servidor.

---

## 3. Usando a página

**Janela própria (`PAINEL.bat`)**: o mesmo painel numa janela sem barra de navegador, com nome e ícone da Central (biblioteca `pywebview`, instalada sozinha na 1ª vez).
- Fechar a janela = desligar o servidor (com logout nas câmeras). Se o `INICIAR.bat` já estiver aberto, o `PAINEL.bat` só abre a janela e não sobe um 2º servidor (evita sessão dupla e 205).
- A janela guarda as preferências da página (câmeras escondidas, colunas, aba) em `janela_dados\`, separado do navegador.
- Sem pywebview ou sem o WebView2 do Windows, ela abre o Edge em modo aplicativo (também sem barra).
- O celular continua em `http://IP-DO-MINI-PC:5050`.

- **🚨 Alerta geral** (topo): luz de alerta + sirene em todas as câmeras por 15 s. Clicar de novo para.
- **Topo**: cada câmera tem um botão. Clique para **mostrar/esconder**. Em "Grade automática" você escolhe 1, 2 ou 3 colunas. O botão **🔊 Sons** abre a biblioteca.
- **Título de cada câmera**: nome · estado (ao vivo/offline/em pausa) · **IP** da câmera. Offline aparece em vermelho "tentando 192.168.3.X" (o IP do `config.py` que o sistema está tentando).
- **Em cada câmera**: ⟲ girar 180° (câmera instalada de cabeça pra baixo; vale pro ao vivo e pros vídeos) · ⛶ tela cheia · — minimizar · ✕ esconder. Câmera escondida ou minimizada **para de transmitir** e o mini PC gasta menos CPU.
- **Barra da câmera**: Leve/Alta · 🎧 Ouvir (som ambiente) · ⏺ Gravar (manual, até 5 min) · 📷 Foto.
- **Abas**:
  - **Alto-falante e luz** (iCSee): tocar som, falar uma frase, **luz de alerta** (LED vermelho/azul: 5 s, 10 s, 30 s, ligar/desligar, com ou sem som junto), volume, luz branca (modo e brilho), alarme da própria câmera, LED de status.
  - **Cartão SD** (iCSee): escolha o dia, filtre (movimento/contínua/já baixadas), clique numa gravação: ela baixa do cartão (~30 s por trecho de 5 min), converte e já começa a tocar. As cópias ficam em `sd_baixados\` (🗑 apaga só a cópia do PC; no cartão continua).
  - **IA e gravação**: liga a detecção de pessoas e a gravação automática ao detectar.
  - **Gravações**: assistir, baixar, apagar.
  - **Fotos**.
- **IA e gravação começam sempre DESLIGADAS** quando o servidor sobe. A gravação automática precisa da IA ligada. Cada IA ligada pesa no mini PC: com 2 ligadas ele já fica perto do limite (~1 s por análise).
- A página lembra quais câmeras você escondeu, as colunas e a aba aberta (fica salvo no navegador).

**Integração com o ESP32:** `GET http://IP-DO-MINI-PC:5050/api/presenca` devolve `{"presenca": true/false, "pessoas": N, ...}` da primeira câmera com IA (a IA precisa estar ligada).

---

## 4. Câmera nova — o caminho certo (checklist)

### Jeito fácil: botão ➕ Câmeras do painel
No topo do painel, **➕ Câmeras** (abre sozinho num PC sem câmeras, ex.: depois do `bootstrap.bat`):
- **No painel**: as câmeras do `config.py`, com 🗑 para remover.
- **🔍 Buscar na rede**: varre a(s) rede(s) do PC (portas 34567/554/8899 + descoberta ONVIF) e lista as câmeras, marcando as que já estão no painel. Ou **Adicionar pelo IP**.
- **Assistente**: tipo (iCSee/ONVIF ou Elsys/RTSP), nome, e-mail e senha do app → **▶ Testar vídeo** (mostra uma foto) → som e luz:
  - **Já sei a conta**: câmera que já roda em outro PC (usuário + senha fixa que estão no `config.py` de lá). Só confere, não muda nada na câmera.
  - **Câmera recém-resetada**: descobre a conta e fixa a senha. **Nunca** numa câmera que já funciona em outro PC (lá ela pararia de conectar).
  - **Só vídeo**: liga o som depois pelo ⚙ Config.
- **Salvar**: grava no `config.py` (com backup), a sessão abre a conexão da câmera e a Central **reinicia sozinha** (a janela fecha e abre de novo) já com a câmera nova.

O caminho manual abaixo continua valendo (e é o que o assistente faz por dentro).


> Faça **na ordem**. Cada passo tem que funcionar antes do próximo.

### Passo 1 — Instalar no app do fabricante
- Configure no app (iCSee, Elsys Home...) com o Wi-Fi da rede das câmeras.
- Anote o **e-mail e a senha do app**: é com eles que o vídeo é liberado via ONVIF.

### Passo 2 — IP fixo
- No roteador, faça a **reserva de DHCP** (IP fixo) para a câmera. Sem isso o IP muda e o sistema perde a câmera.
- **Não** mexa no IP da placa de rede do PC (num teste isso desligou o DHCP do Wi-Fi do PC; o `recuperar_rede.py` do histórico do git desfaz).

### Passo 3 — Checar a câmera (sem risco de bloqueio)
```
python ferramentas\verifica_camera.py 192.168.3.XX seu@email.com
```
Ele mostra:
1. as portas abertas (554 RTSP, 8899 ONVIF, 34567 XM);
2. os endereços de vídeo pelo ONVIF (com o login do **app**);
3. **uma única** tentativa de login local `admin` com senha **em branco** na 34567;
4. o que a câmera tem (volume, luz, vozes de alarme, LED);
5. o trecho pronto para colar no `config.py`.

Se o passo 3 der **203 (senha errada)**: a senha local de admin não é mais a de fábrica. Faça **reset de fábrica** na câmera (botão de reset), adicione de novo no app e rode o verificador outra vez. **Não fique testando senhas** (veja a regra 1).

### Passo 4 — Colocar no config.py
> Atalho: o `provisionar.py` (seção 12) faz os passos 3 e 4 num comando só,
> recuperando e **fixando** a conta real. Para iCSee, prefira ele.

As câmeras ficam numa lista única `CAMERAS = [ {...}, ... ]` (não há mais
`CAM4_IP = ...`). Acrescente um bloco — a iCSee usa a **conta real** em
`admin_usuario`/`admin_senha`, não o `admin`/branco:
```python
{
    "cid": "cam5", "tipo": "icsee", "nome": "Portão",
    "ip": "192.168.3.XX",
    "usuario": "seu@email.com", "senha": "senha do app",
    "porta_onvif": 8899,
    "admin_usuario": "swua", "admin_senha": "SUASENHAFIXA",
    "xm": True, "ptz": True,
},
```

### Passo 5 — Subir o servidor e conferir o vídeo
O cartão da câmera nova aparece na página. No painel "Alto-falante e luz" deve ficar **verde (conectada)**.

### Passo 6 — Descobrir a forma de "falar" (só câmeras com 34567)
Feche o servidor e rode:
```
python ferramentas\diag_fala.py 192.168.3.XX
```
Fique perto da câmera e responda **s/n** aos bips. A forma que tocar 2 vezes seguidas fica salva em `xm_fala_modo.json`. Suba o servidor de novo.

### Passo 7 — Luz de alerta (LED vermelho/azul), se a câmera tiver
Com o servidor fechado e a câmera olhando uma cena parada:
```
python ferramentas\diag_luz_alerta.py 192.168.3.XX
```
Responda s/n se o LED acendeu e se apagou. O resultado vai para `xm_luz_alerta.json`. Sem esse arquivo, o servidor usa a forma que funcionou na cam2.

### Passo 8 — Testar pela página
Tocar som → Parar → volume → falar frase → luz de alerta → luz branca → alarme. Um de cada vez.

### Câmera tipo Elsys (RTSP direto, sem ONVIF)
O endereço é montado assim (stream 0 = alta, 1 = leve):
`rtsp://IP:554/user=admin_password=SENHA_channel=1_stream=0.sdp`
Hoje o servidor tem uma vaga para esse tipo (cam1: `CAM_IP`, `CAM_PORTA`, `CAM_USUARIO`, `CAM_SENHA`). Uma segunda precisaria de um pequeno ajuste no `servidor.py`.

---

## 5. Regras de ouro (o que aprendemos apanhando)

1. **Existem DOIS logins diferentes:**
   - **App** (e-mail + senha): serve para o **vídeo via ONVIF/RTSP**.
   - **Conta local** (porta 34567): som, luz, alarme, cartão SD.
   - Mandar a senha do app na 34567 dá **203**.
2. **205 — RESOLVIDO. A causa não era a rede nem força-bruta.** O `admin`
   de senha em branco é uma **conta de teste de fábrica (backdoor)** que
   **expira sozinha depois do reset** (no nosso caso, ~1 h depois) e passa a
   dar **205**, mesmo sem ninguém tentar nada. Esperar não solta; só o reset
   soltava — e expirava de novo. Isso explica o "às vezes sobe, às vezes não".
   **A solução** é parar de usar o `admin`/branco e usar a **conta REAL** da
   câmera (a mesma que o app usa, nome tipo `swua`/`wwpe`), que **não expira**.
   Ela é recuperada da própria câmera — ver a **seção 10** e
   `ferramentas\recupera_conta.py`. Depois de trocar para a conta real, o 205
   deixou de acontecer. (Confirmado por engenharia reversa independente do app
   iCSee: github.com/voidnullvalue/Icsee-android.)
3. **Uma sessão só por câmera, mantida viva.** O servidor loga uma vez e manda KeepAlive. Scripts paralelos logando na mesma câmera reabrem o problema do 205. Com o servidor rodando, não rode outros testes na mesma câmera.
4. **A trava do sistema** (`sessao_estado.json`) garante pelo menos 20 s entre logins, 60 s depois de uma falha, 15 min depois de um 205 e nenhuma nova tentativa depois de um 203 (até você clicar em "Tentar conectar de novo"). Vale mesmo se reiniciar o servidor.
5. **Falar na câmera** (protocolo XM/DVRIP, porta 34567):
   - `OPTalk Claim` (msgid **1434**) numa **conexão auxiliar sem login**, usando o SessionID da sessão;
   - `OPTalk Start` (msgid **1430**) na sessão principal. **Sem o Start não sai som.** Esse foi o "pulo do gato", copiado do projeto open source go2rtc;
   - áudio em **G.711 A-law, 8 kHz, mono**, pacotes de **320 bytes (40 ms)** com msgid **1432** e cabeçalho `00 00 01 FA 0E 02` + tamanho (2 bytes, little-endian);
   - `OPTalk Stop` (1430) no fim.
   - Tudo pela mesma conexão principal só funciona **uma vez**: o 2º som sai mudo. Por isso a conexão auxiliar existe.
6. **Alarme da própria câmera** (toca sozinho ao detectar movimento): em `Detect.MotionDetect` → `EventHandler`, ligar **`VoiceEnable` E `TipEnable` juntos**. `VoiceType` vem da lista `Ability.VoiceTipType` (na cam2: 24 = Alarme, 523 = "você entrou na área", 550 = personalizado). Volume em `fVideo.Volume` (0–100).
7. **Luz de alerta (LED vermelho/azul)** = a **saída de alarme** da câmera (`Alarm.AlarmOut`). Normal: `AlarmOutType: AUTO` (pisca sozinha uns 4 s no movimento, por causa do `AlarmOutLatch = 4`). Para acender quando quiser: `AlarmOutType: MANUAL` + `AlarmOutStatus: OPEN`. Para apagar: voltar a `AUTO`. O servidor apaga sozinho no fim do tempo, nunca passa de 10 min, e ao fechar ou reconectar ele garante que volta para `AUTO`.
8. **Luz branca**: `Camera.WhiteLight` → `WorkMode` (ex.: `Intelligent`) e `Brightness`. A página mostra o modo que **a câmera confirmou**.
9. **O que NÃO precisou (não perca tempo):** login criptografado RSA, capturar o tráfego do app pela nuvem (com o celular em outra rede o app nem fala direto com a câmera), adicionar IP extra no PC.
10. **Cartão SD das iCSee** (só funciona com o login de admin local, regra 1):
    - listar: `OPFileQuery` (msgid **1440**), no máximo 64 por página, então pagina pelo `BeginTime` do último;
    - baixar: `OPPlayBack Claim` (**1424**) numa conexão auxiliar sem login + `DownloadStart` (**1420**) na sessão; os dados chegam na auxiliar e um pacote vazio marca o fim; `DownloadStop` no final (forma `sub`, igual à fala);
    - o arquivo é o formato XM: cada quadro com cabeçalho `00 00 01 FC` (I, 16 bytes), `FD` (P, 8 bytes), `FA` (áudio G.711, 8 bytes), `F9` (info). O `sd_xm.py` tira os cabeçalhos e monta o MP4 com `ffmpeg -c copy` (sem recodificar);
    - armadilhas: largura/altura do cabeçalho "dão a volta" (use a do vídeo); o byte do codec tem flags (`0x52` = H.264, use o nibble baixo); o fps do cabeçalho é arredondado (calcule pelo relógio dos quadros I); às vezes o tamanho declarado de um quadro é menor que o real (devolver os bytes que sobram ao quadro);
    - nas X6S as duas lentes vêm empilhadas num quadro só (2304×2592). O cartão cheio é normal: grava por cima do mais antigo (~24 h).
    - A Elsys (cam1) continua sem acesso ao SD (senha de admin desconhecida); nela, grave no PC pelo RTSP.
11. **PTZ das iCSee**: esquerda/direita são invertidas no ONVIF (pan +1 = esquerda). A página já corrige.

---

## 6. Problemas e soluções

| Sintoma | O que fazer |
|---|---|
| Cartão "offline" com erro de ONVIF | E-mail/senha do app no `config.py`? IP mudou? (Passo 2) |
| Painel do alto-falante "aguardando … próxima tentativa HH:MM" | Normal: está respeitando a trava. Espere. |
| "205 (bloqueado)" nas iCSee | Era o `admin`/branco expirando (seção 10). Use a conta real no `config.py`. Se ainda ver 205 de uma trava velha: feche a sessão, apague `sessao_estado.json`, reabra. |
| "203 (senha errada)" | Reset de fábrica → adicionar no app → "Tentar conectar de novo". |
| Só o 1º som sai, os outros ficam mudos | `python ferramentas\diag_fala.py IP` (servidor fechado). |
| Tocou mas não saiu som | Volume no 0? App iCSee falando na mesma câmera ao mesmo tempo? |
| Luz: "a câmera aceitou, mas ficou em X" | Esse modo não existe nesse modelo; use os que ela aceita. |
| Voz saiu em inglês | `python gerar_voz.py vozes`. Instale a voz pt-BR no Windows (Configurações → Hora e idioma → Fala). |
| "ffmpeg não encontrado" | `pip install imageio-ffmpeg` |
| Luz de alerta ficou acesa | Botão "Desligar" ou "⏹ Parar alerta". Se o servidor caiu com ela acesa, ao subir de novo ele apaga sozinho. |
| Cartão SD: "a câmera não enviou o arquivo" | Feche o servidor e rode `python ferramentas\diag_sd.py IP` (descobre a forma certa). |
| Vídeo do SD sem som | `python ferramentas\converter_sd.py sd_baixados` e veja a linha do ffmpeg. |
| Mini PC lento | Desligue IAs que não usa e esconda as câmeras que não está olhando. |

---

## 7. Códigos de resposta da porta 34567 (Ret)

| Ret | Significado |
|---|---|
| 100 / 515 | OK |
| 203 | senha errada |
| 205 | usuário/IP bloqueado (anti-força-bruta) |
| 503 | canal de voz já aberto |
| 504 | canal de voz não aberto |
| 607 | configuração não existe nesse modelo |
| 608 | valor inválido na configuração |

msgids usados: 1000 login · 1001 logout · 1006 keepalive · 1020 StorageInfo · 1040 gravar config · 1042 ler config · 1420 OPPlayBack (DownloadStart/Stop) · 1424 OPPlayBack Claim · 1430 OPTalk Start/Stop · 1432 áudio · 1434 OPTalk Claim · 1440 OPFileQuery · 1452 hora da câmera.

---

## 8. Backup

Guarde uma cópia de: `config.py`, `sessao_estado.json`, `xm_fala_modo.json`, `xm_luz_alerta.json`, `xm_sd_modo.json`, `sons\`, `rostos\` e `modelos\`. O resto é código e está no GitHub.

Para a Elsys (câmera RSA, seção 9), guarde também: `ferramentas\elsys_material.json`, `ferramentas\elsys_abre_1413.bin`, `ferramentas\elsys_login_plain.json`, `ferramentas\elsys_login_1000.b64`.

---

## 9. Câmeras com login RSA (tipo Elsys ESC-WY3F) — áudio e luz

> A Elsys (cam1) **não** usa o login simples das iCSee. Ela usa login **RSA**
> ("DVRIP-FutureHome"): a senha nunca trafega em texto, é cifrada com uma chave
> pública que a câmera gera na hora. Foi por isso que `admin`+`2119` e `admin`+vazio
> davam **203** na 34567 (regra 1), e por isso o cartão SD dela nunca abriu.
> Mesmo assim **conseguimos falar na Elsys** (enviar som pelo alto-falante). Esta
> seção registra o caminho inteiro, pra repetir em outra câmera do mesmo tipo.

### 9.1 O que descobrimos (resumo)

- **iCSee** = login simples (`admin` + senha sofia_hash). **Elsys** = login RSA,
  outra liga. O jeito de descobrir qual é: rode `ferramentas\diag_elsys_audio.py IP`
  — se a 34567 abre mas `admin`/vazio dá 203, é bem provável que seja RSA.
- A senha real **não dá pra descobrir** (é RSA, via de mão única). Mas **não precisa**:
  a gente reaproveita o login que o app faz, capturado com o PCAPdroid.
- A câmera gera uma **chave RSA nova a cada conexão**, revezando um punhado delas.
  A chave que estava na captura reaparece de tempos em tempos — e é isso que
  torna o reaproveitamento possível.

### 9.2 Capturar o login do app (PCAPdroid)

Igual à seção sobre o SD, mas aqui o alvo é o **login** e o **falar**:

1. Celular **na mesma rede Wi-Fi da câmera** (192.168.3.x). Confirme no app que a
   câmera abre ao vivo. (Se o celular estiver em outra rede, o app vai pela nuvem
   e a captura não presta — foi o tropeço da primeira vez.)
2. PCAPdroid → filtro **só no app da câmera** → modo **"PCAP file" (Dump PCAP)**.
3. Start → no app, abra a câmera **ao vivo** (faz o login) e **aperte o microfone/falar**
   uns 10 s (faz o OPTalk). Stop.
4. Jogue o `.pcap` na pasta do projeto.

### 9.3 O protocolo (o que a captura revelou)

**Login (na conexão nova, em ordem):**
- `1413` abre-alas (um OPMonitor Claim com uma sessão que a câmera não conhece) →
  a câmera responde `1414` com a **chave pública RSA** dela (1024 bits, expoente
  0x10001) + capacidades + `NotEncryptMsgID` (lista do que **não** é cifrado na sessão).
- `1000` login = **JSON em TEXTO PURO + um byte `\x00`**, com o **cabeçalho usando a
  sessão que veio no 1414** (não a sessão 0). Campos:
  `{"EncryptType":"MD5","LoginType":"DVRIP-FutureHome","UserName":<RSA>,"PassWord":<RSA>,"CommunicateKey":<RSA>}`
  — cada um é 128 bytes (256 hex) cifrados com a chave pública **daquela** conexão.
- Resposta `1001` com `Ret:100` = ok (e um `SessionID` novo pra sessão).

**O pulo do gato do login:** usuário e senha capturados só valem para a chave
pública com que foram cifrados (a "da captura"). Então:
1. abrimos conexões (só o abre-alas, **sem login** = sem risco de 205) até cair numa
   cujo `1414` tenha o **mesmo md5 da captura** (a mesma chave);
2. nessa conexão mandamos **UserName/PassWord capturados** + uma **CommunicateKey NOSSA**
   (uma chave de 16 bytes que a gente escolhe, cifrada com a chave da captura, que
   temos inteira). O login valida e **a sessão passa a usar a nossa chave**.

**Sessão (depois do login):** tudo que não está em `NotEncryptMsgID` vai cifrado:
**AES-128-CBC, IV = 16 bytes zero, chave = a nossa CommunicateKey em texto**, o
resultado em **base64**, com zero-padding, e o payload termina com **`\x00`**.
(As respostas vêm no mesmo esquema; decifram com a mesma chave.)

**Falar (enviar som):** igual às iCSee no formato, com uma diferença de cifra:
- `OPTalk Claim` (**1434**, TEXTO PURO) numa **conexão auxiliar** que usa o SID da sessão;
- `OPTalk Start` (**1430**, **CIFRADO** na sessão principal);
- áudio **G.711 A-law 8 kHz mono** em pacotes de **320 bytes** (**1432**, TEXTO PURO,
  na auxiliar), cada um com cabeçalho `00 00 01 FA 0E 02` + tamanho (2 bytes LE);
- `OPTalk Stop` (**1430**, CIFRADO).

### 9.4 O que esta Elsys (ESC-WY3F) tem e não tem

- **Tem alto-falante** (`fVideo.Volume` = 85) → **falar funciona**. OK
- **NÃO tem** saída de alarme (`Alarm.AlarmOut` = null) → **não existe** o LED
  vermelho/azul nesse modelo. Pro "negado", use a **luz branca** (`Camera.WhiteLight`,
  que ela tem) ou uma **voz de alarme** embutida (`Ability.VoiceTipType`: 24=Alarme,
  520="Local restrito, saia imediatamente!", 521, 522...).

### 9.5 As ferramentas (em `ferramentas\`)

Rode sempre com o `INICIAR_SESSAO.bat` **fechado**. Nenhuma manda senha errada, então
não tomam 205 (mas abrir muitas conexões em sequência ainda pede bom senso).

- `diag_elsys_audio.py IP` — a 34567 abre? `admin`/senha entra? (1 tentativa). Se der
  203, é câmera RSA → siga esta seção.
- `diag_pubkey_elsys.py` — mostra que a chave muda por conexão (compara 3 `1414`).
- `forja_login_elsys.py` — caça a chave da captura e **forja o login** com a nossa
  chave de sessão (prova que dá Ret 100).
- `cracka_sessao_elsys.py` / `confirma_sessao_elsys.py` — descobrem/confirmam a cifra
  da sessão (deu **AES-CBC/IV0**).
- `fala_elsys.py [arquivo]` — **fala na câmera**. Sem argumento toca um tom de teste;
  com um arquivo (`sons\rosto_Acesso_liberado_Vini.wav`, etc.) converte com ffmpeg e toca.

Arquivos de apoio (gerados a partir da captura, guarde-os): `elsys_material.json`
(chave pública + user/pass cifrados), `elsys_abre_1413.bin` (o abre-alas),
`elsys_login_plain.json` e `elsys_login_1000.b64` (o login capturado). O md5 da chave
da captura e a nossa chave de sessão estão no topo de cada script (`ALVO_MD5`, `K`).

### 9.6 Para repetir numa câmera RSA nova (receita)

1. PCAPdroid (9.2) com o celular na rede da câmera; pegue login + um "falar".
2. Do `.pcap`, extraia (um script de análise com scapy faz isso): a **chave pública**
   e os blocos **UserName/PassWord** do `1000` (-> `elsys_material.json`); o **abre-alas
   1413** inteiro (-> `elsys_abre_1413.bin`); o md5 do `1414` da conexão do login (-> `ALVO_MD5`).
3. Ajuste o `IP` e esses valores nos scripts e rode `forja_login_elsys.py`. Ret 100 = pronto.
4. `fala_elsys.py` pra confirmar o som.

### 9.7 Limitação importante (ler antes de depender disso)

O reaproveitamento depende da **chave da captura ainda estar no revezamento** da
câmera. Se a câmera for **resetada de fábrica** ou o revezamento rodar e aposentar
aquela chave, o login para de validar — aí precisa de uma **captura nova** do app.
Por isso, no uso contínuo (reconhecimento facial), o certo é **logar uma vez e manter
a sessão viva** (KeepAlive), em vez de relogar a cada som — igual ao `sessao_xm.py`
das iCSee. Se um dia o login falhar com 203 do nada, provavelmente foi isso: refaça a
captura.

> **Saída definitiva para a Elsys: conta real sem RSA (em andamento).**
> A solução que matou o 205 das iCSee (seção 10) deve servir aqui. A Elsys é
> Xiongmai igual às iCSee, tem a mesma conta real (`GetRandomUser`), e deveria
> logar por **DVRIP-Web em texto** — sem RSA, sem captura, sem expirar. Já
> sabemos que a Elsys aceita DVRIP-Web (ela responde 203 = senha errada, não
> 124 = algoritmo inválido), então com a senha certa deve logar.
>
> **Testado em 10/11/2026 (serial da cam1 = `2c9fea3d01e8fa07`, chave AES =
> `a3d01ec9fea301e8`):**
> - `GetRandomUser` (1660) **sem login** → `Ret 102` (precisa de sessão).
> - `Users` (1470) **sem login** → sem resposta (timeout). O furo de auth
>   pré-login (que vaza a lista de contas em firmwares XM R02,
>   github.com/Raizer1996/xm210-camera-research) está **fechado** nesta Elsys.
> - Então a recuperação precisa de uma **sessão autenticada**. A ferramenta
>   `ferramentas\get_conta_elsys.py IP SERIAL` sobe a sessão RSA (reusa o
>   `elsys_xm.py`) e roda o `GetRandomUser` por dentro dela. Na tentativa a
>   sessão **não subiu** (a chave da captura estava fora do revezamento).
>
> **Próximo passo (custo único):** numa **captura PCAPdroid fresca** da cam1
> (seção 9.2), com a sessão RSA de pé, rodar `get_conta_elsys.py` **uma vez**.
> Ele mostra usuário/senha reais e testa o login em texto puro. Se der Ret 100,
> põe `CAM_ADMIN_USUARIO`/`CAM_ADMIN_SENHA` no `config.py` (precisa ligar isso
> no servidor p/ a cam1 — hoje a Elsys fala pela sessão RSA, não pela conta) e
> o PCAPdroid fica aposentado.
>
> `ferramentas\recupera_conta_elsys.py` é a versão sem-login (não serviu nesta
> firmware, mas fica para Elsys/XM mais antigas que ainda vazem o 1470).

---

## 10. A conta real da porta 34567 (fim do 205) — iCSee

> **Esta é a correção mais importante do projeto.** Antes, a sessão da 34567
> vivia caindo em **205** e só voltava com reset de fábrica — que logo expirava
> de novo. Resolvido em 10/11/2026.

### 10.1 A causa (o que estava errado)

Essas câmeras têm **duas** contas locais na 34567:

- **`admin` / senha em branco** — é uma **conta de teste de fábrica (backdoor)**.
  Funciona por uma **janela de tempo** depois do reset e depois é **desligada
  pela própria câmera** (vira 205), **só pela passagem do tempo**, mesmo sem
  ninguém errar senha nem tentar nada. No nosso caso isso acontecia ~1 h após o
  reset. Trocar senha nela não adianta (o firmware ignora). Era essa a conta em
  que o projeto inteiro estava apoiado — por isso o 205 voltava sempre.
- **Conta REAL por aparelho** (nome gerado, tipo `swua`, `wwpe`) — é a conta que
  o **próprio app** usa. Ela **não expira**. É a certa para o servidor usar.

Confirmado por engenharia reversa independente do app iCSee:
github.com/voidnullvalue/Icsee-android (arquivos `SECURITY.md`,
`PROTOCOL_NOTES.md`). O `205`, aqui, é "User is locked" da conta de fábrica.

### 10.2 Como descobrir a conta real (`ferramentas\recupera_conta.py`)

Com a câmera **recém-resetada** (janela do `admin`/branco aberta) e a **sessão
fechada** (feche o `INICIAR_SESSAO.bat`):

```
python ferramentas\recupera_conta.py 192.168.3.XX
```

Ele loga com `admin`/branco, lê o número de série da câmera (`SystemInfo`, msg
1020), pede a conta real (`GetRandomUser`, msg 1660) e **descriptografa**:

- **AES-128-CBC, IV = 16 bytes zero**;
- **chave (16 chars ASCII) = `serial[5:11] + serial[1:7] + serial[8:12]`** (fatias
  do próprio número de série, convenção de fatia do Python, sem hash);
- o texto decifrado é `p1:<usuário> p2:<senha> t:<token>`.

O número de série vem da câmera (ex.: `0edd2dd0df538e881ah3`), não o que o app
mostra na tela — a ferramenta usa o interno automaticamente.

### 10.3 Pôr no projeto

No `config.py`, cada iCSee é um bloco na lista `CAMERAS`, com a conta real nos
campos `admin_usuario`/`admin_senha` (não mais o `admin`/branco):

```python
{
    "cid": "cam2", "tipo": "icsee", "nome": "iCSee X6S",
    "ip": "192.168.3.67",
    "usuario": "seu@email.com", "senha": "senha do app",
    "porta_onvif": 8899,
    "admin_usuario": "swua", "admin_senha": "SUASENHAFIXA",
    "xm": True, "ptz": True,
},
```

Depois: feche a sessão, **limpe o bloco do IP no `sessao_estado.json`** (tira a
trava velha do 203/205) e reabra o `INICIAR_SESSAO.bat`. As câmeras logam na hora.

### 10.4 Avisos (atualizado 12/11)

- **O `GetRandomUser` GIRA a senha a cada chamada.** Ele não *lê* a conta: GERA
  uma senha nova e invalida a anterior. Logo, rodar a recuperação é uma ação
  **destrutiva**. Rodamos na cam2 três vezes seguidas e vieram `ra3afj`,
  `na4ecw`, `pn634w` — e a senha que estava no `config.py` virou **203**.
- **Por isso, FIXE a senha:** `python ferramentas\recupera_conta.py IP
  --definir-senha SUASENHA` (ou use o `provisionar.py`, seção 12). O
  `ChangeRandomUser` grava uma senha sua que **para de girar** — essa vira a do
  `config.py`.
- **Recupere SÓ em câmera nova / recém-resetada** (janela do `admin`/branco
  aberta). Em câmera que já roda, **nunca** recupere: você já tem a senha fixa.
- Se um dia a câmera der **203 sozinha**, algo chamou o `GetRandomUser` de novo
  (um reset, ou o próprio app). Rode o `--definir-senha` de novo e atualize o
  `config.py`.
- A conta é a mesma do app e aceita sessões simultâneas — o app continua junto.
  Cada câmera tem a sua (cam2 = `swua`, cam3 = `wwpe`); uma não serve para a outra.

---

## 11. Alertas da PRÓPRIA câmera no painel (sem IA no PC) — iCSee

As iCSee já detectam corpo humano sozinhas (app → **Alarme inteligente**). Esses
alertas não vão só para a nuvem do app: a câmera também os **empurra pela porta
34567**, na mesma sessão que o `sessao_xm.py` já mantém com a conta real.

Como funciona (protocolo DVRIP/XM):
1. Depois do login, a sessão manda **GUARD (msg 1500)** = "me avise dos alarmes".
   A câmera responde 1501 com `Ret 100`.
2. A cada detecção a câmera manda **AlarmInfo (msg 1504)**, ex.:
   `{"AlarmInfo":{"Channel":0,"Event":"HumanDetect","Status":"Start",...}}`
   (`Status` = `Start` no início e `Stop` no fim).
3. `camera_xm.py` guarda esses alertas (`SessaoCamera.alarmes()`) e grava cada um
   em `logs\alarmes_camera.log` (o JSON bruto, pra conferir o nome do evento).
4. `servidor.py` busca os novos a cada 1 s (`/api/alertas_camera`), tira uma foto
   em alta no início do alerta (no máx. 1 a cada `ALERTA_CAM_FOTO_S` = 10 s) e a
   página mostra a aba **🔔 Alertas**, o selo "🔔 pessoa" no título e um aviso.

Ajustes (sensibilidade, área de aviso, horário, intervalo de 30 s) continuam
sendo feitos **no app** — a detecção é da câmera.

Como conferir: na janela da sessão deve aparecer
`ALERTAS da camera assinados (GUARD Ret 100)` e, ao passar na frente,
`ALERTA DA CAMERA: evento=... status=Start`.

Elsys: ainda não (a sessão RSA não tem leitor separado; um alarme empurrado no
meio de um comando atrapalharia a resposta). Fica para uma etapa própria.

Confirmado ao vivo na cam2: o evento de pessoa chega como
`"Event": "appEventHumanDetectAlarm"`, `Status` Start/Stop, sempre `Channel 0`.

### 11.1 Tipo de detecção (aba 🔔 Alertas → Detectar)
Comprovado no log (12/11): a câmera é **um OU outro**, nunca os dois juntos:
- `HumanDetection` **ligada** → só manda `appEventHumanDetectAlarm` (pessoa),
  mesmo com o movimento ligado (no "os dois" chegaram só alertas de pessoa).
- `HumanDetection` **desligada** + `MotionDetect` ligada → manda `VideoMotion`
  para **qualquer** coisa que mexer (inclusive pessoa).
Por isso o painel tem só **Só humano** e **Só movimento**. O resto do bloco
(regras de área/linha, sensibilidade, avisos) é regravado igual — só muda o
`Enable`. A escolha fica em `alertas_modo.json`.
Se o "humano" disparar com coisas que não são pessoa: baixe a Sensibilidade no
app e/ou ligue a IA com "Só quando a câmera detectar" para confirmar no PC.

### 11.1b Painel e app sincronizados
- `Detect.MotionDetect[].Enable` = **chave geral** ("Alarme inteligente → Ligado"
  do app). Desligada, o painel mostra "⏸ Alarme inteligente DESLIGADO" e ignora
  alertas; dá para ligar/desligar pela própria aba 🔔 Alertas.
- O servidor relê a config de detecção a cada 10 s: o que você mudar no app
  aparece no painel (ligado/desligado e humano/movimento) sozinho.
- Tudo que o app mudar nessas configs fica registrado, campo a campo, em
  `logs\alarme_config.log` (ex.: `Detect.MotionDetect[0].Enable: true -> false`).
  É a prova de qual campo cada botão do app mexe.

### 11.2 "Só quando a câmera detectar" (IA e Rostos)
Chave nas abas 🧠 IA e 🙂 Rostos. Com ela ligada, a IA/reconhecimento só
analisam enquanto a câmera estiver em alerta e mais `ALERTA_CAM_POS_S` (10 s)
depois do fim (no máx. `ALERTA_CAM_MAX_S` = 120 s sem "fim"). Fora disso nem o
vídeo é puxado (pausa ociosa): economiza o PC, mas o vídeo leva ~3 s para
reconectar quando o alerta chega. O cadastro de rostos não espera alerta.

Foto a cada alerta: desligada (`ALERTA_CAM_FOTO = True` no config.py religa).

### 11.3 Ações do reconhecimento facial (aba 🙂 Rostos → O que fazer)
Vale para todas as câmeras (`rostos\config_validacao.json`):
- **Liberado**: Falar (frase) e/ou **Piscar o holofote** N vezes, T s acesa e
  T s apagada (0,5 a 10 s; até 20 vezes). No fim a luz volta ao modo que estava
  (ex.: Inteligente) — antes ela ficava em "Close".
- **Negado**: Falar (frase) e/ou Acender (luz de alerta vermelho/azul ou
  holofote) por N s. Dá para deixar só o som ou só a luz.
- A chave "Responder na câmera" (por câmera) liga/desliga tudo isso.
- Corrigido: o `rosto_servidor.py` não importava `json`, então essa config
  nunca era salva em disco (voltava ao padrão a cada reinício).

### 11.4 Lentes e "Seguir pessoa" (iCSee X6S, 2 lentes) — lido ao vivo em 12/11
- Testado pelo Vini: **Só movimento** (`VideoMotion`) dispara pela **lente fixa**;
  **Só humano** (`appEventHumanDetectAlarm`) pela **lente móvel (PTZ)**. Os
  alertas vêm sempre com `Channel 0`, então o alerta não diz a lente — vale o teste.
- **Rastreamento de movimento** do app = `Detect.DetectTrack`:
  `{"Enable": 0|1, "Sensitivity": 0 Baixo|1 Médio|2 Alto, "ReturnTime": segundos}`
  (`ReturnTime` = "Hora daemon": tempo sem ninguém até voltar à posição inicial;
  300 = 5 min). Gravar `Enable: 1` liga na hora (testado e desfeito na cam2).
- Painel: aba 🔔 Alertas → **🎯 Seguir pessoa** (liga, sensibilidade, minutos para
  voltar). O servidor relê a cada 10 s e registra mudanças do app no
  `logs\alarme_config.log`.
- Outras configs descobertas: `Detect.MotionDetect[0].Level` (sensibilidade do
  movimento, 6 na cam2), `Detect.HumanDetection[0].Sensitivity` (sensibilidade da
  detecção humana, 1 na cam2), `PushInterval` 3000 ms, `PedRule[].SensorIndex`.

### 11.5 Pisca-pisca do holofote — limite medido (cam2, 12/11)
- 1 leitura de config ≈ 0,2 s; 1 gravação de `Camera.WhiteLight` ≈ 0,23 s (Ret 100).
- O caminho antigo (`set_luz`: lê + grava + lê) levava ≈ 0,65 s por troca —
  por isso 0,5 s não era respeitado.
- Agora o servidor lê a config da luz 1 vez, troca só o `WorkMode`
  (`KeepOpen`/`Close`) e no fim regrava a config original inteira.
- Mínimo no painel: **0,25 s** por fase (≈ 2 piscadas/s). Abaixo disso a câmera
  não acompanha (o comando em si já leva esse tempo).

---

## 12. Portabilidade e replicação (levar o sistema para outro lugar / câmera nova)

> Jeito fácil de pensar: o sistema tem **três camadas**. Cada coisa pertence a
> uma delas, e o que fazer quando algo muda depende só de **qual camada mexeu**.

### 12.1 As três camadas

- **Câmera (aparelho)** — *viaja com a câmera*: a **conta real** (recuperável pelo
  nº de série; não muda ao trocar de rede) e as **capacidades** (fala, luz, PTZ, SD).
- **Rede (local)** — *reconfigura no destino*: o **IP fixo** (reserva de DHCP no
  roteador) e o **Wi-Fi** (SSID/senha). Se a faixa de IP mudar (3.x → 0.x), os `ip`
  do `config.py` mudam.
- **PC (software)** — *copia a pasta*: o **código**, o **Python + libs** e o
  **`config.py`** (que amarra IPs + contas), mais os `.json` de estado.

### 12.2 Trocar o Wi-Fi (mesmo lugar) — mexe só na camada de rede
- Reconfigure cada câmera no app do fabricante apontando para o Wi-Fi novo.
- Refaça a reserva de IP fixo no roteador novo.
- Se a faixa de IP mudou, corrija os `ip` no `config.py`.
- A conta real das iCSee **não muda** (é do nº de série). Se der 205 de trava
  velha, limpe o `sessao_estado.json`.

### 12.3 Resetar uma câmera — mexe na câmera, mas a conta real volta
- O reset zera: senha de admin local, bloqueio 205 e o cadastro no app (readicione).
- A conta real continua **recuperável** pelo serial — rode a recuperação de novo
  (12.6) e **fixe** a senha. Limpe o `sessao_estado.json` antes de reabrir.

### 12.4 Levar para outro PC — copia a camada de baixo
- Siga a **seção 2** (copiar a pasta inteira, Python, `pip install -r`, mesma rede,
  `INICIAR.bat`).
- É o único ponto onde a **versão do Python** importa (hoje 3.15: sherpa-onnx sim,
  faster-whisper não).

### 12.5 Câmera nova do mesmo modelo
- **iCSee:** use o wizard `provisionar.py` (12.6) — ele faz portas → vídeo → conta
  real → `config.py`.
- **Elsys:** ainda **não** é plug-and-play (login RSA, seção 9).

### 12.6 O wizard: `ferramentas\provisionar.py` (só iCSee)

> **IMPORTANTE — o `GetRandomUser` GIRA a senha.** Ver seção 10.4: cada chamada
> gera uma senha nova e mata a anterior. Por isso o wizard, na câmera nova,
> **recupera E já fixa** uma senha sua (`ChangeRandomUser`), que não gira mais.

**Regra de ouro:**
- **Recuperar+fixar: SÓ em câmera nova / recém-resetada** (admin/branco aberto).
- **Câmera que já roda: NUNCA recupere** — use `--conta USUARIO SENHA` com a senha
  fixa que você já definiu (esse modo **não toca** na 34567 da câmera).

**Câmera nova** (com a sessão e o servidor FECHADOS):
1. App do fabricante no Wi-Fi certo; anote e-mail/senha do app.
2. IP fixo (reserva de DHCP no roteador).
3. Rode (o `--gravar` insere no config com backup; sem ele, só mostra o bloco —
   mas a senha **já é trocada** na câmera):
   ```
   python ferramentas\provisionar.py 192.168.3.XX seu@email.com --senha-fixa MinhaSenha --gravar
   ```
   Ele: confere portas → vídeo ONVIF (modelo) → recupera a conta real e **fixa**
   `MinhaSenha` → **confirma com login real** → insere o bloco no `config.py`.
4. Perto da câmera, com tudo fechado: `diag_fala.py IP` e `diag_luz_alerta.py IP`.
5. Reabra a sessão e o servidor.

**Câmera que já tem senha fixa conhecida** (não toca na câmera):
```
python ferramentas\provisionar.py 192.168.3.XX seu@email.com --conta USUARIO SENHA --gravar
```

### 12.7 Formato atual do `config.py`

Hoje as câmeras ficam numa **lista única** `CAMERAS = [ {...}, ... ]` (acabou o
`CAM4_IP = ...`). Cada iCSee é um bloco assim:
```python
{
    "cid": "cam5", "tipo": "icsee", "nome": "iCSee Portão",
    "ip": "192.168.3.XX",
    "usuario": "seu@email.com", "senha": "senha do app",
    "porta_onvif": 8899,
    "admin_usuario": "swua", "admin_senha": "SUASENHAFIXA",
    "xm": True, "ptz": True,
},
```
O `provisionar.py --gravar` insere esse bloco sozinho (e guarda um backup
`config.py.bak_AAAAMMDD_HHMMSS` antes de mexer).

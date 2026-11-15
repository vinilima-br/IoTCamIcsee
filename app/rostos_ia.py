# =============================================================
#  rostos_ia.py - Reconhecimento facial (módulo compartilhado)
#
#  YuNet (OpenCV zoo)  -> acha os rostos e 5 pontos (olhos, nariz, boca)
#  SFace (OpenCV zoo)  -> transforma cada rosto num "código" de 128
#                         números; rostos da mesma pessoa dão códigos
#                         parecidos (semelhança de cosseno alta)
#
#  Banco de pessoas (só arquivos, fácil de conferir e editar):
#    rostos\pessoas.json            -> {"Vini": {"permitido": true}, ...}
#    rostos\pessoas\<Nome>\*.jpg    -> rostos alinhados 112x112
#  Os códigos são recalculados das fotos ao carregar. Para tirar uma
#  amostra ruim, é só apagar a foto.
#
#  Usado por:  ferramentas\rosto_cadastro.py  (etapa 2)
#              e, nas próximas etapas, pelo reconhecimento ao vivo.
# =============================================================

import json
import os
import re
import sys
import threading
import time
import urllib.request

# RTSP via TCP (igual ao servidor). Precisa vir ANTES do import cv2.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")     # esconde os avisos "WARN" do OpenCV 5

import cv2  # noqa: E402
import numpy as np  # noqa: E402

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_MODELOS = os.path.join(PASTA_BASE, "modelos")
PASTA_ROSTOS = os.path.join(PASTA_BASE, "rostos")
PASTA_PESSOAS = os.path.join(PASTA_ROSTOS, "pessoas")
ARQUIVO_PESSOAS = os.path.join(PASTA_ROSTOS, "pessoas.json")

MODELO_DET = "face_detection_yunet_2023mar.onnx"
MODELO_REC = "face_recognition_sface_2021dec.onnx"
MODELOS = {
    MODELO_DET: [
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    ],
    MODELO_REC: [
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    ],
}
TAMANHO_MINIMO_MODELO = 100 * 1024

LADO_DETECCAO = 960       # a detecção roda numa cópia reduzida (lado maior = 960 px)
LIMIAR_MESMA_PESSOA = 0.363   # valor de referência do SFace (cosseno)
LIMIAR_ACEITO = 0.45          # >= isso: é a pessoa cadastrada
LIMIAR_DESCONHECIDO = 0.36    # <  isso: não é ninguém do cadastro (entre os dois: "incerto")
TIMEOUT_MS = 10000


# -------------------------------------------------------------
#  Modelos
# -------------------------------------------------------------
def confere_opencv():
    partes = cv2.__version__.split(".")
    versao = (int(partes[0]), int(partes[1]))
    if versao < (4, 8) or not hasattr(cv2, "FaceDetectorYN") or not hasattr(cv2, "FaceRecognizerSF"):
        print("OpenCV {} é antigo demais (precisa 4.8 ou mais novo).".format(cv2.__version__))
        print("Atualize com:  pip install -U opencv-python")
        sys.exit(1)


def garante_modelos():
    """Baixa os modelos que faltarem. Retorna (caminho_det, caminho_rec)."""
    os.makedirs(PASTA_MODELOS, exist_ok=True)
    for nome, urls in MODELOS.items():
        destino = os.path.join(PASTA_MODELOS, nome)
        if os.path.isfile(destino) and os.path.getsize(destino) >= TAMANHO_MINIMO_MODELO:
            continue
        baixou = False
        for url in urls:
            print("Baixando {} ...".format(nome))
            temp = destino + ".part"
            try:
                urllib.request.urlretrieve(url, temp)
                if os.path.getsize(temp) < TAMANHO_MINIMO_MODELO:
                    raise IOError("arquivo veio pequeno demais ({} bytes)".format(os.path.getsize(temp)))
                os.replace(temp, destino)
                baixou = True
                break
            except Exception as erro:  # noqa: BLE001
                print("   falhou: {}".format(erro))
                if os.path.exists(temp):
                    os.remove(temp)
        if not baixou:
            print("Não consegui baixar {}. Baixe por este link e salve em {}:".format(nome, PASTA_MODELOS))
            print("   " + urls[0])
            sys.exit(1)
    return os.path.join(PASTA_MODELOS, MODELO_DET), os.path.join(PASTA_MODELOS, MODELO_REC)


# -------------------------------------------------------------
#  Detecção + código do rosto
# -------------------------------------------------------------
class Rostos:
    def __init__(self, confianca_min=0.8):
        confere_opencv()
        det, rec = garante_modelos()
        self.det = cv2.FaceDetectorYN.create(det, "", (320, 320), confianca_min, 0.3, 5000)
        self.rec = cv2.FaceRecognizerSF.create(rec, "")
        self.tamanho_atual = None
        # As redes do OpenCV NÃO podem ser usadas por duas threads ao mesmo tempo
        # (no servidor: várias câmeras + recarregar o cadastro). RLock: analisa()
        # chama codigo_do_recorte() já com a trava na mão.
        self.trava = threading.RLock()

    def analisa(self, frame, tamanho_min=0):
        """
        Acha os rostos (largura >= tamanho_min px) e calcula o código de cada um.
        Retorna (rostos, ms_deteccao, ms_codigo). Cada rosto:
          {"caixa": (x, y, w, h), "conf": 0..1, "codigo": vetor 128, "recorte": imagem 112x112}
        Ordenados do maior para o menor.
        """
        with self.trava:
            altura, largura = frame.shape[:2]
            escala = min(1.0, LADO_DETECCAO / max(altura, largura))
            if escala < 1.0:
                pequeno = cv2.resize(frame, (int(largura * escala), int(altura * escala)),
                                     interpolation=cv2.INTER_AREA)
            else:
                pequeno = frame
            a, l = pequeno.shape[:2]
            if self.tamanho_atual != (l, a):
                self.det.setInputSize((l, a))
                self.tamanho_atual = (l, a)

            t0 = time.perf_counter()
            _, achados = self.det.detect(pequeno)
            ms_det = (time.perf_counter() - t0) * 1000

            rostos = []
            ms_cod = 0.0
            if achados is None:
                return rostos, ms_det, ms_cod
            for linha in achados:
                original = linha.copy()
                original[:14] = linha[:14] / escala      # caixa + 5 pontos na resolução original
                x, y, w, h = [int(v) for v in original[:4]]
                if w < tamanho_min:
                    continue
                t1 = time.perf_counter()
                recorte = self.rec.alignCrop(frame, original)
                codigo = self.codigo_do_recorte(recorte)
                ms_cod += (time.perf_counter() - t1) * 1000
                pontos = [(float(original[4 + 2 * i]), float(original[5 + 2 * i])) for i in range(5)]
                rostos.append({"caixa": (x, y, w, h), "conf": float(linha[14]),
                               "codigo": codigo, "recorte": recorte,
                               "pontos": pontos})     # olho, olho, nariz, boca, boca
            rostos.sort(key=lambda r: r["caixa"][2], reverse=True)
            return rostos, ms_det, ms_cod

    def codigo_do_recorte(self, recorte):
        """Recorte alinhado 112x112 -> código normalizado (comprimento 1)."""
        with self.trava:
            codigo = self.rec.feature(recorte).flatten().astype(np.float32)
        return codigo / (np.linalg.norm(codigo) + 1e-9)


def semelhanca(a, b):
    """Cosseno entre dois códigos normalizados (1 = idêntico, ~0 = sem relação)."""
    return float(np.dot(a, b))


# -------------------------------------------------------------
#  Banco de pessoas
# -------------------------------------------------------------
def nome_seguro(nome):
    """Tira do nome os caracteres que o Windows não aceita em pasta."""
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome).strip().strip(".")
    return re.sub(r"\s+", " ", limpo)


class BancoRostos:
    def __init__(self, rostos):
        self.rostos = rostos
        self.pessoas = {}      # nome -> {"permitido": bool, "codigos": matriz Nx128, "fotos": [caminhos]}

    # ---- arquivo de permissões ----
    @staticmethod
    def le_permissoes():
        if os.path.isfile(ARQUIVO_PESSOAS):
            with open(ARQUIVO_PESSOAS, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @staticmethod
    def grava_permissoes(dados):
        os.makedirs(PASTA_ROSTOS, exist_ok=True)
        temp = ARQUIVO_PESSOAS + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(temp, ARQUIVO_PESSOAS)

    # ---- carregar ----
    def carrega(self):
        permissoes = self.le_permissoes()
        novas = {}                     # monta à parte e troca de uma vez (outras threads podem estar comparando)
        if not os.path.isdir(PASTA_PESSOAS):
            self.pessoas = novas
            return self
        for nome in sorted(os.listdir(PASTA_PESSOAS)):
            pasta = os.path.join(PASTA_PESSOAS, nome)
            if not os.path.isdir(pasta):
                continue
            fotos, codigos = [], []
            for arq in sorted(os.listdir(pasta)):
                if not arq.lower().endswith((".jpg", ".png")):
                    continue
                caminho = os.path.join(pasta, arq)
                img = cv2.imdecode(np.fromfile(caminho, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                if img.shape[:2] != (112, 112):
                    img = cv2.resize(img, (112, 112))
                fotos.append(caminho)
                codigos.append(self.rostos.codigo_do_recorte(img))
            if codigos:
                novas[nome] = {
                    "permitido": bool(permissoes.get(nome, {}).get("permitido", True)),
                    "codigos": np.vstack(codigos),
                    "fotos": fotos,
                }
        self.pessoas = novas
        return self

    # ---- gravar uma pessoa ----
    def adiciona(self, nome, recortes, permitido=None):
        """permitido=None mantém o que já estava (ou True se for pessoa nova)."""
        nome = nome_seguro(nome)
        pasta = os.path.join(PASTA_PESSOAS, nome)
        os.makedirs(pasta, exist_ok=True)
        carimbo = time.strftime("%Y%m%d_%H%M%S")
        for i, recorte in enumerate(recortes, 1):
            caminho = os.path.join(pasta, "{}_{:02d}.jpg".format(carimbo, i))
            ok, dados = cv2.imencode(".jpg", recorte, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if ok:
                dados.tofile(caminho)          # tofile aceita acentos no caminho (Windows)
        permissoes = self.le_permissoes()
        if permitido is None:
            permitido = permissoes.get(nome, {}).get("permitido", True)
        permissoes[nome] = {"permitido": bool(permitido)}
        self.grava_permissoes(permissoes)
        return pasta

    # ---- comparar ----
    def compara(self, codigo, ignorar=None):
        """Retorna lista [(nome, melhor_semelhanca)] da mais parecida para a menos."""
        resultado = []
        for nome, p in list(self.pessoas.items()):
            if nome == ignorar:
                continue
            resultado.append((nome, float(np.max(p["codigos"] @ codigo))))
        resultado.sort(key=lambda t: t[1], reverse=True)
        return resultado


def filtra_amostras(rostos_obj, recortes, minimo=0.30):
    """
    Tira amostras que não combinam com as outras (ex.: um 'rosto' falso
    na prateleira ou outra pessoa que passou). Retorna (bons, ruins, media_geral).
    """
    if len(recortes) < 3:
        return recortes, [], 1.0
    codigos = np.vstack([rostos_obj.codigo_do_recorte(r) for r in recortes])
    sim = codigos @ codigos.T
    np.fill_diagonal(sim, np.nan)
    media_de_cada = np.nanmean(sim, axis=1)
    bons = [r for r, m in zip(recortes, media_de_cada) if m >= minimo]
    ruins = [r for r, m in zip(recortes, media_de_cada) if m < minimo]
    if len(bons) >= 2:
        cod_bons = np.vstack([rostos_obj.codigo_do_recorte(r) for r in bons])
        s = cod_bons @ cod_bons.T
        np.fill_diagonal(s, np.nan)
        media_geral = float(np.nanmean(s))
    else:
        media_geral = 0.0
    return bons, ruins, media_geral


# -------------------------------------------------------------
#  Decisão: permitido / negado
# -------------------------------------------------------------
def classifica(banco, codigo):
    """
    Compara um rosto com o cadastro. Retorna {"status", "nome", "sim"}:
      permitido    -> é uma pessoa cadastrada e permitida
      negado       -> é uma pessoa cadastrada como NEGADA (--negado)
      desconhecido -> não parece ninguém do cadastro (também é negado)
      incerto      -> parecido, mas não o bastante: espera o próximo quadro
    "nome" é sempre a pessoa mais parecida (no desconhecido, só para conferência).
    """
    ranking = banco.compara(codigo)
    if not ranking:
        return {"status": "desconhecido", "nome": None, "sim": 0.0}
    nome, sim = ranking[0]
    if sim >= LIMIAR_ACEITO:
        pessoa = banco.pessoas.get(nome)
        status = "permitido" if pessoa and pessoa["permitido"] else "negado"
    elif sim < LIMIAR_DESCONHECIDO:
        status = "desconhecido"
    else:
        status = "incerto"
    return {"status": status, "nome": nome, "sim": sim}


class Validador:
    """
    Transforma as análises quadro a quadro numa decisão firme:
      - precisa do MESMO resultado em `seguidos` análises seguidas
        (`seguidos_negado` para negar: evita acender a luz por causa de
        um quadro ruim antes de reconhecer a pessoa);
      - dispara uma vez por presença: só dispara de novo depois que a
        pessoa sai (`sem_rosto_s` sem rosto) ou se o resultado mudar;
      - nunca dispara dois eventos com menos de `intervalo_s` entre eles.
    Se no mesmo quadro houver um permitido e um desconhecido (ex.: as duas
    lentes da X6S vendo a mesma pessoa de ângulos diferentes), vale o permitido.
    """

    def __init__(self, seguidos=3, seguidos_negado=6, sem_rosto_s=3.0, intervalo_s=3.0, revalidar_s=0.0):
        self.revalidar_s = revalidar_s            # > 0: a mesma pessoa parada é validada de novo a cada X s
        self.presenca = 0                         # muda quando a pessoa sai e chega outra (ou volta)
        self.seguidos = seguidos
        self.seguidos_negado = seguidos_negado    # negar exige mais certeza que liberar
        self.sem_rosto_s = sem_rosto_s
        self.intervalo_s = intervalo_s
        self.chave_atual = None
        self.contagem = 0
        self.ultima_chave_disparada = None
        self.ultimo_disparo = 0.0
        self.ultimo_rosto = 0.0

    def atualiza(self, resultados, agora=None):
        """resultados = lista de classifica() do quadro. Retorna um evento ou None."""
        agora = time.time() if agora is None else agora
        if not resultados:
            if agora - self.ultimo_rosto >= self.sem_rosto_s:
                if self.ultima_chave_disparada is not None or self.chave_atual is not None:
                    self.presenca += 1                  # a pessoa foi embora
                self.chave_atual, self.contagem = None, 0
                self.ultima_chave_disparada = None      # rearma para a próxima pessoa
            return None
        self.ultimo_rosto = agora

        permitidos = [r for r in resultados if r["status"] == "permitido"]
        negados = [r for r in resultados if r["status"] in ("negado", "desconhecido")]
        if permitidos:
            melhor = max(permitidos, key=lambda r: r["sim"])
            chave = ("permitido", melhor["nome"])
        elif negados:
            cadastrados = [r for r in negados if r["status"] == "negado"]
            melhor = max(cadastrados, key=lambda r: r["sim"]) if cadastrados else negados[0]
            chave = ("negado", melhor["nome"] if melhor["status"] == "negado" else None)
        else:
            return None        # só "incerto": não decide, não zera

        if chave == self.chave_atual:
            self.contagem += 1
        else:
            self.chave_atual, self.contagem = chave, 1

        precisa = self.seguidos if chave[0] == "permitido" else self.seguidos_negado
        nova = chave != self.ultima_chave_disparada
        repete = (not nova and self.revalidar_s > 0
                  and agora - self.ultimo_disparo >= max(self.revalidar_s, self.intervalo_s))
        if self.contagem >= precisa and (nova or repete) and agora - self.ultimo_disparo >= self.intervalo_s:
            self.ultima_chave_disparada = chave
            self.ultimo_disparo = agora
            return {"status": chave[0], "nome": chave[1], "sim": melhor["sim"],
                    "motivo": melhor["status"], "quando": agora,
                    "repeticao": not nova, "presenca": self.presenca}
        return None


def texto_simples(texto):
    """Tira acentos (o desenho de texto do OpenCV não mostra acentos)."""
    import unicodedata
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")


# -------------------------------------------------------------
#  Vídeo
# -------------------------------------------------------------
def url_da_camera(cid, leve=False):
    """cam1 = Elsys (RTSP direto); cam2..cam9 = iCSee via ONVIF (mesma regra do servidor)."""
    if PASTA_BASE not in sys.path:
        sys.path.append(PASTA_BASE)
    import config
    stream = 1 if leve else 0
    if cid == "cam1":
        return "rtsp://{ip}:{porta}/user={u}_password={s}_channel=1_stream={st}.sdp".format(
            ip=config.CAM_IP, porta=config.CAM_PORTA, u=config.CAM_USUARIO, s=config.CAM_SENHA, st=stream)

    import onvif_rtsp
    n = cid[3:]
    ip = getattr(config, "CAM{}_IP".format(n), None)
    if not ip:
        raise ValueError("{} não existe no config.py".format(cid))
    usuario = getattr(config, "CAM{}_USUARIO".format(n), None) or getattr(config, "CAM2_USUARIO", "admin")
    senha = getattr(config, "CAM{}_SENHA".format(n), "") or getattr(config, "CAM2_SENHA", "")
    porta = getattr(config, "CAM{}_PORTA_ONVIF".format(n), 0) or None
    urls = onvif_rtsp.descobre_urls(ip, usuario, senha, porta_onvif=porta)
    return urls[min(stream, len(urls) - 1)]


def abre_captura(fonte):
    if isinstance(fonte, int):
        return cv2.VideoCapture(fonte)
    try:
        return cv2.VideoCapture(fonte, cv2.CAP_FFMPEG,
                                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, TIMEOUT_MS,
                                 cv2.CAP_PROP_READ_TIMEOUT_MSEC, TIMEOUT_MS])
    except (TypeError, AttributeError, cv2.error):
        return cv2.VideoCapture(fonte, cv2.CAP_FFMPEG)


class Leitor:
    """Lê a câmera numa thread e guarda só o quadro mais novo (sem atraso acumulado)."""

    def __init__(self, cap):
        self.cap = cap
        self.quadro = None
        self.numero = 0
        self.rodando = True
        self.trava = threading.Lock()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.rodando:
            try:
                ok, quadro = self.cap.read()
            except cv2.error:
                ok, quadro = False, None
            if not self.rodando:
                break
            if not ok:
                time.sleep(0.05)
                continue
            with self.trava:
                self.quadro = quadro
                self.numero += 1

    def pega(self):
        with self.trava:
            return self.numero, (None if self.quadro is None else self.quadro.copy())

    def espera_primeiro(self, segundos=TIMEOUT_MS / 1000):
        inicio = time.time()
        while self.pega()[1] is None:
            if time.time() - inicio > segundos:
                return False
            time.sleep(0.05)
        return True

    def para(self):
        """Espera a leitura em andamento terminar ANTES de fechar a câmera."""
        self.rodando = False
        self.thread.join(timeout=TIMEOUT_MS / 1000 + 2)
        if not self.thread.is_alive():
            self.cap.release()


def cabe_na_tela(frame, maximo=(1280, 900)):
    altura, largura = frame.shape[:2]
    escala = min(1.0, maximo[0] / largura, maximo[1] / altura)
    if escala < 1.0:
        return cv2.resize(frame, (int(largura * escala), int(altura * escala)), interpolation=cv2.INTER_AREA)
    return frame

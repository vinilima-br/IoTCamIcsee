# =============================================================
#  Detector de pessoas com YOLOv8n (ONNX) rodando no OpenCV DNN
#
#  - Não precisa de PyTorch: só opencv-python
#  - Arquivo do modelo: modelos/yolov8n.onnx
#  - Detecta só a classe "pessoa" (classe 0 do COCO)
#
#  Teste rápido numa imagem:
#   python detector_pessoas.py foto.jpg
# =============================================================

import os
import sys
import time

import cv2
import numpy as np

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELO_PADRAO = os.path.join(PASTA_BASE, "modelos", "yolov8n.onnx")

TAMANHO_ENTRADA = 640     # o modelo foi exportado para 640x640
CLASSE_PESSOA = 0


class DetectorPessoas:
    def __init__(self, caminho_modelo=MODELO_PADRAO, confianca_min=0.5, nms=0.45):
        if not os.path.isfile(caminho_modelo):
            raise FileNotFoundError("Modelo não encontrado: {}".format(caminho_modelo))
        self.rede = cv2.dnn.readNetFromONNX(caminho_modelo)  # roda na CPU (padrão)
        self.confianca_min = confianca_min
        self.nms = nms

    def detectar(self, frame):
        """
        Recebe um frame BGR (qualquer tamanho).
        Retorna lista de pessoas: [{"x1","y1","x2","y2" (0 a 1), "conf"}]
        """
        altura, largura = frame.shape[:2]

        # Letterbox: encaixa a imagem num quadrado sem distorcer
        escala = TAMANHO_ENTRADA / max(altura, largura)
        nova_l, nova_a = int(round(largura * escala)), int(round(altura * escala))
        redimensionada = cv2.resize(frame, (nova_l, nova_a), interpolation=cv2.INTER_LINEAR)
        quadrado = np.full((TAMANHO_ENTRADA, TAMANHO_ENTRADA, 3), 114, dtype=np.uint8)
        quadrado[:nova_a, :nova_l] = redimensionada

        blob = cv2.dnn.blobFromImage(quadrado, 1 / 255.0, (TAMANHO_ENTRADA, TAMANHO_ENTRADA),
                                     swapRB=True, crop=False)
        self.rede.setInput(blob)
        saida = self.rede.forward()            # formato (1, 84, 8400)
        saida = np.squeeze(saida, axis=0).T    # -> (8400, 84)

        # Colunas: cx, cy, w, h, depois 80 pontuações de classe
        pontuacao_pessoa = saida[:, 4 + CLASSE_PESSOA]
        maior_classe = np.argmax(saida[:, 4:], axis=1)
        filtro = (pontuacao_pessoa >= self.confianca_min) & (maior_classe == CLASSE_PESSOA)
        candidatos = saida[filtro]
        confiancas = pontuacao_pessoa[filtro]
        if len(candidatos) == 0:
            return []

        # Converte para coordenadas da imagem original
        cx, cy, w, h = candidatos[:, 0], candidatos[:, 1], candidatos[:, 2], candidatos[:, 3]
        x1 = (cx - w / 2) / escala
        y1 = (cy - h / 2) / escala
        caixas_xywh = np.stack([x1, y1, w / escala, h / escala], axis=1)

        indices = cv2.dnn.NMSBoxes(caixas_xywh.tolist(), confiancas.tolist(),
                                   self.confianca_min, self.nms)
        pessoas = []
        for i in np.array(indices).flatten():
            x, y, cw, ch = caixas_xywh[i]
            pessoas.append({
                "x1": float(np.clip(x / largura, 0, 1)),
                "y1": float(np.clip(y / altura, 0, 1)),
                "x2": float(np.clip((x + cw) / largura, 0, 1)),
                "y2": float(np.clip((y + ch) / altura, 0, 1)),
                "conf": round(float(confiancas[i]), 2),
            })
        return pessoas


def desenhar_pessoas(frame, pessoas, cor=(0, 200, 255)):
    """Desenha as caixas (coordenadas 0 a 1) no frame, no lugar."""
    altura, largura = frame.shape[:2]
    espessura = max(2, largura // 400)
    escala_fonte = max(0.5, largura / 1400)
    for p in pessoas:
        x1, y1 = int(p["x1"] * largura), int(p["y1"] * altura)
        x2, y2 = int(p["x2"] * largura), int(p["y2"] * altura)
        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, espessura)
        texto = "pessoa {:.0f}%".format(p["conf"] * 100)
        (tl, ta), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, escala_fonte, 1)
        y_texto = max(y1, ta + 6)
        cv2.rectangle(frame, (x1, y_texto - ta - 6), (x1 + tl + 6, y_texto), cor, -1)
        cv2.putText(frame, texto, (x1 + 3, y_texto - 4), cv2.FONT_HERSHEY_SIMPLEX,
                    escala_fonte, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python detector_pessoas.py imagem.jpg")
        sys.exit(1)

    imagem = cv2.imread(sys.argv[1])
    if imagem is None:
        print("Não consegui abrir a imagem: {}".format(sys.argv[1]))
        sys.exit(1)

    detector = DetectorPessoas()
    detector.detectar(imagem)  # 1ª execução é mais lenta (aquecimento)

    inicio = time.time()
    resultado = detector.detectar(imagem)
    ms = (time.time() - inicio) * 1000

    print("Pessoas encontradas: {}  ({:.0f} ms por detecção)".format(len(resultado), ms))
    for p in resultado:
        print("  conf {:.2f}  caixa ({:.2f}, {:.2f}) -> ({:.2f}, {:.2f})".format(
            p["conf"], p["x1"], p["y1"], p["x2"], p["y2"]))

    saida = os.path.splitext(sys.argv[1])[0] + "_detectado.jpg"
    cv2.imwrite(saida, desenhar_pessoas(imagem, resultado))
    print("Imagem marcada salva em: {}".format(saida))

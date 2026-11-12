# =============================================================
#  rosto_cadastro.py - Reconhecimento facial, ETAPA 2: cadastro
#
#  Cadastra uma pessoa olhando para a câmera (ou a partir de fotos)
#  e salva em  rostos\pessoas\<Nome>\  +  rostos\pessoas.json
#
#  Uso (dentro da pasta do projeto):
#    python ferramentas\rosto_cadastro.py cam2 "Vini"            cadastra ao vivo
#    python ferramentas\rosto_cadastro.py cam2 "Visita" --negado cadastra como NÃO permitido
#    python ferramentas\rosto_cadastro.py C:\fotos\vini "Vini"   cadastra de foto(s) (arquivo ou pasta)
#    python ferramentas\rosto_cadastro.py --lista                mostra quem está cadastrado
#    python ferramentas\rosto_cadastro.py --permitir "Vini"      muda a permissão
#    python ferramentas\rosto_cadastro.py --negar "Visita"
#    (acrescente --leve para usar o stream leve da câmera)
#
#  Ao vivo:  ESPAÇO = começa a capturar   Q / ESC = sair sem salvar
#  Durante a captura, vire o rosto devagar: frente, um pouco para os
#  lados, para cima e para baixo. Só uma pessoa na frente da câmera.
#
#  Não usa a porta 34567 (só vídeo), pode rodar com o servidor ligado.
# =============================================================

import os
import sys
import time

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_BASE)

import rostos_ia as ia  # noqa: E402  (antes do cv2: configura RTSP/TCP e logs)
import cv2  # noqa: E402
import numpy as np  # noqa: E402

AMOSTRAS = 20              # quantas fotos do rosto guardar
INTERVALO_S = 0.5          # tempo mínimo entre uma amostra e outra
TAMANHO_MIN_PX = 100       # rosto menor que isso não entra no cadastro
CONFIANCA_MIN = 0.90       # certeza mínima de que é um rosto


# -------------------------------------------------------------
#  Relatório final (vale para ao vivo e para fotos)
# -------------------------------------------------------------
def conclui(rostos, nome, recortes, permitido):
    nome = ia.nome_seguro(nome)
    if not nome:
        print("Nome inválido.")
        return False
    bons, ruins, media = ia.filtra_amostras(rostos, recortes)
    print("\nAmostras capturadas: {}  |  aproveitadas: {}  |  descartadas (não combinavam): {}".format(
        len(recortes), len(bons), len(ruins)))
    if len(bons) < 3:
        print("Poucas amostras boas. Nada foi salvo; tente de novo mais perto da câmera.")
        return False
    print("Semelhança média entre as amostras: {:.2f}  ({})".format(
        media, "ótimo" if media >= 0.55 else "bom" if media >= 0.45 else "fraco: refaça com mais luz/mais perto"))

    banco = ia.BancoRostos(rostos).carrega()
    ja_existia = nome in banco.pessoas
    codigos = np.vstack([rostos.codigo_do_recorte(r) for r in bons])
    parecidos = []
    for outro, p in banco.pessoas.items():
        if outro == nome:
            continue
        s = float(np.max(codigos @ p["codigos"].T))
        parecidos.append((outro, s))
    parecidos.sort(key=lambda t: t[1], reverse=True)
    for outro, s in parecidos[:3]:
        aviso = "  <<< ATENÇÃO: parecido demais!" if s >= ia.LIMIAR_MESMA_PESSOA else ""
        print("  comparado com {}: {:.2f}{}".format(outro, s, aviso))

    pasta = banco.adiciona(nome, bons, permitido)
    situacao = ia.BancoRostos.le_permissoes().get(nome, {}).get("permitido", True)
    print("{} '{}' em {}".format("Amostras somadas a" if ja_existia else "Cadastrado", nome, pasta))
    print("Situação: {}".format("PERMITIDO" if situacao else "NEGADO"))
    return True


# -------------------------------------------------------------
#  Cadastro ao vivo
# -------------------------------------------------------------
def escreve(img, texto, linha, cor=(255, 255, 255)):
    fonte = max(0.6, img.shape[1] / 1300)
    y = int((linha + 1) * 34 * fonte)
    cv2.putText(img, texto, (12, y), cv2.FONT_HERSHEY_SIMPLEX, fonte, (0, 0, 0), 5, cv2.LINE_AA)
    cv2.putText(img, texto, (12, y), cv2.FONT_HERSHEY_SIMPLEX, fonte, cor, 2, cv2.LINE_AA)


def cadastro_ao_vivo(rostos, cid, nome, permitido, leve):
    print("Perguntando o endereço de vídeo de {} ...".format(cid))
    try:
        url = ia.url_da_camera(cid, leve)
    except Exception as erro:  # noqa: BLE001
        print("Não consegui o vídeo de {}: {}".format(cid, erro))
        return False
    cap = ia.abre_captura(url)
    if not cap.isOpened():
        print("Não consegui abrir o vídeo de {}. A câmera está ligada? O IP mudou?".format(cid))
        return False
    leitor = ia.Leitor(cap)
    if not leitor.espera_primeiro():
        print("A câmera abriu mas não mandou imagem.")
        leitor.para()
        return False

    janela = "Cadastro: {}  (ESPACO comeca, Q sai)".format(nome)
    cv2.namedWindow(janela, cv2.WINDOW_NORMAL)
    recortes = []
    capturando = False
    ultima = 0.0
    ultimo_numero = -1
    cancelado = False
    print("Posicione a pessoa e aperte ESPAÇO na janela do vídeo.")

    try:
        while len(recortes) < AMOSTRAS:
            numero, quadro = leitor.pega()
            if quadro is not None and numero != ultimo_numero:
                ultimo_numero = numero
                achados, _, _ = rostos.analisa(quadro)
                validos = [r for r in achados if r["caixa"][2] >= TAMANHO_MIN_PX and r["conf"] >= CONFIANCA_MIN]

                for r in achados:
                    x, y, w, h = r["caixa"]
                    principal = validos and r is validos[0]
                    cor = (0, 200, 0) if principal else (0, 0, 255) if w < TAMANHO_MIN_PX else (0, 200, 255)
                    cv2.rectangle(quadro, (x, y), (x + w, y + h), cor, max(2, quadro.shape[1] // 500))

                agora = time.time()
                if capturando and validos and agora - ultima >= INTERVALO_S:
                    recortes.append(validos[0]["recorte"].copy())
                    ultima = agora
                    print("  amostra {}/{}".format(len(recortes), AMOSTRAS))

                tela = ia.cabe_na_tela(quadro)
                if capturando:
                    escreve(tela, "Capturando {}/{} - vire o rosto devagar".format(len(recortes), AMOSTRAS), 0,
                            (0, 255, 0))
                else:
                    escreve(tela, "ESPACO = comecar   Q = sair", 0)
                if not validos:
                    escreve(tela, "Rosto nao encontrado ou pequeno (min {} px)".format(TAMANHO_MIN_PX), 1,
                            (0, 0, 255))
                else:
                    escreve(tela, "Rosto: {} px".format(validos[0]["caixa"][2]), 1, (0, 255, 0))
                if recortes:
                    mini = cv2.resize(recortes[-1], (168, 168))
                    tela[-178:-10, -178:-10] = mini
                cv2.imshow(janela, tela)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), ord("Q"), 27):
                cancelado = True
                break
            if tecla == ord(" "):
                capturando = True
            if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) < 1:
                cancelado = True
                break
    except KeyboardInterrupt:
        cancelado = True
    finally:
        leitor.para()
        cv2.destroyAllWindows()

    if cancelado:
        print("Cancelado. Nada foi salvo.")
        return False
    return conclui(rostos, nome, recortes, permitido)


# -------------------------------------------------------------
#  Cadastro por fotos
# -------------------------------------------------------------
def cadastro_por_fotos(rostos, caminho, nome, permitido):
    if os.path.isdir(caminho):
        arquivos = [os.path.join(caminho, a) for a in sorted(os.listdir(caminho))
                    if a.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))]
    else:
        arquivos = [caminho]
    recortes = []
    for arq in arquivos:
        img = cv2.imdecode(np.fromfile(arq, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            print("  {}: não abriu".format(os.path.basename(arq)))
            continue
        achados, _, _ = rostos.analisa(img)
        validos = [r for r in achados if r["caixa"][2] >= TAMANHO_MIN_PX and r["conf"] >= CONFIANCA_MIN]
        if not validos:
            print("  {}: nenhum rosto com {} px ou mais".format(os.path.basename(arq), TAMANHO_MIN_PX))
            continue
        if len(validos) > 1:
            print("  {}: {} rostos, usei o maior".format(os.path.basename(arq), len(validos)))
        recortes.append(validos[0]["recorte"])
        print("  {}: ok ({} px)".format(os.path.basename(arq), validos[0]["caixa"][2]))
    if not recortes:
        print("Nenhuma foto aproveitável.")
        return False
    return conclui(rostos, nome, recortes, permitido)


# -------------------------------------------------------------
#  Lista e permissões
# -------------------------------------------------------------
def lista(rostos):
    banco = ia.BancoRostos(rostos).carrega()
    if not banco.pessoas:
        print("Ninguém cadastrado ainda.")
        return
    print("{:<25} {:>6}  {}".format("Pessoa", "fotos", "situação"))
    for nome, p in banco.pessoas.items():
        print("{:<25} {:>6}  {}".format(nome, len(p["fotos"]), "PERMITIDO" if p["permitido"] else "NEGADO"))


def muda_permissao(nome, permitido):
    nome = ia.nome_seguro(nome)
    if not os.path.isdir(os.path.join(ia.PASTA_PESSOAS, nome)):
        print("'{}' não está cadastrado.".format(nome))
        return
    dados = ia.BancoRostos.le_permissoes()
    dados[nome] = {"permitido": permitido}
    ia.BancoRostos.grava_permissoes(dados)
    print("'{}' agora está {}.".format(nome, "PERMITIDO" if permitido else "NEGADO"))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opcoes = [a for a in sys.argv[1:] if a.startswith("--")]

    if "--permitir" in opcoes or "--negar" in opcoes:
        if not args:
            print('Informe o nome:  --permitir "Nome"')
            return
        muda_permissao(args[0], "--permitir" in opcoes)
        return

    rostos = ia.Rostos()

    if "--lista" in opcoes:
        lista(rostos)
        return

    if len(args) < 2:
        print('Uso: python ferramentas\\rosto_cadastro.py cam2 "Nome" [--negado] [--leve]')
        print('     python ferramentas\\rosto_cadastro.py pasta_ou_foto "Nome" [--negado]')
        print('     python ferramentas\\rosto_cadastro.py --lista')
        return

    fonte, nome = args[0], args[1]
    permitido = False if "--negado" in opcoes else None

    if fonte.lower().startswith("cam") and fonte[3:].isdigit():
        cadastro_ao_vivo(rostos, fonte.lower(), nome, permitido, "--leve" in opcoes)
    elif os.path.exists(fonte):
        cadastro_por_fotos(rostos, fonte, nome, permitido)
    else:
        print("Não entendi '{}'. Use cam1, cam2, cam3... ou o caminho de uma foto/pasta.".format(fonte))


if __name__ == "__main__":
    main()

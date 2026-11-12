# -*- coding: utf-8 -*-
"""
inverter_imagem.py  -  Inverte a imagem NA PROPRIA CAMERA (igual ao app).

A camera guarda isso em "Camera.Param":
    PictureFlip   = de cima pra baixo
    PictureMirror = espelho (esquerda/direita)
    os dois juntos = girar 180 graus (camera instalada de cabeca pra baixo)

Como a mudanca e feita no sensor, vale pra tudo: pagina, gravacoes no PC,
cartao SD, reconhecimento facial e o proprio app.

NAO faz login na camera: usa a sessao que ja esta aberta (INICIAR_SESSAO.bat),
entao nao tem risco de bloqueio 205. Deixe a janela da sessao ABERTA.

Uso (dentro da pasta do projeto):
   python ferramentas\\inverter_imagem.py                 lista as cameras
   python ferramentas\\inverter_imagem.py cam2            mostra como esta
   python ferramentas\\inverter_imagem.py cam2 girar      liga/desliga o giro de 180
   python ferramentas\\inverter_imagem.py cam2 flip       liga/desliga so cima/baixo
   python ferramentas\\inverter_imagem.py cam2 espelho    liga/desliga so o espelho
   python ferramentas\\inverter_imagem.py cam2 normal     desliga tudo
   ... acrescente  --lente 1  para mexer so em uma lente (0 = primeira)
"""
import json
import sys
import urllib.error
import urllib.request

PORTA_SESSAO = 5051
URL = "http://127.0.0.1:%d" % PORTA_SESSAO
NOME = "Camera.Param"
ACOES = ("girar", "flip", "espelho", "normal")


def http(metodo, caminho, corpo=None, timeout=15.0):
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(URL + caminho, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def rpc(cid, metodo, *args):
    r = http("POST", "/rpc", {"cid": cid, "metodo": metodo, "args": list(args), "kwargs": {}})
    if r is None:
        sai("A sessao das cameras nao respondeu. Abra o INICIAR_SESSAO.bat e tente de novo.")
    if not r.get("ok"):
        sai("A camera/sessao recusou (%s): %s" % (metodo, r.get("erro")))
    return r.get("r")


def sai(msg, codigo=1):
    print(msg)
    sys.exit(codigo)


def ligado(valor):
    """'0x1', '0x00000001', 1, True -> True"""
    if isinstance(valor, str):
        try:
            return int(valor, 16) != 0
        except ValueError:
            return False
    return bool(valor)


def no_formato(antigo, liga):
    """Devolve o novo valor no MESMO formato que a camera usa ('0x1' ou '0x00000001' ou numero)."""
    if isinstance(antigo, str):
        digitos = len(antigo[2:]) if antigo.lower().startswith("0x") else 1
        return "0x" + ("1" if liga else "0").rjust(max(1, digitos), "0")
    if isinstance(antigo, bool):
        return bool(liga)
    return 1 if liga else 0


def descreve(flip, espelho):
    if flip and espelho:
        return "GIRADA 180 graus (flip + espelho)"
    if flip:
        return "invertida de cima pra baixo (flip)"
    if espelho:
        return "espelhada (esquerda/direita)"
    return "normal"


def le_param(cid):
    dados = rpc(cid, "ler", NOME)
    if dados is None:
        sai("A camera nao devolveu %s (sessao dela esta logada?)." % NOME)
    eh_lista = isinstance(dados, list)
    itens = dados if eh_lista else [dados]
    if not itens or not all(isinstance(i, dict) for i in itens):
        sai("Formato inesperado de %s:\n%s" % (NOME, json.dumps(dados, indent=1)))
    return dados, itens


def mostra(itens):
    for n, item in enumerate(itens):
        if "PictureFlip" not in item and "PictureMirror" not in item:
            print("   lente %d: esta camera nao tem PictureFlip/PictureMirror aqui" % n)
            continue
        f, m = item.get("PictureFlip"), item.get("PictureMirror")
        print("   lente %d: %-38s  PictureFlip=%s  PictureMirror=%s"
              % (n, descreve(ligado(f), ligado(m)), f, m))


def main():
    args = [a for a in sys.argv[1:]]
    lente = None
    if "--lente" in args:
        i = args.index("--lente")
        try:
            lente = int(args[i + 1])
        except (IndexError, ValueError):
            sai("Use assim:  --lente 0   (ou 1)")
        del args[i:i + 2]

    estado = http("GET", "/estado", timeout=3.0)
    if estado is None:
        sai("A sessao das cameras nao esta rodando. Abra o INICIAR_SESSAO.bat e tente de novo.")
    cams = estado.get("cams", {})

    if not args:
        print("Cameras na sessao:")
        for cid, c in cams.items():
            print("   %-10s %-16s %s" % (cid, c.get("ip"), "logada" if c.get("conectada") else "NAO logada"))
        print("\nExemplo:  python ferramentas\\inverter_imagem.py %s" % (next(iter(cams), "cam2")))
        return

    cid = args[0]
    acao = args[1].lower() if len(args) > 1 else None
    if cid not in cams:
        sai("Camera '%s' nao esta na sessao. Tem: %s" % (cid, ", ".join(cams) or "nenhuma"))
    if not cams[cid].get("conectada"):
        sai("A %s nao esta logada na sessao agora. Espere ela logar e tente de novo." % cid)
    if acao is not None and acao not in ACOES:
        sai("Acao desconhecida: %s. Use uma de: %s" % (acao, ", ".join(ACOES)))

    dados, itens = le_param(cid)
    print("%s (%s) - como esta AGORA:" % (cid, cams[cid].get("ip")))
    mostra(itens)
    if acao is None:
        print("\nPara mudar:  python ferramentas\\inverter_imagem.py %s girar" % cid)
        return

    if lente is not None and not (0 <= lente < len(itens)):
        sai("Essa camera tem %d lente(s) aqui: use --lente 0 a %d." % (len(itens), len(itens) - 1))

    mudou = False
    for n, item in enumerate(itens):
        if lente is not None and n != lente:
            continue
        if "PictureFlip" not in item or "PictureMirror" not in item:
            continue
        f, m = ligado(item["PictureFlip"]), ligado(item["PictureMirror"])
        if acao == "girar":
            alvo = not (f and m)
            nf, nm = alvo, alvo
        elif acao == "flip":
            nf, nm = (not f), m
        elif acao == "espelho":
            nf, nm = f, (not m)
        else:
            nf, nm = False, False
        if (nf, nm) != (f, m):
            item["PictureFlip"] = no_formato(item["PictureFlip"], nf)
            item["PictureMirror"] = no_formato(item["PictureMirror"], nm)
            mudou = True

    if not mudou:
        print("\nNada a mudar: ja esta assim.")
        return

    r = rpc(cid, "gravar", NOME, dados)
    if isinstance(r, dict) and r.get("ok") is False:
        sai("A camera recusou gravar (Ret=%s)." % r.get("ret"))

    _, depois = le_param(cid)
    print("\nGravado. Como ficou (lido de volta da camera):")
    mostra(depois)
    print("\nOlhe o video (pagina ou app): a imagem muda em 1 a 3 segundos.")
    print("Se o botao de girar da PAGINA estiver ligado nessa camera, desligue-o,")
    print("senao a pagina gira de novo por cima.")


if __name__ == "__main__":
    main()

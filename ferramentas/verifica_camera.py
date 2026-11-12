# -*- coding: utf-8 -*-
"""
ferramentas/verifica_camera.py  -  Checa uma camera NOVA antes de por no servidor.

Faz, em ordem, sem insistir (nao toma bloqueio 205):
  1. Portas abertas: 554 (RTSP), ONVIF (8899/80/8000/8080), 34567 (XM/iCSee)
  2. ONVIF: com o e-mail/senha do APP, descobre os enderecos de video (RTSP)
  3. Porta 34567: UMA tentativa de login como admin + senha em branco
     (respeita a trava em sessao_estado.json)
  4. Le o que a camera tem: volume, luz branca, vozes de alarme, LED
  5. Imprime o trecho pronto para colar no config.py

Uso (na pasta do projeto, com o servidor FECHADO se a camera ja estiver nele):
   python ferramentas\\verifica_camera.py 192.168.3.50
   python ferramentas\\verifica_camera.py 192.168.3.50 seu@email.com
"""
import getpass
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import camera_xm as xm  # noqa: E402
import onvif_rtsp  # noqa: E402

OK, FALHA, AVISO = "  [OK]   ", "  [X]    ", "  [!]    "


def porta_aberta(ip, porta, timeout=2.0):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def mascara(url):
    """Esconde a senha que o ONVIF poe dentro do endereco."""
    if "@" in url and "://" in url:
        proto, resto = url.split("://", 1)
        cred, host = resto.split("@", 1)
        return "%s://%s:***@%s" % (proto, cred.split(":")[0], host)
    return url


def login_unico(ip, senha_admin=""):
    """1 tentativa de login na 34567. Retorna (aux ou None, mensagem)."""
    libera, motivo = xm.liberado_em(ip)
    if libera is None:
        return None, ("a ultima tentativa deu SENHA ERRADA (203). Para tentar de novo, apague "
                      "o bloco do IP %s no sessao_estado.json (ou clique 'Tentar conectar de novo' "
                      "na pagina)" % ip)
    espera = libera - time.time()
    if espera > 0:
        if espera > 90:
            return None, "trava ativa (%s). Tente de novo as %s" % (motivo, xm.hora(libera))
        print("        aguardando %d s (trava anti-bloqueio: %s)..." % (espera + 1, motivo))
        time.sleep(espera + 1)
    xm.grava_estado(ip, ultima_tentativa=time.time(), ultimo_ret="conectando")
    try:
        aux = xm.ConexaoAux(ip, 0)
    except OSError as e:
        xm.grava_estado(ip, ultimo_ret="tcp")
        return None, "nao conectou na 34567: %s" % e
    dados = ('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
             '"PassWord":"%s","UserName":"admin"}') % xm.sofia_hash(senha_admin)
    r = aux.comando(xm.LOGIN, dados, timeout=6)
    ret = r.get("Ret") if r else None
    xm.grava_estado(ip, ultimo_ret=ret if ret is not None else "sem_resposta")
    if ret not in (100, 515):
        aux.fecha()
        return None, "login recusado: %s" % (xm.descreve(ret) if ret is not None else "sem resposta")
    try:
        aux.session = int(str(r.get("SessionID", "0")), 16)
    except ValueError:
        pass
    return aux, "login OK (admin / senha em branco)"


def ler(aux, nome):
    r = aux.comando(xm.GET_CONFIG, json.dumps({"Name": nome, "SessionID": "0x%08X" % aux.session}))
    if not r or r.get("Ret") not in (100, 515):
        return None
    return r.get(nome)


def main():
    if len(sys.argv) < 2 or sys.argv[1].count(".") != 3:
        print(__doc__)
        return
    ip = sys.argv[1]
    usuario = sys.argv[2] if len(sys.argv) > 2 else ""

    print("=" * 64)
    print(" VERIFICA CAMERA  %s" % ip)
    print("=" * 64)

    # ---------------- 1. portas ----------------
    print("\n1) Portas")
    portas = {554: "RTSP (video)", 34567: "XM/iCSee (som, luz, alarme)"}
    for p in onvif_rtsp.PORTAS_ONVIF_PADRAO:
        portas.setdefault(p, "ONVIF?")
    abertas = {}
    for p, desc in portas.items():
        abertas[p] = porta_aberta(ip, p)
        print("%s%-5d %s" % (OK if abertas[p] else "  [ ]    ", p, desc))
    if not any(abertas.values()):
        print("\n%sA camera nao respondeu em nenhuma porta. IP certo? Esta ligada?" % FALHA)
        return

    # ---------------- 2. ONVIF / RTSP ----------------
    print("\n2) Video (ONVIF com o login do APP)")
    urls, porta_onvif = [], 0
    onvif_ok = [p for p in onvif_rtsp.PORTAS_ONVIF_PADRAO if abertas.get(p)]
    if not onvif_ok:
        print("%sNenhuma porta ONVIF aberta. Se for camera tipo Elsys, use RTSP direto (veja o guia)." % AVISO)
    else:
        if not usuario:
            usuario = input("   E-mail/usuario do app da camera: ").strip()
        senha_app = getpass.getpass("   Senha do app (nao aparece ao digitar): ")
        for p in onvif_ok:
            try:
                urls = onvif_rtsp.descobre_urls(ip, usuario, senha_app, porta_onvif=p)
                porta_onvif = p
                break
            except Exception as e:
                ultimo = e
        if urls:
            print("%sONVIF na porta %d, %d endereco(s) de video:" % (OK, porta_onvif, len(urls)))
            for i, u in enumerate(urls):
                print("          %s: %s" % ("alta" if i == 0 else "leve", mascara(u)))
            modelo, firmware = onvif_rtsp.info_dispositivo(ip, usuario, senha_app, porta_onvif)
            if modelo:
                print("%sModelo: %s   firmware: %s" % (OK, modelo, firmware))
        else:
            print("%sONVIF nao entregou o video: %s" % (FALHA, ultimo))
            print("          Confira e-mail/senha do app. (Isso NAO bloqueia a camera.)")

    # ---------------- 3/4. porta 34567 ----------------
    print("\n3) Porta 34567 (alto-falante, luz, alarme)")
    info = {}
    if not abertas.get(34567):
        print("%sPorta fechada: essa camera nao tem o protocolo XM. Fica so com video." % AVISO)
    else:
        aux, msg = login_unico(ip)
        print("%s%s" % (OK if aux else FALHA, msg))
        if aux is None and "203" in msg:
            print("          A senha de admin LOCAL nao e mais a de fabrica (em branco).")
            print("          Solucao: reset de fabrica na camera e adicionar de novo no app.")
            print("          NAO fique tentando outras senhas: depois de algumas a camera da 205.")
        if aux is not None:
            try:
                vol = ler(aux, "fVideo.Volume")
                luz = ler(aux, "Camera.WhiteLight")
                vozes = ler(aux, "Ability.VoiceTipType")
                md = ler(aux, "Detect.MotionDetect")
                led = ler(aux, "FbExtraStateCtrl")
                info = {"vol": vol, "luz": luz, "vozes": vozes, "md": md, "led": led}
                print("\n4) O que a camera tem")
                print("%sVolume do alto-falante: %s" % (OK if vol else AVISO,
                      vol[0].get("LeftVolume") if vol else "nao tem"))
                print("%sLuz branca: %s" % (OK if luz else AVISO,
                      "modo %s, brilho %s" % (luz.get("WorkMode"), luz.get("Brightness")) if luz else "nao tem"))
                lista = (vozes or {}).get("VoiceTip", []) if isinstance(vozes, dict) else []
                if lista:
                    print("%sVozes do alarme:" % OK)
                    for v in lista:
                        print("            %s = %s" % (v.get("VoiceEnum"), v.get("VoiceText")))
                else:
                    print("%sSem lista de vozes de alarme" % AVISO)
                print("%sDeteccao de movimento: %s" % (OK if md else AVISO, "sim" if md else "nao lida"))
                print("%sLED de status controlavel: %s" % (OK if led else "  [ ]    ", "sim" if led else "nao"))
            finally:
                try:
                    aux.envia(xm.LOGOUT, json.dumps({"Name": "", "SessionID": "0x%08X" % aux.session}).encode() + b"\n\x00")
                    time.sleep(0.2)
                except Exception:
                    pass
                aux.fecha()

    # ---------------- 5. trecho do config ----------------
    print("\n5) Para o config.py (troque N pelo numero da camera):")
    print("-" * 64)
    print('CAMN_IP = "%s"' % ip)
    if urls:
        print('CAMN_USUARIO = "%s"' % usuario)
        print('CAMN_SENHA = "...senha do app..."')
        print("CAMN_PORTA_ONVIF = %d" % porta_onvif)
    if info:
        print('CAMN_ADMIN_SENHA = ""      # admin local (porta 34567)')
    print("-" * 64)
    if info:
        print("Depois de por no servidor, rode o teste de fala dessa camera:")
        print("   python ferramentas\\diag_fala.py %s" % ip)


if __name__ == "__main__":
    main()

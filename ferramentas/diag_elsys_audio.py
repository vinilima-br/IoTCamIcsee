# -*- coding: utf-8 -*-
"""
ferramentas/diag_elsys_audio.py  -  A Elsys tem alto-falante e aceita a 34567?

Responde, com UMA unica tentativa de login (sem risco de 205, respeitando a
trava do sessao_estado.json), as duas perguntas que decidem se da pra enviar
som e acender a luz de alerta na Elsys, igual fazemos na iCSee:

  1. A porta 34567 (protocolo XM) esta aberta na Elsys?
  2. O login de admin entra? (testa a senha que voce passar; padrao "2119",
     a mesma do video no config.py)
  3. Se entrar: a camera TEM alto-falante (saida de audio)? tem saida de
     alarme (a luz vermelha/azul)? tem vozes de alarme? LED controlavel?

Uso (na pasta do projeto, com a janela do INICIAR_SESSAO.bat FECHADA):
   python ferramentas\\diag_elsys_audio.py
   python ferramentas\\diag_elsys_audio.py 192.168.3.119 2119
   python ferramentas\\diag_elsys_audio.py 192.168.3.119 ""     (tenta senha em branco)

Regras de ouro respeitadas:
  - 1 tentativa SO. Se der 203 (senha errada) ele NAO insiste (o guia manda
    nao ficar testando senha: depois de algumas a camera da 205).
  - Se o sessao_xm.py estiver aberto, ele avisa e nao faz nada (so aquela
    janela pode logar na 34567).
"""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import camera_xm as xm  # noqa: E402

OK, FALHA, AVISO = "  [OK]   ", "  [X]    ", "  [!]    "

# valores padrao (a Elsys do config.py)
IP_PADRAO = "192.168.3.119"
SENHA_PADRAO = "2119"


def porta_aberta(ip, porta, timeout=2.0):
    try:
        with socket.create_connection((ip, porta), timeout=timeout):
            return True
    except OSError:
        return False


def ler(aux, nome):
    r = aux.comando(xm.GET_CONFIG, json.dumps({"Name": nome, "SessionID": "0x%08X" % aux.session}))
    if not r or r.get("Ret") not in (100, 515):
        return None
    return r.get(nome)


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else IP_PADRAO
    senha = sys.argv[2] if len(sys.argv) > 2 else SENHA_PADRAO

    # o PowerShell engole "" como argumento; use a palavra BRANCO para senha vazia
    if senha.strip().lower() in ("branco", "vazio", "vazia", "nada"):
        senha = ""

    print("=" * 64)
    print(" DIAG ELSYS AUDIO   %s   (senha admin testada: %r)" % (ip, senha))
    print("=" * 64)

    # Se a ultima tentativa deste IP foi 203 (senha errada), este teste e uma
    # nova tentativa DELIBERADA com outra senha: limpamos SO esse bloco (nunca
    # um 205) para a tentativa unica rodar, mantendo a espera de 60 s.
    _e = xm.le_estado().get(ip, {})
    if _e.get("ultimo_ret") == 203:
        ts = _e.get("ultima_tentativa", 0)
        falta = (ts + xm.ESPERA_APOS_FALHA) - time.time()
        if falta > 0:
            print("\n%saguardando %d s desde a ultima tentativa (seguranca anti-205)..."
                  % (AVISO, int(falta) + 1))
            time.sleep(falta + 1)
        xm.grava_estado(ip, ultima_tentativa=ts, ultimo_ret="falha")  # tira o 203, vira falha comum

    # a janela da sessao separada nao pode estar aberta (ela trava a 34567)
    if xm.sessao_separada_rodando():
        print("%sO INICIAR_SESSAO.bat esta ABERTO. Feche aquela janela (Ctrl+C)" % FALHA)
        print("         e rode este teste de novo.")
        return

    # ---- 1. porta 34567 ----
    print("\n1) Porta 34567 (protocolo XM: audio, luz de alerta, alarme)")
    if not porta_aberta(ip, 34567):
        print("%sFECHADA. Essa Elsys NAO fala o protocolo XM nessa porta." % FALHA)
        print("         => por este caminho nao da pra enviar som nem acender a luz.")
        print("         O reconhecimento facial continua so REGISTRANDO nela (sem voz/luz),")
        print("         ou o som/aviso teria que vir por outro caminho (ESP32, buzzer, etc.).")
        return
    print("%sAberta." % OK)

    # ---- 2. login unico (respeita a trava) ----
    print("\n2) Login de admin na 34567 (UMA tentativa)")
    libera, motivo = xm.liberado_em(ip)
    if libera is None:
        print("%sA ultima tentativa deu 203 (senha errada). Para testar outra senha, apague" % FALHA)
        print("         o bloco do IP %s no sessao_estado.json e rode de novo." % ip)
        return
    espera = libera - time.time()
    if espera > 0:
        if espera > 90:
            print("%sTrava ativa (%s). Tente de novo as %s." % (AVISO, motivo, xm.hora(libera)))
            return
        print("        aguardando %d s (trava anti-bloqueio: %s)..." % (espera + 1, motivo))
        time.sleep(espera + 1)

    xm.grava_estado(ip, ultima_tentativa=time.time(), ultimo_ret="conectando")
    try:
        aux = xm.ConexaoAux(ip, 0)
    except OSError as e:
        xm.grava_estado(ip, ultimo_ret="tcp")
        print("%sNao conectou na 34567: %s" % (FALHA, e))
        return

    dados = ('{"EncryptType":"MD5","LoginType":"DVRIP-Web",'
             '"PassWord":"%s","UserName":"admin"}') % xm.sofia_hash(senha)
    r = aux.comando(xm.LOGIN, dados, timeout=6)
    ret = r.get("Ret") if r else None
    xm.grava_estado(ip, ultimo_ret=ret if ret is not None else "sem_resposta")

    if ret not in (100, 515):
        aux.fecha()
        print("%sLogin recusado: %s" % (FALHA, xm.descreve(ret) if ret is not None else "sem resposta"))
        if ret == 203:
            print("         A senha %r nao e a do admin na 34567." % senha)
            print("         NAO fique testando senhas (depois de algumas vem o 205).")
            print("         Caminhos: tentar senha em branco UMA vez (passe \"\" no comando),")
            print("         ou reset de fabrica (admin fica em branco, mas o app pode retrancar).")
        return

    try:
        aux.session = int(str(r.get("SessionID", "0")), 16)
    except ValueError:
        pass
    print("%sLOGIN OK com a senha %r. A 34567 da Elsys esta acessivel." % (OK, senha))

    # ---- 3. o que a camera tem ----
    try:
        vol = ler(aux, "fVideo.Volume")
        luz = ler(aux, "Camera.WhiteLight")
        vozes = ler(aux, "Ability.VoiceTipType")
        alarmout = ler(aux, "Alarm.AlarmOut")
        md = ler(aux, "Detect.MotionDetect")
        led = ler(aux, "FbExtraStateCtrl")

        print("\n3) O que a Elsys tem")
        tem_som = bool(vol)
        print("%sALTO-FALANTE (saida de audio): %s" % (
            OK if tem_som else FALHA,
            ("sim, volume atual %s" % vol[0].get("LeftVolume")) if tem_som
            else "NAO reportou volume -> provavelmente so microfone, sem saida de som"))
        print("%sSaida de alarme (luz vermelha/azul): %s" % (
            OK if alarmout else AVISO, "sim" if alarmout else "nao lida"))
        lista = (vozes or {}).get("VoiceTip", []) if isinstance(vozes, dict) else []
        if lista:
            print("%sVozes de alarme embutidas:" % OK)
            for v in lista:
                print("            %s = %s" % (v.get("VoiceEnum"), v.get("VoiceText")))
        else:
            print("%sSem lista de vozes de alarme embutidas" % AVISO)
        print("%sLuz branca: %s" % (OK if luz else AVISO,
              ("modo %s, brilho %s" % (luz.get("WorkMode"), luz.get("Brightness"))) if luz else "nao tem"))
        print("%sDeteccao de movimento: %s" % (OK if md else AVISO, "sim" if md else "nao lida"))
        print("%sLED de status controlavel: %s" % (OK if led else "  [ ]    ", "sim" if led else "nao"))

        print("\n" + "=" * 64)
        if tem_som:
            print(" VEREDITO: da pra enviar som na Elsys (tem alto-falante + 34567 aberta).")
            print(" Proximo passo: ferramentas\\diag_fala.py %s (perto da camera)." % ip)
        else:
            print(" VEREDITO: a 34567 abre, mas a camera parece NAO ter alto-falante.")
            print(" Ouvir o ambiente pode funcionar; ENVIAR som, nao.")
        print("=" * 64)
    finally:
        try:
            aux.envia(xm.LOGOUT, json.dumps({"Name": "", "SessionID": "0x%08X" % aux.session}).encode() + b"\n\x00")
            time.sleep(0.2)
        except Exception:
            pass
        aux.fecha()


if __name__ == "__main__":
    main()

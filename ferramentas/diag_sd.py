# -*- coding: utf-8 -*-
"""
ferramentas/diag_sd.py  -  Testa o acesso as gravacoes do CARTAO SD da camera.

Com UMA sessao (1 login so):
  1. mostra o cartao (tamanho e espaco livre) e a hora da camera
  2. lista as gravacoes das ultimas 24 h (ou N horas)
  3. baixa a gravacao mais recente ja fechada, tentando as formas de
     download ate uma funcionar, e salva a forma em xm_sd_modo.json
  4. converte para .mp4 em sd_baixados\\ (abre no VLC/Windows)

ANTES DE RODAR: feche o servidor (Ctrl+C) e o app iCSee no celular.

Uso (na pasta do projeto):
   python ferramentas\\diag_sd.py                   # camera 2, ultimas 24 h
   python ferramentas\\diag_sd.py 192.168.3.2       # outra camera
   python ferramentas\\diag_sd.py 192.168.3.2 72    # ultimas 72 h
"""
import os
import socket
import sys
import time
from collections import Counter
from datetime import datetime, timedelta

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # pasta do projeto
sys.path.insert(0, os.path.join(_RAIZ, "app"))                       # o codigo fica em app/
sys.path.append(_RAIZ)                                               # config.py
import config  # noqa: E402
import camera_xm as xm  # noqa: E402
import sd_xm  # noqa: E402

TAMANHO_TESTE_MAX_KB = 25 * 1024     # prefere um arquivo de ate 25 MB para o teste


def servidor_aberto():
    try:
        with socket.create_connection(("127.0.0.1", getattr(config, "WEB_PORTA", 5050)), timeout=0.5):
            return True
    except OSError:
        return False


def barra(recebido, esperado):
    if esperado:
        pct = min(100, recebido * 100 // max(1, esperado))
        print("\r   baixando: %5.1f MB de %5.1f MB (%3d%%)   " % (recebido / 1048576, esperado / 1048576, pct),
              end="", flush=True)
    else:
        print("\r   baixando: %5.1f MB   " % (recebido / 1048576), end="", flush=True)


def main():
    ip = getattr(config, "CAM2_IP", "192.168.3.67")
    senha = getattr(config, "CAM2_ADMIN_SENHA", "")
    horas = 24
    for a in sys.argv[1:]:
        if a.count(".") == 3:
            ip = a
            if ip == getattr(config, "CAM3_IP", None):
                senha = getattr(config, "CAM3_ADMIN_SENHA", "")
        elif a.isdigit():
            horas = int(a)

    print("=" * 64)
    print(" DIAGNOSTICO DO CARTAO SD - %s" % ip)
    print("=" * 64)
    if servidor_aberto():
        print("\n[!] O servidor parece estar ABERTO. Feche ele (Ctrl+C) e rode de novo.")
        return

    s = xm.SessaoCamera("sd", ip, "admin", senha, log=lambda m: print("   " + m))
    s.iniciar()
    print("\nConectando (respeitando a trava anti-205; pode levar ate ~1 min)...")
    t0 = time.time()
    while not s.conectada and time.time() - t0 < 120 and not s.desistiu:
        time.sleep(0.5)
    if not s.conectada:
        print("\n[!] Nao conectou: %s" % (s.ultimo_erro or "tempo esgotado"))
        s.encerrar()
        return

    try:
        # ---------------- 1. cartao e hora ----------------
        print("\n1) Cartao e relogio")
        try:
            arm = sd_xm.armazenamento(s)
        except Exception as e:
            arm = None
            print("   (nao li o cartao: %s)" % e)
        if arm:
            print("   [OK] Cartao: %.1f GB, livre %.1f GB" % (arm["total_mb"] / 1024, arm["livre_mb"] / 1024))
        else:
            print("   [!]  A camera nao informou cartao SD (sem cartao, ou nao suporta a consulta).")
        agora_cam = None
        try:
            agora_cam = sd_xm.hora_camera(s)
        except Exception as e:
            print("   (nao li a hora: %s)" % e)
        agora_pc = datetime.now().replace(microsecond=0)
        if agora_cam:
            dif = (agora_cam - agora_pc).total_seconds()
            print("   [OK] Hora da camera: %s  (PC: %s, diferenca %+d s)" % (agora_cam, agora_pc, dif))
            if abs(dif) > 120:
                print("   [!]  O relogio da camera esta diferente do PC - a busca usa a hora DA CAMERA.")
        referencia = agora_cam or agora_pc

        # ---------------- 2. lista ----------------
        inicio = referencia - timedelta(hours=horas)
        print("\n2) Gravacoes de %s ate %s" % (inicio, referencia))
        try:
            arquivos = sd_xm.listar(s, inicio, referencia + timedelta(minutes=5))
        except Exception as e:
            print("   [X] Falhou ao listar: %s" % e)
            print("\n Me cola esta saida.")
            return
        if not arquivos:
            print("   [!] Nenhuma gravacao nesse periodo.")
            print("       Confira no app se a gravacao no cartao esta ligada, ou rode com mais horas:")
            print("       python ferramentas\\diag_sd.py %s 168" % ip)
            return
        total_mb = sum(a["kb"] for a in arquivos) / 1024
        tipos = Counter(a["tipo"] for a in arquivos)
        print("   [OK] %d gravacao(oes), %.0f MB no total. Tipos: %s" % (
            len(arquivos), total_mb, ", ".join("%s=%d" % kv for kv in tipos.items())))
        print("   Mais recentes:")
        for a in arquivos[:8]:
            print("     %s -> %s   %6.1f MB   %s" % (a["inicio"], (a["fim"] or "")[11:], a["kb"] / 1024, a["tipo"]))

        # ---------------- 3. download ----------------
        limite_fechado = (referencia - timedelta(minutes=1)).strftime(sd_xm.FORMATO)
        fechados = [a for a in arquivos if (a["fim"] or "") < limite_fechado] or arquivos
        candidatos = [a for a in fechados if 0 < a["kb"] <= TAMANHO_TESTE_MAX_KB] or \
            sorted(fechados, key=lambda a: a["kb"])
        alvo = candidatos[0]
        print("\n3) Baixando para teste: %s (%.1f MB)" % (alvo["inicio"], alvo["kb"] / 1024))
        os.makedirs(sd_xm.PASTA_SD, exist_ok=True)
        bruto = os.path.join(sd_xm.PASTA_SD, sd_xm.nome_local(alvo) + ".h264")

        ordem = list(sd_xm.MODOS_SD)
        salvo = sd_xm.modo_salvo(ip)
        if salvo:
            ordem.remove(salvo)
            ordem.insert(0, salvo)
        achou = None
        for modo in ordem:
            print("   forma '%s'..." % modo)
            try:
                r = sd_xm.baixar(s, alvo, bruto, modo=modo, progresso=barra)
                print()
                print("   camera: claim=%s start=%s  recebido=%.1f MB em %.1f s  (%s)" % (
                    r["claim"], r["start"], r["bytes"] / 1048576, r["segundos"], r.get("fim", "")))
                if r["bytes"] > 1024:
                    achou = (modo, r)
                    break
                print("   nao chegou video por essa forma.")
            except Exception as e:
                print()
                print("   [X] %s" % e)
            if not s.conectada:
                print("   (a sessao caiu - parando)")
                break
            time.sleep(1.5)

        if not achou:
            print("\n Nenhuma forma baixou o arquivo. Me cola esta saida inteira.")
            return
        modo, r = achou
        sd_xm.salva_modo(ip, modo)
        vel = r["bytes"] / 1048576 / max(0.1, r["segundos"])
        print("   [OK] Download pela forma '%s' (%.2f MB/s). Salvei em xm_sd_modo.json." % (modo, vel))
        if r["esperado"] and r["bytes"] < r["esperado"] * 0.9:
            print("   [!]  Veio menos que o tamanho informado (%.1f de %.1f MB)." % (
                r["bytes"] / 1048576, r["esperado"] / 1048576))

        # ---------------- 4. MP4 ----------------
        print("\n4) Convertendo para MP4...")
        exe, ver = sd_xm.versao_ffmpeg()
        print("   ffmpeg: %s  (%s)" % (ver, exe))
        mp4 = os.path.splitext(bruto)[0] + ".mp4"
        try:
            info = sd_xm.para_mp4(bruto, mp4)
            print("   [OK] %s" % mp4)
            print("        video %s %dx%d, %s fps, ~%s s, audio: %s" % (
                info["formato_usado"], info["largura"], info["altura"], info["fps"],
                info["duracao_s"], "sim" if info["com_audio"] else
                ("NAO ENTROU (o cartao tem audio) - me avise" if info.get("audio_no_cartao") else "nao gravado")))
            if info["altura"] > info["largura"]:
                print("        (as duas lentes vem empilhadas num quadro so: fixa em cima, movel embaixo)")
            if info["formato_usado"] == "hevc":
                print("        (H.265: abre no VLC. Para o navegador, a pagina vai converter quando precisar.)")
            print("\n Abra o arquivo e me diga se o video ficou certo!")
        except Exception as e:
            print("   [X] %s" % e)
            print("   O arquivo bruto ficou em %s - me cola esta saida." % bruto)
    except KeyboardInterrupt:
        print("\n(cancelado)")
    finally:
        s.encerrar()
        print("=" * 64)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
diag_bloqueio.py - Descobre DE FATO quem está causando o bloqueio 205.

Pergunta para cada câmera iCSee, PELA SESSÃO QUE JÁ ESTÁ ABERTA
(sessao_xm.py), sem fazer nenhum login novo:
  1. o REGISTRO INTERNO da câmera (OPLogQuery): logins, saídas, falhas,
     reinícios... com data/hora (é o "histórico" que a própria câmera guarda);
  2. o relógio da câmera (porta 34567) comparado com o do PC;
  3. o relógio do ONVIF (pergunta SEM senha) comparado com o do PC.
     O login do vídeo (ONVIF) usa a hora do PC: se a câmera estiver com a
     hora muito diferente, ela pode recusar a senha e contar como erro.

Uso (com o INICIAR_SESSAO.bat aberto):
    python ferramentas\\diag_bloqueio.py              últimas 48 h
    python ferramentas\\diag_bloqueio.py --horas 168  última semana

O resultado completo fica em diag_bloqueio\\<cam>_<data>.json (me mande).
"""
import json
import os
import re
import socket
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PASTA, "app"))   # o codigo fica em app/
sys.path.append(PASTA)                           # config.py

import cliente_xm  # noqa: E402
import config  # noqa: E402

LOG_QUERY = 1442
TIME_QUERY = 1452
FORMATO = "%Y-%m-%d %H:%M:%S"
PASTA_SAIDA = os.path.join(PASTA, "diag_bloqueio")
SUSPEITOS = re.compile(r"log|fail|err|lock|senha|pass|user|reboot|restart|boot|ip|net", re.I)


def cameras():
    for n in range(2, 10):
        ip = getattr(config, "CAM{}_IP".format(n), None)
        if ip and getattr(config, "CAM{}_XM".format(n), True):
            yield "cam{}".format(n), ip, getattr(config, "CAM{}_PORTA_ONVIF".format(n), 8899) or 8899


def cmd(s, msgid, nome, extra=None, timeout=10.0):
    corpo = {"Name": nome, "SessionID": "0x%08X" % s.session}
    if extra:
        corpo.update(extra)
    return s.comando(msgid, corpo, timeout=timeout)


def relogio_34567(s):
    r = cmd(s, TIME_QUERY, "OPTimeQuery")
    try:
        return datetime.strptime((r or {}).get("OPTimeQuery", ""), FORMATO)
    except ValueError:
        return None


def relogio_onvif_utc(ip, porta):
    """GetSystemDateAndTime é público no ONVIF: não manda senha nenhuma."""
    corpo = ('<?xml version="1.0" encoding="UTF-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
             '<s:Body><GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/></s:Body></s:Envelope>')
    req = urllib.request.Request("http://{}:{}/onvif/device_service".format(ip, porta), data=corpo.encode(),
                                 headers={"Content-Type": "application/soap+xml; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    bloco = re.search(r"UTCDateTime>(.*?)</[\w-]*:?UTCDateTime", xml, re.S)
    if not bloco:
        return None, "resposta sem UTCDateTime"

    def campo(nome):
        m = re.search(r"<[\w-]*:?{}>(\d+)</".format(nome), bloco.group(1))
        return int(m.group(1)) if m else 0
    try:
        return datetime(campo("Year"), campo("Month"), campo("Day"), campo("Hour"), campo("Minute"),
                        campo("Second"), tzinfo=timezone.utc), None
    except ValueError as e:
        return None, str(e)


def le_registro(s, horas):
    """Lê o registro interno da câmera, paginando. Retorna (entradas, respostas_brutas, erro)."""
    fim = datetime.now()
    inicio = fim - timedelta(hours=horas)
    entradas, brutas, posicao = [], [], 0
    for _ in range(40):                       # no máximo 40 páginas
        r = cmd(s, LOG_QUERY, "OPLogQuery", {"OPLogQuery": {
            "BeginTime": inicio.strftime(FORMATO), "EndTime": fim.strftime(FORMATO),
            "LogPosition": posicao, "Type": "LogAll"}}, timeout=12)
        if r is None:
            return entradas, brutas, "a câmera não respondeu à consulta do registro"
        brutas.append(r)
        if r.get("Ret") not in (100, 515):
            if entradas:
                break
            return entradas, brutas, "a câmera recusou a consulta (Ret {})".format(r.get("Ret"))
        pagina = r.get("OPLogQuery") or []
        if not isinstance(pagina, list) or not pagina:
            break
        novas = [e for e in pagina if e not in entradas]
        if not novas:
            break
        entradas.extend(novas)
        ultima = pagina[-1].get("Position")
        if not isinstance(ultima, int) or ultima + 1 <= posicao:
            break
        posicao = ultima + 1
        time.sleep(0.2)
    return entradas, brutas, None


def ip_deste_pc(ip_camera):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as u:
            u.connect((ip_camera, 34567))
            return u.getsockname()[0]
    except OSError:
        return "?"


def quem(e):
    """'admin,DVRIP-Web:192.168.3.56,205' -> ('192.168.3.56', 'DVRIP-Web', '205')"""
    d = str(e.get("Data", ""))
    ip = re.search(r":(\d+\.\d+\.\d+\.\d+)", d)
    codigo = re.search(r",(\d{3})$", d)
    tipo = re.search(r"(DVRIP-[\w]+|ONVIF|RTSP)", d)
    return (ip.group(1) if ip else "-"), (tipo.group(1) if tipo else "-"), (codigo.group(1) if codigo else None)


def linha(e):
    return "  {:<19}  {:<22} {:<10} {}".format(str(e.get("Time", "")), str(e.get("Type", "")),
                                               str(e.get("User", "")), str(e.get("Data", "")))


def main():
    horas = 48
    if "--horas" in sys.argv:
        try:
            horas = int(sys.argv[sys.argv.index("--horas") + 1])
        except (IndexError, ValueError):
            print("Use: --horas 48")
            return
    if not cliente_xm.sessao_rodando():
        print("A sessão das câmeras não está rodando. Abra o INICIAR_SESSAO.bat e rode de novo.")
        print("(Esta ferramenta NÃO faz login: ela pergunta pela sessão que já está aberta.)")
        return
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    agora_pc = datetime.now()
    agora_utc = datetime.now(timezone.utc)
    print("Hora do PC: {}  (UTC {})".format(agora_pc.strftime(FORMATO), agora_utc.strftime(FORMATO)))

    for cid, ip, porta_onvif in cameras():
        print("\n" + "=" * 70)
        print(" {}  ({})".format(cid, ip))
        print("=" * 70)
        s = cliente_xm.SessaoRemota(cid, ip)
        st = s.status()
        print("Sessão 34567: {}{}".format(st.get("estado"), " - " + st["erro"] if st.get("erro") else ""))
        resultado = {"cid": cid, "ip": ip, "quando": agora_pc.strftime(FORMATO), "sessao": st}

        hora_onvif, erro_onvif = relogio_onvif_utc(ip, porta_onvif)
        if hora_onvif:
            dif = (hora_onvif - agora_utc).total_seconds()
            aviso = "  <<< DIFERENÇA GRANDE: o login do vídeo (ONVIF) pode falhar" if abs(dif) > 60 else ""
            print("Relógio ONVIF (UTC): {}  diferença para o PC: {:+.0f} s{}".format(
                hora_onvif.strftime(FORMATO), dif, aviso))
            resultado["onvif_utc"] = hora_onvif.strftime(FORMATO)
            resultado["onvif_diferenca_s"] = dif
        else:
            print("Relógio ONVIF: não consegui ler ({})".format(erro_onvif))

        if st.get("estado") != "conectada":
            print("A câmera não está logada na sessão: sem registro interno agora.")
            print("(Se for 205, tire da tomada, espere ficar verde e rode de novo: o registro sobrevive.)")
        else:
            try:
                hora_cam = relogio_34567(s)
                if hora_cam:
                    dif = (hora_cam - agora_pc).total_seconds()
                    print("Relógio da câmera (34567): {}  diferença para o PC: {:+.0f} s".format(
                        hora_cam.strftime(FORMATO), dif))
                    resultado["camera_hora"] = hora_cam.strftime(FORMATO)
                    resultado["camera_diferenca_s"] = dif
                entradas, brutas, erro = le_registro(s, horas)
                resultado["registro"] = entradas
                resultado["respostas_brutas"] = brutas[:3]
                if erro:
                    print("Registro interno: " + erro)
                    if brutas:
                        print("  resposta: " + json.dumps(brutas[0], ensure_ascii=False)[:400])
                else:
                    entradas.sort(key=lambda e: e.get("Position", 0))      # ordem real (o relógio pula nos resets)
                    print("Registro interno: {} entradas nas últimas {} h".format(len(entradas), horas))
                    meu_ip = ip_deste_pc(ip)
                    print("IP deste PC: {}".format(meu_ip))
                    recusados = [e for e in entradas if e.get("Type") == "LogIn" and quem(e)[2]]
                    print("\n  LOGINS RECUSADOS ({}):  203 = senha errada, 205 = usuário bloqueado".format(len(recusados)))
                    for e in recusados:
                        print(linha(e) + ("   <<< ESTE PC" if quem(e)[0] == meu_ip else ""))
                    acessos = Counter((quem(e)[0], str(e.get("User")), quem(e)[1]) for e in entradas
                                      if e.get("Type") == "LogIn")
                    print("\n  Quem entrou na câmera (IP / usuário / meio: vezes):")
                    for (ipq, usu, meio), n in acessos.most_common(15):
                        print("    {:<16} {:<8} {:<18} {:>4}x{}".format(ipq, usu, meio, n,
                                                                     "   <<< ESTE PC" if ipq == meu_ip else ""))
                    resets = [e for e in entradas if e.get("Type") in ("AccountRestore", "RestoreConfig")]
                    if resets:
                        print("\n  Resets de fábrica: {}".format(", ".join(str(e.get("Time")) for e in resets
                                                                          if e.get("Type") == "RestoreConfig")))
                    tipos = Counter(str(e.get("Type")) for e in entradas)
                    print("  por tipo: " + ", ".join("{} x{}".format(t, n) for t, n in tipos.most_common()))
                    destaque = [e for e in entradas if SUSPEITOS.search(json.dumps(e, ensure_ascii=False))]
                    print("\n  Logins / falhas / reinícios (mais recentes no fim, até 60):")
                    for e in destaque[-60:]:
                        print(linha(e))
                    if not destaque:
                        print("  (nenhum) - últimas 20 entradas de qualquer tipo:")
                        for e in entradas[-20:]:
                            print(linha(e))
            except (ConnectionError, Exception) as e:  # noqa: BLE001
                print("Erro ao consultar: {}".format(e))
                resultado["erro"] = str(e)

        arq = os.path.join(PASTA_SAIDA, "{}_{}.json".format(cid, agora_pc.strftime("%Y%m%d_%H%M%S")))
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)
        print("\nCompleto em: " + arq)


if __name__ == "__main__":
    main()

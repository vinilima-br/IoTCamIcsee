# -*- coding: utf-8 -*-
"""
ferramentas/teste_durabilidade_elsys.py  -  A sessão forjada dura quanto tempo?

Forja a sessão (material atual de ferramentas\\elsys_<ip>_*) e a mantém viva com
keepalive, lendo uma config a cada minuto. Mostra se a sessão cai (o SID muda =
reconectou). Deixe rodando 20-30 min.

Também diz, de cara, se a chave da última captura ainda está no revezamento:
se "não achou", a chave já rotacionou (faça uma captura nova).

pip install pycryptodome.  INICIAR_SESSAO.bat FECHADO.
   python ferramentas\\teste_durabilidade_elsys.py 192.168.3.119
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import elsys_xm

MINUTOS = 30


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.3.119"
    print("=" * 60)
    print(" DURABILIDADE DA SESSÃO  %s" % ip)
    print("=" * 60)
    s = elsys_xm.ElsysSessao("dur", ip)
    s.iniciar()
    print("forjando (procurando a chave da captura)...")
    if not s.aguardar(90):
        print("\n[X] não forjou em 90s: a chave da última captura JÁ rotacionou.")
        print("    => o revezamento é rápido. Faça uma captura nova (PCAPdroid) e")
        print("       me mande, que eu atualizo o material. Isso já é um dado importante.")
        s.encerrar()
        return
    t0 = time.time()
    sid0 = s.session
    quedas = 0
    print("\n[OK] sessão viva. SID inicial=0x%X. Vou vigiar por %d min...\n" % (sid0, MINUTOS))
    try:
        while time.time() - t0 < MINUTOS * 60:
            time.sleep(60)
            mins = int((time.time() - t0) / 60)
            try:
                v = s.ler("fVideo.Volume")
            except Exception:
                v = None
            sid = s.session
            caiu = ""
            if not s.conectada or v is None:
                caiu = " <-- SEM RESPOSTA"
            if sid != sid0:
                quedas += 1
                caiu += " <-- SID MUDOU (sessão caiu e re-forjou)"
                sid0 = sid
            print("  +%2dmin: conectada=%s SID=0x%X vol_ok=%s%s"
                  % (mins, s.conectada, sid, v is not None, caiu))
    except KeyboardInterrupt:
        pass
    finally:
        dur = int((time.time() - t0) / 60)
        print("\n" + "-" * 60)
        print(" Vigiou %d min. Quedas/reconexões detectadas: %d" % (dur, quedas))
        if quedas == 0:
            print(" => a sessão AGUENTOU o período inteiro. Keepalive segura: o emulador")
            print("    só precisaria realimentar após reboot/queda de rede. Vale a pena.")
        else:
            print(" => a sessão caiu %d vez(es). Me manda o log que a gente decide o plano." % quedas)
        s.encerrar()


if __name__ == "__main__":
    main()

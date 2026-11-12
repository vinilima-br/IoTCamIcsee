# -*- coding: utf-8 -*-
"""
ferramentas/teste_elsys_cam.py  -  Testa uma camera Elsys pelo elsys_xm.py.

Forja a sessao, FALA (tom de teste ou um arquivo) e pisca a LUZ BRANCA (o
"alerta" das Elsys). Use para validar cada camera antes de ligar no servidor.

pip install pycryptodome.  Com o INICIAR_SESSAO.bat fechado:
    python ferramentas\\teste_elsys_cam.py 192.168.3.119
    python ferramentas\\teste_elsys_cam.py 192.168.3.118 sons\\rosto_Acesso_liberado_Vini.wav
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import elsys_xm


def main():
    if len(sys.argv) < 2:
        print("uso: python ferramentas\\teste_elsys_cam.py <IP> [arquivo_audio]")
        return
    ip = sys.argv[1]
    arq = sys.argv[2] if len(sys.argv) > 2 else None

    print("=" * 60)
    print(" TESTE ELSYS  %s" % ip)
    print("=" * 60)
    s = elsys_xm.ElsysSessao("teste", ip)
    s.iniciar()
    print("forjando (procurando a chave da captura, aguarde até ~2min)...")
    if not s.aguardar(130):
        print("[X] nao forjou: %s" % (s.ultimo_erro or "chave nao apareceu"))
        print("    Rode de novo (o revezamento é sorte a cada conexão). Se insistir em")
        print("    não cair, a captura pode ter envelhecido — faça uma nova.")
        s.encerrar()
        return
    print("[OK] sessao forjada. SID=0x%X\n" % s.session)
    try:
        print("-> FALAR (fique perto da camera)...")
        if arq:
            s.falar_arquivo(arq)
        else:
            s.falar(elsys_xm.gera_tom(2.0), "tom")
        print("   ok.\n")
        time.sleep(0.5)

        print("-> LUZ BRANCA liga por 4s (olhe a camera)...")
        s.set_alerta(True)
        time.sleep(4)
        s.set_alerta(False)
        print("   apagou.\n")

        print("saiu som e acendeu a luz? Me conta.")
    finally:
        s.encerrar()


if __name__ == "__main__":
    main()

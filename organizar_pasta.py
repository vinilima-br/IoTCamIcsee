# -*- coding: utf-8 -*-
"""
organizar_pasta.py  -  Arruma a pasta do projeto (NÃO apaga nada).

Deixa na raiz só o que o sistema usa e MOVE o resto (scripts de teste
das etapas 1 a 31, servidores antigos, fotos de teste, dumps) para a
pasta historico/. Tudo continua lá se um dia precisar consultar.

Uso:
   python organizar_pasta.py              # só MOSTRA o que vai mover
   python organizar_pasta.py --executar   # move de verdade

Antes de executar: feche o servidor (Ctrl+C).
"""
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))

# O que fica na raiz (o sistema em uso)
FICA_NA_RAIZ = {
    "servidor.py", "config.py", "camera_xm.py", "biblioteca_sons.py", "gerar_voz.py",
    "gravador.py", "ptz.py", "onvif_rtsp.py", "detector_pessoas.py",
    "requirements.txt", "INICIAR.bat", "GUIA_COMPLETO.md", "organizar_pasta.py",
    "sessao_estado.json", "xm_fala_modo.json", "xm_luz_alerta.json", "xm_sd_modo.json", "sd_xm.py",
}
PASTAS_DO_SISTEMA = {"ferramentas", "templates", "sons", "fotos", "gravacoes", "modelos", "sd_baixados",
                     "historico", "__pycache__", ".git", ".venv", "venv"}
TEMPLATES_EM_USO = {"painel.html"}


def destino(nome):
    ext = os.path.splitext(nome)[1].lower()
    if ext == ".py":
        return "scripts"
    if ext in (".jpg", ".jpeg", ".png", ".wav", ".mp3"):
        return "imagens_e_sons"
    if ext in (".md", ".txt"):
        return "anotacoes"
    return "dados"


def planeja():
    plano = []
    for nome in sorted(os.listdir(BASE)):
        caminho = os.path.join(BASE, nome)
        if os.path.isdir(caminho) or nome in FICA_NA_RAIZ:
            continue
        plano.append((caminho, os.path.join(BASE, "historico", destino(nome), nome)))
    pasta_tpl = os.path.join(BASE, "templates")
    if os.path.isdir(pasta_tpl):
        for nome in sorted(os.listdir(pasta_tpl)):
            if nome not in TEMPLATES_EM_USO and os.path.isfile(os.path.join(pasta_tpl, nome)):
                plano.append((os.path.join(pasta_tpl, nome),
                              os.path.join(BASE, "historico", "templates", nome)))
    for nome in sorted(os.listdir(BASE)):
        if os.path.isdir(os.path.join(BASE, nome)) and nome not in PASTAS_DO_SISTEMA:
            print("  (pasta '%s' não é do sistema - deixei onde está)" % nome)
    return plano


def livre(caminho):
    if not os.path.exists(caminho):
        return caminho
    base, ext = os.path.splitext(caminho)
    n = 2
    while os.path.exists("%s_%d%s" % (base, n, ext)):
        n += 1
    return "%s_%d%s" % (base, n, ext)


def main():
    executar = "--executar" in sys.argv
    faltando = [f for f in ("servidor.py", "camera_xm.py", os.path.join("templates", "painel.html"))
                if not os.path.exists(os.path.join(BASE, f))]
    if faltando:
        print("Faltam arquivos do sistema novo: %s. Não vou mover nada." % ", ".join(faltando))
        return

    plano = planeja()
    print("=" * 60)
    print(" ORGANIZAR PASTA  -  %d arquivo(s) para historico/" % len(plano))
    print("=" * 60)
    for origem, dest in plano:
        print("  %-38s -> %s" % (os.path.relpath(origem, BASE), os.path.relpath(os.path.dirname(dest), BASE)))
    if not plano:
        print("  Nada a mover: a pasta já está organizada.")
        return
    if not executar:
        print("\nNada foi movido ainda. Confira a lista e rode:")
        print("   python organizar_pasta.py --executar")
        return

    registro = []
    for origem, dest in plano:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        dest = livre(dest)
        shutil.move(origem, dest)
        registro.append("%s -> %s" % (os.path.relpath(origem, BASE), os.path.relpath(dest, BASE)))
    with open(os.path.join(BASE, "historico", "MOVIDOS.txt"), "a", encoding="utf-8") as f:
        f.write("\n# %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        f.write("\n".join(registro) + "\n")
    print("\nPronto: %d arquivo(s) movido(s). Lista em historico\\MOVIDOS.txt" % len(registro))
    print("Suba o servidor:  python servidor.py   (ou dois cliques no INICIAR.bat)")


if __name__ == "__main__":
    main()

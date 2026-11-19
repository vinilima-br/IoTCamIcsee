# -*- coding: utf-8 -*-
"""
caminhos.py - onde fica cada coisa que o sistema GERA (fora do Git).

Tudo que o painel cria sozinho mora em  dados\\  (e não mais solto na raiz):
    dados\\estado\\      escolhas e estado: lentes, PTZ invertido, modos de alerta/fala/SD,
                        sessão das câmeras, senha do painel (acesso.json)
    dados\\backups\\     cópias do config.py feitas ao adicionar/remover câmera
    dados\\cache\\       vozes geradas, arquivos temporários do Python
    dados\\janela\\      o que a janela do painel lembra (navegador interno)
    dados\\diagnosticos\\ resultados das ferramentas de diagnóstico
    dados\\gestao\\      banco e fotos da gestão de pessoas (pasta gestao/)

Ao abrir pela 1ª vez depois da atualização, cada arquivo antigo da raiz é MOVIDO para cá
sozinho (mesmo disco: instantâneo). Se não der para mover, continua usando o antigo.
"""
import os

PASTA_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(PASTA_BASE, "dados")
PASTA_ESTADO = os.path.join(PASTA_DADOS, "estado")
PASTA_BACKUPS = os.path.join(PASTA_DADOS, "backups")
PASTA_CACHE = os.path.join(PASTA_DADOS, "cache")


def _migra(antigo, novo):
    """Move arquivo ou pasta antiga para o lugar novo. Se as duas PASTAS já existem
    (ex.: dados\cache criada antes), junta: leva o que ainda não existe no novo e
    apaga a antiga se ficar vazia. Nunca sobrescreve nada que já está no novo."""
    if not os.path.exists(antigo):
        return
    try:
        if not os.path.exists(novo):
            os.makedirs(os.path.dirname(novo), exist_ok=True)
            os.replace(antigo, novo)
        elif os.path.isdir(antigo) and os.path.isdir(novo):
            for nome in os.listdir(antigo):
                _migra(os.path.join(antigo, nome), os.path.join(novo, nome))
            if not os.listdir(antigo):
                os.rmdir(antigo)
    except OSError:
        pass                          # em uso / sem permissão: segue com o antigo


def _escolhe(antigo, novo):
    if antigo and os.path.exists(antigo) and not os.path.exists(novo):
        return antigo                 # não conseguiu mover: não perde o que já estava salvo
    return novo


def arquivo(relativo, antigo=None):
    """dados\\<relativo>; traz da raiz o arquivo `antigo` (caminho relativo à raiz), se houver."""
    novo = os.path.join(PASTA_DADOS, relativo)
    velho = os.path.join(PASTA_BASE, antigo) if antigo else None
    if velho:
        _migra(velho, novo)
    os.makedirs(os.path.dirname(novo), exist_ok=True)
    return _escolhe(velho, novo)


def estado(nome):
    """dados\\estado\\<nome> (ex.: "lentes_deteccao.json"), trazendo o da raiz se ainda estiver lá."""
    return arquivo(os.path.join("estado", nome), antigo=nome)


def pasta(relativo, antiga=None):
    """dados\\<relativo> (pasta), trazendo a pasta `antiga` da raiz se houver. Já cria a pasta."""
    novo = os.path.join(PASTA_DADOS, relativo)
    velho = os.path.join(PASTA_BASE, antiga) if antiga else None
    if velho:
        _migra(velho, novo)
    escolhido = _escolhe(velho, novo)
    os.makedirs(escolhido, exist_ok=True)
    return escolhido


def backup_config(caminho_config, carimbo, manter=15):
    """Caminho novo para a cópia do config.py em dados\\backups\\ (guarda só as `manter` últimas)."""
    os.makedirs(PASTA_BACKUPS, exist_ok=True)
    base = os.path.join(PASTA_BACKUPS, os.path.basename(caminho_config) + ".bak_" + carimbo)
    destino, n = base, 2
    while os.path.exists(destino):
        destino, n = "{}_{}".format(base, n), n + 1
    try:
        antigos = sorted((f for f in os.listdir(PASTA_BACKUPS) if f.startswith(os.path.basename(caminho_config) + ".bak_")),
                         key=lambda f: os.path.getmtime(os.path.join(PASTA_BACKUPS, f)))
        for f in antigos[:max(0, len(antigos) - (manter - 1))]:
            os.remove(os.path.join(PASTA_BACKUPS, f))
    except OSError:
        pass
    return destino

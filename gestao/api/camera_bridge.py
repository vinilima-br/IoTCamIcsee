import base64
import hashlib
import importlib
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from datetime import datetime
from http.server import ThreadingHTTPServer

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .database import DATA_DIR, SessionLocal
from .models import LogAcesso, Pessoa, VisitantePrestador


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = DATA_DIR / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
FACE_SYNC_STATE = DATA_DIR / "face_sync.json"


class CameraBridge:
    def __init__(self):
        self.module = None
        self.error = "Integração ainda não inicializada"
        self._loop = None
        self._face_lock = threading.Lock()
        self._camera_alert_thread = None
        self._seen_alert_seq = 0
        self._session_module = None
        self._session_http = None
        # Modo embutido: a gestão roda DENTRO do servidor.py (painel), que já é o dono
        # das câmeras. Aqui só se pendura nos objetos dele - não abre câmera nem sessão.
        self.embedded = False
        self._embedded_module = None
        self.auth = None          # função (scope ASGI) -> bool; None = sem porteiro (modo isolado)

    @property
    def available(self):
        return self.module is not None

    def attach(self, camera_app, auth=None):
        """Liga o modo embutido: usa o servidor.py que já está rodando."""
        self.embedded = True
        self._embedded_module = camera_app
        self.auth = auth

    def _start_embedded(self):
        camera_app = self._embedded_module
        try:
            for recognizer in camera_app.RECS.values():
                self._install_face_callback(recognizer)
            self.module = camera_app
            self.sync_existing_faces()
            self.error = ""
            self._camera_alert_thread = threading.Thread(
                target=self._watch_camera_alerts, daemon=True, name="gestao-camera-alerts"
            )
            self._camera_alert_thread.start()
            logger.info("Gestão embutida no painel: %d câmera(s).", len(camera_app.CAMERAS))
        except Exception as exc:
            self.error = "Falha ao ligar a gestão às câmeras do painel: {}".format(exc)
            logger.exception(self.error)

    def start(self, loop):
        self._loop = loop
        if self.embedded:
            self._start_embedded()
            return
        app_dir = PROJECT_ROOT / "app"
        if not (PROJECT_ROOT / "config.py").is_file():
            self.error = "Arquivo config.py ausente na raiz; configure as câmeras antes de conectá-las."
            logger.warning(self.error)
            return
        if not app_dir.is_dir():
            self.error = "Diretório app/ do sistema de câmeras não encontrado."
            logger.error(self.error)
            return

        sys.path.insert(0, str(app_dir))
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            importlib.import_module("config")
            self._start_camera_session()
            camera_app = importlib.import_module("servidor")
            self._liga_logs(camera_app)
            camera_app.monta_cameras()
            camera_app.monta_rostos()
            for recognizer in camera_app.RECS.values():
                self._install_face_callback(recognizer)
            self.module = camera_app
            self.sync_existing_faces()
            camera_app.iniciar_tudo()
            self.error = ""
            self._camera_alert_thread = threading.Thread(
                target=self._watch_camera_alerts, daemon=True, name="portaria-camera-alerts"
            )
            self._camera_alert_thread.start()
            logger.info("Integração de câmeras iniciada: %d câmera(s).", len(camera_app.CAMERAS))
        except Exception as exc:
            self.error = "Falha ao iniciar a integração com câmeras: {}".format(exc)
            logger.exception(self.error)

    def _liga_logs(self, camera_app):
        """Mesmo log em arquivo do painel (logs/central_DATA.log) e um log próprio
        da Portaria (logs/portaria_DATA.log): antes tudo ia só para a janela preta."""
        try:
            liga = getattr(camera_app, "_liga_log_arquivo", None)
            if liga is not None:
                liga()
            pasta = PROJECT_ROOT / "logs"
            pasta.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(
                pasta / "portaria_{}.log".format(time.strftime("%Y-%m-%d")), encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logging.getLogger().addHandler(handler)
        except Exception:
            logger.exception("Não foi possível ligar o log em arquivo da Portaria")

    def _start_camera_session(self):
        session_module = importlib.import_module("sessao_xm")
        client_module = importlib.import_module("cliente_xm")
        self._session_module = session_module
        if client_module.sessao_rodando():
            logger.info("Reutilizando a sessão de câmeras iCSee já ativa.")
            return
        http = ThreadingHTTPServer(("127.0.0.1", session_module.PORTA), session_module.Pedido)
        http.daemon_threads = True
        session_module.monta_sessoes()
        for camera_session in session_module.SESSOES.values():
            camera_session.iniciar()
        self._session_http = http
        threading.Thread(target=http.serve_forever, daemon=True, name="portaria-xm-session").start()
        logger.info("Sessão local das câmeras iniciada dentro do processo da Portaria.")

    def stop(self):
        if self.embedded:
            return                # câmeras e sessões são do painel
        if self._session_http is not None:
            self._session_http.shutdown()
            self._session_http.server_close()
            self._session_http = None
        if self._session_module is not None:
            self._session_module.encerrar()

    def sync_existing_faces(self):
        if not self.module or not self.module.MOTOR_ROSTO or not self.module.MOTOR_ROSTO.disponivel:
            return
        with SessionLocal() as db:
            people = [
                (person.face_id_externo or person.nome, person.foto_path, person.ativo)
                for person in db.query(Pessoa).all()
            ]
            visitors = [
                (
                    "VISITANTE-{}-{}".format(visitor.id, visitor.nome),
                    visitor.foto_path,
                    visitor.status_atual == "no_condominio" and self._visitor_in_validity(visitor),
                )
                for visitor in db.query(VisitantePrestador).all()
            ]
        for name, image_path, allowed in people + visitors:
            if image_path:
                result = self.sync_face(name, image_path, allowed)
                if not result["ok"]:
                    logger.warning("Sincronização facial pendente para %s: %s", name, result["error"])
            else:
                self.remove_face(name)

    @staticmethod
    def _visitor_in_validity(visitor):
        if visitor.tipo_acesso != "recorrente":
            return True
        if not visitor.validade_inicio or not visitor.validade_fim:
            return False
        now = datetime.now()
        start = _local_naive(visitor.validade_inicio)
        end = _local_naive(visitor.validade_fim)
        return start <= now <= end

    @staticmethod
    def _read_face_sync_state():
        if not FACE_SYNC_STATE.exists():
            return {}
        try:
            return json.loads(FACE_SYNC_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("Arquivo de estado da sincronização facial inválido")
            return {}

    @staticmethod
    def _write_face_sync_state(state):
        temporary = FACE_SYNC_STATE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, FACE_SYNC_STATE)

    def _install_face_callback(self, recognizer):
        original = recognizer._registra

        def registra(event, frame):
            original(event, frame)
            try:
                self._record_face_event(recognizer.cid, event, frame)
            except Exception:
                logger.exception("Falha ao persistir evento facial da câmera %s", recognizer.cid)

        recognizer._registra = registra

    def _record_face_event(self, camera_id, event, frame):
        snapshot_path = self.save_snapshot(frame, "face-{}".format(camera_id))
        recognized_name = event.get("nome")
        with SessionLocal() as db:
            person = None
            visitor = None
            if recognized_name:
                if recognized_name.startswith("PESSOA-"):
                    try:
                        person_id = int(recognized_name.split("-", 2)[1])
                    except (IndexError, ValueError):
                        person_id = None
                    if person_id is not None:
                        person = db.query(Pessoa).filter(
                            Pessoa.id == person_id
                        ).first()
                if person is None and recognized_name.startswith("VISITANTE-"):
                    try:
                        visitor_id = int(recognized_name.split("-", 2)[1])
                    except (IndexError, ValueError):
                        visitor_id = None
                    if visitor_id is not None:
                        visitor = db.query(VisitantePrestador).filter(
                            VisitantePrestador.id == visitor_id,
                        ).first()
                if person is None and visitor is None and not recognized_name.startswith(("PESSOA-", "VISITANTE-")):
                    person = db.query(Pessoa).filter(
                        Pessoa.nome.ilike(recognized_name), Pessoa.ativo.is_(True)
                    ).first()
            visitor_valid = visitor is not None and visitor.status_atual == "no_condominio"
            if visitor_valid and visitor.tipo_acesso == "recorrente":
                now = datetime.now()
                visitor_valid = (
                    visitor.validade_inicio is not None
                    and visitor.validade_fim is not None
                    and _local_naive(visitor.validade_inicio) <= now <= _local_naive(visitor.validade_fim)
                )
            # Rosto que o reconhecimento conhece (cadastrado no painel) mas que ainda não tem
            # ficha aqui na gestão: vale a decisão do reconhecimento (antes virava "desconhecido").
            known_face = bool(recognized_name)
            no_record = person is None and visitor is None
            if no_record:
                authorized = event.get("status") == "permitido" and known_face
            else:
                authorized = event.get("status") == "permitido" and (
                    person is not None and person.ativo or visitor_valid
                )
            event_type = "reconhecimento_facial" if (known_face or not no_record) else "alerta_desconhecido"
            if authorized:
                status_out = "permitido"
            elif known_face or not no_record:
                status_out = "negado"
            else:
                status_out = "desconhecido"
            log_entry = LogAcesso(
                pessoa_id=person.id if person else None,
                visitante_id=visitor.id if visitor else None,
                camera_id=camera_id,
                tipo_evento=event_type,
                metodo="facial",
                snapshot_path=snapshot_path,
                detalhes={
                    "status_reconhecimento": event.get("status"),
                    "nome_reconhecido": recognized_name,
                    "motivo": event.get("motivo"),
                    "similaridade": event.get("sim"),
                    "aguardando_liberacao_manual": authorized,
                    "sem_ficha_na_gestao": no_record and known_face,
                    "unidade_id": person.unidade_id if person else (visitor.unidade_destino_id if visitor else None),
                },
            )
            db.add(log_entry)
            db.commit()
            db.refresh(log_entry)
            payload = {
                "type": "face_recognition",
                "data": {
                    "log_id": log_entry.id,
                    "pessoa_id": person.id if person else None,
                    "visitante_id": visitor.id if visitor else None,
                    "nome": person.nome if person else (visitor.nome if visitor else (recognized_name or "Desconhecido")),
                    "unidade_id": person.unidade_id if person else (visitor.unidade_destino_id if visitor else None),
                    "tipo_vinculo": person.tipo if person else ("visitante" if visitor else ("cadastrado só no reconhecimento (sem ficha na gestão)" if known_face else None)),
                    "sem_ficha": no_record and known_face,
                    "foto_path": person.foto_path if person else (visitor.foto_path if visitor else None),
                    "veiculos": [
                        {"id": vehicle.id, "placa": vehicle.placa, "modelo": vehicle.modelo}
                        for vehicle in person.veiculos
                    ] if person else [],
                    "status": status_out,
                    "tipo_evento": event_type,
                    "camera_id": camera_id,
                    "snapshot_path": snapshot_path,
                    "timestamp": log_entry.timestamp.isoformat() if log_entry.timestamp else None,
                    "similaridade": event.get("sim"),
                },
            }
        self.publish_from_thread(payload)

    def _watch_camera_alerts(self):
        while self.module is not None:
            try:
                for event in list(self.module.ALERTAS_CAM):
                    sequence = event.get("seq", 0)
                    if sequence <= self._seen_alert_seq:
                        continue
                    self._seen_alert_seq = sequence
                    payload = {
                        "type": "camera_alert",
                        "data": {
                            "camera_id": event.get("cid"),
                            "event": event.get("evento"),
                            "description": event.get("texto"),
                            "status": event.get("status"),
                            "timestamp": event.get("hora"),
                        },
                    }
                    camera_id = event.get("cid")
                    camera = self.module.CAMERAS.get(camera_id)
                    snapshot_path = None
                    if camera is not None:
                        with camera.cond:
                            frame = camera.frame.copy() if camera.frame is not None else None
                        if frame is not None:
                            try:
                                snapshot_path = self.save_snapshot(frame, "alert-{}".format(camera_id))
                            except (OSError, RuntimeError):
                                logger.exception("Falha ao salvar snapshot do alerta da câmera %s", camera_id)
                    with SessionLocal() as db:
                        log_entry = LogAcesso(
                            camera_id=camera_id,
                            tipo_evento="alerta_camera",      # detecção da própria câmera (não é rosto desconhecido)
                            metodo="camera",
                            snapshot_path=snapshot_path,
                            detalhes={
                                "evento_camera": event.get("evento"),
                                "descricao": event.get("texto"),
                                "status_camera": event.get("status"),
                            },
                        )
                        db.add(log_entry)
                        db.commit()
                    payload["data"]["snapshot_path"] = snapshot_path
                    payload["data"]["log_id"] = log_entry.id
                    self.publish_from_thread(payload)
            except Exception:
                logger.exception("Falha ao encaminhar alertas das câmeras")
            time.sleep(0.25)

    def set_event_publisher(self, publisher):
        self._publisher = publisher

    def publish_from_thread(self, payload):
        publisher = getattr(self, "_publisher", None)
        if publisher is not None and self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(publisher, payload)

    def camera(self, camera_id):
        if not self.module:
            raise HTTPException(status_code=503, detail=self.error)
        camera = self.module.CAMERAS.get(camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Câmera não encontrada")
        return camera

    def stream(self, camera_id):
        camera = self.camera(camera_id)

        def generate():
            frame_id = 0
            with camera.cond:
                camera.espectadores += 1
            try:
                while True:
                    frame_id, jpeg = camera.proximo_jpeg(frame_id)
                    if jpeg is None:
                        continue
                    yield (
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(jpeg)).encode("ascii")
                        + b"\r\n\r\n"
                        + jpeg
                        + b"\r\n"
                    )
            finally:
                with camera.cond:
                    camera.espectadores = max(0, camera.espectadores - 1)

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    def save_snapshot(self, frame, prefix="snapshot"):
        import cv2

        encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not encoded:
            raise RuntimeError("Não foi possível codificar o snapshot")
        name = "{}-{}-{}.jpg".format(prefix, time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex)
        path = SNAPSHOT_DIR / name
        if not cv2.imwrite(os.fspath(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise OSError("Não foi possível salvar o snapshot em {}".format(path))
        return path.relative_to(DATA_DIR).as_posix()

    def snapshot(self, camera_id):
        camera = self.camera(camera_id)
        with camera.cond:
            frame = camera.frame.copy() if camera.frame is not None else None
        if frame is None:
            raise HTTPException(status_code=503, detail="A câmera ainda não forneceu um quadro")
        try:
            return self.save_snapshot(frame, "manual-{}".format(camera_id))
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def control_ptz(self, camera_id, pan, tilt, zoom):
        self.camera(camera_id)
        control = self.module.PTZS.get(camera_id)
        if control is None:
            raise HTTPException(status_code=404, detail="PTZ indisponível para esta câmera")
        try:
            control.mover(pan=pan, tilt=tilt, zoom=zoom)
        except self.module.mod_ptz.ErroPTZ as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def stop_ptz(self, camera_id):
        self.camera(camera_id)
        control = self.module.PTZS.get(camera_id)
        if control is None:
            raise HTTPException(status_code=404, detail="PTZ indisponível para esta câmera")
        try:
            control.parar()
        except self.module.mod_ptz.ErroPTZ as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def audio(self, camera_id, action, audio_base64=None):
        self.camera(camera_id)
        session = self.module.XMS.get(camera_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Áudio bidirecional indisponível para esta câmera")
        try:
            if action == "stop":
                session.parar_fala()
                return {"ok": True, "action": action}
            if action != "speak" or not audio_base64:
                raise HTTPException(status_code=400, detail="Envie action='speak' com áudio G.711 A-law em base64 ou action='stop'")
            try:
                audio_data = base64.b64decode(audio_base64, validate=True)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Áudio base64 inválido") from exc
            if not audio_data:
                raise HTTPException(status_code=400, detail="O áudio enviado está vazio")
            iniciadas, erros = self.module._toca_em([camera_id], audio_data, "portaria: microfone")
            if not iniciadas:
                raise HTTPException(status_code=503, detail=erros.get(camera_id) or "A câmera não aceitou o áudio")
            return {"ok": True, "action": action}
        except self.module.camera_xm.ErroXM as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def audio_stream(self, camera_id):
        camera = self.camera(camera_id)
        url = camera.urls.get(1) or camera.urls.get(0)
        if not url:
            raise HTTPException(status_code=503, detail="Câmera sem URL RTSP disponível")
        ffmpeg = self.module.gravador.acha_ffmpeg()
        if not ffmpeg:
            raise HTTPException(status_code=503, detail="FFmpeg não encontrado no sistema de câmeras")
        import subprocess

        process = subprocess.Popen(
            [
                ffmpeg, "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
                "-probesize", "32", "-analyzeduration", "0", "-rtsp_transport", "tcp",
                "-i", url, "-vn", "-ac", "1", "-c:a", "aac", "-b:a", "48k",
                "-flush_packets", "1", "-f", "adts", "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        def generate():
            try:
                while True:
                    chunk = process.stdout.read(1024)
                    if not chunk:
                        break
                    yield chunk
            finally:
                process.kill()
                process.wait(timeout=3)

        return StreamingResponse(generate(), media_type="audio/aac", headers={"Cache-Control": "no-store"})

    def audio_pcm_stream(self, camera_id):
        """Áudio cru (PCM 16 bits, 8 kHz mono) para a Web Audio API — o mesmo do /audio_pcm do painel."""
        camera = self.camera(camera_id)
        url = camera.urls.get(1) or camera.urls.get(0)
        if not url:
            raise HTTPException(status_code=503, detail="Câmera sem endereço RTSP (ainda conectando?)")
        ffmpeg = self.module.gravador.acha_ffmpeg()
        if not ffmpeg:
            raise HTTPException(status_code=503, detail="FFmpeg não encontrado no sistema de câmeras")
        import subprocess

        process = subprocess.Popen(
            [
                ffmpeg, "-loglevel", "error", "-fflags", "nobuffer", "-flags", "low_delay",
                "-probesize", "32", "-analyzeduration", "0", "-rtsp_transport", "tcp",
                "-i", url, "-vn", "-ac", "1", "-ar", "8000",
                "-flush_packets", "1", "-f", "s16le", "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        def generate():
            try:
                while True:
                    chunk = process.stdout.read(512)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    process.kill()
                    process.wait(timeout=3)
                except Exception:
                    pass

        return StreamingResponse(
            generate(), media_type="application/octet-stream", headers={"Cache-Control": "no-cache, no-store"}
        )

    def speak_text(self, camera_id, text):
        """Fala um texto na câmera (voz gerada), pelo mesmo caminho do "Falar" do painel."""
        self.camera(camera_id)
        if camera_id not in self.module.XMS:
            raise HTTPException(status_code=404, detail="Esta câmera não tem alto-falante pela sessão 34567")
        text = (text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Digite o que a câmera deve falar")
        if len(text) > 500:
            raise HTTPException(status_code=400, detail="Texto muito longo (máximo de 500 letras)")
        gerar_voz = importlib.import_module("gerar_voz")
        camera_xm = self.module.camera_xm
        os.makedirs(self.module.PASTA_TTS, exist_ok=True)
        destino = os.path.join(self.module.PASTA_TTS, "voz_portaria.wav")
        try:
            voz, aviso_voz = gerar_voz.gerar_detalhado(text, destino)
            alaw = camera_xm.arquivo_para_alaw(destino)
        except (gerar_voz.ErroVoz, camera_xm.ErroXM) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        iniciadas, erros = self.module._toca_em([camera_id], alaw, "portaria: " + text[:30])
        if not iniciadas:
            raise HTTPException(status_code=503, detail=erros.get(camera_id) or "A câmera não aceitou o áudio")
        return {"ok": True, "voz": voz, "aviso_voz": aviso_voz, "segundos": round(len(alaw) / 8000.0, 1)}

    def sync_face(self, name, image_path, allowed=True):
        if not self.module or not self.module.MOTOR_ROSTO or not self.module.MOTOR_ROSTO.disponivel:
            return {"ok": False, "error": self.error or "Reconhecimento facial indisponível"}
        import cv2

        name = self.module.rosto_servidor.ia.nome_seguro(name)
        absolute_path = (DATA_DIR / image_path).resolve()
        if not absolute_path.is_relative_to(DATA_DIR.resolve()) or not absolute_path.is_file():
            return {"ok": False, "error": "Caminho da foto de cadastro inválido"}
        image = cv2.imread(os.fspath(absolute_path))
        if image is None:
            return {"ok": False, "error": "Foto facial não pôde ser lida"}
        try:
            with self._face_lock:
                motor = self.module.MOTOR_ROSTO
                digest = hashlib.sha256(absolute_path.read_bytes()).hexdigest()
                state = self._read_face_sync_state()
                if (
                    name in motor.banco.pessoas
                    and state.get(name) == {"sha256": digest, "permitido": bool(allowed)}
                ):
                    return {"ok": True, "error": None}
                # mesma regra do "Por foto" do painel: 1 rosto só, grande o bastante, + variações
                try:
                    amostras, _avisos = motor.amostras_da_foto(image)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
                if name in motor.banco.pessoas:
                    motor.remove(name)
                motor.banco.adiciona(name, amostras, permitido=allowed)
                motor.banco.carrega()
                state[name] = {"sha256": digest, "permitido": bool(allowed)}
                self._write_face_sync_state(state)
            return {"ok": True, "error": None}
        except Exception as exc:
            logger.exception("Falha ao sincronizar face %s com o banco de câmeras", name)
            return {"ok": False, "error": str(exc)}

    def remove_face(self, name):
        if not self.module or not self.module.MOTOR_ROSTO or not self.module.MOTOR_ROSTO.disponivel:
            return {"ok": False, "error": self.error or "Reconhecimento facial indisponível"}
        try:
            name = self.module.rosto_servidor.ia.nome_seguro(name)
            with self._face_lock:
                motor = self.module.MOTOR_ROSTO
                if name in motor.banco.pessoas:
                    motor.remove(name)
                state = self._read_face_sync_state()
                state.pop(name, None)
                self._write_face_sync_state(state)
            return {"ok": True, "error": None}
        except Exception as exc:
            logger.exception("Falha ao remover face %s do banco de câmeras", name)
            return {"ok": False, "error": str(exc)}

    def _camera_ips(self):
        """IP de cada câmera, lido da mesma lista do config.py que o painel usa."""
        if getattr(self, "_ips", None) is None:
            ips = {}
            try:
                config = importlib.import_module("config")
                lista = config.cameras() if hasattr(config, "cameras") else getattr(config, "CAMERAS", [])
                for item in lista:
                    if item.get("cid"):
                        ips[item["cid"]] = item.get("ip")
            except Exception:
                logger.exception("Não foi possível ler os IPs das câmeras no config.py")
            self._ips = ips
        return self._ips

    def status(self):
        if not self.module:
            return {"available": False, "error": self.error, "cameras": []}
        ips = self._camera_ips()
        try:
            lentes_salvas = self.module.lentes.le()
        except Exception:
            lentes_salvas = {}
        cameras = []
        for camera_id in self.module.ORDEM:
            camera = self.module.CAMERAS[camera_id]
            recognizer = self.module.RECS.get(camera_id)
            lente = getattr(recognizer, "lente", None) or lentes_salvas.get(camera_id, "ambas")
            cameras.append({
                "id": camera_id,
                "ip": ips.get(camera_id),
                "lente_det": lente,
                "tem_som": camera_id in self.module.XMS,
                **camera.status(),
            })
        return {"available": True, "error": None, "cameras": cameras}


camera_bridge = CameraBridge()


def _local_naive(value):
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value

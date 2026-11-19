import asyncio
import logging
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models
from .camera_bridge import camera_bridge
from .database import DATA_DIR, engine, get_db
from .models import Encomenda, LogAcesso, Pessoa, Unidade, Veiculo, VisitantePrestador
from .schemas import EncomendaIn, LogIn, PessoaIn, RetiradaIn, UnidadeIn, VeiculoIn, VisitanteIn


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
FOTOS_DIR = DATA_DIR / "fotos_cadastro"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
FOTOS_DIR.mkdir(parents=True, exist_ok=True)
SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024


class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self.lock:
            self.active.add(websocket)

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            self.active.discard(websocket)

    async def broadcast(self, payload):
        message = jsonable_encoder(payload)
        async with self.lock:
            clients = tuple(self.active)
        if not clients:
            return
        results = await asyncio.gather(
            *(client.send_json(message) for client in clients),
            return_exceptions=True,
        )
        failed = [client for client, result in zip(clients, results) if isinstance(result, Exception)]
        if failed:
            async with self.lock:
                self.active.difference_update(failed)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Conexão WebSocket removida após falha de envio: %s", result)


manager = ConnectionManager()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    loop = asyncio.get_running_loop()
    camera_bridge.set_event_publisher(lambda payload: asyncio.create_task(manager.broadcast(payload)))
    await asyncio.to_thread(camera_bridge.start, loop)
    try:
        yield
    finally:
        if camera_bridge.module and not camera_bridge.embedded:
            try:
                camera_bridge.module.encerrar_xm()
            except Exception:
                logger.exception("Falha ao encerrar as sessões das câmeras")
        try:
            camera_bridge.stop()
        except Exception:
            logger.exception("Falha ao encerrar a sessão de câmera iniciada pela Portaria")


app = FastAPI(title="Portaria Administrativa", version="1.0.0", lifespan=lifespan)


class PorteiroGestao:
    """Modo embutido (dentro do painel): só entra quem pode entrar no painel.
    Mesmo critério do painel: o próprio PC entra direto; outro aparelho precisa da
    senha do painel (o cookie de login do painel vale aqui também, é o mesmo endereço)."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        checker = camera_bridge.auth
        if scope["type"] not in ("http", "websocket") or checker is None or checker(scope):
            await self.inner(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse({"detail": "Entre com a senha do painel de câmeras."}, status_code=401)
        await response(scope, receive, send)


app.add_middleware(PorteiroGestao)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _commit(db: Session):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Registro duplicado ou relacionado a outros dados; confira os vínculos e valores únicos.",
        ) from exc


def _get_or_404(db: Session, model, item_id: int):
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Registro não encontrado")
    return item


def _paged(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _camera_face_sync(name, foto_path, allowed=True):
    if not foto_path:
        return None
    result = camera_bridge.sync_face(name, foto_path, allowed)
    if not result["ok"]:
        logger.warning("Sincronização facial pendente para %s: %s", name, result["error"])
    return result


def _visitor_face_name(visitor):
    return "VISITANTE-{}-{}".format(visitor.id, visitor.nome)


def _visitor_face_allowed(visitor):
    if visitor.tipo_acesso != "recorrente":
        return True
    start, end = visitor.validade_inicio, visitor.validade_fim
    if start is None or end is None:
        return False
    now = datetime.now()
    if start.tzinfo:
        start = start.astimezone().replace(tzinfo=None)
    if end.tzinfo:
        end = end.astimezone().replace(tzinfo=None)
    return start <= now <= end


def _photo_path(path: str | None):
    if not path:
        return None
    candidate = (DATA_DIR / path).resolve()
    photos_root = FOTOS_DIR.resolve()
    if not candidate.is_relative_to(photos_root) or not candidate.is_file():
        raise HTTPException(status_code=400, detail="Caminho de foto inválido ou inexistente")
    return candidate


@app.get("/api/health")
def health():
    return {"ok": True, "service": "portaria", "cameras": camera_bridge.status()}


@app.get("/api/resumo")
def summary(db: Session = Depends(get_db)):
    active_visitors = db.query(VisitantePrestador).filter(
        VisitantePrestador.status_atual == "no_condominio"
    ).count()
    pending_packages = db.query(Encomenda).filter(Encomenda.status == "pendente").count()
    return {"visitantes_ativos": active_visitors, "encomendas_pendentes": pending_packages}


@app.get("/api/unidades")
def list_units(
    q: str | None = None,
    ativo: bool | None = None,
    page_size: int = Query(default=100, ge=1, le=100),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    query = db.query(Unidade)
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(Unidade.bloco.ilike(term), Unidade.numero.ilike(term)))
    if ativo is not None:
        query = query.filter(Unidade.ativo.is_(ativo))
    return _paged(query.order_by(Unidade.bloco, Unidade.numero), page, page_size)


@app.post("/api/unidades", status_code=201)
async def create_unit(payload: UnidadeIn, db: Session = Depends(get_db)):
    item = Unidade(**payload.model_dump())
    db.add(item)
    _commit(db)
    await manager.broadcast({"type": "unit_created", "data": {"id": item.id}})
    return item


@app.get("/api/unidades/{item_id}")
def get_unit(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Unidade, item_id)


@app.put("/api/unidades/{item_id}")
async def update_unit(item_id: int, payload: UnidadeIn, db: Session = Depends(get_db)):
    item = _get_or_404(db, Unidade, item_id)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    _commit(db)
    await manager.broadcast({"type": "unit_updated", "data": {"id": item.id}})
    return item


@app.delete("/api/unidades/{item_id}", status_code=204)
async def delete_unit(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, Unidade, item_id)
    db.delete(item)
    _commit(db)
    await manager.broadcast({"type": "unit_deleted", "data": {"id": item_id}})


@app.get("/api/pessoas")
def list_people(
    q: str | None = None,
    unidade_id: int | None = Query(default=None, gt=0),
    ativo: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Pessoa)
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(Pessoa.nome.ilike(term), Pessoa.cpf.ilike(term), Pessoa.telefone.ilike(term)))
    if unidade_id:
        query = query.filter(Pessoa.unidade_id == unidade_id)
    if ativo is not None:
        query = query.filter(Pessoa.ativo.is_(ativo))
    return _paged(query.order_by(Pessoa.nome), page, page_size)


@app.post("/api/pessoas", status_code=201)
async def create_person(payload: PessoaIn, db: Session = Depends(get_db)):
    if payload.foto_path:
        _photo_path(payload.foto_path)
    item = Pessoa(**payload.model_dump())
    db.add(item)
    db.flush()
    item.face_id_externo = "PESSOA-{}-{}".format(item.id, item.nome)
    _commit(db)
    camera_sync = _camera_face_sync(item.face_id_externo, item.foto_path, item.ativo) if item.foto_path else None
    await manager.broadcast({"type": "person_created", "data": {"id": item.id, "nome": item.nome}})
    result = jsonable_encoder(item)
    result["camera_sync"] = camera_sync
    return result


@app.get("/api/pessoas/{item_id}")
def get_person(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Pessoa, item_id)


@app.put("/api/pessoas/{item_id}")
async def update_person(item_id: int, payload: PessoaIn, db: Session = Depends(get_db)):
    if payload.foto_path:
        _photo_path(payload.foto_path)
    item = _get_or_404(db, Pessoa, item_id)
    old_face_id, old_name, old_photo, old_active = item.face_id_externo, item.nome, item.foto_path, item.ativo
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    item.face_id_externo = "PESSOA-{}-{}".format(item.id, item.nome)
    _commit(db)
    camera_sync = None
    if old_photo and (old_photo != item.foto_path or old_face_id != item.face_id_externo):
        camera_bridge.remove_face(old_face_id or old_name)
    if item.foto_path and (old_photo != item.foto_path or old_name != item.nome or old_active != item.ativo):
        camera_sync = _camera_face_sync(item.face_id_externo, item.foto_path, item.ativo)
    elif old_active and not item.ativo:
        camera_bridge.remove_face(old_face_id or old_name)
    await manager.broadcast({"type": "person_updated", "data": {"id": item.id, "nome": item.nome}})
    result = jsonable_encoder(item)
    result["camera_sync"] = camera_sync
    return result


@app.delete("/api/pessoas/{item_id}", status_code=204)
async def delete_person(item_id: int, db: Session = Depends(get_db)):
    item = _get_or_404(db, Pessoa, item_id)
    camera_bridge.remove_face(item.face_id_externo or item.nome)
    db.delete(item)
    _commit(db)
    await manager.broadcast({"type": "person_deleted", "data": {"id": item_id}})


@app.post("/api/pessoas/{item_id}/entrada", status_code=201)
async def register_person_entry(item_id: int, db: Session = Depends(get_db)):
    person = _get_or_404(db, Pessoa, item_id)
    if not person.ativo:
        raise HTTPException(status_code=409, detail="Pessoa inativa não pode registrar entrada")
    log_entry = LogAcesso(
        pessoa_id=person.id,
        tipo_evento="entrada",
        metodo="manual",
        detalhes={"origem": "ação rápida da portaria"},
    )
    db.add(log_entry)
    _commit(db)
    await manager.broadcast({"type": "access_log_created", "data": jsonable_encoder(log_entry)})
    return log_entry


@app.get("/api/veiculos")
def list_vehicles(
    q: str | None = None,
    unidade_id: int | None = Query(default=None, gt=0),
    pessoa_id: int | None = Query(default=None, gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Veiculo)
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(Veiculo.placa.ilike(term), Veiculo.modelo.ilike(term)))
    if unidade_id:
        query = query.filter(Veiculo.unidade_id == unidade_id)
    if pessoa_id:
        query = query.filter(Veiculo.pessoa_id == pessoa_id)
    return _paged(query.order_by(Veiculo.placa), page, page_size)


@app.post("/api/veiculos", status_code=201)
async def create_vehicle(payload: VeiculoIn, db: Session = Depends(get_db)):
    item = Veiculo(**payload.model_dump())
    db.add(item)
    _commit(db)
    await manager.broadcast({"type": "vehicle_created", "data": {"id": item.id, "placa": item.placa}})
    return item


@app.get("/api/veiculos/{item_id}")
def get_vehicle(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Veiculo, item_id)


@app.put("/api/veiculos/{item_id}")
async def update_vehicle(item_id: int, payload: VeiculoIn, db: Session = Depends(get_db)):
    item = _get_or_404(db, Veiculo, item_id)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    _commit(db)
    await manager.broadcast({"type": "vehicle_updated", "data": {"id": item.id, "placa": item.placa}})
    return item


@app.delete("/api/veiculos/{item_id}", status_code=204)
async def delete_vehicle(item_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, Veiculo, item_id))
    _commit(db)
    await manager.broadcast({"type": "vehicle_deleted", "data": {"id": item_id}})


@app.get("/api/visitantes")
def list_visitors(
    q: str | None = None,
    unidade_destino_id: int | None = Query(default=None, gt=0),
    status_atual: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(VisitantePrestador)
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(VisitantePrestador.nome.ilike(term), VisitantePrestador.documento.ilike(term)))
    if unidade_destino_id:
        query = query.filter(VisitantePrestador.unidade_destino_id == unidade_destino_id)
    if status_atual:
        if status_atual not in {"no_condominio", "saiu"}:
            raise HTTPException(status_code=400, detail="status_atual inválido")
        query = query.filter(VisitantePrestador.status_atual == status_atual)
    return _paged(query.order_by(VisitantePrestador.id.desc()), page, page_size)


@app.post("/api/visitantes", status_code=201)
async def create_visitor(payload: VisitanteIn, db: Session = Depends(get_db)):
    if payload.foto_path:
        _photo_path(payload.foto_path)
    item = VisitantePrestador(**payload.model_dump())
    db.add(item)
    _commit(db)
    camera_sync = _camera_face_sync(
        _visitor_face_name(item), item.foto_path,
        item.status_atual == "no_condominio" and _visitor_face_allowed(item),
    ) if item.foto_path else None
    log_entry = LogAcesso(
        visitante_id=item.id,
        tipo_evento="entrada",
        metodo="manual",
        detalhes={"origem": "registro de visitante", "unidade_destino_id": item.unidade_destino_id},
    )
    db.add(log_entry)
    _commit(db)
    await manager.broadcast({"type": "visitor_created", "data": {"id": item.id, "nome": item.nome}})
    result = jsonable_encoder(item)
    result["camera_sync"] = camera_sync
    return result


@app.get("/api/visitantes/{item_id}")
def get_visitor(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, VisitantePrestador, item_id)


@app.put("/api/visitantes/{item_id}")
async def update_visitor(item_id: int, payload: VisitanteIn, db: Session = Depends(get_db)):
    if payload.foto_path:
        _photo_path(payload.foto_path)
    item = _get_or_404(db, VisitantePrestador, item_id)
    old_photo, old_status, old_name = item.foto_path, item.status_atual, item.nome
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    _commit(db)
    camera_sync = None
    if old_photo and (old_photo != item.foto_path or old_name != item.nome):
        camera_bridge.remove_face("VISITANTE-{}-{}".format(item.id, old_name))
    if item.foto_path and (old_photo != item.foto_path or old_status != item.status_atual):
        camera_sync = _camera_face_sync(
            _visitor_face_name(item), item.foto_path,
            item.status_atual == "no_condominio" and _visitor_face_allowed(item),
        )
    elif item.foto_path and old_name != item.nome:
        camera_sync = _camera_face_sync(
            _visitor_face_name(item), item.foto_path,
            item.status_atual == "no_condominio" and _visitor_face_allowed(item),
        )
    if old_status != item.status_atual:
        db.add(LogAcesso(
            visitante_id=item.id,
            tipo_evento="saida" if item.status_atual == "saiu" else "entrada",
            metodo="manual",
            detalhes={"origem": "atualização do cadastro"},
        ))
        _commit(db)
    await manager.broadcast({"type": "visitor_updated", "data": {"id": item.id}})
    result = jsonable_encoder(item)
    result["camera_sync"] = camera_sync
    return result


@app.post("/api/visitantes/{item_id}/saida")
async def visitor_exit(item_id: int, db: Session = Depends(get_db)):
    visitor = _get_or_404(db, VisitantePrestador, item_id)
    if visitor.status_atual != "no_condominio":
        raise HTTPException(status_code=409, detail="Visitante já consta como saiu")
    visitor.status_atual = "saiu"
    if visitor.foto_path:
        _camera_face_sync(_visitor_face_name(visitor), visitor.foto_path, allowed=False)
    log_entry = LogAcesso(
        visitante_id=visitor.id,
        tipo_evento="saida",
        metodo="manual",
        detalhes={"origem": "baixa rápida de saída"},
    )
    db.add(log_entry)
    _commit(db)
    await manager.broadcast({"type": "visitor_exited", "data": {"id": visitor.id}})
    return visitor


@app.post("/api/visitantes/{item_id}/entrada", status_code=201)
async def visitor_entry(item_id: int, db: Session = Depends(get_db)):
    visitor = _get_or_404(db, VisitantePrestador, item_id)
    if not _visitor_face_allowed(visitor):
        raise HTTPException(status_code=409, detail="A validade ou o status não permite registrar entrada")
    if visitor.status_atual == "saiu" and visitor.tipo_acesso != "recorrente":
        raise HTTPException(status_code=409, detail="Visitante avulso já encerrou o acesso")
    visitor.status_atual = "no_condominio"
    if visitor.foto_path:
        _camera_face_sync(_visitor_face_name(visitor), visitor.foto_path, allowed=True)
    log_entry = LogAcesso(
        visitante_id=visitor.id,
        tipo_evento="entrada",
        metodo="manual",
        detalhes={"origem": "ação rápida de acesso"},
    )
    db.add(log_entry)
    _commit(db)
    await manager.broadcast({"type": "visitor_entered", "data": {"id": visitor.id}})
    return visitor


@app.delete("/api/visitantes/{item_id}", status_code=204)
async def delete_visitor(item_id: int, db: Session = Depends(get_db)):
    visitor = _get_or_404(db, VisitantePrestador, item_id)
    camera_bridge.remove_face(_visitor_face_name(visitor))
    db.delete(visitor)
    _commit(db)
    await manager.broadcast({"type": "visitor_deleted", "data": {"id": item_id}})


@app.get("/api/encomendas")
def list_packages(
    q: str | None = None,
    unidade_id: int | None = Query(default=None, gt=0),
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Encomenda)
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(Encomenda.codigo_rastreio.ilike(term), Encomenda.transportadora.ilike(term)))
    if unidade_id:
        query = query.filter(Encomenda.unidade_id == unidade_id)
    if status:
        if status not in {"pendente", "retirada"}:
            raise HTTPException(status_code=400, detail="status inválido")
        query = query.filter(Encomenda.status == status)
    return _paged(query.order_by(Encomenda.data_recebimento.desc()), page, page_size)


@app.post("/api/encomendas", status_code=201)
async def create_package(payload: EncomendaIn, db: Session = Depends(get_db)):
    item = Encomenda(**payload.model_dump(exclude_none=True))
    db.add(item)
    _commit(db)
    await manager.broadcast({"type": "package_created", "data": {"id": item.id, "unidade_id": item.unidade_id}})
    return item


@app.get("/api/encomendas/{item_id}")
def get_package(item_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, Encomenda, item_id)


@app.put("/api/encomendas/{item_id}")
async def update_package(item_id: int, payload: EncomendaIn, db: Session = Depends(get_db)):
    item = _get_or_404(db, Encomenda, item_id)
    for key, value in payload.model_dump(exclude_none=True).items():
        setattr(item, key, value)
    _commit(db)
    await manager.broadcast({"type": "package_updated", "data": {"id": item.id}})
    return item


@app.post("/api/encomendas/{item_id}/retirada")
async def package_pickup(item_id: int, payload: RetiradaIn, db: Session = Depends(get_db)):
    item = _get_or_404(db, Encomenda, item_id)
    if item.status != "pendente":
        raise HTTPException(status_code=409, detail="Encomenda já foi retirada")
    item.status = "retirada"
    item.retirado_por = payload.retirado_por.strip()
    item.data_retirada = datetime.now()
    _commit(db)
    await manager.broadcast({"type": "package_picked_up", "data": {"id": item.id, "unidade_id": item.unidade_id}})
    return item


@app.delete("/api/encomendas/{item_id}", status_code=204)
async def delete_package(item_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, Encomenda, item_id))
    _commit(db)
    await manager.broadcast({"type": "package_deleted", "data": {"id": item_id}})


@app.get("/api/logs")
def list_logs(
    inicio: datetime | None = None,
    fim: datetime | None = None,
    unidade_id: int | None = Query(default=None, gt=0),
    q: str | None = None,
    tipo_evento: str | None = None,
    metodo: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(LogAcesso)
    if unidade_id or q:
        query = query.outerjoin(Pessoa, LogAcesso.pessoa_id == Pessoa.id).outerjoin(
            VisitantePrestador, LogAcesso.visitante_id == VisitantePrestador.id
        )
    if inicio:
        query = query.filter(LogAcesso.timestamp >= inicio)
    if fim:
        query = query.filter(LogAcesso.timestamp <= fim)
    if unidade_id:
        query = query.filter(or_(Pessoa.unidade_id == unidade_id, VisitantePrestador.unidade_destino_id == unidade_id))
    if q:
        term = "%{}%".format(q.strip())
        query = query.filter(or_(Pessoa.nome.ilike(term), VisitantePrestador.nome.ilike(term)))
    if tipo_evento:
        if tipo_evento not in {"entrada", "saida", "alerta_desconhecido", "reconhecimento_facial"}:
            raise HTTPException(status_code=400, detail="tipo_evento inválido")
        query = query.filter(LogAcesso.tipo_evento == tipo_evento)
    if metodo:
        if metodo not in {"facial", "manual", "placa"}:
            raise HTTPException(status_code=400, detail="metodo inválido")
        query = query.filter(LogAcesso.metodo == metodo)
    return _paged(query.order_by(LogAcesso.timestamp.desc()), page, page_size)


@app.post("/api/logs", status_code=201)
async def create_log(payload: LogIn, db: Session = Depends(get_db)):
    item = LogAcesso(**payload.model_dump(exclude_none=True))
    db.add(item)
    _commit(db)
    await manager.broadcast({"type": "access_log_created", "data": jsonable_encoder(item)})
    return item


@app.get("/api/arquivos/{categoria}/{nome}")
def get_file(categoria: str, nome: str):
    if categoria not in {"fotos_cadastro", "snapshots"}:
        raise HTTPException(status_code=404, detail="Categoria de arquivo não encontrada")
    base = (DATA_DIR / categoria).resolve()
    target = (base / nome).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(target)


@app.post("/api/arquivos/cadastro", status_code=201)
async def upload_photo(file: UploadFile = File(...)):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_IMAGE_TYPES or file.content_type != ALLOWED_IMAGE_TYPES[extension]:
        raise HTTPException(status_code=415, detail="Envie uma imagem JPG, PNG ou WEBP válida")
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo vazio")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="A imagem deve ter no máximo 8 MB")
    valid_signature = (
        extension in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff")
        or extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")
        or extension == ".webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    )
    if not valid_signature:
        raise HTTPException(status_code=415, detail="O conteúdo enviado não corresponde a uma imagem válida")
    filename = "{}{}".format(uuid.uuid4().hex, extension)
    target = FOTOS_DIR / filename
    try:
        target.write_bytes(content)
    except OSError as exc:
        logger.exception("Falha ao salvar foto de cadastro")
        raise HTTPException(status_code=500, detail="Não foi possível salvar a imagem") from exc
    relative = "fotos_cadastro/{}".format(filename)
    return {"foto_path": relative, "url": "/api/arquivos/{}".format(relative.replace("/", "/", 1))}


@app.get("/api/cameras")
def list_cameras():
    return camera_bridge.status()


@app.get("/api/cameras/{camera_id}/stream")
def camera_stream(camera_id: str):
    return camera_bridge.stream(camera_id)


@app.post("/api/cameras/{camera_id}/snapshot")
async def camera_snapshot(camera_id: str):
    path = camera_bridge.snapshot(camera_id)
    payload = {"type": "camera_snapshot", "data": {"camera_id": camera_id, "snapshot_path": path}}
    await manager.broadcast(payload)
    return {"snapshot_path": path, "url": "/api/arquivos/{}".format(path)}


@app.post("/api/cameras/{camera_id}/ptz")
def camera_ptz(camera_id: str, payload: dict):
    if payload.get("action") == "stop":
        camera_bridge.stop_ptz(camera_id)
        return {"ok": True}
    try:
        pan = float(payload.get("pan", 0))
        tilt = float(payload.get("tilt", 0))
        zoom = float(payload.get("zoom", 0))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="pan, tilt e zoom devem ser numéricos") from exc
    if any(value < -1 or value > 1 for value in (pan, tilt, zoom)):
        raise HTTPException(status_code=422, detail="pan, tilt e zoom devem estar entre -1 e 1")
    camera_bridge.control_ptz(camera_id, pan, tilt, zoom)
    return {"ok": True}


@app.get("/api/cameras/{camera_id}/audio")
def camera_audio_stream(camera_id: str):
    return camera_bridge.audio_stream(camera_id)


@app.post("/api/cameras/{camera_id}/audio")
def camera_audio_control(camera_id: str, payload: dict):
    action = payload.get("action")
    if action not in {"speak", "stop"}:
        raise HTTPException(status_code=422, detail="action deve ser 'speak' ou 'stop'")
    return camera_bridge.audio(camera_id, action, payload.get("audio_base64"))


@app.get("/api/cameras/{camera_id}/audio_pcm")
def camera_audio_pcm(camera_id: str):
    return camera_bridge.audio_pcm_stream(camera_id)


@app.post("/api/cameras/{camera_id}/falar")
def camera_speak_text(camera_id: str, payload: dict):
    return camera_bridge.speak_text(camera_id, payload.get("texto"))


@app.websocket("/ws/eventos")
async def websocket_events(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)


bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
dist_dir = bundle_root / "gestao" / "ui" / "dist"
assets_dir = dist_dir / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/", include_in_schema=False)
def spa_index():
    index = dist_dir / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend ainda não foi compilado")
    return FileResponse(index)


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "ws/")):
        raise HTTPException(status_code=404, detail="Rota não encontrada")
    if not dist_dir.is_dir():
        raise HTTPException(status_code=404, detail="Frontend ainda não foi compilado")
    target = (dist_dir / full_path).resolve()
    if target.is_relative_to(dist_dir.resolve()) and target.is_file():
        return FileResponse(target)
    index = dist_dir / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend ainda não foi compilado")
    return FileResponse(index)

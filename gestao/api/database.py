from pathlib import Path
import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


ROOT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
# Banco e fotos da gestão: dados/gestao/ (junto com o resto do que o sistema gera).
# A pasta antiga data/ é trazida sozinha na 1ª vez (se estiver em uso, segue usando a antiga).
_DATA_ANTIGA = ROOT_DIR / "data"
DATA_DIR = ROOT_DIR / "dados" / "gestao"
if _DATA_ANTIGA.is_dir() and not DATA_DIR.exists():
    try:
        DATA_DIR.parent.mkdir(parents=True, exist_ok=True)
        _DATA_ANTIGA.replace(DATA_DIR)
    except OSError:
        DATA_DIR = _DATA_ANTIGA
DATABASE_PATH = DATA_DIR / "portaria.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    "sqlite:///{}".format(DATABASE_PATH.as_posix()),
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def configure_sqlite(connection, _record):
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

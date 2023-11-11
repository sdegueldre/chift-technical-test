import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

pg_url = os.environ.get("POSTGRES_URL", "postgresql://username:password@postgres/chift_technical_test")

engine = create_engine(pg_url)
Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_session():
    db = Session()
    try:
        yield db
    finally:
        db.close()

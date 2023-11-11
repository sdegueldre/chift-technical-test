import os
from datetime import datetime
# FastAPI + DB access
from fastapi import FastAPI, Depends
from sqlalchemy import DateTime, Column, Integer, String
from sqlalchemy.dialects.postgresql import insert
from .database import Base, get_session, engine, Session
# Synchronization utilities
from apscheduler.schedulers.background import BackgroundScheduler
import httpx

odoo_url = os.environ.get("ODOO_SERVER_URL", "http://host.docker.internal:8069")
odoo_db_name = os.environ.get("ODOO_DB_NAME", "odoo")
odoo_username = os.environ.get("ODOO_USERNAME", "admin")
odoo_api_key = os.environ.get("ODOO_API_KEY", "admin")

class OdooContact(Base):
    __tablename__ = "odoo_contact"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(Integer, unique=True, index=True)
    email = Column(String)
    name = Column(String)
    write_date = Column(DateTime, index=True)

Base.metadata.create_all(bind=engine)

app = FastAPI()

@app.get("/contacts")
async def contacts(session = Depends(get_session)):
    return session.query(OdooContact).all()

@app.get("/contact/{contact_id}")
async def contact(contact_id, session = Depends(get_session)):
    return session.query(OdooContact).filter(OdooContact.id == contact_id).first()


@app.on_event("startup")
async def schedule_cron():
    scheduler = BackgroundScheduler()
    sync_odoo()
    scheduler.add_job(sync_odoo, 'interval', seconds=int(os.environ.get("SYNC_INTERVAL_SECONDS", "3600")))
    scheduler.start()

def sync_odoo():
    response = httpx.post(f"{odoo_url}/jsonrpc", json={
        "jsonrpc": "2.0",
        "params": {
            "service": "common",
            "method": "authenticate",
            "args": [
                odoo_db_name,
                odoo_username,
                odoo_api_key,
                ""
            ]
        },
        "id": 1
    }).json()
    if response.get("error"):
        print("Couldn't authenticate with the odoo server", response.get("error"))
        return
    uid = response.get("result")

    with Session() as session:
        last_updated_contact = session.query(OdooContact).order_by(OdooContact.write_date.desc()).first()
        # find the last write date that we accounted for, and update all records that have been
        # updated more recently than that.
        # Note that because Odoo returns datetimes truncated to the second, when many records are
        # created programmatically, for example because they are demo-data, they will keep being
        # returned and "synced" even though there has been no change.
        # TODO: use a limit and do this in batches in case there are lots of contacts to sync
        last_update = None
        if last_updated_contact:
            last_update = last_updated_contact.write_date

        response = httpx.post(f"{odoo_url}/jsonrpc", json={
            "jsonrpc": "2.0",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    odoo_db_name,
                    uid,
                    odoo_api_key,
                    "res.partner",
                    "search_read",
                    [],
                    {
                        "fields": ["name", "write_date", "email"],
                        # TODO: do we also want to sync archived contacts? Domain would need to account for that
                        "domain": [["write_date", ">=", str(last_update)]] if last_update else []
                    },
                ]
            },
            "id": 2
        }).json()
        if response.get("error"):
            print("An error occured when fetching the contacts,", response.get("error"))
            return
        contacts = response.get("result")
        for contact in contacts:
            contact["external_id"] = contact.pop("id")
            contact["write_date"] = datetime.fromisoformat(contact["write_date"])
            stmt = insert(OdooContact).values(contact)
            stmt = stmt.on_conflict_do_update(
                index_elements=["external_id"],
                set_=contact
            )
            # Possible improvement: bulk upsert with excluded
            session.execute(stmt)
        print(f"Created or updated {len(contacts)} contact(s)")
        session.commit()

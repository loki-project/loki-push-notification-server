from peewee import *
from const import SQLITE_DB
import os
from utils import *

db = SqliteDatabase(SQLITE_DB)


class BaseModel(Model):
    class Meta:
        database = db


class LastHash(BaseModel):
    hash_value = CharField(default="")
    expiration = IntegerField(default=0)


class Session(BaseModel):
    session_id = CharField(primary_key=True)
    last_hash = ForeignKeyField(LastHash, default=LastHash())
    swarm = TextField(default="")


class Token(BaseModel):
    device_token = CharField()
    session = ForeignKeyField(Session)


class LokiDatabase:
    def __init__(self):
        self.sqlite_db = db

    def create_tables(self):
        self.sqlite_db.create_tables([LastHash, Session, Token])

    def migration(self):
        pass

    def insert_token(self, session_id, token):
        self.sqlite_db.connect()
        session = Session.get(Session.session_id == session_id)
        if not session:
            session = Session.create(session_id=session_id)
        token_record = Token.create(device_token=token, session=session)
        self.sqlite_db.close()
        return token_record

    def remove_token(self, token):
        self.sqlite_db.connect()
        token_record = Token.get(Token.device_token == token)
        token_record.delete()
        self.sqlite_db.close()

    def get_all_session_ids(self):
        self.sqlite_db.connect()
        session_ids = []
        tokens = Token.select()
        for token in tokens:
            if token.session.session_id not in session_ids:
                session_ids.append(token.session.session_id)
        self.sqlite_db.close()
        return session_ids

    def get_tokens(self, session_id):
        self.sqlite_db.connect()
        tokens = []
        query = (Token.select(Token, Session).join(Session).where(Session.session_id == session_id))
        for token in query:
            tokens.append(token.device_token)
        self.sqlite_db.close()
        return tokens

    def get_last_hash(self, session_id):
        self.sqlite_db.connect()
        session = Session.get(Session.session_id == session_id)
        self.sqlite_db.close()
        return session.last_hash.hash_value

    def update_last_hash(self, session_id, hash_value, expiration):
        self.sqlite_db.connect()
        session = Session.get(Session.session_id == session_id)
        old_hash = session.last_hash
        if old_hash.expiration < process_expiration(expiration):
            old_hash.hash_value = hash_value
            old_hash.expiration = expiration
            old_hash.save()
        self.sqlite_db.close()

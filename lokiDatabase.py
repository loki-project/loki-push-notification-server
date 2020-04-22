from peewee import *
from const import *
import os, pickle


class LokiAPITarget:
    def __init__(self, address, port, id_key, encryption_key):
        self.address = 'https://' + address
        self.port = str(port)
        self.id_key = id_key
        self.encryption_key = encryption_key

    def __str__(self):
        return self.address + ':' + self.port


is_new_db = not os.path.isfile(SQLITE_DB)
db = SqliteDatabase(SQLITE_DB)


class BaseModel(Model):
    class Meta:
        database = db


class LastHash(BaseModel):
    hash_value = CharField(default="")
    expiration = IntegerField(default=0)


class Session(BaseModel):
    session_id = CharField(primary_key=True)
    last_hash = ForeignKeyField(LastHash)


class Token(BaseModel):
    device_token = CharField()
    session = ForeignKeyField(Session)


class RandomSnode(BaseModel):
    address = CharField()
    port = CharField()
    id_key = CharField()
    encryption_key = CharField()


class Swarm(BaseModel):
    address = CharField()
    port = CharField()
    id_key = CharField()
    encryption_key = CharField()
    session = ForeignKeyField(Session)


class LokiDatabase:
    __instance = None

    @staticmethod
    def get_instance():
        """ Static access method. """
        if LokiDatabase.__instance is None:
            LokiDatabase()
        return LokiDatabase.__instance

    def __init__(self):
        if LokiDatabase.__instance is not None:
            raise Exception("LokiDatabase is a singleton!")
        else:
            self.sqlite_db = db
            LokiDatabase.__instance = self

    def connect_db_if_needed(self):
        if self.sqlite_db.is_connection_usable():
            return
        self.sqlite_db.connect()

    def close_db_if_needed(self):
        if self.sqlite_db.is_closed():
            return
        self.sqlite_db.close()

    def create_tables(self):
        self.sqlite_db.create_tables([LastHash, Session, Token, RandomSnode, Swarm])

    def migration(self):
        self.connect_db_if_needed()
        pubkey_token_dict = {}
        self.create_tables()
        if os.path.isfile(PUBKEY_TOKEN_DB):
            with open(PUBKEY_TOKEN_DB, 'rb') as pubkey_token_db:
                pubkey_token_dict = dict(pickle.load(pubkey_token_db))
            pubkey_token_db.close()
        for session_id, tokens in pubkey_token_dict.items():
            last_hash = LastHash.create()
            session = Session.create(session_id=session_id, last_hash=last_hash)
            for token in tokens:
                Token.create(device_token=token, session=session)
        self.close_db_if_needed()

    def insert_token(self, session_id, token):
        self.connect_db_if_needed()
        session = Session.get_or_none(Session.session_id == session_id)
        if session is None:
            session = Session.create(session_id=session_id, last_hash=LastHash.create())
        token_record = Token.get_or_create(device_token=token, session=session)
        self.close_db_if_needed()
        return token_record

    def remove_token(self, token):
        self.connect_db_if_needed()
        token_record = Token.get_or_none(Token.device_token == token)
        if token_record:
            token_record.delete()
        self.close_db_if_needed()

    def get_valid_session_ids(self):
        self.connect_db_if_needed()
        session_ids = []
        tokens = Token.select()
        for token in tokens:
            if token.session.session_id not in session_ids:
                session_ids.append(token.session.session_id)
        self.close_db_if_needed()
        return session_ids

    def get_tokens(self, session_id):
        self.connect_db_if_needed()
        tokens = []
        query = (Token.select(Token, Session).join(Session).where(Session.session_id == session_id))
        for token in query:
            tokens.append(token.device_token)
        self.close_db_if_needed()
        return tokens

    def get_last_hash(self, session_id):
        self.connect_db_if_needed()
        session = Session.get_or_none(session_id=session_id)
        self.close_db_if_needed()
        if session:
            return session.last_hash.hash_value
        else:
            return ""

    def update_last_hash(self, session_id, hash_value, expiration):
        self.connect_db_if_needed()
        session = Session.get_or_none(Session.session_id == session_id)
        if session:
            old_hash = session.last_hash
            if old_hash.expiration < expiration:
                old_hash.hash_value = hash_value
                old_hash.expiration = expiration
                old_hash.save()
        self.close_db_if_needed()

    def get_random_snode_pool(self):
        random_snode_pool = []
        self.connect_db_if_needed()
        list_from_db = RandomSnode.select()
        for snode in list_from_db:
            target = LokiAPITarget(address=snode.address,
                                   port=snode.port,
                                   id_key=snode.id_key,
                                   encryption_key=snode.encryption_key)
            random_snode_pool.append(target)
        self.close_db_if_needed()
        return random_snode_pool

    def save_random_snodes(self, random_snode_pool):
        self.connect_db_if_needed()
        for target in random_snode_pool:
            RandomSnode.create(address=target.address,
                               port=target.port,
                               id_key=target.id_key,
                               encryption_key=target.encryption_key)
        self.close_db_if_needed()

    def get_swarms(self, session_id):
        swarms = []
        self.connect_db_if_needed()
        list_from_db = (Swarm.select(Swarm, Session).join(Session).where(Session.session_id == session_id))
        for snode in list_from_db:
            target = LokiAPITarget(address=snode.address,
                                   port=snode.port,
                                   id_key=snode.id_key,
                                   encryption_key=snode.encryption_key)
            swarms.append(target)
        self.close_db_if_needed()
        return swarms

    def save_swarms(self, session_id, swarms):
        self.connect_db_if_needed()
        session = Session.get_or_none(Session.session_id == session_id)
        if session:
            for target in swarms:
                Swarm.create(address=target.address,
                             port=target.port,
                             id_key=target.id_key,
                             encryption_key=target.encryption_key,
                             session=session)
        self.close_db_if_needed()

from flask import Flask, request, jsonify
from pushNotificationHandler import SilentPushNotificationHelper, NormalPushNotificationHelper
from const import *
from gevent.pywsgi import WSGIServer
from lokiLogger import LokiLogger
import urllib3
from lokiDatabase import *

urllib3.disable_warnings()

app = Flask(__name__)
logger = LokiLogger().logger
if is_new_db:
    LokiDatabase.get_instance().migration()
SPN_helper = SilentPushNotificationHelper(logger)
NPN_helper = NormalPushNotificationHelper(logger)


@app.route('/register', methods=[GET, POST])
def register():
    token = None
    pubkey = None
    response = jsonify({CODE: 0,
                        MSG: PARA_MISSING})

    if TOKEN in request.args:
        token = request.args[TOKEN]
        if PUBKEY in request.args:
            pubkey = request.args[PUBKEY]

    if request.json and TOKEN in request.json:
        token = request.json[TOKEN]
        if PUBKEY in request.json:
            pubkey = request.json[PUBKEY]

    if request.form and TOKEN in request.form:
        token = request.form[TOKEN]
        if PUBKEY in request.form:
            pubkey = request.form[PUBKEY]

    if token and pubkey:
        NPN_helper.update_token_pubkey_pair(token, pubkey)
        SPN_helper.disable_token(token)
        response = jsonify({CODE: 1,
                            MSG: SUCCESS})
    elif token:
        SPN_helper.update_token(token)
        NPN_helper.disable_token(token)
        response = jsonify({CODE: 1,
                            MSG: SUCCESS})
    return response


@app.route('/acknowledge_message_delivery', methods=[GET, POST])
def update_last_hash():
    last_hash = None
    pubkey = None
    expiration = None
    response = jsonify({CODE: 0,
                        MSG: PARA_MISSING})

    if LASTHASH in request.args:
        last_hash = request.args[LASTHASH]
        if PUBKEY in request.args:
            pubkey = request.args[PUBKEY]
        if EXPIRATION in request.args:
            expiration = request.args[EXPIRATION]

    if request.json and LASTHASH in request.json:
        last_hash = request.json[LASTHASH]
        if PUBKEY in request.json:
            pubkey = request.json[PUBKEY]
        if EXPIRATION in request.json:
            expiration = request.json[EXPIRATION]

    if request.form and LASTHASH in request.form:
        last_hash = request.form[LASTHASH]
        if PUBKEY in request.form:
            pubkey = request.form[PUBKEY]
        if EXPIRATION in request.form:
            expiration = request.form[EXPIRATION]

    if last_hash and pubkey and expiration:
        NPN_helper.update_last_hash(pubkey, last_hash, expiration)
        response = jsonify({CODE: 1,
                            MSG: SUCCESS})

    return response


if __name__ == '__main__':
    SPN_helper.run()
    NPN_helper.run()
    port = 3000 if debug_mode else 5000
    http_server = WSGIServer(('', port), app)
    http_server.serve_forever()
    SPN_helper.stop()
    NPN_helper.stop()


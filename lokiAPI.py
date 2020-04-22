import grequests, random, json
from curve25519 import _curve25519
from const import *
from base64 import b64decode
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
from lokiDatabase import *


class LokiSnodeProxy:
    def __init__(self, target, api):
        self.target = target
        self.random_snode_pool = api.random_snode_pool
        self.private_key_bytes = _curve25519.make_private(get_random_bytes(32))
        self.public_key_bytes = _curve25519.make_public(self.private_key_bytes)
        target_public_key_bytes = bytes.fromhex(target.encryption_key)
        self.symmetric_key = _curve25519.make_shared(self.private_key_bytes, target_public_key_bytes)

    def request_with_proxy(self, parameters, header={}):
        proxy = random.choice(self.random_snode_pool)
        url = proxy.address + ':' + proxy.port + '/proxy'
        proxy_request_parameters = {
            'method': 'POST',
            'body': json.dumps(parameters),
            'headers': header
        }
        proxy_request_parameters_as_data = json.dumps(proxy_request_parameters).encode()
        cipher = AES.new(self.symmetric_key, AES.MODE_CBC)
        iv_and_cipher_text = cipher.iv + cipher.encrypt(pad(proxy_request_parameters_as_data, AES.block_size))
        proxy_request_headers = {
            'X-Sender-Public-Key': self.public_key_bytes.hex(),
            'X-Target-Snode-Key': self.target.id_key
        }
        return grequests.post(url,
                              data=iv_and_cipher_text,
                              headers=proxy_request_headers,
                              timeout=defaultTimeout,
                              verify=False)

    def parse_response(self, res):
        result = None
        if res:
            try:
                cipher_text = bytearray(b64decode(res.content))
                iv_bytes = cipher_text[:16]
                cipher_bytes = cipher_text[16:]
                cipher = AES.new(self.symmetric_key, AES.MODE_CBC, iv=iv_bytes)
                plain_text = unpad(cipher.decrypt(cipher_bytes), AES.block_size)
                result = json.loads(plain_text.decode())
            except Exception as e:
                print('parse error')
        return result


class LokiAPI:
    def __init__(self):
        self.swarm_cache = {}
        self.seed_node_pool = ["http://storage.seed1.loki.network:22023",
                               "http://storage.seed2.loki.network:38157",
                               "http://149.56.148.124:38157"]
        self.random_snode_pool = []
        self.get_random_snode()

    def get_swarm(self, session_id):
        print("get swarm for " + session_id)
        if len(self.random_snode_pool) == 0:
            self.get_random_snode()

        if session_id not in self.swarm_cache.keys():
            self.swarm_cache[session_id] = LokiDatabase.get_instance().get_swarms(session_id)

        if len(self.swarm_cache[session_id]) > 0:
            return
        random_snode = random.choice(self.random_snode_pool)
        url = random_snode.address + ':' + random_snode.port + '/storage_rpc/' + apiVersion
        parameters = {'method': 'get_snodes_for_pubkey',
                      'params': {
                          'pubKey': session_id
                      }}
        proxy = LokiSnodeProxy(random_snode, self)
        requests = [proxy.request_with_proxy(parameters)]
        response = grequests.map(requests)
        result = None
        for res in response:
            result = proxy.parse_response(res)
        if result and result['body']:
            snodes = json.loads(result['body'])['snodes']
            for snode in snodes:
                address = snode['ip']
                if address == '0.0.0.0':
                    continue
                target = LokiAPITarget(address,
                                       snode['port'],
                                       snode['pubkey_ed25519'],
                                       snode['pubkey_x25519'])
                self.swarm_cache[session_id].append(target)
            LokiDatabase.get_instance().save_swarms(session_id, self.swarm_cache[session_id])

    def get_random_snode(self):
        self.random_snode_pool = LokiDatabase.get_instance().get_random_snode_pool()
        if len(self.random_snode_pool) > 0:
            return
        target = random.choice(self.seed_node_pool)
        url = target + '/json_rpc'
        parameters = {'method': 'get_n_service_nodes',
                      'params': {
                          'active_only': True,
                          'limit': maxRandomSnodePoolSize,
                          'fields': {
                              'public_ip': True,
                              'storage_port': True,
                              'pubkey_ed25519': True,
                              'pubkey_x25519': True
                          }
                      }}
        response = grequests.imap([grequests.post(url, json=parameters)])
        for res in response:
            result = json.loads(res.content.decode())['result']
            snodes = result['service_node_states']
            for snode in snodes:
                address = snode['public_ip']
                if address == '0.0.0.0':
                    continue
                target = LokiAPITarget(address,
                                       snode['storage_port'],
                                       snode['pubkey_ed25519'],
                                       snode['pubkey_x25519'])
                self.random_snode_pool.append(target)
        LokiDatabase.get_instance().save_random_snodes(self.random_snode_pool)

    def get_target_snodes(self, pubkey):
        if pubkey not in self.swarm_cache.keys() or len(self.swarm_cache[pubkey]) < minimumSnodeCount:
            self.swarm_cache[pubkey] = []
            retry = 0
            while len(self.swarm_cache[pubkey]) < minimumSnodeCount and retry < 5:
                self.get_swarm(pubkey)
                retry += 1
        random.shuffle(self.swarm_cache[pubkey])
        return self.swarm_cache[pubkey][:3]

    def get_raw_messages(self, pubkey, last_hash):
        target_snodes = self.get_target_snodes(pubkey)
        proxies = []
        requests = []
        for target_snode in target_snodes:
            url = target_snode.address + ':' + target_snode.port + '/storage_rpc/' + apiVersion
            parameters = {'method': 'retrieve',
                          'params': {
                              'pubKey': pubkey,
                              'lastHash': last_hash
                          }}
            proxy = LokiSnodeProxy(target_snode, self)
            proxies.append(proxy)
            requests.append(proxy.request_with_proxy(parameters))
        return proxies, requests

    def fetch_raw_messages(self, session_ids):
        proxies = []
        requests = []
        messages_dict = {}
        for session_id in session_ids:
            messages_dict[session_id] = []
            hash_value = LokiDatabase.get_instance().get_last_hash(session_id)
            print(hash_value)
            prx, req = self.get_raw_messages(session_id, hash_value)
            proxies += prx
            requests += req
        response = grequests.map(requests)
        proxy_index = 0
        for res in response:
            data = proxies[proxy_index].parse_response(res)
            pubkey_index = proxy_index // 3
            proxy_index += 1
            if data is None or data['body'] is None or len(data['body']) < 3:
                continue
            try:
                message_json = json.loads(data['body'], strict=False)
            except Exception:
                message_json = None
            if not message_json or 'messages' not in dict(message_json).keys():
                continue
            messages = list(message_json['messages'])
            old_length = len(messages_dict[session_ids[pubkey_index]])
            new_length = len(messages)
            if old_length == 0:
                messages_dict[session_ids[pubkey_index]] = messages
            elif new_length > 0:
                old_expiration = int(messages_dict[session_ids[pubkey_index]][old_length - 1]['expiration'])
                new_expiration = int(messages[new_length - 1]['expiration'])
                if new_expiration > old_expiration:
                    messages_dict[session_ids[pubkey_index]] = messages
        return messages_dict


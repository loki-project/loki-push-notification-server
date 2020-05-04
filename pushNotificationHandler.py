from const import *
import os.path, asyncio, random, pickle
from threading import Thread
from PyAPNs.apns2.client import APNsClient, NotificationPriority, Notification
from PyAPNs.apns2.payload import Payload, PayloadAlert
from PyAPNs.apns2.errors import *
from lokiAPI import LokiAPI
from lokiDatabase import *
from utils import *
import firebase_admin
from firebase_admin import credentials, messaging
from firebase_admin.exceptions import *


class PushNotificationHelper:
    def __init__(self, logger):
        self.apns = APNsClient(CERT_FILE, use_sandbox=debug_mode, use_alternative_port=False)
        self.firebase_app = None
        self.thread = Thread(target=self.run_tasks)
        self.push_fails = {}
        self.logger = logger
        self.stop_running = False
        self.load_tokens()

    def load_tokens(self):
        # TODO: Setup a DB?
        pass

    async def send_push_notification(self):
        pass

    async def create_tasks(self):
        task = asyncio.create_task(self.send_push_notification())
        await task

    def run_tasks(self):
        asyncio.run(self.create_tasks())

    def execute_push_Android(self, notifications):
        if len(notifications) == 0:
            return
        results = None
        try:
            results = messaging.send_all(messages=notifications, app=self.firebase_app)
        except FirebaseError as e:
            self.logger.error(e.cause)
        except Exception as e:
            self.logger.exception(e)

        if results is not None:
            for i in range(len(notifications)):
                response = results.responses[i]
                token = notifications[i].token
                if not response.success:
                    error = response.exception
                    self.logger.exception(error)
                    self.handle_fail_result(token, ("HttpError", ""))
                else:
                    self.push_fails[token] = 0

    def execute_push_iOS(self, notifications, priority):
        if len(notifications) == 0:
            return
        results = {}
        try:
            results = self.apns.send_notification_batch(notifications=notifications, topic=BUNDLE_ID, priority=priority)
        except ConnectionFailed:
            self.logger.error('Connection failed')
            self.execute_push_iOS(notifications, priority)
        except Exception as e:
            self.logger.exception(e)
            self.execute_push_iOS(notifications, priority)
        for token, result in results.items():
            if result != 'Success':
                self.handle_fail_result(token, result)
            else:
                self.push_fails[token] = 0

    def run(self):
        self.logger.info(self.__class__.__name__ + ' start running...')
        self.stop_running = False
        self.thread.start()

    def stop(self):
        self.logger.info(self.__class__.__name__ + 'stop running...')
        self.stop_running = True

    def handle_fail_result(self, key, result):
        if key in self.push_fails.keys():
            self.push_fails[key] += 1
        else:
            self.push_fails[key] = 1

        if self.push_fails[key] > 5:
            self.remove_invalid_token(key)
            del self.push_fails[key]
        if isinstance(result, tuple):
            reason, info = result
            self.logger.warning("Push fail " + str(reason) + ' ' + str(info))
        else:
            self.logger.warning("Push fail for unknown reason")

    def disable_token(self, token):
        self.remove_invalid_token(token)
        if token in self.push_fails.keys():
            del self.push_fails[token]

    def remove_invalid_token(self, token):
        pass


class SilentPushNotificationHelper(PushNotificationHelper):
    def __init__(self, logger):
        self.tokens = []
        super().__init__(logger)

    def load_tokens(self):
        if os.path.isfile(TOKEN_DB):
            with open(TOKEN_DB, 'rb') as token_db:
                self.tokens = list(pickle.load(token_db))
            token_db.close()

        for token in self.tokens:
            self.push_fails[token] = 0

    def update_token(self, token):
        if token in self.tokens or not is_iOS_device_token(token):
            return
        self.tokens.append(token)
        self.push_fails[token] = 0
        with open(TOKEN_DB, 'wb') as token_db:
            pickle.dump(self.tokens, token_db)
        token_db.close()

    def remove_invalid_token(self, token):
        if token in self.tokens:
            self.tokens.remove(token)
            with open(TOKEN_DB, 'wb') as token_db:
                pickle.dump(self.tokens, token_db)
            token_db.close()

    async def send_push_notification(self):
        self.logger.info('Start to push')
        payload = Payload(content_available=True)
        while True:
            random_sleep_time = random.randint(60, 180)
            self.logger.info('sleep for ' + str(random_sleep_time))
            for i in range(random_sleep_time):
                await asyncio.sleep(1)
                if self.stop_running:
                    return
            self.logger.info('push run at ' + time.asctime(time.localtime(time.time())) +
                             ' for ' + str(len(self.tokens)) + ' tokens')
            notifications = []
            for token in self.tokens:
                notifications.append(Notification(payload=payload, token=token))
            self.execute_push_iOS(notifications, NotificationPriority.Delayed)


class NormalPushNotificationHelper(PushNotificationHelper):
    def __init__(self, logger):
        self.api = LokiAPI(logger)
        self.session_ids = []
        super().__init__(logger)
        self.firebase_app = firebase_admin.initialize_app(credentials.Certificate(FIREBASE_TOKEN))

    def load_tokens(self):
        self.session_ids = LokiDatabase.get_instance().get_valid_session_ids()

        for session_id in self.session_ids:
            tokens = LokiDatabase.get_instance().get_tokens(session_id)
            for token in tokens:
                self.push_fails[token] = 0

    def update_last_hash(self, session_id, last_hash, expiration):
        expiration = process_expiration(expiration)
        if session_id in self.session_ids:
            LokiDatabase.get_instance().update_last_hash(session_id, last_hash, expiration)

    def update_token_pubkey_pair(self, token, session_id):
        if session_id not in self.session_ids:
            self.session_ids.append(session_id)
        LokiDatabase.get_instance().insert_token(session_id, token)
        if token not in self.push_fails.keys():
            self.push_fails[token] = 0

    def remove_invalid_token(self, token):
        LokiDatabase.get_instance().remove_token(token)
        self.session_ids = LokiDatabase.get_instance().get_valid_session_ids()

    async def fetch_messages(self):
        self.logger.info('fetch run at ' + time.asctime(time.localtime(time.time())) +
                         ' for ' + str(len(self.session_ids)) + ' pubkeys')
        return self.api.fetch_raw_messages(self.session_ids)

    async def send_push_notification(self):
        self.logger.info('Start to fetch and push')
        while not self.stop_running:
            notifications_iOS = []
            notifications_Android = []
            start_fetching_time = int(round(time.time()))
            raw_messages = await self.fetch_messages()
            for session_id, messages in raw_messages.items():
                if len(messages) == 0:
                    continue
                for message in messages:
                    if session_id not in self.session_ids:
                        continue
                    message_expiration = process_expiration(message['expiration'])
                    current_time = int(round(time.time() * 1000))
                    self.update_last_hash(session_id, message['hash'], message_expiration)
                    if message_expiration - current_time < 23.9 * 60 * 60 * 1000:
                        continue
                    for token in LokiDatabase.get_instance().get_tokens(session_id):
                        if is_iOS_device_token(token):
                            alert = PayloadAlert(title='Session', body='You\'ve got a new message')
                            payload = Payload(alert=alert, badge=1, sound="default",
                                              mutable_content=True, category="SECRET",
                                              custom={'ENCRYPTED_DATA': message['data']})
                            notifications_iOS.append(Notification(token=token, payload=payload))
                        else:
                            notification = messaging.Message(data={'ENCRYPTED_DATA': message['data']},
                                                             token=token)
                            notifications_Android.append(notification)
            self.execute_push_iOS(notifications_iOS, NotificationPriority.Immediate)
            self.execute_push_Android(notifications_Android)
            fetching_time = int(round(time.time())) - start_fetching_time
            waiting_time = 60 - fetching_time
            if waiting_time < 0:
                self.logger.warning('Fetching messages over 60 seconds')
            else:
                for i in range(waiting_time):
                    await asyncio.sleep(1)
                    if self.stop_running:
                        return

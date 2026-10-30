"""Use the installed client without retrying a request; preserve timeout on rebuild."""
from instrumentserver.client import Client as BaseClient
from labremote.runtime.network import configure_client_timeout

class Client(BaseClient):
    def connect(self):
        old_context = getattr(self, 'context', None)
        timeout_s = getattr(self,'recv_timeout',20000)/1000
        super().connect()
        configure_client_timeout(self, timeout_s)
        if old_context is not None and old_context is not self.context:
            old_context.destroy(linger=0)

    def ask(self, message):
        import zmq
        try:
            response = super().ask(message)
        except zmq.ZMQError as error:
            raise ConnectionError(f'Transport unavailable: {error}') from error
        except Exception as error:
            if 'Server did not reply before timeout' in str(error):
                self.consecutive_timeouts = getattr(self, 'consecutive_timeouts', 0) + 1
            else:
                self.consecutive_timeouts = 0
            raise
        else:
            self.consecutive_timeouts = 0
            return response

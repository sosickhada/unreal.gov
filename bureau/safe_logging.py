"""Redact configured credentials from messages and formatted exception chains."""
import logging


class CredentialFormatter(logging.Formatter):
    def __init__(self, env):
        super().__init__('%(levelname)s %(name)s: %(message)s')
        self.secrets=sorted({value for key,value in env.items() if isinstance(value,str) and len(value)>=6
            and any(word in key.upper() for word in ('TOKEN','API_KEY','SECRET','PASSWORD'))},key=len,reverse=True)

    def format(self, record):
        text=super().format(record)
        for secret in self.secrets:text=text.replace(secret,'[REDACTED]')
        return text


def configure_logging(env):
    handler=logging.StreamHandler();handler.setFormatter(CredentialFormatter(env))
    logging.basicConfig(level=logging.WARNING,handlers=[handler],force=True)

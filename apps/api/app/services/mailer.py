from functools import lru_cache


class MailerError(Exception):
    pass


@lru_cache
def get_mailer() -> object:
    raise NotImplementedError

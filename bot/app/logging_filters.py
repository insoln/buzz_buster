import logging
from contextvars import ContextVar

current_update_id = ContextVar("current_update_id", default=None)


class UpdateIDFilter(logging.Filter):
    def filter(self, record):
        update_id = current_update_id.get()
        record.update_id = update_id if update_id is not None else "__main__"
        return True

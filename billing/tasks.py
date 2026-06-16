try:
    from celery import shared_task
except ModuleNotFoundError:
    def shared_task(func):
        return func

from .services import deactivate_expired_subscriptions


@shared_task
def deactivate_expired_users() -> int:
    return deactivate_expired_subscriptions()

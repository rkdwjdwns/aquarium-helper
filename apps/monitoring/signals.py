# apps/monitoring/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Tank, DeviceControl


@receiver(post_save, sender=Tank)
def create_default_devices(sender, instance: Tank, created: bool, **kwargs):
    """
    Tank가 새로 생성될 때, DEVICE_TYPES에 정의된 모든 장치 종류에 대해
    기본 DeviceControl 레코드를 자동으로 만들어준다.
    (is_on=False, is_auto=True 는 모델 필드 기본값을 그대로 사용)

    이미 존재하는 타입은 건너뛰므로, 기존 tank에 대해 다시 저장해도
    중복 생성되지 않는다.
    """
    if not created:
        return

    existing_types = set(
        DeviceControl.objects.filter(tank=instance).values_list('type', flat=True)
    )

    to_create = [
        DeviceControl(tank=instance, type=device_type)
        for device_type, _label in DeviceControl.DEVICE_TYPES
        if device_type not in existing_types
    ]

    if to_create:
        DeviceControl.objects.bulk_create(to_create)
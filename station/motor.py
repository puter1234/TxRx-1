"""Minimum OFF time for the motor contactor, independent of DO4 speed."""
import math

MOTOR_RESTART_SECONDS = 5


def restart_message(remaining_ms):
    return f"모터 정지 후 5초 동안 다시 켤 수 없습니다. {math.ceil(remaining_ms / 1000)}초 후 다시 시작하세요."

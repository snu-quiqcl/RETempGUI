"""OSA 반복 측정을 UI에서 시작한 뒤 실행하세요. 목표/계수는 config에 설정합니다."""
def main(devices):
    osa = devices.osa('aq6373')
    mdt = devices.mdt('mdt693b')
    # labremote/config/mdt/device_config.yml의 pid_defaults를 사용합니다.
    # target_thz와 PID 계수가 0이면 실행을 거부하므로 실제 값을 먼저 설정하세요.
    mdt.start_pid(osa).wait()  # workflow Cancel로 전체 중단; 마지막 전압 유지

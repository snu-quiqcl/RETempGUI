from labremote.runtime.monitor import ParameterMonitor

PATHS = ('ch1.target_voltage', 'ch1.target_current', 'ch1.voltage', 'ch1.current', 'ch1.power', 'ch1.output', 'ch1.voltage_limit', 'ch1.voltage_limit_state', 'ch2.target_voltage', 'ch2.target_current', 'ch2.voltage', 'ch2.current', 'ch2.power', 'ch2.output', 'ch2.voltage_limit', 'ch2.voltage_limit_state', 'ch3.target_voltage', 'ch3.target_current', 'ch3.voltage', 'ch3.current', 'ch3.power', 'ch3.output', 'ch3.voltage_limit', 'ch3.voltage_limit_state')

class KeithleyMonitor(ParameterMonitor):
    def __init__(self,worker):super().__init__(worker,PATHS)

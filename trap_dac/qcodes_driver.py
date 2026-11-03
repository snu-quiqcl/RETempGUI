"""InstrumentServer facade. Import as trap_dac.qcodes_driver.DAC81416."""
from qcodes.instrument import Instrument
from .service import DACService


class DAC81416(Instrument):
    def __init__(self,name,config_path,serial_port,data_root,lease_seconds=5.0,internal_reference=False,**kwargs):
        super().__init__(name,**kwargs)
        self._service=DACService(config_path,serial_port,data_root,
            lease_seconds=lease_seconds,internal_reference=internal_reference)

    def get_idn(self):
        return dict(vendor='TI / custom ArtyS7',model='DAC81416',serial=None,firmware='trap-dac-api-1')

    def describe_dac(self):
        return self._service.describe()

    def start_dac_job(self,owner,request_id,action,payload):
        return self._service.start(owner,request_id,action,payload)

    def dac_job_status(self,job_id):
        return self._service.status(job_id)

    def dac_heartbeat(self,owner,job_id):
        return self._service.heartbeat(owner,job_id)

    def stop_dac_job(self,owner,job_id):
        return self._service.stop(owner,job_id)

    def close(self):
        if hasattr(self,'_service'):self._service.close()
        super().close()

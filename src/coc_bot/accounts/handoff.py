"""One-use identity proof shared only by successive bots under one live lease."""
from dataclasses import dataclass,field
from pathlib import Path
import threading
import time

from coc_bot.runtime.device_lease import DeviceLease


@dataclass
class VerifiedHandoff:
    tag:str
    data_dir:Path
    device:str
    lease:DeviceLease
    issued_at:float=field(default_factory=time.monotonic)
    thread:int=field(default_factory=threading.get_ident)
    used:bool=False

    def consume(self,config):
        if self.used:return False
        self.used=True
        age=time.monotonic()-self.issued_at
        return (isinstance(self.lease,DeviceLease)
                and (self.lease.handle is not None or self.lease.bridge is not None)
                and self.lease.device==self.device==config.adb_device
                and self.tag==config.account_tag and Path(self.data_dir).resolve()==Path(config.data_dir).resolve()
                and self.thread==threading.get_ident() and 0<=age<=30)

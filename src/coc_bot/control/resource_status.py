"""Display-only resource status; corrupt observations must not break Stop/status."""
import json
import math
from coc_bot.accounts.store import read


def resource_status(config):
    base={'enabled':config.farm_enabled,'start_percent':config.farm_resource_start_percent,
          'target_percent':config.farm_resource_target_percent,'status':'unchecked',
          'message':None,'observation':None,'observed_at':None}
    try:
        saved=read(config.data_dir/'resources/home.json',{})
        # JSON accepts NaN/Infinity by default; HTTP JSON and the frontend do not.
        json.dumps(saved,allow_nan=False)
        account=getattr(config,'account_tag',None)
        if saved.get('account',account)!=account:
            raise ValueError('Resource observations belong to another account')
        if not isinstance(saved.get('status','unchecked'),str):raise ValueError('Invalid resource status')
        if saved.get('message') is not None and not isinstance(saved['message'],str):raise ValueError('Invalid resource message')
        observed=saved.get('observed_at')
        if observed is not None and (type(observed) not in (int,float) or not math.isfinite(observed) or observed<0):
            raise ValueError('Invalid resource observation time')
        observation=saved.get('observation')
        if observation is not None:
            if not isinstance(observation,dict):raise ValueError('Invalid resource observation')
            for name in ('balances','capacities'):
                values=observation.get(name,{})
                if not isinstance(values,dict) or any(v is not None and (type(v) is not int or v<0) for v in values.values()):
                    raise ValueError('Invalid resource amounts')
        return base|{k:saved.get(k,base[k]) for k in ('status','message','observation','observed_at')}
    except (OSError,ValueError,TypeError):
        return base|{'status':'unverified','message':'Saved resource readings are unreadable; farming needs a fresh check'}

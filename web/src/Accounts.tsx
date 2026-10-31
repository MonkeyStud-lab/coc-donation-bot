import {RefractiveLayer} from './RefractiveLayer';
import React, {useEffect, useRef, useState} from 'react';
import {EmptyState,Icon} from './ui';

const roles = {donating:'Donating', farming:'Farming', upgrading:'Upgrading', builder_base:'Builder Base'};
type Maintenance = {categories?:Record<string,{at:number;status:string;message?:string;availability?:number[]}>};
type Account = {id:string;tag:string;nickname:string;roles:string[];clan_tag?:string|null;maintenance?:Maintenance};
type Rotation = {enabled:boolean;primary_id:string|null;watch_seconds:number;visit_seconds:number;interval_seconds:number};
type Registry = {accounts:Account[];active:string|null;pending:{kind:string;target?:string|null}|null;rotation?:Rotation};

export function Accounts({api,locked,result,operation,working,jobError,live,onChanged,stop}:{api:(p:string,m?:string,b?:unknown)=>Promise<any>;
  locked:boolean;result:any;operation:string|null;working:boolean;jobError:string|null;
  live:()=>void;onChanged:()=>Promise<void>;stop:()=>void}) {
  const [data,setData]=useState<Registry|null>(null),[error,setError]=useState('');
  const [name,setName]=useState(''),[chosen,setChosen]=useState<string[]>([]);
  const initialized=useRef(false);
  const [busy,setBusy]=useState(false),[editing,setEditing]=useState<string|null>(null);
  const refresh=()=>api('accounts').then(setData).catch(e=>setError(e.message));
  // A failed background job has no result. Refresh when it unlocks too, so its
  // persisted Add/Switch state still exposes the right recovery action.
  useEffect(()=>{refresh();},[result,locked]);
  useEffect(()=>{const timer=setInterval(refresh,15000);return()=>clearInterval(timer);},[api]);
  useEffect(()=>{
    if(data&&!initialized.current){
      setChosen(data.accounts.length?[]:Object.keys(roles));
      initialized.current=true;
    }
  },[data]);
  async function act(action:string,target?:string){
    setBusy(true);setError('');
    if(action==='add'){setName('');setChosen([]);setEditing(null);}
    try {await api('accounts/action','POST',{action,target,nickname:name,roles:chosen});}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  useEffect(()=>{
    if(result?.accounts){refresh();onChanged();}
  },[result]);
  const disabled=locked||busy||!data;
  const adding=!!data&&(!data.accounts.length||data.pending?.kind==='add');
  const switching=data?.pending?.kind==='switch';
  const target=data?.accounts.find(a=>a.id===data.pending?.target);
  const accountJob=!!operation?.startsWith('accounts_');
  return <>
    {error&&<p role="alert">{error}</p>}
    {!error&&jobError&&accountJob&&<p role="alert">{jobError}</p>}
    {result?.accounts&&<p role="status">{result.message}</p>}
    {working&&accountJob&&<p role="status">Reading the village and confirming its saved Supercell ID. Keep Live view control released.</p>}
    {switching&&<div className="notice">Switching to {target?.nickname||'the selected account'} is unfinished. Release Live view control, then press Finish switch to reload and verify it.</div>}
    <div className="page-actions">
      <span className="item-count">{data?.accounts.length??0} accounts</span><div className="action-spacer"/>
      {!adding&&<button className={switching?'primary':undefined} disabled={disabled||!data?.active} onClick={()=>act('verify')}>
        <Icon name="refresh" size={17}/>{switching?'Finish switch':'Verify account'}</button>}
      <button className="primary" disabled={disabled||!data?.active||!!data?.pending} onClick={()=>act('add')}><Icon name="plus" size={17}/>Add account</button>
    </div>
    {adding&&<section className="panel account-onboarding refractive-glass"><RefractiveLayer radius={16}/>
      <ol>
        <li>{data?.accounts.length?'In Live view, choose Log in to Supercell ID and sign in to the new account.':'Open your own home village in Live view.'}</li>
        <li>Return to the home village, close any game menus, then release Live view control.</li>
        <li>Choose what this account should do, then press Save and verify account. No separate verification is needed.</li>
      </ol>
      <label>Nickname (optional)<input disabled={disabled} maxLength={60} value={name} onChange={e=>setName(e.target.value)} placeholder="Use the village name"/></label>
      <div className="toolbar">{Object.entries(roles).map(([key,label])=><label className="toggle" key={key}>
        <input type="checkbox" disabled={disabled} checked={chosen.includes(key)} onChange={e=>setChosen(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label}</label>)}</div>
      <button className="primary" disabled={disabled} onClick={()=>act('register')}>
        {working&&operation==='accounts_register'?'Saving and verifying…':'Save and verify account'}</button>
      {data?.pending?.kind==='add'&&<details><summary>Use an account already saved in the app instead</summary>
        <p>Choose that account in the game's Supercell ID menu, return to its home village, and release Live view control.</p>
        <button disabled={disabled} onClick={()=>act('verify')}>Confirm saved account</button></details>}
    </section>}
    <div className="accounts-grid">{data?.accounts.map(account=><section className={'panel account-card refractive-glass '+(data.active===account.id?'current-account':'')} key={account.id}><RefractiveLayer radius={16}/>
      <div className="account-card-heading"><span className="avatar">{account.nickname.slice(0,2).toUpperCase()}</span><div className="account-identity"><strong>{account.nickname}</strong><span>{account.tag}</span></div>
        {data.active===account.id&&<span className="badge current-badge"><i className="status-dot connected"/>{data.pending?'Previous':'Current'}</span>}
        <button className="icon-button" aria-label={'Edit '+account.nickname} title="Edit account" disabled={disabled||!!data.pending} onClick={()=>{setEditing(account.id);setName(account.nickname);setChosen(account.roles);}}><Icon name="edit" size={17}/></button></div>
      {editing===account.id?<>
        <label className="stacked-label">Name<input value={name} maxLength={60} onChange={e=>setName(e.target.value)}/></label>
        <div className="toolbar">{Object.entries(roles).map(([key,label])=><label className="toggle" key={key}><input type="checkbox" checked={chosen.includes(key)} onChange={e=>setChosen(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label}</label>)}</div>
        <div className="toolbar"><button className="primary" disabled={disabled||!name.trim()} onClick={async()=>{setBusy(true);try{await api('accounts/'+account.id,'PUT',{nickname:name,roles:chosen});setEditing(null);await refresh();await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Save</button>
        <button onClick={()=>setEditing(null)}>Cancel</button></div>
      </>:<><div className="role-badges">{account.roles.length?account.roles.map(r=><span className={'role-badge role-'+r} key={r}><Icon name={{donating:'heart',farming:'swords',upgrading:'hammer',builder_base:'castle'}[r]||'settings'} size={13}/>{roles[r as keyof typeof roles]||r}</span>):<span className="muted">No automatic tasks</span>}</div>
        {account.roles.includes('upgrading')&&<div className="maintenance-status">{Object.entries({buildings:'Builders',research:'Laboratory',pets:'Pets'}).map(([key,label])=>{
          const check=account.maintenance?.categories?.[key];if(!check)return null;
          const recent=Date.now()/1000-check.at>=0&&Date.now()/1000-check.at<3600;
          const ok=recent&&['busy','started','built','recovered'].includes(check.status);
          const caption=!recent?'Check due':check.status==='busy'?'Busy at last check':['started','built','recovered'].includes(check.status)?'Upgrade verified':'Needs another check';
          return <details key={key}><summary><i className={'status-dot '+(ok?'connected':'working')}/><span>{label}</span><span>{caption}</span></summary>
            <p>{check.message||check.status} · Checked {new Date(check.at*1000).toLocaleString()}</p></details>;
        })}</div>}
        <div className="account-card-bottom"><span className="clan-tag">{account.clan_tag?<><Icon name="castle" size={14}/>{account.clan_tag}</>:'Clan not yet verified'}</span>
          {data.active!==account.id&&<button disabled={disabled||!!data.pending} onClick={()=>act('switch',account.id)}>Switch<Icon name="chevron" size={14}/></button>}</div></>}
    </section>)}</div>
    {!data&&!error&&<EmptyState icon="accounts">Loading accounts…</EmptyState>}
    {data&&data.accounts.length>1&&<section className="panel rotation-card refractive-glass"><RefractiveLayer radius={16}/>
      <label className="toggle"><input type="checkbox" disabled={disabled||!!data.pending}
        checked={!!data.rotation?.enabled} onChange={async e=>{
          const primary=data.rotation?.primary_id||data.accounts.find(a=>a.roles.includes('donating'))?.id;
          if(!primary){setError('Give the main account the Donating role first.');return;}
          setBusy(true);try{setData(await api('accounts/rotation','PUT',{
            enabled:e.target.checked,primary_id:primary,
            watch_seconds:data.rotation?.watch_seconds||900,visit_seconds:data.rotation?.visit_seconds||180,
            interval_seconds:data.rotation?.interval_seconds||1800}));}
          catch(e){setError((e as Error).message);}finally{setBusy(false);}
        }}/>Automatic account visits</label>
      {!!data.rotation?.enabled&&<label>Main donation account<select disabled={disabled||!!data.pending}
        value={data.rotation.primary_id||''} onChange={async e=>{
          setBusy(true);try{setData(await api('accounts/rotation','PUT',{
            primary_id:e.target.value,
            enabled:true,watch_seconds:data.rotation!.watch_seconds,visit_seconds:data.rotation!.visit_seconds,
            interval_seconds:data.rotation!.interval_seconds}));}
          catch(e){setError((e as Error).message);}finally{setBusy(false);}
        }}>{data.accounts.filter(a=>a.roles.includes('donating')).map(a=><option key={a.id} value={a.id}>{a.nickname}</option>)}</select></label>}
    </section>}
  </>;
}

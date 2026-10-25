import React, {useEffect, useRef, useState} from 'react';

const roles = {donating:'Donating', farming:'Farming', upgrading:'Upgrading', builder_base:'Builder Base'};
type Account = {id:string;tag:string;nickname:string;roles:string[]};
type Registry = {accounts:Account[];active:string|null;pending:{kind:string}|null};

export function Accounts({api,locked,result,live,onChanged,stop}:{api:(p:string,m?:string,b?:unknown)=>Promise<any>;
  locked:boolean;result:any;live:()=>void;onChanged:()=>Promise<void>;stop:()=>void}) {
  const [data,setData]=useState<Registry|null>(null),[error,setError]=useState('');
  const [name,setName]=useState(''),[chosen,setChosen]=useState<string[]>([]);
  const initialized=useRef(false);
  const [busy,setBusy]=useState(false),[editing,setEditing]=useState<string|null>(null);
  const refresh=()=>api('accounts').then(setData).catch(e=>setError(e.message));
  useEffect(()=>{refresh();},[result]);
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
  return <>
    {error&&<p role="alert">{error}</p>}
    {result?.accounts&&<p role="status">{result.message}</p>}
    {data?.pending&&<div className="notice">Account setup is unfinished. Automation stays paused until the loaded account is verified.</div>}
    <div className="toolbar">
      <button disabled={disabled||!data?.active||!!data?.pending} onClick={()=>act('add')}>Add account</button>
      <button disabled={disabled||!data?.active} onClick={()=>act('verify')}>Verify current account</button>
      <button onClick={live}>Live view</button>
      <button className="danger" onClick={stop}>Stop</button>
    </div>
    {(!data?.accounts.length||data.pending?.kind==='add')&&<section>
      <p>{data?.accounts.length?'In Live view, choose Log in to Supercell ID and sign in. When the new village loads, save it here.':'Open your home village, choose a name and roles, then save your current account. Your existing settings are preserved.'}</p>
      <label>Name<input maxLength={60} value={name} onChange={e=>setName(e.target.value)} placeholder="Account nickname"/></label>
      <div className="toolbar">{Object.entries(roles).map(([key,label])=><label className="toggle" key={key}>
        <input type="checkbox" checked={chosen.includes(key)} onChange={e=>setChosen(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label}</label>)}</div>
      <button disabled={disabled||!name.trim()} onClick={()=>act('register')}>Save loaded account</button>
    </section>}
    {data?.accounts.map(account=><section key={account.id}>
      <div className="toolbar"><strong>{account.nickname}</strong><span>{account.tag}</span>
        {data.active===account.id?<span className="chip">Selected</span>:<button disabled={disabled||!!data.pending} onClick={()=>act('switch',account.id)}>Switch</button>}
        <button disabled={disabled||!!data.pending} onClick={()=>{setEditing(account.id);setName(account.nickname);setChosen(account.roles);}}>Edit</button></div>
      {editing===account.id?<>
        <label>Name<input value={name} maxLength={60} onChange={e=>setName(e.target.value)}/></label>
        <div className="toolbar">{Object.entries(roles).map(([key,label])=><label className="toggle" key={key}><input type="checkbox" checked={chosen.includes(key)} onChange={e=>setChosen(old=>e.target.checked?[...old,key]:old.filter(x=>x!==key))}/>{label}</label>)}</div>
        <button disabled={disabled||!name.trim()} onClick={async()=>{setBusy(true);try{await api('accounts/'+account.id,'PUT',{nickname:name,roles:chosen});setEditing(null);await refresh();await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Save</button>
        <button onClick={()=>setEditing(null)}>Cancel</button>
      </>:<p>{account.roles.map(r=>roles[r as keyof typeof roles]).join(' · ')||'No automatic tasks'}</p>}
    </section>)}
  </>;
}

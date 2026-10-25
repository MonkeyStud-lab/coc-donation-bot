import React, {useEffect, useRef, useState} from 'react';

const roles = {donating:'Donating', farming:'Farming', upgrading:'Upgrading', builder_base:'Builder Base'};
type Account = {id:string;tag:string;nickname:string;roles:string[]};
type Registry = {accounts:Account[];active:string|null;pending:{kind:string;target?:string|null}|null};

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
    {switching&&<div className="notice">Switching to {target?.nickname||'the selected account'} is unfinished. Open that village in Live view, release control, then finish the switch.</div>}
    <div className="toolbar">
      <button disabled={disabled||!data?.active||!!data?.pending} onClick={()=>act('add')}>Add account</button>
      {!adding&&<button className={switching?'primary':undefined} disabled={disabled||!data?.active} onClick={()=>act('verify')}>
        {switching?'Finish switch':'Check loaded account'}</button>}
      <button onClick={live}>Live view</button>
      <button className="danger" onClick={stop}>Stop</button>
    </div>
    {adding&&<section>
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
    {data?.accounts.map(account=><section key={account.id}>
      <div className="toolbar"><strong>{account.nickname}</strong><span>{account.tag}</span>
        {data.active===account.id?<span className="chip">{data.pending?'Previous account':'Ready'}</span>:<button disabled={disabled||!!data.pending} onClick={()=>act('switch',account.id)}>Switch</button>}
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

import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

type Status = {active:boolean; state:string; operation:string|null; activity:string|null; result:any; error:string|null;
  timers:{farm_seconds:number|null;break_seconds:number|null}; manual_control:boolean;on_break:boolean};
type Entry = {id:number; level:string; text:string; at:string};
type Field = {key:string;label:string;description:string;kind:string;choices:string[];section:string;advanced:boolean};
type SettingsData = {revision:string;values:Record<string,any>;fields:Field[];themes:any[]};
type Part = {key:string;label:string;kind:string;configured:boolean;optional:boolean;instructions:string};
type SetupData = {revision:string;steps:{id:string;label:string;parts:Part[]}[]};
type Capture = {id:string;width:number;height:number;revision:string;at:string;taps?:number[][];jitter?:number};
let csrf='';
const FIRST_LAUNCH=location.pathname.startsWith('/first-launch');
const BASE=FIRST_LAUNCH?'/first-launch':'';
const BASIC_SETTINGS=new Set(['gui_timing_preset','donate_open_requests','farm_enabled',
  'farm_interval_seconds','farm_interval_variance_seconds','session_limit_seconds',
  'session_limit_variance_seconds','gui_theme','gui_show_debug_activity','gui_dev_options']);
async function api(path:string, method='GET', body?:unknown) {
  const response=await fetch(BASE+'/api/'+path,{method,headers:{
    'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':csrf})},
    body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok) {
    const text=await response.text();
    if(response.status===401) window.dispatchEvent(new Event('session-expired'));
    throw new Error(text || 'Request failed');
  }
  return response.json();
}
const fmt=(value:number|null)=>value===null?'Off':Math.floor(value/3600)+':'+
  String(Math.floor(value%3600/60)).padStart(2,'0')+':'+String(Math.floor(value%60)).padStart(2,'0');

function useDialog(ref:React.RefObject<HTMLElement|null>,close:()=>void){
  const exit=useRef(close);exit.current=close;
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const dialog=ref.current;
    const controls=()=>Array.from(dialog?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]')||[]);
    controls()[0]?.focus();
    function key(e:KeyboardEvent){
      if(e.key==='Escape'){e.preventDefault();exit.current();}
      if(e.key==='Tab'){
        const list=controls(),first=list[0],last=list[list.length-1];
        if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}
      }
    }
    dialog?.addEventListener('keydown',key);
    return ()=>{dialog?.removeEventListener('keydown',key);previous?.focus();};
  },[]);
}

function App(){
  const [signed,setSigned]=useState(false),[password,setPassword]=useState('');
  const [passwordRequired,setPasswordRequired]=useState(true),[checkingSession,setCheckingSession]=useState(true);
  const [page,setPage]=useState(FIRST_LAUNCH?'Setup':'Dashboard'),[notice,setNotice]=useState('');
  const [online,setOnline]=useState(false),[status,setStatus]=useState<Status|null>(null);
  const [logs,setLogs]=useState<Entry[]>([]),[debug,setDebug]=useState(false),[scroll,setScroll]=useState(true);
  const [settings,setSettings]=useState<SettingsData|null>(null),[values,setValues]=useState<Record<string,any>>({});
  const [dirty,setDirty]=useState(false),[search,setSearch]=useState(''),[advanced,setAdvanced]=useState(false);
  const [setup,setSetup]=useState<SetupData|null>(null),[selected,setSelected]=useState('');
  const [queue,setQueue]=useState<string[]>([]),[collection,setCollection]=useState<any>(null);
  const [galleryOffset,setGalleryOffset]=useState(0),[galleryTotal,setGalleryTotal]=useState(0);
  const [capture,setCapture]=useState<Capture|null>(null),[editor,setEditor]=useState<Part|null>(null);
  const [backups,setBackups]=useState<{id:string;label:string}[]>([]);
  const [gallery,setGallery]=useState<{id:string;label:string}[]>([]);
  const [practice,setPractice]=useState(false),[busy,setBusy]=useState(false);
  const [viewer,setViewer]=useState(false);
  const [captureIntent,setCaptureIntent]=useState<Part|null>(null);
  const pendingCapture=useRef(false),logEnd=useRef<HTMLDivElement>(null);
  function acceptSession(x:{csrf:string;password_required:boolean}){
    csrf=x.csrf;setPasswordRequired(x.password_required!==false);setSigned(true);
  }
  const expired=()=>{
    setSigned(false);setOnline(false);csrf='';
    if(!passwordRequired){
      setCheckingSession(true);
      api('session').then(acceptSession).catch(()=>{}).finally(()=>setCheckingSession(false));
    }
  };
  async function attempt(fn:()=>Promise<unknown>){
    setBusy(true);try{return await fn();}catch(e){setNotice((e as Error).message);return undefined;}
    finally{setBusy(false);}
  }
  async function reload(){
    const [a,b,c,d]=await Promise.all([api('settings'),api('setup'),api('backups'),api('library')]);
    setSettings(a);setValues(a.values);setSetup(b);setBackups(c);setGallery(d.images);setDirty(false);
    setCollection(d.collection);setGalleryTotal(d.total);setGalleryOffset(0);
    setPractice(!!a.values.gui_practice_mode);setDebug(!!a.values.gui_show_debug_activity);
    setSelected(previous=>previous||b.steps[0].parts[0].key);
  }
  useEffect(()=>{
    window.addEventListener('session-expired',expired);
    api('session').then(acceptSession).catch(()=>{}).finally(()=>setCheckingSession(false));
    return ()=>window.removeEventListener('session-expired',expired);
  },[passwordRequired]);
  useEffect(()=>{
    if(!signed)return;
    attempt(reload);
    let stopped=false,socket:WebSocket,reconnect:ReturnType<typeof setTimeout>;
    function connect(){
      socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+BASE+'/api/events/ws');
      socket.onopen=()=>setOnline(true);
      socket.onmessage=e=>{
        const data=JSON.parse(e.data);setStatus(data.status);
        setLogs(old=>{
          const merged=new Map<number,Entry>((data.events.reset?[]:old).map((x:Entry)=>[x.id,x]));
          data.events.entries.forEach((x:Entry)=>merged.set(x.id,x));
          return [...merged.values()].slice(-500);
        });
      };
      socket.onclose=e=>{setOnline(false);if(e.code===1008){expired();return;}
        // A restarted server rejects an old cookie before WebSocket acceptance,
        // which browsers report as 1006 rather than the application close code.
        api('session').then(acceptSession).catch(()=>{}).finally(()=>{
          if(!stopped)reconnect=setTimeout(connect,2500);
        });};
    }
    connect();
    return ()=>{stopped=true;clearTimeout(reconnect);socket?.close();};
  },[signed]);
  useEffect(()=>{
    const handler=(e:BeforeUnloadEvent)=>{if(dirty||editor){e.preventDefault();}};
    window.addEventListener('beforeunload',handler);
    return ()=>window.removeEventListener('beforeunload',handler);
  },[dirty,editor]);
  useEffect(()=>{if(scroll)logEnd.current?.scrollIntoView({block:'nearest'});},[logs,scroll]);
  useEffect(()=>{
    if(!pendingCapture.current||status?.active||status?.operation!=='capture')return;
    pendingCapture.current=false;
    if(status.result?.id){setCapture(status.result);setEditor(captureIntent);}
    else setNotice(status.error||'Screenshot could not be captured');
  },[status]);
  useEffect(()=>{
    const theme=settings?.themes.find(t=>t.label===values.gui_theme);
    if(theme)for(const key of ['bg','sidebar','surface','text','border','accent','danger','field_bg','text_secondary'])
      document.documentElement.style.setProperty('--'+key.replace('_','-'),theme[key]);
  },[values.gui_theme,settings]);
  async function captureScreen(part:Part|null=null,pan=false){
    setCaptureIntent(part);pendingCapture.current=true;
    const result=await attempt(()=>api('capture'+(pan?'/pan':''),'POST'));
    if(!result)pendingCapture.current=false;
  }
  function navigate(next:string){
    if(dirty&&!confirm('Leave these unsaved settings?'))return;
    if(dirty&&settings){setValues(settings.values);setDirty(false);}
    setPage(next);
  }
  function advance(){
    if(queue.length){setSelected(queue[0]);setQueue(queue.slice(1));}
    else {const all=setup!.steps.flatMap(s=>s.parts);setSelected(all[(all.findIndex(p=>p.key===selected)+1)%all.length].key);}
  }
  function beginSetup(missing:boolean){
    const keys=setup!.steps.flatMap(s=>s.parts).filter(p=>!missing||(!p.configured&&!p.optional)).map(p=>p.key);
    if(!keys.length){setNotice('All required calibration parts are saved');return;}
    setSelected(keys[0]);setQueue(keys.slice(1));
  }
  const locked=!!status?.active||!!status?.manual_control||busy||!online;
  const part=setup?.steps.flatMap(s=>s.parts).find(p=>p.key===selected);
  async function save(){
    const updated=await attempt(()=>api('settings','PUT',{revision:settings!.revision,values}));
    if(updated){setSettings(updated as SettingsData);setValues((updated as SettingsData).values);setDirty(false);setNotice('Settings saved');}
  }
  async function command(path:string,body?:unknown){
    const updated=await attempt(()=>api(path,'POST',body));
    if(updated)setStatus(updated as Status);
  }
  if(checkingSession||(!signed&&!passwordRequired))return <main className="login" role="status">Connecting…</main>;
  if(!signed)return <main className="login"><form onSubmit={e=>{e.preventDefault();attempt(async()=>{
    const result=await api('login','POST',{password});csrf=result.csrf;setSigned(true);setPassword('');
  });}}><h1>CoC Bot</h1><label>Password<input type="password" autoComplete="current-password"
    value={password} onChange={e=>setPassword(e.target.value)} required/></label>
    <button className="primary" disabled={busy}>Sign in</button><p role="alert">{notice}</p></form></main>;
  const fields=settings?.fields.filter(f=>(!f.advanced||values.gui_dev_options)&&
    (advanced||BASIC_SETTINGS.has(f.key))&&
    (f.label+' '+f.description).toLowerCase().includes(search.toLowerCase()))||[];
  return <div className="app"><aside><a className="brand" href="#" onClick={e=>e.preventDefault()}>CoC Bot</a>
    <nav>{['Dashboard','Settings','Setup','Library','Diagnostics'].map(p=><button key={p}
      className={page===p?'selected':''} onClick={()=>navigate(p)}>{p}</button>)}</nav>
    {FIRST_LAUNCH&&<button disabled={locked} onClick={()=>location.assign('/')}>Exit first-launch test</button>}
    {passwordRequired&&<button onClick={()=>attempt(async()=>{await api('logout','POST');expired();})}>Sign out</button>}</aside>
    <main>{FIRST_LAUNCH&&<div className="notice">First-launch test · changes are kept separate from your saved setup.</div>}
    <header><h1>{page}</h1><span className={'connection '+(online?'connected':'')}>
      {online?'Connected':'Reconnecting'}</span></header>
    {notice&&<div className="notice" role="status">{notice}<button aria-label="Dismiss message" onClick={()=>setNotice('')}>×</button></div>}
    {page==='Dashboard'&&<>
      <section className="play"><span className="chip">{status?.active?
        (status.state==='running'&&status.activity?status.activity:status.operation+' · '+status.state):status?.state||'Stopped'}</span>
      <div className="controls"><button className="primary" disabled={locked} onClick={()=>command('start',{practice})}>Start</button>
        <button className="danger" disabled={!online||(!status?.active&&!status?.manual_control)} onClick={()=>command('stop')}>Stop</button>
        <button disabled={!online||busy||status?.manual_control||
          (status?.active&&(status.operation!=='bot'||status.state!=='running'))}
          onClick={()=>attempt(()=>api('farm','POST'))}>Farm now</button></div>
      <div className="timers"><span>Farm <strong>{fmt(status?.timers.farm_seconds??null)}</strong></span>
        <span>{status?.on_break?'Break ends':'Next break'} <strong>{fmt(status?.timers.break_seconds??null)}</strong></span></div>
      <label className="toggle"><input type="checkbox" checked={practice} disabled={!!status?.active} onChange={e=>setPractice(e.target.checked)}/>Practice mode</label>
      {status?.error&&<p role="alert">{status.error}</p>}</section>
      <section className="activity"><div className="toolbar"><span>Activity</span>
        <label className="toggle"><input type="checkbox" checked={debug} onChange={e=>setDebug(e.target.checked)}/>Debug</label>
        <label className="toggle"><input type="checkbox" checked={scroll} onChange={e=>setScroll(e.target.checked)}/>Auto-scroll</label>
        <button onClick={()=>navigator.clipboard.writeText(logs.map(x=>x.at+' '+x.level+' '+x.text).join('\n')).catch(()=>setNotice('Clipboard unavailable. Use Export in Diagnostics.'))}>Copy</button></div>
        <div className="log">{logs.filter(x=>debug||x.level!=='DEBUG').map(x=><div key={x.id}><time>{new Date(x.at).toLocaleTimeString()}</time> {x.text}</div>)}<div ref={logEnd}/></div></section>
    </>}
    {page==='Settings'&&<>
      <div className="toolbar"><input aria-label="Search settings" placeholder="Search settings" value={search} onChange={e=>setSearch(e.target.value)}/>
        <label className="toggle"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>Advanced</label>
        <button disabled={locked||!dirty} className="primary" onClick={save}>Save</button>
        <button disabled={busy} onClick={()=>{if(!dirty||confirm('Discard unsaved settings?'))attempt(reload);}}>Reload</button></div>
      <section className="settings">{fields.map(f=><div className="setting" key={f.key}>
        <label htmlFor={f.key}>{f.label}<span>{f.description}</span></label>
        {f.kind==='bool'?<input id={f.key} className="switch" type="checkbox" checked={!!values[f.key]} disabled={locked}
          onChange={e=>{setValues({...values,[f.key]:e.target.checked});setDirty(true);}}/>:
        f.kind==='choice'?<select id={f.key} value={values[f.key]} disabled={locked}
          onChange={e=>{setValues({...values,[f.key]:e.target.value});setDirty(true);}}>
          {f.choices.map(c=><option key={c}>{c}</option>)}</select>:
        <input id={f.key} value={values[f.key]??''} disabled={locked} type={['int','float'].includes(f.kind)?'number':'text'}
          min={0} step={f.kind==='float'?'any':1} onChange={e=>{setValues({...values,[f.key]:e.target.value});setDirty(true);}}/>}
      </div>)}</section>
    </>}
    {page==='Setup'&&<><div className="toolbar">
      <button disabled={locked||!setup} onClick={()=>beginSetup(true)}>Calibrate missing</button>
      <button disabled={locked||!setup} onClick={()=>beginSetup(false)}>Calibrate all</button>
      {!!queue.length&&<button onClick={()=>setQueue([])}>Exit guided setup</button>}</div>
      <div className="setup"><section className="checklist">
      {setup?.steps.map(s=><details open key={s.id}><summary>{s.label}</summary>{s.parts.map(p=><button key={p.key}
      className={selected===p.key?'selected':''} onClick={()=>{setSelected(p.key);setQueue([]);}}>
        <span className={p.configured?'complete':'missing'}>{p.configured?'✓':'○'}</span>{p.label}</button>)}</details>)}
      </section><section className="guide">{part&&<>
        <h2>{part.label}</h2><p className="instructions">{part.instructions}</p>
        <div className="toolbar"><button className="primary" disabled={locked} onClick={()=>captureScreen(part)}>Capture screen</button>
        {part.key==='deploy_sequence'&&<button disabled={locked} onClick={()=>captureScreen(part,true)}>Pan and capture</button>}
        <button onClick={advance}>Skip</button>
        <button disabled={locked} onClick={()=>attempt(async()=>{await api('backups','POST');await reload();setNotice('Calibration backed up');})}>Back up</button></div>
      </>}</section></div></>}
    {page==='Library'&&<>
      <div className="toolbar"><button disabled={locked} onClick={()=>attempt(async()=>{await api('backups','POST');await reload();})}>Back up calibration</button>
        <button disabled={locked} onClick={()=>{const name=prompt('Profile name');if(name)attempt(async()=>{await api('profiles','POST',{name});await reload();});}}>Save profile</button>
        <label className="upload">Import calibration<input type="file" accept=".zip" disabled={locked} onChange={e=>{
          const file=e.target.files?.[0];if(!file)return;const name=prompt('Imported calibration name',file.name.replace(/\.zip$/i,''));
          if(name)attempt(async()=>{const response=await fetch(BASE+'/api/backups/import?name='+encodeURIComponent(name),{
            method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/zip'},body:file});
            if(!response.ok)throw new Error(await response.text());await reload();});e.target.value='';
        }}/></label>
        <button onClick={()=>attempt(reload)}>Refresh</button></div>
      <section>{backups.map(b=><div className="setting" key={b.id}><span>{b.label}</span><div className="toolbar">
        <button disabled={locked} onClick={()=>confirm('Restore this calibration? A safety backup will be saved.')&&attempt(async()=>{await api('backups/'+b.id+'/restore','POST');await reload();})}>Restore</button>
        <a href={BASE+'/api/backups/'+b.id+'/export'} download>Export</a>
        <button disabled={locked} onClick={()=>{const name=prompt('Calibration name',b.label);if(name)attempt(async()=>{await api('backups/'+b.id,'PATCH',{name});await reload();});}}>Rename</button>
        <button disabled={locked} onClick={()=>confirm('Delete this saved calibration?')&&attempt(async()=>{await api('backups/'+b.id,'DELETE');await reload();})}>Delete</button>
      </div></div>)}</section>
      {collection&&<p>{collection.paused?'Collection paused: '+collection.paused:
        'Collection active'} · {collection.stats?.saved??0} saved · {Math.round((collection.approximate_storage_bytes??0)/1024/1024)} MB</p>}
      <div className="gallery">{gallery.map(x=><a key={x.id} href={BASE+'/api/library/images/'+x.id} target="_blank" rel="noreferrer">
        <img src={BASE+'/api/library/images/'+x.id} alt={x.label} loading="lazy"/><span>{x.label}</span></a>)}</div>
      {galleryTotal>24&&<div className="toolbar">{[-24,24].map(delta=><button key={delta}
        disabled={galleryOffset+delta<0||galleryOffset+delta>=galleryTotal}
        onClick={()=>attempt(async()=>{const next=galleryOffset+delta,data=await api('library?offset='+next);setGallery(data.images);setGalleryOffset(next);})}>
        {delta<0?'Previous':'Next'}</button>)}</div>}
    </>}
    {page==='Diagnostics'&&<>
      <div className="toolbar"><button disabled={locked} onClick={()=>captureScreen()}>Current screenshot</button>
        <button disabled={locked} onClick={()=>setViewer(true)}>Open game</button>
        {!!values.gui_dev_options&&<button disabled={locked} onClick={()=>attempt(async()=>{
          if(!FIRST_LAUNCH)await api('first-launch/reset','POST');
          location.assign(FIRST_LAUNCH?'/':'/first-launch/');
        })}>
          {FIRST_LAUNCH?'Exit first-launch test':'Simulate first launch'}</button>}
        <button onClick={()=>attempt(async()=>{const data=await api('readiness');setNotice(data.issues.length?data.issues.join(' · '):'Calibration checks passed');})}>Check calibration</button>
        <button onClick={()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([logs.map(x=>x.at+' '+x.level+' '+x.text).join('\n')],{type:'text/plain'}));a.download='bot-activity.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}}>Export activity</button>
        <a href={BASE+'/api/report'} download="bot-report.json">Download report</a></div>
      <section>{[['health_check','Check device'],['classify_screen','Recognize screen'],['open_clan_chat','Open clan chat'],
        ['find_classify_request','Inspect request'],['open_donation','Open donation'],['close_donation','Close donation'],
        ['scroll_chat','Scroll chat'],['anti_idle','Test inactivity nudge'],['farm_open_attack','Open Attack menu'],
        ['farm_start_search','Start opponent search'],['farm_classify','Recognize battle'],
        ['farm_deploy_dry','Preview deploy taps'],['farm_clear_deploy','Clear deploy sequence'],
        ['force_stop','Close Clash'],['close_waydroid','Close Waydroid and Clash'],
        ['relaunch','Relaunch Clash'],['break_cycle','Test break cycle']].map(([id,label])=>
        <div className="setting" key={id}><span>{label}</span><button disabled={locked}
          onClick={()=>{if(id==='farm_clear_deploy'&&!confirm('Remove your saved farm deploy sequence?'))return;
            attempt(()=>api('diagnostics/'+id,'POST'));}}>Run</button></div>)}</section>
      {status?.result&&!status.result?.id&&<pre className="result">{typeof status.result==='string'?status.result:JSON.stringify(status.result,null,2)}</pre>}
    </>}
    </main>
    {viewer&&<GameViewer close={()=>setViewer(false)}/>}
    {capture&&<Editor capture={capture} part={editor} locked={locked} refresh={()=>captureScreen(editor)}
      close={()=>{setCapture(null);setEditor(null);}}
      save={async(selection,cols,rows,jitter)=>{const saved=await attempt(()=>api('setup','POST',{
        capture:capture.id,part:editor!.key,selection,revision:capture.revision,cols,rows,jitter}));
        if(saved){setSetup(saved as SetupData);setCapture(null);setEditor(null);setNotice('Calibration saved');if(queue.length)advance();}}}/>}
  </div>;
}

function GameViewer({close}:{close:()=>void}){
  const dialog=useRef<HTMLElement|null>(null);useDialog(dialog,close);
  const socket=useRef<WebSocket|null>(null),image=useRef<HTMLImageElement>(null);
  const [source,setSource]=useState(''),[error,setError]=useState('');
  const start=useRef<number[]|null>(null);
  useEffect(()=>{
    const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+BASE+'/api/viewer/ws');
    socket.current=ws;ws.binaryType='blob';
    let url='',timer:ReturnType<typeof setTimeout>;
    ws.onmessage=e=>{
      if(typeof e.data==='string'){ws.send(JSON.stringify({type:'frame'}));return;}
      if(url)URL.revokeObjectURL(url);
      url=URL.createObjectURL(e.data);setSource(url);
      timer=setTimeout(()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'frame'}));},1000);
    };
    ws.onclose=()=>setError('Game viewer closed. The bot remains stopped.');
    return ()=>{clearTimeout(timer);ws.close();if(url)URL.revokeObjectURL(url);socket.current=null;};
  },[]);
  function send(value:unknown){if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify(value));}
  function point(e:React.PointerEvent<HTMLImageElement>){
    const r=e.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(e.currentTarget.naturalWidth-1,Math.round((e.clientX-r.left)*e.currentTarget.naturalWidth/r.width))),
      Math.max(0,Math.min(e.currentTarget.naturalHeight-1,Math.round((e.clientY-r.top)*e.currentTarget.naturalHeight/r.height)))];
  }
  return <div className="modal-backdrop"><section ref={dialog} className="modal" role="dialog" aria-modal="true" aria-label="Game viewer">
    <div className="toolbar"><h2>Game</h2><button onClick={close}>Close</button></div>
    {error?<p role="alert">{error}</p>:source?<img ref={image} src={source} alt="Current Android screen" className="game"
      draggable={false} onPointerDown={e=>{start.current=point(e);e.currentTarget.setPointerCapture(e.pointerId);}}
      onPointerUp={e=>{if(!start.current)return;const end=point(e),from=start.current;start.current=null;
        send(Math.hypot(end[0]-from[0],end[1]-from[1])>12?{type:'swipe',from,to:end}:{type:'tap',from});}}/>:<p>Connecting…</p>}
    <div className="toolbar"><button onClick={()=>send({type:'key',key:'back'})}>Android Back</button>
      <button onClick={()=>send({type:'key',key:'home'})}>Android Home</button></div>
  </section></div>;
}

function Editor({capture,part,locked,close,save,refresh}:{capture:Capture;part:Part|null;locked:boolean;close:()=>void;refresh:()=>void;
  save:(selection:any[],cols:number,rows:number,jitter:number)=>void}){
  const canvas=useRef<HTMLCanvasElement>(null),image=useRef<HTMLImageElement|null>(null);
  const dialog=useRef<HTMLElement|null>(null);useDialog(dialog,close);
  const [points,setPoints]=useState<number[][]>(part?.key==='deploy_sequence'?capture.taps||[]:[]),[box,setBox]=useState<number[]>([]);
  const [mode,setMode]=useState(part?.kind==='tap'?'point':'box'),[jitter,setJitter]=useState(capture.jitter??6);
  const [cols,setCols]=useState(part?.key==='troop_bar'?7:5),[rows,setRows]=useState(part?.key==='troop_bar'?2:1);
  const origin=useRef<number[]|null>(null);
  const sequence=part?.key==='deploy_sequence';
  useEffect(()=>{
    const img=new Image();img.onload=()=>{image.current=img;paint();};
    img.src=BASE+'/api/captures/'+capture.id;
  },[capture.id]);
  function paint(){
    const c=canvas.current;if(!c||!image.current)return;
    const ctx=c.getContext('2d')!;ctx.clearRect(0,0,c.width,c.height);ctx.drawImage(image.current,0,0);
    ctx.strokeStyle='#55d4ff';ctx.fillStyle='#55d4ff44';ctx.lineWidth=3;
    if(box.length){ctx.fillRect(...box as [number,number,number,number]);ctx.strokeRect(...box as [number,number,number,number]);}
    points.forEach(([x,y],i)=>{
      ctx.beginPath();ctx.arc(x,y,sequence?Math.SQRT2*jitter:8,0,Math.PI*2);ctx.fill();ctx.stroke();
      // Existing engine varies each axis independently. The circle encloses
      // its furthest diagonal offset; the number does not inflate that radius.
      ctx.font='bold 20px sans-serif';ctx.fillStyle='#fff';ctx.strokeStyle='#101820';ctx.lineWidth=4;
      ctx.strokeText(String(i+1),x+12,y-12);ctx.fillText(String(i+1),x+12,y-12);
      ctx.fillStyle='#55d4ff44';ctx.strokeStyle='#55d4ff';ctx.lineWidth=3;
    });
  }
  useEffect(paint,[points,box,jitter]);
  function coordinate(e:React.PointerEvent){
    const rect=e.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(capture.width-1,Math.round((e.clientX-rect.left)*capture.width/rect.width))),
      Math.max(0,Math.min(capture.height-1,Math.round((e.clientY-rect.top)*capture.height/rect.height)))];
  }
  return <div className="modal-backdrop"><section ref={dialog} className="modal" role="dialog" aria-modal="true"
    aria-label={part?.label||'Game screenshot'}><div className="toolbar"><h2>{part?.label||'Game screenshot'}</h2>
    <button disabled={locked} onClick={refresh}>Refresh screenshot</button><button onClick={close}>Cancel</button></div>
    {part&&<p className="instructions">{part.instructions}</p>}
    {part?.kind==='tap'&&<select aria-label="Selection type" value={mode} onChange={e=>{setMode(e.target.value);setBox([]);setPoints([]);}}>
      <option value="point">Click a point</option><option value="box">Box the button and save its picture</option></select>}
    <canvas ref={canvas} width={capture.width} height={capture.height}
      onPointerDown={e=>{if(!part||part.key==='frame_width')return;e.currentTarget.setPointerCapture(e.pointerId);
        const p=coordinate(e);if(sequence)setPoints([...points,p]);else if(mode==='point')setPoints([p]);else{origin.current=p;setBox([]);}}}
      onPointerMove={e=>{if(!origin.current)return;const [x,y]=coordinate(e),[a,b]=origin.current;
        setBox([Math.min(a,x),Math.min(b,y),Math.abs(x-a),Math.abs(y-b)]);}}
      onPointerUp={()=>{origin.current=null;}} onPointerCancel={()=>{origin.current=null;}}/>
    {sequence&&<div className="toolbar"><label>Farm tap variation ±{jitter} px per axis<input type="range" min="0" max="40"
      value={jitter} onChange={e=>setJitter(Number(e.target.value))}/></label>
      <button onClick={()=>setPoints(points.slice(0,-1))}>Undo</button><button onClick={()=>setPoints([])}>Clear</button><span>{points.length} taps</span></div>}
    {part?.kind==='grid'&&<div className="toolbar"><label>Columns<input type="number" min="1" max="20" value={cols} onChange={e=>setCols(Number(e.target.value))}/></label>
      <label>Rows<input type="number" min="1" max="10" value={rows} onChange={e=>setRows(Number(e.target.value))}/></label></div>}
    {part&&<button className="primary" disabled={locked||(part.key!=='frame_width'&&!points.length&&!box.length)}
      onClick={()=>save(sequence?points:part.key==='frame_width'?[]:mode==='point'?points[0]:box,cols,rows,jitter)}>Save</button>}
  </section></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);

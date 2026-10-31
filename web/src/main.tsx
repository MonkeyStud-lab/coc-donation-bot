import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {AttackObservation} from './AttackObservation';
import {AttackPlanner} from './AttackPlanner';
import {Accounts} from './Accounts';
import {SettingsPanel} from './SettingsPanel';
import {harborPalette,paletteProperties} from './interfacePalettes';
import {EmptyState,Icon,pageIcons,pageLabels,ResourceLevels,ResourceStatus} from './ui';
import {createRoot} from 'react-dom/client';
import './style.css';
import './harbor.css';

type Status = {active:boolean; state:string; operation:string|null; activity:string|null; result:any; error:string|null;
  account?:{id:string;nickname:string;tag:string};account_pending?:boolean;
  manual_control:boolean;settings_update:string|null;
  resource_farming?:ResourceStatus;
  platform:{stage:string;message:string;ready:boolean;busy:boolean;error:string|null;game_update?:string|null}|null};
type Entry = {id:number; level:string; text:string; at:string};
type Field = {key:string;label:string;description:string;kind:string;choices:string[];section:string;advanced:boolean;restart_required?:boolean;expert?:boolean};
type SettingsData = {revision:string;values:Record<string,any>;fields:Field[];themes:any[]};
type Part = {key:string;label:string;kind:string;configured:boolean;optional:boolean;advanced?:boolean;instructions:string};
type SetupData = {revision:string;steps:{id:string;label:string;parts:Part[]}[]};
type Capture = {id:string;width:number;height:number;revision:string;at:string;taps?:number[][];jitter?:number};
let csrf='';
const FIRST_LAUNCH=location.pathname.startsWith('/first-launch');
const BASE=FIRST_LAUNCH?'/first-launch':'';
const BASIC_SETTINGS=new Set(['gui_timing_preset','donate_open_requests','farm_enabled','farm_engine',
  'farm_resource_start_percent','farm_resource_target_percent','gui_theme','gui_show_debug_activity','gui_dev_options']);
const toolCategory=(id:string)=>['health_check','classify_screen','zoom_home'].includes(id)?'Device':
  ['open_clan_chat','find_classify_request','open_donation','close_donation','scroll_chat','anti_idle'].includes(id)?'Donations':
  ['inspect_attack','farm_open_attack','farm_start_search','farm_classify','farm_deploy_dry','farm_clear_deploy'].includes(id)?'Attacks':'System';
async function api(path:string, method='GET', body?:unknown) {
  const response=await fetch(BASE+'/api/'+path,{method,headers:{
    'Content-Type':'application/json',...(method==='GET'?{}:{'X-CSRF-Token':csrf})},
    body:body===undefined?undefined:JSON.stringify(body)});
  if(!response.ok) {
    let text=await response.text();
    try{const parsed=JSON.parse(text);if(typeof parsed.detail==='string')text=parsed.detail;}catch{}
    if(response.status===401) window.dispatchEvent(new Event('session-expired'));
    throw new Error(text || 'Request failed');
  }
  return response.json();
}

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
  const [savingSettings,setSavingSettings]=useState(false);
  const draftVersion=useRef(0);
  const loadVersion=useRef(0);
  const [workspaceAccount,setWorkspaceAccount]=useState<{id:string;nickname:string}|null>(null);
  const [workspaceLoaded,setWorkspaceLoaded]=useState(false);
  const [setup,setSetup]=useState<SetupData|null>(null),[selected,setSelected]=useState('');
  const [queue,setQueue]=useState<string[]>([]),[collection,setCollection]=useState<any>(null);
  const [galleryOffset,setGalleryOffset]=useState(0),[galleryTotal,setGalleryTotal]=useState(0);
  const [capture,setCapture]=useState<Capture|null>(null),[editor,setEditor]=useState<Part|null>(null);
  const [backups,setBackups]=useState<{id:string;label:string}[]>([]);
  const [gallery,setGallery]=useState<{id:string;label:string}[]>([]);
  const [practice,setPractice]=useState(false),[busy,setBusy]=useState(false);
  const [viewer,setViewer]=useState(false);
  const [live,setLive]=useState(false);
  const [libraryTab,setLibraryTab]=useState('Calibrations'),[toolGroup,setToolGroup]=useState('Upgrades');
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
    const version=++loadVersion.current;
    const draft=draftVersion.current;
    const workspace=await api('workspace');
    if(version!==loadVersion.current||draft!==draftVersion.current)return;
    const {settings:a,setup:b,backups:c,library:d}=workspace;
    setWorkspaceAccount(workspace.account);setWorkspaceLoaded(true);
    draftVersion.current++;
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
    if(signed&&status&&workspaceLoaded&&!dirty&&!editor&&!status.account_pending
      &&(workspaceAccount?.id??null)!==(status?.account?.id??null))attempt(reload);
  },[signed,workspaceLoaded,dirty,editor,status?.account?.id,status?.account_pending,workspaceAccount?.id]);
  useEffect(()=>{
    const handler=(e:BeforeUnloadEvent)=>{if(dirty||editor){e.preventDefault();}};
    window.addEventListener('beforeunload',handler);
    return ()=>window.removeEventListener('beforeunload',handler);
  },[dirty,editor]);
  useEffect(()=>{const feed=logEnd.current?.parentElement;if(scroll&&feed)feed.scrollTop=feed.scrollHeight;},[logs,scroll]);
  useEffect(()=>{
    if(!pendingCapture.current||status?.active||status?.operation!=='capture')return;
    pendingCapture.current=false;
    if(status.result?.id){setCapture(status.result);setEditor(captureIntent);}
    else setNotice(status.error||'Screenshot could not be captured');
  },[status]);
  useLayoutEffect(()=>{
    const palette=harborPalette;
    document.documentElement.dataset.interface='harbor';
    document.documentElement.dataset.appearance=palette.appearance;
    document.documentElement.style.colorScheme=palette.appearance;
    for(const [key,value] of Object.entries(paletteProperties(palette)))
      document.documentElement.style.setProperty(key,value);
  },[]);
  async function captureScreen(part:Part|null=null,pan=false){
    setCaptureIntent(part);pendingCapture.current=true;
    const result=await attempt(()=>api('capture'+(pan?'/pan':''),'POST'));
    if(!result)pendingCapture.current=false;
  }
  function navigate(next:string){
    if(next===page)return;
    if(dirty&&!confirm('Leave these unsaved settings?'))return;
    if(dirty&&settings){draftVersion.current++;setValues(settings.values);setDirty(false);}
    setPage(next);
  }
  const [advancedSetup,setAdvancedSetup]=useState(false);
  const setupSteps=(setup?.steps??[]).map(s=>({...s,parts:s.parts.filter(p=>advancedSetup||!p.advanced)})).filter(s=>s.parts.length);
  function advance(){
    if(queue.length){setSelected(queue[0]);setQueue(queue.slice(1));}
    else {const all=setupSteps.flatMap(s=>s.parts);if(all.length)setSelected(all[(all.findIndex(p=>p.key===(part?.key||selected))+1)%all.length].key);}
  }
  function beginSetup(missing:boolean){
    const keys=setupSteps.flatMap(s=>s.parts).filter(p=>!missing||(!p.configured&&!p.optional)).map(p=>p.key);
    if(!keys.length){setNotice('All required calibration parts are saved');return;}
    setSelected(keys[0]);setQueue(keys.slice(1));
  }
  const accountChanged=workspaceLoaded&&(workspaceAccount?.id??null)!==(status?.account?.id??null);
  const restartRequired=settings?.fields.some(f=>f.restart_required!==false&&
    (['int','float'].includes(f.kind)?Number(values[f.key])!==Number(settings.values[f.key]):values[f.key]!==settings.values[f.key]))??false;
  const canStop=!!(status?.active||status?.manual_control||status?.settings_update||savingSettings||status?.platform?.busy);
  const locked=!!status?.active||!!status?.manual_control||!!status?.settings_update||!!status?.platform?.busy||busy||!online||accountChanged;
  const part=setupSteps.flatMap(s=>s.parts).find(p=>p.key===selected)||setupSteps[0]?.parts[0];
  async function save(){
    const version=draftVersion.current;
    setSavingSettings(true);
    setNotice('');
    try {
      const updated=await api('settings','PUT',{revision:settings!.revision,values});
      setSettings(updated);
      if(version===draftVersion.current){setValues(updated.values);setDirty(false);}
      setNotice(updated.restarted?'Settings saved — bot restarting':'Settings saved');
    } catch(e){setNotice((e as Error).message);}
    finally{setSavingSettings(false);}
  }
  function editSetting(key:string,value:any){
    draftVersion.current++;setValues(previous=>({...previous,[key]:value}));setDirty(true);
  }
  async function command(path:string,body?:unknown){
    const updated=await attempt(()=>api(path,'POST',body));
    if(updated)setStatus(updated as Status);
  }
  async function importGame(file:File){
    await attempt(async()=>{
      const response=await fetch(BASE+'/api/runtime/import-game',{method:'POST',
        headers:{'Content-Type':'application/zip','X-CSRF-Token':csrf},body:file});
      if(!response.ok)throw new Error(await response.text());
      setStatus(await response.json());setNotice('Game archive imported. Preparing Clash…');
    });
  }
  const activityPanel=(<section key="activity" className="activity panel"><div className="panel-label activity-controls"><span>Activity <span className="live-indicator"><i className={'status-dot '+(online?'connected':'')}/></span></span><div className="activity-options">
        <label className="toggle"><input type="checkbox" checked={debug} onChange={e=>setDebug(e.target.checked)}/>Debug</label>
        <label className="toggle"><input type="checkbox" checked={scroll} onChange={e=>setScroll(e.target.checked)}/>Auto-scroll</label>
        <button className="icon-button" aria-label="Copy activity" title="Copy activity" onClick={()=>navigator.clipboard.writeText(logs.map(x=>x.at+' '+x.level+' '+x.text).join('\n')).catch(()=>setNotice('Clipboard unavailable. Use Export in Tools.'))}><Icon name="copy" size={17}/></button></div></div>
        <div className="log" role="log" aria-label="Bot activity" aria-live="off">{logs.filter(x=>debug||x.level!=='DEBUG').map(x=><div className={'log-entry '+x.level.toLowerCase()} key={x.id}><time>{new Date(x.at).toLocaleTimeString(undefined,{hour12:false})}</time><i className="log-dot"/><span>{x.text}</span></div>)}
        {!logs.filter(x=>debug||x.level!=='DEBUG').length&&<EmptyState icon="overview">Activity will appear here</EmptyState>}<div ref={logEnd}/></div></section>);
  const resourcePanel=(<div key="resources" className="overview-side"><ResourceLevels data={status?.resource_farming}/>
      <label className="toggle overview-practice"><span>Practice mode</span><input type="checkbox" checked={practice} disabled={!!status?.active} onChange={e=>setPractice(e.target.checked)}/></label></div>);
  if(checkingSession||(!signed&&!passwordRequired))return <main className="login" role="status">Connecting…</main>;
  if(!signed)return <main className="login"><form onSubmit={e=>{e.preventDefault();attempt(async()=>{
    const result=await api('login','POST',{password});csrf=result.csrf;setSigned(true);setPassword('');
  });}}><h1>CoC Bot</h1><label>Password<input type="password" autoComplete="current-password"
    value={password} onChange={e=>setPassword(e.target.value)} required/></label>
    <button className="primary" disabled={busy}>Sign in</button><p role="alert">{notice}</p></form></main>;
  const fields=settings?.fields.filter(f=>f.key!=='gui_theme'&&(!f.advanced||values.gui_dev_options)&&
    (advanced||!f.expert)&&
    (advanced||BASIC_SETTINGS.has(f.key)||f.key.startsWith('upgrade_')||f.key.startsWith('progression_')||f.key.startsWith('builder_base_')||f.key.startsWith('layouts_')||f.key.startsWith('collection_'))&&
    (f.label+' '+f.description).toLowerCase().includes(search.toLowerCase()))||[];
  return <div className="app"><a className="skip-link" href="#main-content">Skip to content</a><aside className="sidebar"><a className="brand" href="#" onClick={e=>{e.preventDefault();navigate('Dashboard');}}><span className="brand-icon"><Icon name="castle" size={23}/></span><span>CoC Bot</span></a>
    <nav className="primary-nav" aria-label="Main navigation">{['Dashboard','Accounts','Settings','Setup','Library','Diagnostics'].map(p=><button key={p}
      aria-label={pageLabels[p]} title={pageLabels[p]} aria-current={page===p?'page':undefined} className={page===p?'selected':''} onClick={()=>navigate(p)}><Icon name={pageIcons[p]}/><span>{pageLabels[p]}</span>{page===p&&<i/>}</button>)}</nav>
    <div className="sidebar-bottom"><button className="account-shortcut" onClick={()=>navigate('Accounts')}><span className="avatar">{status?.account?.nickname?.slice(0,2).toUpperCase()||'CC'}</span><span><strong>{status?.account?.nickname||'No account selected'}</strong><small><i className={'status-dot '+(online?'connected':'')}/>{online?'Connected':'Reconnecting'}</small></span><Icon name="chevron" size={15}/></button>
    {FIRST_LAUNCH&&<button disabled={locked} onClick={()=>location.assign('/')}>Exit first-launch test</button>}
    {passwordRequired&&<button className="quiet" onClick={()=>attempt(async()=>{await api('logout','POST');expired();})}><Icon name="logout" size={17}/>Sign out</button>}</div></aside>
    <main id="main-content" className={'page page-'+page.toLowerCase()}>{FIRST_LAUNCH&&<div className="notice">First-launch test · changes are kept separate from your saved setup.</div>}
    <header className="page-header"><h1>{pageLabels[page]||page}</h1><div className="header-actions">
      {status?.account&&<button className="header-account quiet" title={status.account.nickname} onClick={()=>navigate('Accounts')}><span className="avatar">{status.account.nickname.slice(0,2).toUpperCase()}</span><span>{status.account.nickname}</span></button>}
      {!online&&<span className="connection"><i className="status-dot working"/>Reconnecting</span>}
      {page!=='Dashboard'&&canStop&&<button className="danger" disabled={!online} onClick={()=>command('stop')}><Icon name="stop" size={16}/>Stop</button>}
      <button className="live-button" aria-label="Live view" disabled={!online} onClick={()=>setLive(true)}><Icon name="video" size={18}/><span>Live view</span></button>
    </div></header>
    {notice&&<div className="notice" role="status"><span>{notice}</span><button className="icon-button" aria-label="Dismiss message" onClick={()=>setNotice('')}><Icon name="close" size={17}/></button></div>}
    {status?.account_pending&&page!=='Accounts'&&<div className="notice">Finish account setup before starting automation.<button onClick={()=>navigate('Accounts')}>Accounts</button></div>}
    {status?.platform&&!status.platform.ready&&<div className="notice" role="status">{status.platform.message}
      {!status.platform.busy&&<button disabled={locked} onClick={()=>command('runtime/retry')}>Retry startup</button>}
      {status.platform.stage==='needs_game'&&<label className="upload">Import Clash APK archive
        <input type="file" accept=".zip" disabled={locked} onChange={e=>{
          const file=e.target.files?.[0];e.target.value='';if(file)importGame(file);
        }}/></label>}
    </div>}
    {page==='Dashboard'&&<>
      <section className={'play panel '+(status?.active?'is-running':'')}>
      <div className="run-state"><span className={'run-indicator '+(status?.active?'running':status?.error?'failed':'')}><Icon name={status?.active?'refresh':status?.error?'info':'castle'} size={23}/></span>
        <div><div className="run-status"><span className={'status-dot '+(status?.active?'connected':status?.error?'failed':'')}/>{status?.manual_control?'Manual control':status?.active?(status.state==='running'?'Running':status.state.replaceAll('_',' ')):status?.state==='failed'?'Needs attention':'Stopped'}{practice&&<span className="badge">Practice</span>}</div>
        <strong className="run-activity">{status?.manual_control?'You have control':status?.active?(status.state==='stopping'?'Stopping safely…':status.activity||'Preparing automation'):status?.error?'Automation paused':status?.platform?.busy?'Preparing the game':'Ready when you are'}</strong></div>
      </div>
      <div className="controls"><button className="primary" disabled={locked||!!(status?.platform&&!status.platform.ready)} onClick={()=>command('start',{practice})}><Icon name="play" size={17}/>Start</button>
        <button className="danger" disabled={!online||!canStop} onClick={()=>command('stop')}><Icon name="stop" size={16}/>Stop</button>
        <button disabled={!online||busy||status?.manual_control||!!(status?.platform&&!status.platform.ready)||
          (status?.active&&(status.operation!=='bot'||status.state!=='running'))}
          onClick={()=>attempt(()=>api('farm','POST'))}><Icon name="swords" size={17}/>Farm now</button></div>
      {status?.error&&<div className="run-error" role="alert"><Icon name="info" size={17}/>{status.error}</div>}</section>
      <div className="dashboard-grid">{[resourcePanel,activityPanel]}</div>
    </>}
    {page==='Accounts'&&<Accounts api={api} locked={locked} result={status?.result} operation={status?.operation||null}
      working={!!status?.active} jobError={status?.error||null} live={()=>setLive(true)} onChanged={reload} stop={()=>command('stop')}/>}
    {accountChanged&&dirty&&<div className="notice" role="status">Your unsaved settings belong to {workspaceAccount?.nickname||'the previous profile'}. The active account has changed.
      <button onClick={()=>{if(confirm('Discard this draft and load the active account?'))attempt(reload);}}>Load active account</button></div>}
    {page==='Settings'&&<SettingsPanel fields={fields} values={values} search={search} setSearch={setSearch} advanced={advanced} setAdvanced={setAdvanced}
      dirty={dirty} saving={savingSettings||!!status?.settings_update} restarting={restartRequired&&!!status?.active&&status.operation==='bot'}
      saveDisabled={!online||busy||savingSettings||!!status?.settings_update||!!status?.manual_control||!!status?.account_pending||accountChanged||!dirty}
      resetDisabled={busy||savingSettings||!!status?.settings_update} save={save} reset={()=>{if(!dirty||confirm('Discard unsaved settings?'))attempt(reload);}}
      edit={editSetting} updateMessage={status?.settings_update}/>}
    {page==='Setup'&&<><div className="page-actions">
      <label className="toggle"><input type="checkbox" checked={advancedSetup} onChange={e=>{setAdvancedSetup(e.target.checked);setQueue([]);setSelected('');}}/>Advanced</label>
      <span className="item-count">{setupSteps.flatMap(s=>s.parts).filter(p=>p.configured).length} / {setupSteps.flatMap(s=>s.parts).length} configured</span><div className="action-spacer"/>
      <button disabled={locked||!setup} onClick={()=>beginSetup(false)}>Recalibrate all</button>
      <button className="primary" disabled={locked||!setup} onClick={()=>beginSetup(true)}><Icon name="setup" size={17}/>Set up missing</button>
      {!!queue.length&&<button onClick={()=>setQueue([])}>Exit guided setup</button>}</div>
      <div className="setup"><section className="checklist panel" aria-label="Calibration steps">
      {setupSteps.map(s=><details open key={s.id}><summary><span>{s.label}</span><small>{s.parts.filter(p=>p.configured).length}/{s.parts.length}</small></summary>{s.parts.map(p=><button key={p.key}
      aria-current={part?.key===p.key?'step':undefined} className={part?.key===p.key?'selected':''} onClick={()=>{setSelected(p.key);setQueue([]);}}>
        <span className={p.configured?'complete':'missing'}>{p.configured?<Icon name="check" size={14}/>:<i/>}</span><span>{p.label}</span></button>)}</details>)}
      </section><section className="guide panel">{part?<>
        <div className="guide-state"><span className={'badge '+(part.configured?'configured':'')}>{part.configured?'Configured':'Not configured'}</span>{part.optional&&<span className="badge">Optional</span>}</div>
        <h2>{part.label}</h2><p className="instructions">{part.instructions}</p>
        <div className="toolbar"><button className="primary" disabled={locked} onClick={()=>captureScreen(part)}>Capture screen</button>
        {part.key==='deploy_sequence'&&<button disabled={locked} onClick={()=>captureScreen(part,true)}>Pan and capture</button>}
        <button onClick={advance}>Skip<Icon name="chevron" size={15}/></button>
        </div>
      </>:<EmptyState icon="setup">Loading setup…</EmptyState>}</section></div></>}
    {page==='Library'&&<>
      <div className="page-actions"><div className="tabs" aria-label="Library views">{['Calibrations','Screenshots'].map(tab=><button key={tab} aria-pressed={libraryTab===tab} className={libraryTab===tab?'selected':''} onClick={()=>setLibraryTab(tab)}>{tab}</button>)}</div><div className="action-spacer"/><button className="icon-button" aria-label="Refresh library" onClick={()=>attempt(reload)}><Icon name="refresh" size={18}/></button></div>
      {libraryTab==='Calibrations'&&<><div className="toolbar"><button className="primary" disabled={locked} onClick={()=>attempt(async()=>{await api('backups','POST');await reload();})}><Icon name="plus" size={17}/>Back up calibration</button>
        <button disabled={locked} onClick={()=>{const name=prompt('Profile name');if(name)attempt(async()=>{await api('profiles','POST',{name});await reload();});}}>Save profile</button>
        <label className="upload">Import calibration<input type="file" accept=".zip" disabled={locked} onChange={e=>{
          const file=e.target.files?.[0];if(!file)return;const name=prompt('Imported calibration name',file.name.replace(/\.zip$/i,''));
          if(name)attempt(async()=>{const response=await fetch(BASE+'/api/backups/import?name='+encodeURIComponent(name),{
            method:'POST',headers:{'X-CSRF-Token':csrf,'Content-Type':'application/zip'},body:file});
            if(!response.ok)throw new Error(await response.text());await reload();});e.target.value='';
        }}/></label>
        </div>
      <section className="backup-list panel">{backups.map(b=><div className="setting backup-row" key={b.id}><span><Icon name="library" size={18}/>{b.label}</span><div className="toolbar">
        <button disabled={locked} onClick={()=>confirm('Restore this calibration? A safety backup will be saved.')&&attempt(async()=>{await api('backups/'+b.id+'/restore','POST');await reload();})}>Restore</button>
        <a href={BASE+'/api/backups/'+b.id+'/export'} download>Export</a>
        <button disabled={locked} onClick={()=>{const name=prompt('Calibration name',b.label);if(name)attempt(async()=>{await api('backups/'+b.id,'PATCH',{name});await reload();});}}>Rename</button>
        <button className="danger-quiet" disabled={locked} onClick={()=>confirm('Delete this saved calibration?')&&attempt(async()=>{await api('backups/'+b.id,'DELETE');await reload();})}>Delete</button>
      </div></div>)}{!backups.length&&<EmptyState icon="library">No saved calibrations</EmptyState>}</section></>}
      {libraryTab==='Screenshots'&&<>{collection&&<div className="collection-status"><span className={'status-dot '+(!collection.paused?'connected':'')}/>{collection.paused?'Paused: '+collection.paused:
        'Collecting'}<span>{collection.stats?.saved??0} saved</span><span>{Math.round((collection.approximate_storage_bytes??0)/1024/1024)} MB</span></div>}
      <div className="gallery">{gallery.map(x=><a key={x.id} href={BASE+'/api/library/images/'+x.id} target="_blank" rel="noreferrer">
        <img src={BASE+'/api/library/images/'+x.id} alt={x.label} loading="lazy"/><span>{x.label}</span></a>)}</div>
      {!gallery.length&&<EmptyState icon="image">No screenshots collected yet</EmptyState>}
      {galleryTotal>24&&<div className="toolbar">{[-24,24].map(delta=><button key={delta}
        disabled={galleryOffset+delta<0||galleryOffset+delta>=galleryTotal}
        onClick={()=>attempt(async()=>{const next=galleryOffset+delta,data=await api('library?offset='+next);setGallery(data.images);setGalleryOffset(next);})}>
        {delta<0?'Previous':'Next'}</button>)}</div>}</>}
    </>}
    {page==='Diagnostics'&&<>
      <div className="page-actions"><div className="tabs" aria-label="Tool categories">{['Upgrades','Device','Donations','Attacks','System'].map(group=><button key={group} aria-pressed={toolGroup===group} className={toolGroup===group?'selected':''} onClick={()=>setToolGroup(group)}>{group}</button>)}</div></div>
      {toolGroup==='Attacks'&&<AttackPlanner api={api} base={BASE} result={status?.result} locked={locked}/>}
      {toolGroup==='Upgrades'&&<div className="upgrade-grid">{(['buildings','research','pets'] as const).map(kind=>{
        const report=status?.result?.upgrade_report&&status.result.kind===kind?status.result:null;
        return <section key={kind} className="panel upgrade-card">
          <div className="upgrade-card-label"><span className="tool-icon"><Icon name={{buildings:'hammer',research:'swords',pets:'heart'}[kind]} size={23}/></span><span>{{buildings:'Building upgrades',research:'Army research',pets:'Pet upgrades'}[kind]}</span></div><div className="upgrade-actions">
            <button disabled={locked} onClick={()=>command('upgrades/preview',{kind})}>Check upgrades</button>
            <button disabled={locked||report?.status!=='ready'||!report?.token} onClick={()=>{
              const item=report.selected;
              if(confirm(`Start ${item.name} for ${item.cost.toLocaleString()} ${item.currency.replaceAll('_',' ')}?`))
                command('upgrades/start',{kind,token:report.token});
            }}>Start recommended upgrade</button></div>
          {report&&<div role="status">
            {report.message&&<p>{report.message}</p>}
            {report.availability&&<p>{report.availability[0]} / {report.availability[1]} {{buildings:'builders',research:'research slots',pets:'pet-upgrade slots'}[kind]} free</p>}
            {report.recommendations?.map((item:any,index:number)=><div className="setting" key={index}>
              <span>{item.name}</span><span>{item.cost.toLocaleString()} {item.currency.replaceAll('_',' ')} · {item.skip||'Eligible'}</span>
            </div>)}
          </div>}
        </section>;
      })}</div>}
      {toolGroup==='System'&&status?.platform&&<div className="toolbar">
        <button disabled={locked} onClick={()=>command('runtime/update-game')}>Update Clash</button>
        {status.platform.game_update&&<span role="status">{status.platform.game_update}</span>}
      </div>}
      {(toolGroup==='Device'||toolGroup==='System')&&<div className="toolbar">{toolGroup==='Device'&&<><button disabled={locked} onClick={()=>captureScreen()}><Icon name="image" size={17}/>Current screenshot</button>
        <button disabled={locked} onClick={()=>setViewer(true)}>Open game</button></>}
        {!!values.gui_dev_options&&<button disabled={locked} onClick={()=>attempt(async()=>{
          if(!FIRST_LAUNCH)await api('first-launch/reset','POST');
          location.assign(FIRST_LAUNCH?'/':'/first-launch/');
        })}>
          {FIRST_LAUNCH?'Exit first-launch test':'Simulate first launch'}</button>}
        <button onClick={()=>attempt(async()=>{const data=await api('readiness');setNotice(data.issues.length?data.issues.join(' · '):'Calibration checks passed');})}>Check calibration</button>
        <button onClick={()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([logs.map(x=>x.at+' '+x.level+' '+x.text).join('\n')],{type:'text/plain'}));a.download='bot-activity.txt';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}}>Export activity</button>
        <a href={BASE+'/api/report'} download="bot-report.json">Download report</a></div>}
      <section className="diagnostic-list">{[['health_check','Check device'],['classify_screen','Recognize screen'],['zoom_home','Test zoom out at home'],['inspect_attack','Inspect army and opponent map'],['open_clan_chat','Open clan chat'],
        ['find_classify_request','Inspect request'],['open_donation','Open donation'],['close_donation','Close donation'],
        ['scroll_chat','Scroll chat'],['anti_idle','Test inactivity nudge'],['farm_open_attack','Open Attack menu'],
        ['farm_start_search','Start opponent search'],['farm_classify','Recognize battle'],
        ['farm_deploy_dry','Preview deploy taps'],['farm_clear_deploy','Clear deploy sequence'],
        ['force_stop','Close Clash'],['close_waydroid','Close Waydroid and Clash'],
        ['relaunch','Relaunch Clash']].filter(([id])=>toolCategory(id)===toolGroup).map(([id,label])=>
        <button className="diagnostic-action panel" key={id} disabled={locked}
          onClick={()=>{if(id==='farm_clear_deploy'&&!confirm('Remove your saved farm deploy sequence?'))return;
            attempt(()=>api('diagnostics/'+id,'POST'));}}><Icon name={pageIcons[toolGroup==='Device'?'Diagnostics':toolGroup==='Attacks'?'Attacks':'Setup']} size={19}/><span>{label}</span><Icon name="chevron" size={16}/></button>)}</section>
      {toolGroup==='Attacks'&&status?.result?.attack_observation&&!status.result.survey&&<AttackObservation report={status.result} base={BASE}
        save={(id,revision,corrections)=>api('attack-observations/'+id,'PATCH',{revision,corrections})}/>}
      {status?.result&&!status.result?.id&&!status.result?.upgrade_report&&!status.result?.attack_observation&&<pre className="result">{typeof status.result==='string'?status.result:JSON.stringify(status.result,null,2)}</pre>}
    </>}
    </main>
    {viewer&&<GameViewer close={()=>setViewer(false)}/>}
    {live&&<LiveView close={()=>setLive(false)} active={!!status?.active} recovering={!!status?.platform?.busy} ready={status?.platform?.ready??true} stop={()=>command('stop')}/>}
    {capture&&<Editor key={capture.id+':'+editor?.key} capture={capture} part={editor} locked={locked} refresh={()=>captureScreen(editor)}
      close={()=>{setCapture(null);setEditor(null);}}
      save={async(selection,cols,rows,jitter)=>{const saved=await attempt(()=>api('setup','POST',{
        capture:capture.id,part:editor!.key,selection,revision:capture.revision,cols,rows,jitter}));
        if(saved){setSetup(saved as SetupData);setCapture(null);setEditor(null);setNotice('Calibration saved');if(queue.length)advance();}}}/>}
  </div>;
}

function LiveView({close,active,recovering,ready,stop}:{close:()=>void;active:boolean;recovering:boolean;ready:boolean;stop:()=>void}){
  const dialog=useRef<HTMLElement|null>(null);useDialog(dialog,close);
  const video=useRef<HTMLVideoElement>(null);
  const socket=useRef<WebSocket|null>(null),gesture=useRef<{point:number[];pointer:number;token:string}|null>(null);
  const pointerInputAt=useRef(-Infinity);
  const [token,setToken]=useState<string|null>(null),[controlError,setControlError]=useState(''),[playing,setPlaying]=useState(false);
  function send(value:object){if(socket.current?.readyState===WebSocket.OPEN)socket.current.send(JSON.stringify(value));}
  function point(e:React.PointerEvent<HTMLVideoElement>|React.MouseEvent<HTMLVideoElement>){
    const v=e.currentTarget,r=v.getBoundingClientRect();
    if(!v.videoWidth||!v.videoHeight)return null;
    const scale=Math.min(r.width/v.videoWidth,r.height/v.videoHeight),w=v.videoWidth*scale,h=v.videoHeight*scale;
    const x=(e.clientX-r.left-(r.width-w)/2)/w,y=(e.clientY-r.top-(r.height-h)/2)/h;
    return x>=0&&x<=1&&y>=0&&y<=1?[x,y]:null;
  }
  const [state,setState]=useState('Connecting…'),[error,setError]=useState('');
  const [fps,setFps]=useState<number|null>(null);
  const [retry,setRetry]=useState(0);
  const runtimeWasRecovering=useRef(false);
  useEffect(()=>{
    if(recovering)runtimeWasRecovering.current=true;
    else if(runtimeWasRecovering.current){
      runtimeWasRecovering.current=false;
      if(ready&&error)setRetry(x=>x+1);
    }
  },[recovering,ready,error]);
  useEffect(()=>{
    let disposed=false,failed=false,timer:ReturnType<typeof setInterval>,timeout:ReturnType<typeof setTimeout>;
    let frameTimer:ReturnType<typeof setInterval>,lastFrames=0,lastCheck=performance.now(),lastProgress=performance.now(),sampled=false;
    const pc=new RTCPeerConnection({iceServers:[]});
    pc.addTransceiver('video',{direction:'recvonly'});
    const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+BASE+'/api/live/ws');
    socket.current=ws;setToken(null);setPlaying(false);gesture.current=null;
    setError('');setState('Connecting…');setFps(null);
    const element=video.current,played=()=>{clearTimeout(timeout);lastProgress=performance.now();};
    element?.addEventListener('playing',played);
    function fail(message:string){if(disposed||failed)return;failed=true;setPlaying(false);setFps(null);setToken(null);gesture.current=null;setState('Unavailable');setError(message);clearInterval(timer);clearInterval(frameTimer);clearTimeout(timeout);ws.close();pc.close();}
    pc.ontrack=e=>{if(video.current){video.current.srcObject=new MediaStream([e.track]);video.current.play().catch(()=>fail('Playback blocked. Close and reopen Live view.'));}};
    pc.onconnectionstatechange=()=>{
      if(pc.connectionState==='failed')fail('Live connection failed. Retry to reconnect.');
    };
    ws.onmessage=async e=>{
      try{
        const m=JSON.parse(e.data);
        if(m.type==='control'){setToken(m.token);setControlError(m.message||'');gesture.current=null;return;}
        if(m.type==='error'){fail(m.message);return;}
        if(m.type==='ready'){
          await pc.setLocalDescription(await pc.createOffer());
          // Send a complete offer, including LAN ICE candidates. No public relay.
          if(pc.iceGatheringState!=='complete')await new Promise<void>(resolve=>{
            const changed=()=>{if(pc.iceGatheringState==='complete'){pc.removeEventListener('icegatheringstatechange',changed);resolve();}};
            pc.addEventListener('icegatheringstatechange',changed);changed();
          });
          if(!disposed&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'offer',sdp:pc.localDescription!.sdp}));
        }
        if(m.type==='answer'){
          await pc.setRemoteDescription({type:'answer',sdp:m.sdp});
          timer=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'ping'}));},5000);
          frameTimer=setInterval(async()=>{
            if(disposed||failed)return;
            try{
              const stats=await pc.getStats();let frames:number|undefined;
              stats.forEach(report=>{if(report.type==='inbound-rtp'&&(report.kind==='video'||report.mediaType==='video')&&typeof report.framesDecoded==='number')frames=report.framesDecoded;});
              if(disposed||failed)return;
              frames??=element?.getVideoPlaybackQuality?.().totalVideoFrames;
              const now=performance.now();
              if(document.visibilityState!=='visible'){lastProgress=now;sampled=false;setFps(null);return;}
              if(typeof frames!=='number')return;
              if(sampled){
                setFps(Math.max(0,Math.round((frames-lastFrames)*1000/(now-lastCheck))));
                if(frames>lastFrames)lastProgress=now;
                else if(element?.readyState===4&&now-lastProgress>12000)fail('Video stopped updating. Retry to reconnect the live stream.');
              }else{lastProgress=now;sampled=true;}
              lastFrames=frames;lastCheck=now;
            }catch{if(!disposed&&!failed)fail('Unable to verify live video. Retry to reconnect.');}
          },2000);
        }
      }catch(e){fail((e as Error).message);}
    };
    ws.onclose=()=>{if(!disposed)fail('Live view disconnected. Retry to reconnect.');};
    ws.onerror=()=>fail('Unable to connect to live view.');
    timeout=setTimeout(()=>fail('Live view timed out. Check the device connection and retry.'),25000);
    return ()=>{disposed=true;clearInterval(timer);clearInterval(frameTimer);clearTimeout(timeout);ws.close();pc.close();socket.current=null;gesture.current=null;element?.removeEventListener('playing',played);if(element)element.srcObject=null;};
  },[retry]);
  return <div className="modal-backdrop"><section ref={dialog} className="modal" role="dialog" aria-modal="true" aria-label="Live view">
    <div className="toolbar"><h2>Live view</h2><span>{playing&&!error?`${token?'Live · You have control':'Live · View only'}${fps===null?'':` · ${fps} fps`}`:state}</span>
      <button disabled={!playing||!!error||(!token&&active)} onClick={()=>{gesture.current=null;setControlError('');send({type:token?'release_control':'take_control'});}}>{token?'Release control':'Take control'}</button>
      <button className="danger" disabled={!active&&!token&&!recovering} onClick={()=>{gesture.current=null;stop();}}>Stop</button><button onClick={close}>Close</button></div>
    {controlError&&<div className="notice" role="alert">{controlError}</div>}
    {error&&<div className="notice" role="alert">{error}<button onClick={()=>setRetry(x=>x+1)}>Retry</button></div>}
    <video ref={video} hidden={!!error} className={'game live-video'+(token?' controlled':'')} autoPlay playsInline muted onPlaying={()=>{setPlaying(true);setState('Live');}}
      onPointerDown={e=>{if(!token||e.button!==0)return;const p=point(e);if(!p)return;gesture.current={point:p,pointer:e.pointerId,token};e.currentTarget.setPointerCapture(e.pointerId);e.preventDefault();}}
      onPointerCancel={()=>{gesture.current=null;}}
      onPointerUp={e=>{const g=gesture.current;if(!g||g.pointer!==e.pointerId)return;gesture.current=null;const p=point(e);if(!p||!token||token!==g.token)return;
        pointerInputAt.current=performance.now();
        const v=e.currentTarget;const swipe=Math.hypot((p[0]-g.point[0])*v.videoWidth,(p[1]-g.point[1])*v.videoHeight)>12;
        send({type:swipe?'swipe':'tap',from:g.point,to:p,token});}}
      onClick={e=>{if(!token||performance.now()-pointerInputAt.current<500)return;const p=point(e);if(p)send({type:'tap',from:p,token});}}/>
    {token&&<div className="toolbar"><button onClick={()=>send({type:'key',key:'back',token})}>Android Back</button><button onClick={()=>send({type:'key',key:'home',token})}>Android Home</button></div>}
  </section></div>;
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
  const [suggesting,setSuggesting]=useState(false),[suggestionNote,setSuggestionNote]=useState('');
  const canSuggest=new Set(['donation_panel','donation_elixir_button','donation_troop_bar',
    'donation_spell_bar','troop_bar','spell_bar']).has(part?.key||'');
  async function suggest(){
    setSuggesting(true);setSuggestionNote('');
    try{
      const result=await api('captures/'+capture.id+'/suggestions');
      const proposed=result.proposals.find((p:{part:string})=>p.part===part?.key);
      if(proposed){setMode('box');setPoints([]);setBox(proposed.selection);
        if(proposed.cols)setCols(proposed.cols);if(proposed.rows)setRows(proposed.rows);}
      setSuggestionNote(result.message);
    }catch(error){setSuggestionNote(error instanceof Error?error.message:'Unable to suggest an area. Draw it manually.');}
    finally{setSuggesting(false);}
  }
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
    if(box.length){ctx.fillRect(...box as [number,number,number,number]);ctx.strokeRect(...box as [number,number,number,number]);
      if(part?.kind==='grid'&&Number.isInteger(cols)&&cols>=1&&cols<=20&&Number.isInteger(rows)&&rows>=1&&rows<=10){
        const [x,y,w,h]=box;ctx.font='bold 18px sans-serif';
        for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){
          ctx.strokeRect(x+c*w/cols,y+r*h/rows,w/cols,h/rows);
          ctx.strokeText(String(r*cols+c+1),x+(c+.5)*w/cols,y+(r+.5)*h/rows);
        }
      }
    }
    points.forEach(([x,y],i)=>{
      ctx.beginPath();ctx.arc(x,y,sequence?Math.SQRT2*jitter:8,0,Math.PI*2);ctx.fill();ctx.stroke();
      // Existing engine varies each axis independently. The circle encloses
      // its furthest diagonal offset; the number does not inflate that radius.
      ctx.font='bold 20px sans-serif';ctx.fillStyle='#fff';ctx.strokeStyle='#101820';ctx.lineWidth=4;
      ctx.strokeText(String(i+1),x+12,y-12);ctx.fillText(String(i+1),x+12,y-12);
      ctx.fillStyle='#55d4ff44';ctx.strokeStyle='#55d4ff';ctx.lineWidth=3;
    });
  }
  useEffect(paint,[points,box,jitter,cols,rows]);
  function coordinate(e:React.PointerEvent){
    const rect=e.currentTarget.getBoundingClientRect();
    return [Math.max(0,Math.min(capture.width-1,Math.round((e.clientX-rect.left)*capture.width/rect.width))),
      Math.max(0,Math.min(capture.height-1,Math.round((e.clientY-rect.top)*capture.height/rect.height)))];
  }
  return <div className="modal-backdrop"><section ref={dialog} className="modal" role="dialog" aria-modal="true"
    aria-label={part?.label||'Game screenshot'}><div className="toolbar"><h2>{part?.label||'Game screenshot'}</h2>
    <button disabled={locked} onClick={refresh}>Refresh screenshot</button><button onClick={close}>Cancel</button></div>
    {part&&<p className="instructions">{part.instructions}</p>}
    {canSuggest&&<div className="toolbar"><button disabled={locked||suggesting} onClick={suggest}>
      {suggesting?'Finding area…':'Suggest area'}</button>
      <span role="status">{suggestionNote||'Preview a suggested area, then check it before saving.'}</span></div>}
    {part?.kind==='tap'&&<select aria-label="Selection type" value={mode} onChange={e=>{setMode(e.target.value);setBox([]);setPoints([]);}}>
      <option value="point">Click a point</option><option value="box">Box the button and save its picture</option></select>}
    <canvas ref={canvas} width={capture.width} height={capture.height}
      onPointerDown={e=>{if(!part||part.key==='frame_width'||locked||suggesting)return;e.currentTarget.setPointerCapture(e.pointerId);
        const p=coordinate(e);if(sequence)setPoints([...points,p]);else if(mode==='point')setPoints([p]);else{origin.current=p;setBox([]);}}}
      onPointerMove={e=>{if(!origin.current)return;const [x,y]=coordinate(e),[a,b]=origin.current;
        setBox([Math.min(a,x),Math.min(b,y),Math.abs(x-a),Math.abs(y-b)]);}}
      onPointerUp={()=>{origin.current=null;}} onPointerCancel={()=>{origin.current=null;}}/>
    {sequence&&<div className="toolbar"><label>Farm tap variation ±{jitter} px per axis<input type="range" min="0" max="40"
      value={jitter} onChange={e=>setJitter(Number(e.target.value))}/></label>
      <button onClick={()=>setPoints(points.slice(0,-1))}>Undo</button><button onClick={()=>setPoints([])}>Clear</button><span>{points.length} taps</span></div>}
    {part?.kind==='grid'&&<div className="toolbar"><label>Columns<input type="number" min="1" max="20" value={cols} onChange={e=>setCols(Number(e.target.value))}/></label>
      <label>Rows<input type="number" min="1" max="10" value={rows} onChange={e=>setRows(Number(e.target.value))}/></label></div>}
    {part&&<button className="primary" disabled={locked||suggesting||(part.key!=='frame_width'&&!points.length&&!box.length)}
      onClick={()=>save(sequence?points:part.key==='frame_width'?[]:mode==='point'?points[0]:box,cols,rows,jitter)}>Save</button>}
  </section></div>;
}
createRoot(document.getElementById('root')!).render(<App/>);

import {RefractiveLayer} from './RefractiveLayer';
import React,{useState} from 'react';
import {EmptyState,Icon} from './ui';

type Field={key:string;label:string;description:string;kind:string;choices:string[];section:string;advanced:boolean};
const categories=[['General','settings'],['Donations','heart'],['Attacks','swords'],['Upgrades','hammer'],
  ['Builder Base','castle'],['Appearance','palette'],['Screenshots','image'],['Device','link']];
function category(f:Field){
  if(f.key.startsWith('builder_base_'))return 'Builder Base';
  if(/^(upgrade_|progression_|layouts_)/.test(f.key))return 'Upgrades';
  if(f.key.startsWith('farm_'))return 'Attacks';
  if(f.key.startsWith('collection_'))return 'Screenshots';
  if(['gui_theme','gui_show_debug_activity','gui_dev_options'].includes(f.key))return 'Appearance';
  if(f.section==='Donation')return 'Donations';
  if(/Device|Clan/.test(f.section))return 'Device';
  return 'General';
}

function SettingRow({field:f,value,edit}:{field:Field;value:any;edit:(v:any)=>void}){
  const [help,setHelp]=useState(false);
  return <div className={'setting '+(help?'help-open':'')}>
    <div className="setting-name"><label htmlFor={f.key}>{f.label}</label>{f.description&&<button type="button" className="icon-button field-help"
      aria-label={'Help for '+f.label} aria-expanded={help} aria-controls={f.key+'-help'} title={f.description} onClick={()=>setHelp(!help)}><Icon name="info" size={15}/></button>}</div>
    {f.kind==='bool'?<input id={f.key} className="switch" type="checkbox" checked={!!value} onChange={e=>edit(e.target.checked)}/>:
      f.kind==='choice'?<select id={f.key} value={value??''} onChange={e=>edit(e.target.value)}>{f.choices.map(c=><option key={c}>{c}</option>)}</select>:
      <input id={f.key} value={value??''} type={['int','float'].includes(f.kind)?'number':'text'} min={0} step={f.kind==='float'?'any':1} onChange={e=>edit(e.target.value)}/>}
    {help&&<p id={f.key+'-help'} className="setting-description">{f.description}</p>}
  </div>;
}

export function SettingsPanel({fields,values,search,setSearch,advanced,setAdvanced,dirty,saving,restarting,saveDisabled,resetDisabled,save,reset,edit,updateMessage}: {
  fields:Field[];values:Record<string,any>;search:string;setSearch:(s:string)=>void;advanced:boolean;setAdvanced:(v:boolean)=>void;
  dirty:boolean;saving:boolean;restarting:boolean;saveDisabled:boolean;resetDisabled:boolean;save:()=>void;reset:()=>void;
  edit:(key:string,value:any)=>void;updateMessage?:string|null;
}){
  const [selected,setSelected]=useState('General');
  const available=categories.filter(([name])=>fields.some(f=>category(f)===name));
  const active=available.some(([name])=>name===selected)?selected:available[0]?.[0];
  const shown=fields.filter(f=>search.trim()||category(f)===active);
  return <div className="settings-workspace">
    <div className="page-actions settings-actions"><label className="search-field"><Icon name="search" size={18}/><input aria-label="Search settings" placeholder="Find a setting…" value={search} onChange={e=>setSearch(e.target.value)}/>
      {search&&<button className="icon-button" aria-label="Clear search" onClick={()=>setSearch('')}><Icon name="close" size={15}/></button>}</label>
      <label className="toggle"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)}/>Advanced</label>
      <div className="action-spacer"/>{(dirty||saving)&&<><button disabled={resetDisabled||!dirty} onClick={reset}>Discard</button>
      <button disabled={saveDisabled} className="primary" onClick={save}><Icon name={saving?'refresh':'check'} size={17}/>{saving?'Applying…':restarting?'Save & restart':'Save changes'}</button>
      </>}
    </div>
    <div className="settings-layout"><nav className="settings-nav" aria-label="Setting categories">{available.map(([name,icon])=><button key={name} aria-current={!search&&active===name?'page':undefined}
      className={!search&&active===name?'selected':''} onClick={()=>{setSelected(name);setSearch('');}}><Icon name={icon} size={18}/>{name}</button>)}</nav>
      <div className="settings-content">
      {updateMessage&&<div className="notice" role="status">{updateMessage}</div>}
      <section className="settings panel refractive-glass"><RefractiveLayer radius={16}/>{shown.map(f=><SettingRow key={f.key} field={f} value={values[f.key]} edit={v=>edit(f.key,v)}/>)}
      {!shown.length&&<EmptyState icon="search">No matching settings</EmptyState>}</section></div>
    </div>
  </div>;
}

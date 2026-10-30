import React,{useLayoutEffect,useState} from 'react';

export const interfaces=[
  {id:'original',label:'Original'},
  {id:'watchtower',label:'Watchtower'},
  {id:'harbor',label:'Harbor'},
] as const;
export type InterfaceId=typeof interfaces[number]['id'];
const valid=(value:unknown):value is InterfaceId=>interfaces.some(item=>item.id===value);
export function interfaceStorageKey(firstLaunch=false){
  return 'coc-bot.interface'+(firstLaunch?'.first-launch':'');
}
// A display preference belongs to this browser, not the currently selected game account.
// Storage can be blocked in private/embedded browsers; switching must still work.
export function readInterface(storage:Pick<Storage,'getItem'>|undefined,key:string):InterfaceId{
  try{const value=storage?.getItem(key);return valid(value)?value:'original';}
  catch{return 'original';}
}
export function writeInterface(storage:Pick<Storage,'setItem'>|undefined,key:string,value:InterfaceId){
  try{storage?.setItem(key,value);}catch{/* Keep the in-memory choice. */}
}
function storage(){try{return window.localStorage;}catch{return undefined;}}
export function useInterface(firstLaunch=false){
  const key=interfaceStorageKey(firstLaunch);
  const [current,setCurrent]=useState(()=>readInterface(storage(),key));
  useLayoutEffect(()=>{document.documentElement.dataset.interface=current;},[current]);
  function choose(value:string){
    if(!valid(value))return;
    writeInterface(storage(),key,value);setCurrent(value);
  }
  return [current,choose] as const;
}
export function InterfacePicker({value,onChange}:{value:InterfaceId;onChange:(value:string)=>void}){
  return <label className="interface-picker"><span>Interface</span>
    <select aria-label="Interface" title="Saved in this browser; applies immediately" value={value}
      onChange={event=>onChange(event.target.value)}>
      {interfaces.map(item=><option value={item.id} key={item.id}>{item.label}</option>)}
    </select></label>;
}

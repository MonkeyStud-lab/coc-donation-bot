import React from 'react';

const paths:Record<string,React.ReactNode>={
  overview:<><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
  accounts:<><circle cx="9" cy="8" r="3"/><path d="M3 21v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 4a6 6 0 0 1 3 5"/></>,
  swords:<><path d="M14.5 17.5 3 6V3h3l11.5 11.5M13 19l6-6m-3 3 4 4m-1 1 2-2M14.5 6.5 18 3h3v3l-3.5 3.5M5 13l6 6m-3-3-4 4m-1-1 2 2"/></>,
  settings:<><path d="M4 7h7m5 0h4M4 17h3m5 0h8"/><circle cx="13.5" cy="7" r="2.5"/><circle cx="9.5" cy="17" r="2.5"/></>,
  setup:<><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/></>,
  library:<><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18m-11 5h4"/></>,
  tools:<><path d="m14 6 4 4M4 20l8-8m2-8a6 6 0 0 0-7 7l-4 4a3 3 0 0 0 4 4l4-4a6 6 0 0 0 8-8l-4 4-3-3 4-4Z"/></>,
  castle:<><path d="M3 21V8h4V4h3v4h4V4h3v4h4v13H3Zm0-7h18M9 21v-5h6v5"/></>,
  play:<path d="m9 5 11 7-11 7V5Z"/>,stop:<rect x="6" y="6" width="12" height="12" rx="2"/>,
  video:<><rect x="3" y="5" width="12" height="14" rx="2"/><path d="m15 9 6-3v12l-6-3"/></>,
  copy:<><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M15 8V4H4v11h4"/></>,
  search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  refresh:<><path d="M20 11a8 8 0 0 0-14-5L3 9m0-6v6h6m-5 4a8 8 0 0 0 14 5l3-3m0 6v-6h-6"/></>,
  check:<path d="m5 12 4 4L19 6"/>,chevron:<path d="m9 5 7 7-7 7"/>,
  plus:<path d="M12 5v14M5 12h14"/>,close:<path d="m6 6 12 12M6 18 18 6"/>,
  info:<><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/></>,
  edit:<><path d="m15 5 4 4M4 20l5-1L21 7l-4-4L5 15l-1 5Z"/></>,
  image:<><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 3 4-6 5 7"/></>,
  hammer:<><path d="m13 3 8 8-4 4-8-8 4-4ZM11 9l-8 8a2.12 2.12 0 0 0 3 3l8-8"/></>,
  link:<><path d="m10 14 4-4m-5 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m0 8a4 4 0 0 0 6 0l4-4a4 4 0 0 0-6-6l-1 1"/></>,
  palette:<><path d="M12 3a9 9 0 1 0 0 18h1a2 2 0 0 0 1-4c-2-1 1-3 3-3h2a2 2 0 0 0 2-2 9 9 0 0 0-9-9Z"/><path d="M7 9h.1M11 6h.1M16 8h.1M6 14h.1"/></>,
  heart:<path d="M20 5a5 5 0 0 0-8 1 5 5 0 0 0-8-1c-4 5 3 10 8 15 5-5 12-10 8-15Z"/>,
  logout:<><path d="M9 3H4v18h5m0-9h12m-5-5 5 5-5 5"/></>,
};

export function Icon({name,size=20,...props}:{name:string;size?:number}&React.SVGProps<SVGSVGElement>){
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...props}>{paths[name]||paths.settings}</svg>;
}

export function EmptyState({icon='library',children}:{icon?:string;children:React.ReactNode}){
  return <div className="empty-state"><Icon name={icon} size={28}/><span>{children}</span></div>;
}

export const pageIcons:Record<string,string>={Dashboard:'overview',Accounts:'accounts',Attacks:'swords',Settings:'settings',Setup:'setup',Library:'library',Diagnostics:'tools'};
export const pageLabels:Record<string,string>={Dashboard:'Overview',Accounts:'Accounts',Attacks:'Attacks',Settings:'Settings',Setup:'Setup',Library:'Library',Diagnostics:'Tools'};

export type ResourceStatus={enabled:boolean;start_percent:number;target_percent:number;status:string;message?:string;
  observed_at?:number;observation?:{resources:string[];balances:Record<string,number>;capacities:Record<string,number>}};
const number=new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1});
export function ResourceLevels({data}:{data?:ResourceStatus}){
  const labels:Record<string,string>={gold:'Gold',elixir:'Elixir',dark_elixir:'Dark elixir'};
  const observation=data?.observation;
  return <section className="resource-card panel">
    <div className="panel-label"><span title={data?.observed_at?'Last checked '+new Date(data.observed_at*1000).toLocaleString():undefined}>Resources</span><span className="badge">{data?.enabled?`${data.start_percent}% → ${data.target_percent}%`:'Refill off'}</span></div>
    {observation?.resources?.length?<div className="resource-levels">{observation.resources.map(resource=>{
      const balance=observation.balances[resource],capacity=observation.capacities[resource];
      const known=Number.isFinite(balance)&&Number.isFinite(capacity)&&capacity>0;
      const percent=known?Math.min(100,Math.max(0,balance/capacity*100)):0;
      return <div className={'resource '+resource} key={resource}>
        <div className="resource-caption"><span><i/>{labels[resource]||resource}</span><strong>{known?Math.round(percent)+'%':'—'}</strong></div>
        <div className="resource-track" role={known?'meter':undefined} aria-label={labels[resource]||resource} aria-valuemin={known?0:undefined} aria-valuemax={known?100:undefined}
          aria-valuenow={known?Math.round(percent):undefined} aria-valuetext={known?`${balance.toLocaleString()} of ${capacity.toLocaleString()}`:'Not yet read'}>
          <span style={{width:percent+'%'}}/>
          {data?.enabled&&<i style={{left:Math.min(100,Math.max(0,data.target_percent))+'%'}}/>}
        </div><div className="resource-amount">{known?<>{number.format(balance)} <span>/ {number.format(capacity)}</span></>:'Not yet read'}</div>
      </div>;
    })}</div>:<EmptyState icon="refresh">Waiting for a resource check</EmptyState>}
    {data?.message&&<div className="resource-status" role="status"><span className={'status-dot '+(data.status==='refilling'?'working':'')}/>{data.message}</div>}
  </section>;
}

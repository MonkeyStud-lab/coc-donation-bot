import React,{useEffect,useRef,useState} from 'react';
import {AttackObservation} from './AttackObservation';
import {mapTransform,inverse,transform} from './attackGeometry';

type Point={x:number;y:number};
type Step={action:string;unit_id:string;quantity:number;points:Point[];seconds:number};
type Plan={army:{unit_id:string;kind:string;quantity:number;confirmed:boolean}[];steps:Step[];schema_version:number;mode:string;strategy:string};

export function AttackPlanner({api,base,result,locked,stop,operation}:{api:(p:string,m?:string,b?:unknown)=>Promise<any>;base:string;result:any;locked:boolean;stop:()=>void;operation?:string|null}){
  const [report,setReport]=useState<any>(null),[plan,setPlan]=useState<Plan|null>(null);
  const [corners,setCorners]=useState<number[][]>([]),[mark,setMark]=useState(false),[target,setTarget]=useState<number|null>(null);
  const [pending,setPending]=useState<Point[]>([]),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[dirty,setDirty]=useState(false);
  const [saved,setSaved]=useState(false);const svg=useRef<SVGSVGElement>(null);
  function accept(next:any){setReport(next);setCorners(next.projection?.corners||[]);setPlan(next.plan||null);setDirty(false);setTarget(null);setMark(false);}
  useEffect(()=>{api('attack-planner').then(s=>{if(s.report)accept(s.report);setSaved(s.routine_saved);}).catch(e=>setMessage(String(e)));},[]);
  useEffect(()=>{if(result?.survey){if(result.observation_id!==report?.observation_id)accept(result);else setReport(result);}},[result?.observation_id,result?.revision]);
  async function action(fn:()=>Promise<any>){setBusy(true);setMessage('');try{await fn();}catch(e){setMessage(String(e));}finally{setBusy(false);}}
  const disabled=locked||busy;
  const images=report?base+'/api/attack-observations/'+report.observation_id+'/images/':'';
  const [w,h]=report?.survey?.reference_size||[1000,600];
  const [ox,oy]=report?.survey?.mosaic_offset||[0,0];
  const bounds=report?.survey?.mosaic_bounds||[0,0,w*2,h*2];
  const left=Math.min(bounds[0],...corners.map(p=>p[0]+ox-110)),top=Math.min(bounds[1],...corners.map(p=>p[1]+oy-110));
  const right=Math.max(bounds[0]+bounds[2],...corners.map(p=>p[0]+ox+110)),bottom=Math.max(bounds[1]+bounds[3],...corners.map(p=>p[1]+oy+110));
  const mapBounds=[left,top,right-left,bottom-top];
  function screen(point:Point){
    if(corners.length!==4)return [0,0];
    const matrix=mapTransform(corners);
    if(!matrix)return [0,0];
    const [x,y]=transform(matrix,(point.x-.1)/.8,(point.y-.1)/.8);
    return [x+ox,y+oy];
  }
  function world(x:number,y:number):Point{
    const matrix=mapTransform(corners),back=matrix?inverse(matrix):null;
    if(!back)return {x:NaN,y:NaN};
    const [u,v]=transform(back,x,y);
    return {x:.1+.8*u,y:.1+.8*v};
  }
  function click(e:React.MouseEvent<SVGSVGElement>){
    if(disabled||!svg.current)return;
    const pt=svg.current.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;
    const p=pt.matrixTransform(svg.current.getScreenCTM()!.inverse()),x=p.x-ox,y=p.y-oy;
    if(mark){setCorners(old=>{const points=[...old,[x,y]];if(points.length===4)setMark(false);return points;});setDirty(true);return;}
    if(target===null||!plan||corners.length!==4)return;
    const point=world(x,y);
    if(!Number.isFinite(point.x)||!Number.isFinite(point.y)||point.x<0||point.x>1||point.y<0||point.y>1){setMessage('Choose a point on the village or its deployment border.');return;}
    const step=plan.steps[target],points=[...pending,point],needed=step.action==='deploy_line'?2:step.action==='cast_points'?step.quantity:1;
    if(points.length===needed){edit(target,{points});setPending([]);setTarget(null);}else setPending(points);
  }
  function edit(index:number,patch:Partial<Step>){setPlan(old=>old?{...old,steps:old.steps.map((s,i)=>i===index?{...s,...patch}:s)}:old);setDirty(true);}
  function move(index:number,delta:number){if(!plan)return;setTarget(null);setPending([]);const steps=[...plan.steps];[steps[index],steps[index+delta]]=[steps[index+delta],steps[index]];setPlan({...plan,steps});setDirty(true);}
  function add(){if(!plan?.army.length)return;const unit=plan.army[0];setPlan({...plan,steps:[...plan.steps,{action:unit.kind==='spell'?'cast_points':'deploy_point',unit_id:unit.unit_id,quantity:1,points:[],seconds:0}]});setDirty(true);}
  async function save(routine:boolean){
    if(!plan)return;
    const updated=await api('attack-planner/preview','POST',{observation_id:report.observation_id,revision:report.revision,plan,corners,save_routine:routine});
    setReport(updated);setDirty(false);if(routine)setSaved(true);setMessage(routine?'Routine saved.':'Preview validated. Ready for a supervised attack.');
  }
  return <>
    <div className="toolbar">
      <button disabled={disabled} onClick={()=>action(()=>api('attack-planner/automatic','POST'))}>Automatic attack</button>
      <button disabled={disabled} onClick={()=>action(()=>api('diagnostics/prepare_attack','POST'))}>Prepare opponent</button>
      <button disabled={disabled} onClick={()=>action(()=>api('diagnostics/survey_attack','POST'))}>Map current opponent</button>
      <button disabled={disabled} onClick={()=>action(()=>api('diagnostics/restore_attack_camera','POST'))}>Restore camera</button>
      <button className="danger" onClick={stop}>Stop</button>
      <span>{saved?'Routine saved':'No saved routine'}</span>
    </div>
    {result?.automatic_attack&&<p role="status">{result.message}</p>}
    {operation==='automatic_attack'&&locked&&<p role="status">Automatic attack running. Follow progress in Dashboard activity.</p>}
    {!report&&<p>Automatic attack reads your army and uses a built-in Electro Dragon routine. For custom steps, choose Prepare opponent instead.</p>}
    {report&&<>
      <details open={!report.plan}><summary>Review army · {report.cards.filter((c:any)=>c.confirmed).length}/{report.cards.length} checked</summary>
        <AttackObservation report={report} base={base} save={async(id,revision,corrections)=>{const updated=await api('attack-observations/'+id,'PATCH',{revision,corrections});setReport(updated);setDirty(true);return updated;}}/>
      </details>
      <div className="toolbar">
        <button disabled={disabled} onClick={()=>{setCorners([]);setMark(true);setTarget(null);setPending([]);setDirty(true);}}>Mark village corners</button>
        <button disabled={disabled||corners.length!==4} onClick={()=>action(async()=>{setPlan(await api('attack-observations/'+report.observation_id+'/default-plan'));setDirty(true);})}>Create Electro Dragon routine</button>
        <button disabled={disabled||!saved} onClick={()=>action(async()=>{setPlan(await api('attack-planner/routine'));setTarget(null);setPending([]);setDirty(true);})}>Load saved routine</button>
        <span role="status">{mark?['Click the top corner','Click the right corner','Click the bottom corner','Click the left corner'][corners.length]:target!==null?'Click '+(plan?.steps[target]?.action==='deploy_line'?'two line endpoints':plan?.steps[target]?.action==='cast_points'?'each spell target':'a deployment point'):corners.length===4?'Village corners marked':'Four village corners needed'}</span>
      </div>
      <svg ref={svg} className={'attack-map '+((mark||target!==null)?'placing':'')} viewBox={mapBounds.join(' ')} onClick={click} aria-label="Attack map">
        <image href={images+'mosaic.png'} width={w*2} height={h*2}/>
        {corners.length>1&&<polygon points={corners.map(([x,y])=>`${x+ox},${y+oy}`).join(' ')} fill="none" stroke="#63b3ff" strokeWidth="5"/>}
        {corners.map(([x,y],i)=><g key={'corner'+i}><circle cx={x+ox} cy={y+oy} r={13} fill="#63b3ff"/><text x={x+ox+18} y={y+oy} fill="white" fontSize={28}>{['Top','Right','Bottom','Left'][i]}</text></g>)}
        {plan?.steps.map((s,i)=><g key={i}>
          {s.action==='deploy_line'&&s.points.length===2&&<line x1={screen(s.points[0])[0]} y1={screen(s.points[0])[1]} x2={screen(s.points[1])[0]} y2={screen(s.points[1])[1]} stroke="#73e3a5" strokeWidth={7}/>}
          {s.points.map((point,j)=>{const [x,y]=screen(point);return <g key={j}><circle cx={x} cy={y} r={s.action==='cast_points'?35:19} fill={s.action==='cast_points'?'#a66bff88':'#73e3a5'}/><text x={x} y={y+8} textAnchor="middle" fill="white" stroke="#111" strokeWidth={1} fontSize={26}>{i+1}</text></g>;})}
        </g>)}
        {pending.map((p,i)=>{const [x,y]=screen(p);return <circle key={i} cx={x} cy={y} r={15} fill="white"/>;})}
      </svg>
      {plan&&<section className="attack-steps">{plan.steps.map((step,index)=><div className="attack-step" key={index}>
        <strong>{index+1}</strong>
        <select aria-label="Action" value={step.action} onChange={e=>edit(index,{action:e.target.value,points:[],unit_id:e.target.value==='wait'?'':step.unit_id,quantity:e.target.value==='wait'?0:1,seconds:e.target.value==='wait'?1:0})}>
          <option value="deploy_line">Deploy along line</option><option value="deploy_point">Deploy at point</option><option value="cast_points">Cast spells</option><option value="ability">Hero ability</option><option value="wait">Wait</option>
        </select>
        {step.action!=='wait'&&<select aria-label="Unit" value={step.unit_id} onChange={e=>edit(index,{unit_id:e.target.value,points:[]})}>{plan.army.map(u=><option value={u.unit_id} key={u.unit_id}>{u.unit_id.replaceAll('_',' ')}</option>)}</select>}
        <label>{step.action==='wait'?'Seconds':'Quantity'}<input type="number" min={step.action==='wait'?0.1:1} max={step.action==='wait'?210:300} step={step.action==='wait'?0.1:1} value={step.action==='wait'?step.seconds:step.quantity} onChange={e=>edit(index,step.action==='wait'?{seconds:Number(e.target.value)}:{quantity:Number(e.target.value),...(step.action==='cast_points'?{points:[]}:{})})}/></label>
        {!['wait','ability'].includes(step.action)&&<button disabled={disabled||corners.length!==4} onClick={()=>{setMark(false);setTarget(index);setPending([]);}}>Place on map</button>}
        <div className="toolbar"><button aria-label="Move up" disabled={index===0} onClick={()=>move(index,-1)}>↑</button><button aria-label="Move down" disabled={index===plan.steps.length-1} onClick={()=>move(index,1)}>↓</button><button onClick={()=>{setTarget(null);setPending([]);setPlan({...plan,steps:plan.steps.filter((_,i)=>i!==index)});setDirty(true);}}>Remove</button></div>
      </div>)}<button onClick={add}>Add step</button></section>}
      <div className="toolbar">
        <button disabled={disabled||!plan||corners.length!==4} onClick={()=>action(()=>save(false))}>Validate preview</button>
        <button disabled={disabled||!plan||corners.length!==4} onClick={()=>action(()=>save(true))}>Save routine</button>
        <button disabled={disabled||dirty||!report.plan||report.executed} onClick={()=>action(()=>api('attack-planner/execute','POST',{observation_id:report.observation_id,revision:report.revision}))}>Run this attack</button>
      </div>
      {report.execution&&<p role="status">Last custom run: {report.execution.reason} · {report.execution.verified_taps} verified deployments{report.returned_home?' · Home confirmed':''}</p>}
    </>}
    <p role="status">{message}</p>
  </>;
}

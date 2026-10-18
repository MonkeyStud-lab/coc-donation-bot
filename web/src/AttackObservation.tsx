import React, {useEffect, useState} from 'react';

export function AttackObservation({report,base,save}:{report:any;base:string;save:(id:string,revision:string,corrections:any[])=>Promise<any>}){
  const [review,setReview]=useState(report),[cards,setCards]=useState<any[]>(report.cards);
  const [busy,setBusy]=useState(false),[message,setMessage]=useState('');
  useEffect(()=>{setReview(report);setCards(report.cards);setMessage('');},[report.observation_id,report.revision]);
  function edit(index:number,key:string,value:any){setCards(old=>old.map((card,i)=>i===index?{...card,[key]:value}:card));}
  async function submit(){
    setBusy(true);setMessage('');
    try{
      if(cards.some(c=>c.confirmed&&(!c.unit_id||c.kind==='unknown'||c.quantity===null)))
        throw new Error('Enter the unit, type and quantity before checking a card.');
      const corrections=cards.map(c=>({
        slot:c.slot,unit_id:c.unit_id||null,kind:c.kind,quantity:c.quantity===null?null:Number(c.quantity),confirmed:!!c.confirmed}));
      const updated=await save(review.observation_id,review.revision,corrections);
      setReview(updated);setCards(updated.cards);setMessage('Review saved. Game and calibration unchanged.');
    }catch(error){setMessage(String(error));}finally{setBusy(false);}
  }
  const images=base+'/api/attack-observations/'+review.observation_id+'/images/';
  return <section className="army-observation">
    <div className="toolbar"><strong>{review.page==='battle'?'Opponent observation':'Army observation'}</strong>
      <span>{review.map?review.map.coverage+' map · ':''}Army review</span>
      <a href={images+'overlay.png'} target="_blank" rel="noreferrer">View marked screenshot</a></div>
    <div className="army-cards">{cards.map((card,index)=><div className="army-card-review" key={card.slot}>
      <img src={images+card.slot+'.png'} alt={'Card '+(index+1)} loading="lazy"/>
      <div className="army-card-fields">
        <strong>Card {index+1}{card.stable?' · Consistent reading':''}</strong>
        <label>Unit<input value={card.unit_id||''} maxLength={64} placeholder="Unknown — enter unit name"
          onChange={e=>edit(index,'unit_id',e.target.value.toLowerCase().replaceAll(' ','_'))}/></label>
        <label>Type<select value={card.kind} onChange={e=>edit(index,'kind',e.target.value)}>
          <option value="unknown">Unknown</option>{['troop','hero','siege','spell'].map(kind=><option key={kind} value={kind}>{kind}</option>)}
        </select></label>
        <label>Quantity<input type="number" min={0} max={300} step={1} value={card.quantity??''}
          onChange={e=>edit(index,'quantity',e.target.value===''?null:Number(e.target.value))}/></label>
        <label className="toggle"><input type="checkbox" checked={!!card.confirmed}
          onChange={e=>edit(index,'confirmed',e.target.checked)}/>I checked this card</label>
      </div>
    </div>)}</div>
    {review.map&&<p>{review.map.reason}</p>}
    <div className="toolbar"><button disabled={busy||!cards.length} onClick={submit}>{busy?'Saving…':'Save review'}</button>
      <span role="status">{message}</span></div>
  </section>;
}

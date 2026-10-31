import React,{useLayoutEffect,useRef} from 'react';
import {Container,type GlassRegion} from './vendor/liquid-glass/Container';

export const WALLPAPER='/harbor-abstract.jpg';
export function coverRectangle(iw:number,ih:number,width:number,height:number){
  const scale=Math.max(width/iw,height/ih);
  return {x:(width-iw*scale)/2,y:(height-ih*scale)/2,width:iw*scale,height:ih*scale};
}

// One wallpaper texture and GL context. React retains all native content/focus.
class GlassScene {
  readonly surfaces=new Map<HTMLElement,number>();
  readonly stage=document.createElement('div');
  private image=new Image();
  private texture=document.createElement('canvas');
  private renderer?:Container;
  private frame=0;
  private disposed=false;
  private unavailable=false;
  private preferences=window.matchMedia('(prefers-reduced-transparency: reduce), (prefers-contrast: more), (forced-colors: active)');
  private observer=new ResizeObserver(()=>this.schedule());
  constructor(){
    this.stage.className='glass-scene';this.stage.setAttribute('aria-hidden','true');
    document.body.prepend(this.stage);
    this.observer.observe(document.body);
    window.addEventListener('resize',this.schedule);
    // Scroll already arrives at a rendering boundary. Another RAF displayed the
    // previous position, especially during compositor scrolling.
    window.addEventListener('scroll',this.scroll,{passive:true});
    document.addEventListener('scroll',this.nestedScroll,{capture:true,passive:true});
    document.addEventListener('visibilitychange',this.schedule);
    this.preferences.addEventListener('change',this.schedule);
    this.image.onload=this.schedule;this.image.onerror=()=>this.fallback(true);
    this.image.src=WALLPAPER;
  }
  add(parent:HTMLElement,radius:number){
    this.surfaces.set(parent,radius);this.observer.observe(parent);this.schedule();
  }
  remove(parent:HTMLElement){
    this.surfaces.delete(parent);this.observer.unobserve(parent);delete parent.dataset.refraction;
    if(this.surfaces.size)this.schedule();else this.destroy();
  }
  private scroll=()=>this.paint();
  private nestedScroll=(event:Event)=>{
    const target=event.target;
    if(target instanceof Element&&[...this.surfaces.keys()].some(host=>target!==host&&target.contains(host)))this.paint();
  };
  private schedule=()=>{if(!this.disposed&&!this.frame)this.frame=requestAnimationFrame(this.paint);};
  private lost=(event:Event)=>{event.preventDefault();this.fallback(true);};
  private fallback(terminal=false){
    this.unavailable=terminal;
    this.renderer?.canvas.removeEventListener('webglcontextlost',this.lost);
    this.renderer?.destroy();this.renderer=undefined;
    for(const parent of this.surfaces.keys())parent.dataset.refraction='fallback';
  }
  private paint=()=>{
    cancelAnimationFrame(this.frame);this.frame=0;
    if(this.disposed||this.unavailable)return;
    if(this.preferences.matches){this.fallback();return;}
    if(document.hidden||!this.image.complete||!this.image.naturalWidth)return;
    const width=Math.max(1,document.documentElement.clientWidth),height=Math.max(1,document.documentElement.clientHeight);
    const resized=this.texture.width!==width||this.texture.height!==height;
    try{
      if(resized||!this.renderer){
        const context=this.texture.getContext('2d');if(!context)throw new Error('Wallpaper canvas unavailable');
        this.texture.width=width;this.texture.height=height;
        const rect=coverRectangle(this.image.naturalWidth,this.image.naturalHeight,width,height);
        context.drawImage(this.image,rect.x,rect.y,rect.width,rect.height);
      }
      if(!this.renderer){
        this.renderer=new Container(this.stage,this.texture,{manualDraw:true,controls:{blurRadius:0}});
        this.renderer.canvas.addEventListener('webglcontextlost',this.lost);
      }else if(resized)this.renderer.refresh(this.texture);
      const regions:GlassRegion[]=[];
      for(const [parent,radius] of this.surfaces){
        const rect=parent.getBoundingClientRect();
        if(rect.bottom<=0||rect.top>=height||rect.right<=0||rect.left>=width||!rect.width||!rect.height)continue;
        const style=getComputedStyle(parent);
        if(style.visibility==='hidden'||style.display==='none')continue;
        regions.push({left:rect.left,top:rect.top,width:rect.width,height:rect.height,
          radius:parseFloat(style.borderTopLeftRadius)||radius});
      }
      this.renderer.renderRegions(regions);
      for(const parent of this.surfaces.keys())parent.dataset.refraction='ready';
      // Read-only QA diagnostics without adding persistent interface elements.
      this.stage.dataset.scrollY=String(window.scrollY);
      this.stage.dataset.surfaces=String(this.surfaces.size);
      this.stage.dataset.visible=String(regions.length);
    }catch{this.fallback(true);}
  };
  private destroy(){
    this.disposed=true;cancelAnimationFrame(this.frame);this.observer.disconnect();
    window.removeEventListener('resize',this.schedule);window.removeEventListener('scroll',this.scroll);
    document.removeEventListener('scroll',this.nestedScroll,true);
    document.removeEventListener('visibilitychange',this.schedule);
    this.preferences.removeEventListener('change',this.schedule);
    this.image.onload=null;this.image.onerror=null;
    this.fallback();this.stage.remove();scene=undefined;
  }
}
let scene:GlassScene|undefined;
export function RefractiveLayer({radius}:{radius:number}){
  const mount=useRef<HTMLSpanElement|null>(null);
  useLayoutEffect(()=>{
    const parent=mount.current?.parentElement;if(!parent)return;
    const owner=scene??(scene=new GlassScene());owner.add(parent,radius);
    return ()=>owner.remove(parent);
  },[radius]);
  return <span hidden aria-hidden="true" ref={mount}/>;
}

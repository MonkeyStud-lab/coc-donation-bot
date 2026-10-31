import React,{useEffect,useRef} from 'react';
import {Container} from './vendor/liquid-glass/Container';

export const WALLPAPER='/harbor-abstract.jpg';
export function coverRectangle(iw:number,ih:number,width:number,height:number){
  const scale=Math.max(width/iw,height/ih);
  return {x:(width-iw*scale)/2,y:(height-ih*scale)/2,width:iw*scale,height:ih*scale};
}

// Real upstream refraction, drawn on load/resize/scroll rather than an idle loop.
// React retains ownership of all actual links, buttons, labels, and focus targets.
export function RefractiveLayer({radius}:{radius:number}){
  const mount=useRef<HTMLDivElement|null>(null);
  useEffect(()=>{
    const host=mount.current,parent=host?.parentElement;
    if(!host||!parent)return;
    let disposed=false,unavailable=false,renderer:Container|undefined,frame=0;
    const image=new Image(),texture=document.createElement('canvas');
    const preferences=window.matchMedia('(prefers-reduced-transparency: reduce), (prefers-contrast: more), (forced-colors: active)');
    const context=texture.getContext('2d');
    const fail=(terminal=false)=>{
      unavailable=terminal;
      renderer?.canvas.removeEventListener('webglcontextlost',lost);
      renderer?.destroy();renderer=undefined;parent.dataset.refraction='fallback';
    };
    function paint(){
      frame=0;
      if(disposed||unavailable||!context||!image.complete||!image.naturalWidth)return;
      if(preferences.matches){fail();return;}
      if(document.hidden)return;
      const width=Math.max(1,document.documentElement.clientWidth),height=Math.max(1,document.documentElement.clientHeight);
      const resized=texture.width!==width||texture.height!==height;
      if(resized||!renderer){
        texture.width=width;texture.height=height;
        const rect=coverRectangle(image.naturalWidth,image.naturalHeight,width,height);
        context!.drawImage(image,rect.x,rect.y,rect.width,rect.height);
      }
      try{
        if(renderer){
          renderer.borderRadius=parseFloat(getComputedStyle(parent!).borderTopLeftRadius)||radius;
          if(resized)renderer.refresh(texture);
          else renderer.resize();
        }
        else{
          renderer=new Container(host!,texture,{borderRadius:parseFloat(getComputedStyle(parent!).borderTopLeftRadius)||radius});
          renderer.canvas.addEventListener('webglcontextlost',lost);
        }
        parent!.dataset.refraction='ready';
      }catch{fail(true);}
    }
    function schedule(){if(!disposed&&!frame)frame=requestAnimationFrame(paint);}
    function lost(event:Event){event.preventDefault();fail(true);}
    const observer=new ResizeObserver(schedule);
    observer.observe(parent);
    preferences.addEventListener('change',schedule);
    window.addEventListener('resize',schedule);
    window.addEventListener('scroll',schedule,{passive:true});
    document.addEventListener('visibilitychange',schedule);
    image.onload=schedule;image.onerror=()=>fail(true);image.src=WALLPAPER;
    return ()=>{
      disposed=true;cancelAnimationFrame(frame);observer.disconnect();
      preferences.removeEventListener('change',schedule);
      window.removeEventListener('resize',schedule);window.removeEventListener('scroll',schedule);
      document.removeEventListener('visibilitychange',schedule);
      image.onload=null;image.onerror=null;
      renderer?.canvas.removeEventListener('webglcontextlost',lost);
      renderer?.destroy();delete parent.dataset.refraction;
    };
  },[radius]);
  return <div className="glass-mount" aria-hidden="true" ref={mount}/>;
}

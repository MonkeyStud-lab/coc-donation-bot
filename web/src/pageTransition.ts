import {useLayoutEffect} from 'react';
import type {RefObject} from 'react';

// Animate the existing element, rather than keying/remounting the page tree.
// New navigation cancels the previous animation immediately; input never waits.
export function animatePage(element:HTMLElement|null,reducedMotion:boolean){
  if(!element?.animate||reducedMotion)return;
  return element.animate(
    [{opacity:.65,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],
    {duration:180,easing:'cubic-bezier(.22,1,.36,1)'},
  );
}
export function usePageTransition(ref:RefObject<HTMLElement|null>,page:string){
  useLayoutEffect(()=>{
    const animation=animatePage(ref.current,window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    return ()=>animation?.cancel();
  },[page,ref]);
}

export type GlassRegion={left:number;top:number;width:number;height:number;radius:number;sourceLeft?:number;sourceTop?:number};
export function clipRegion(rect:Pick<GlassRegion,'left'|'top'|'width'|'height'>,width:number,height:number):{left:number;top:number;right:number;bottom:number}|null;
export class Container {
  constructor(host:HTMLElement,image:HTMLCanvasElement,options?:{borderRadius?:number;controls?:Record<string,number>;manualDraw?:boolean});
  canvas:HTMLCanvasElement;
  borderRadius:number;
  resize():void;
  refresh(image:HTMLCanvasElement):void;
  render():void;
  renderRegions(regions:GlassRegion[]):void;
  destroy():void;
}

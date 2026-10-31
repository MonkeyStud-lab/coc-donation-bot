export class Container {
  constructor(host:HTMLElement,image:HTMLCanvasElement,options?:{borderRadius?:number;controls?:Record<string,number>});
  canvas:HTMLCanvasElement;
  borderRadius:number;
  resize():void;
  refresh(image:HTMLCanvasElement):void;
  render():void;
  destroy():void;
}

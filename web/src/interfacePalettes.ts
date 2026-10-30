import type {InterfaceId} from './InterfacePicker';

export type InterfacePalette={
  appearance:'dark'|'light';bg:string;sidebar:string;surface:string;surface_hover:string;
  text:string;text_secondary:string;border:string;accent:string;accent_fg:string;
  danger:string;error:string;warning:string;success:string;field_bg:string;
  gold:string;elixir:string;dark_elixir:string;
};
// Named roles are shared across controls and content; no remote fonts or artwork.
// Watchtower's neutral chrome leaves the resource meters as its color moment.
export const slate:InterfacePalette={
  appearance:'dark',bg:'#17191c',sidebar:'#121416',surface:'#202328',surface_hover:'#2b3037',
  text:'#f0f1f3',text_secondary:'#b2b7c0',border:'#697586',accent:'#e5b567',accent_fg:'#20190e',
  danger:'#b93848',error:'#f2a1aa',warning:'#e5b567',success:'#8cc9a8',field_bg:'#17191c',
  gold:'#e5b567',elixir:'#c89bd5',dark_elixir:'#aaa4ce',
};
export const pearl:InterfacePalette={
  appearance:'light',bg:'#f4f5f7',sidebar:'#eceef2',surface:'#ffffff',surface_hover:'#e8ebf0',
  text:'#22262d',text_secondary:'#555e6b',border:'#737d8c',accent:'#2459b5',accent_fg:'#ffffff',
  danger:'#b52a3c',error:'#9d2436',warning:'#875b14',success:'#246b45',field_bg:'#ffffff',
  gold:'#967019',elixir:'#8b469c',dark_elixir:'#65608e',
};
export function interfacePalette(id:InterfaceId){return id==='harbor'?pearl:slate;}

export function paletteProperties(palette:InterfacePalette){
  return Object.fromEntries(Object.entries(palette).filter(([key])=>key!=='appearance')
    .map(([key,value])=>['--'+key.replaceAll('_','-'),value]));
}

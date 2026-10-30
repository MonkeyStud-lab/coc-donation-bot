export type InterfacePalette={
  appearance:'dark'|'light';bg:string;sidebar:string;surface:string;surface_hover:string;
  text:string;text_secondary:string;border:string;accent:string;accent_fg:string;
  danger:string;error:string;warning:string;success:string;field_bg:string;
  gold:string;elixir:string;dark_elixir:string;
};
// One semantic palette for Harbor; no account-dependent appearance state.
export const harborPalette:InterfacePalette={
  appearance:'light',bg:'#f4f5f7',sidebar:'#eceef2',surface:'#ffffff',surface_hover:'#e8ebf0',
  text:'#22262d',text_secondary:'#555e6b',border:'#737d8c',accent:'#2459b5',accent_fg:'#ffffff',
  danger:'#b52a3c',error:'#9d2436',warning:'#875b14',success:'#246b45',field_bg:'#ffffff',
  gold:'#967019',elixir:'#8b469c',dark_elixir:'#65608e',
};

export function paletteProperties(palette:InterfacePalette){
  return Object.fromEntries(Object.entries(palette).filter(([key])=>key!=='appearance')
    .map(([key,value])=>['--'+key.replaceAll('_','-'),value]));
}

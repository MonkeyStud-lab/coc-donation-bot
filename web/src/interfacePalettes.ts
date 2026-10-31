export type InterfacePalette={
  appearance:'dark'|'light';bg:string;sidebar:string;surface:string;surface_hover:string;
  text:string;text_secondary:string;border:string;accent:string;accent_fg:string;
  danger:string;error:string;warning:string;success:string;field_bg:string;
  gold:string;elixir:string;dark_elixir:string;
  cobalt:string;brass:string;
};
// One semantic palette for Harbor; no account-dependent appearance state.
export const harborPalette:InterfacePalette={
  appearance:'dark',bg:'#07090d',sidebar:'#0b0e14',surface:'#101319',surface_hover:'#1a1f29',
  text:'#f1f2f5',text_secondary:'#b9c2d1',border:'#737f94',accent:'#9cb9ff',accent_fg:'#07090d',
  danger:'#bf3448',error:'#ffabb4',warning:'#d1b17c',success:'#9ec9ac',field_bg:'#0a0d13',
  gold:'#c4a36c',elixir:'#91aaff',dark_elixir:'#adb5c7',cobalt:'#2448c7',brass:'#d4b27a',
};

export function paletteProperties(palette:InterfacePalette){
  return Object.fromEntries(Object.entries(palette).filter(([key])=>key!=='appearance')
    .map(([key,value])=>['--'+key.replaceAll('_','-'),value]));
}

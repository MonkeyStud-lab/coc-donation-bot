// Browser-independent component checks; never connects to Android or a profile.
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const server=await createServer({server:{middlewareMode:true},appType:'custom',optimizeDeps:{noDiscovery:true,include:[]}});
try {
  const {SettingsPanel}=await server.ssrLoadModule('/src/SettingsPanel.tsx');
  const props={fields:[{key:'gui_theme',label:'Theme',description:'Preview immediately',kind:'choice',choices:['Modern','Ember'],section:'Interface',advanced:false}],
    values:{gui_theme:'Ember'},search:'',setSearch(){},advanced:false,setAdvanced(){},dirty:false,saving:false,restarting:false,
    saveDisabled:false,resetDisabled:false,save(){},reset(){},edit(){}};
  const render=changes=>renderToStaticMarkup(React.createElement(SettingsPanel,{...props,...changes}));
  const clean=render({});assert.ok(clean.includes('Theme'));assert.ok(!clean.includes('Discard'));assert.ok(!clean.includes('Save changes'));
  assert.ok(!clean.includes('account-context'));assert.ok(!clean.includes('>Stop<'));
  const appearance=render({dirty:true});assert.ok(appearance.includes('Save changes'));assert.ok(!appearance.includes('Save &amp; restart'));
  assert.ok(render({dirty:true,restarting:true}).includes('Save &amp; restart'));
  assert.ok(render({dirty:true,saving:true}).includes('Applying…'));
  const {harborPalette,paletteProperties}=await server.ssrLoadModule('/src/interfacePalettes.ts');
  const {coverRectangle}=await server.ssrLoadModule('/src/RefractiveLayer.tsx');
  assert.deepEqual(coverRectangle(100,100,200,100),{x:0,y:-50,width:200,height:200});
  assert.deepEqual(coverRectangle(400,200,100,100),{x:-50,y:0,width:200,height:100});
  const {clipRegion}=await server.ssrLoadModule('/src/vendor/liquid-glass/Container.js');
  assert.deepEqual(clipRegion({left:20,top:30,width:200,height:100},800,600),{left:20,top:30,right:220,bottom:130});
  assert.deepEqual(clipRegion({left:-10,top:-10000,width:400,height:20000},800,600),{left:0,top:0,right:390,bottom:600});
  assert.deepEqual(clipRegion({left:799.5,top:599.5,width:200,height:100},800,600),{left:799,top:599,right:800,bottom:600});
  assert.equal(clipRegion({left:801,top:0,width:200,height:100},800,600),null);
  assert.equal(clipRegion({left:0,top:0,width:0,height:100},800,600),null);
  function luminance(hex){
    const rgb=hex.match(/[0-9a-f]{2}/gi).map(x=>parseInt(x,16)/255)
      .map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  }
  function contrast(a,b){const values=[luminance(a),luminance(b)].sort((a,b)=>a-b);return (values[1]+.05)/(values[0]+.05);}
  for(const palette of [harborPalette]){
    for(const surface of [palette.bg,palette.sidebar,palette.surface,palette.surface_hover]){
      for(const ink of [palette.text,palette.text_secondary,palette.accent,palette.error,palette.success])
        assert.ok(contrast(ink,surface)>=4.5,ink+' on '+surface+' needs readable contrast');
    }
    assert.ok(contrast(palette.accent_fg,palette.accent)>=4.5);
    assert.ok(contrast('#ffffff',palette.danger)>=4.5);
    assert.ok(contrast('#ffffff',palette.cobalt)>=4.5);
    assert.ok(contrast(palette.border,palette.field_bg)>=3,'Input boundaries need 3:1 contrast');
    for(const meter of [palette.gold,palette.elixir,palette.dark_elixir])
      assert.ok(contrast(meter,palette.surface)>=3);
    assert.equal(paletteProperties(palette)['--field-bg'],palette.field_bg);
    const blend=(hex,base,alpha)=>'#'+hex.match(/[0-9a-f]{2}/gi)
      .map((part,i)=>Math.round(parseInt(part,16)*alpha+parseInt(base.slice(1+i*2,3+i*2),16)*(1-alpha)).toString(16).padStart(2,'0')).join('');
    for(const backdrop of ['#000000','#ffffff']){
      const glass=blend('#05080e',backdrop,.74);
      for(const ink of [palette.text,palette.text_secondary,palette.accent,palette.brass])
        assert.ok(contrast(ink,glass)>=4.5,'Glass must stay readable over any wallpaper luminance');
    }
  }
  console.log('Settings component checks passed');
  console.log('Fixed wallpaper cover geometry passed');
  console.log('Shared viewport clipping: tall, partial, fractional, and offscreen surfaces passed');
  console.log('Harbor palette: readable text, actions, fields, and resource meters passed');
} finally {await server.close();}

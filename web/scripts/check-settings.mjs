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
  const {InterfacePicker,readInterface,writeInterface,interfaceStorageKey}=await server.ssrLoadModule('/src/InterfacePicker.tsx');
  const key=interfaceStorageKey();
  assert.notEqual(key,interfaceStorageKey(true),'First-launch tests must not overwrite the normal interface preference');
  assert.equal(readInterface(undefined,key),'original');
  assert.equal(readInterface({getItem:()=>'{broken preference'},key),'original');
  assert.equal(readInterface({getItem(){throw Error('Storage blocked');}},key),'original');
  const stored=new Map();
  const storage={getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)};
  for(const id of ['original','watchtower','harbor']){
    writeInterface(storage,key,id);assert.equal(readInterface(storage,key),id);
    const picker=renderToStaticMarkup(React.createElement(InterfacePicker,{value:id,onChange(){}}));
    assert.ok(picker.includes('aria-label="Interface"'));
    assert.ok(picker.includes('value="'+id+'" selected=""'));
    assert.equal((picker.match(/<option /g)||[]).length,3);
  }
  writeInterface({setItem(){throw Error('Storage blocked');}},key,'harbor');
  const {slate,pearl,interfacePalette,paletteProperties}=await server.ssrLoadModule('/src/interfacePalettes.ts');
  assert.equal(interfacePalette('watchtower'),slate);
  assert.equal(interfacePalette('harbor'),pearl);
  assert.equal(interfacePalette('original'),slate);
  function luminance(hex){
    const rgb=hex.match(/[0-9a-f]{2}/gi).map(x=>parseInt(x,16)/255)
      .map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  }
  function contrast(a,b){const values=[luminance(a),luminance(b)].sort((a,b)=>a-b);return (values[1]+.05)/(values[0]+.05);}
  for(const palette of [slate,pearl]){
    for(const surface of [palette.bg,palette.sidebar,palette.surface,palette.surface_hover]){
      for(const ink of [palette.text,palette.text_secondary,palette.accent,palette.error,palette.success])
        assert.ok(contrast(ink,surface)>=4.5,ink+' on '+surface+' needs readable contrast');
    }
    assert.ok(contrast(palette.accent_fg,palette.accent)>=4.5);
    assert.ok(contrast('#ffffff',palette.danger)>=4.5);
    assert.ok(contrast(palette.border,palette.field_bg)>=3,'Input boundaries need 3:1 contrast');
    for(const meter of [palette.gold,palette.elixir,palette.dark_elixir])
      assert.ok(contrast(meter,palette.surface)>=3);
    assert.equal(paletteProperties(palette)['--field-bg'],palette.field_bg);
  }
  console.log('Settings component checks passed');
  console.log('Interface choices, persistence, fallback, and isolated first-launch preference passed');
  console.log('Paired palettes: text 4.5:1, action labels 4.5:1, resource meters 3:1 passed');
} finally {await server.close();}

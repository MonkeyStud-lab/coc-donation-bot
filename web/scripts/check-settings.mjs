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
  console.log('Settings component checks passed');
} finally {await server.close();}

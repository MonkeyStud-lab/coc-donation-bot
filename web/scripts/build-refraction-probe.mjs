// Builds a separate developer fixture, never into the distributed application.
import {build} from 'vite';
await build({configFile:false,publicDir:false,base:'./',build:{
  outDir:'../data/debug/refraction-probe',emptyOutDir:true,
  rollupOptions:{input:'scripts/refraction-probe.html'},
}});

const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person1',thumb:'thumb/person1/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:1},
 {stem:'a2',chat:'person1',thumb:'thumb/person1/a2.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
// server-side foldermeta state (mutated by setcover) — simulates persistence
let serverMeta={};
function mk(beforeParse){return new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse});}
function fetchStub(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['person1'])});
   if(u.indexOf('/foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(serverMeta)))});
   if(u.indexOf('/setcover')>=0){var b=JSON.parse(opts.body); serverMeta[b.folder]=serverMeta[b.folder]||{}; if(b.stem) serverMeta[b.folder].cover=b.stem; else delete serverMeta[b.folder].cover; return Promise.resolve({status:200,text:()=>Promise.resolve('{}'),json:()=>Promise.resolve({})});}
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}
function coverSrc(doc){var g=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person1')g=f;});var c=g?g.querySelector('img.cover'):null;return c?c.getAttribute('src'):'(none)';}
function rclick(el){el.dispatchEvent(new (el.ownerDocument.defaultView.MouseEvent)('contextmenu',{bubbles:true,cancelable:true,clientX:10,clientY:10}));}
function click(el){el.dispatchEvent(new (el.ownerDocument.defaultView.MouseEvent)('click',{bubbles:true,cancelable:true}));}
// SESSION 1: open person1, set a2 as cover
var dom1=mk(fetchStub);
setTimeout(()=>{ try{
 var doc=dom1.window.document;
 console.log('default cover (newest a1):',coverSrc(doc));
 // open person1, right-click a2 tile -> set cover. Simpler: call setFolderCover directly via a tile
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person1')p1=f;});
 click(p1); // open folder
 setTimeout(()=>{
   var tiles=doc.querySelectorAll('#photoGrid .tile');
   // find a2 tile, right-click -> Set as folder cover
   var a2tile=null;tiles.forEach(t=>{if(t.dataset.stem==='a2')a2tile=t;});
   rclick(a2tile);
   var menu=doc.getElementById('ctxMenu'); var setBtn=null;
   menu.querySelectorAll('button').forEach(b=>{if(b.textContent.indexOf('Set as folder cover')>=0)setBtn=b;});
   click(setBtn);
   setTimeout(()=>{
     console.log('serverMeta after set:',JSON.stringify(serverMeta));
     // SESSION 2: fresh load (simulate refresh) — does the cover persist?
     var dom2=mk(fetchStub);
     setTimeout(()=>{
       var doc2=dom2.window.document;
       var src=coverSrc(doc2);
       console.log('cover after refresh:',src);
       console.log(src.indexOf('a2')>=0?'PASS cover persisted across refresh':'FAIL cover reset (expected a2)');
       process.exit(0);
     },700);
   },150);
 },200);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

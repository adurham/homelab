const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'F1',thumb:'thumb/F1/a1.jpg',file:'f',type:'image',date:'2026-01-02',size:1},
 {stem:'a2',chat:'F1',thumb:'thumb/F1/a2.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
let markBody=null, batchCalled=false, queueDepth=2;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F1'])});
   if(u.indexOf('/trashmark')>=0){markBody=JSON.parse(opts.body);return Promise.resolve({status:200,json:()=>Promise.resolve({marked:markBody.stems.length,queue_depth:queueDepth})});}
   if(u.indexOf('/trashbatch')>=0){batchCalled=true;return Promise.resolve({status:200,json:()=>Promise.resolve({deleted:1})});}
   if(u.indexOf('/trashqueue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:queueDepth,reaped:0,failed:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};window.AbortController=window.AbortController||function(){this.signal={};this.abort=function(){};};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F1')p1=f;});
 click(p1);
 var tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
 var t0=Date.now();
 click(doc.getElementById('bulkDelete'));
 // immediately after click, tiles should already be gone (instant) without waiting for fetch
 setTimeout(()=>{
   var remain=doc.querySelectorAll('#photoGrid .tile').length;
   console.log('tiles remaining immediately after delete:',remain,'(expect 0 - instant)', remain===0?'PASS':'FAIL');
   console.log('used /trashmark:',!!markBody,'| used old /trashbatch:',batchCalled, (markBody&&!batchCalled)?'PASS instant path':'FAIL');
   console.log('trashmark body:',JSON.stringify(markBody));
   var bg=doc.getElementById('bgTasks');
   console.log('bg indicator shown:',bg.classList.contains('show'), bg.classList.contains('show')?'PASS':'(may need poll)');
 },150); setTimeout(()=>process.exit(0),1200);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);

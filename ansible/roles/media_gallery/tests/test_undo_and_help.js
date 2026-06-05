const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'F1',thumb:'thumb/F1/a1.jpg',file:'f',type:'image',date:'2026-01-01',size:1},
 {stem:'a2',chat:'F1',thumb:'thumb/F1/a2.jpg',file:'f',type:'image',date:'2026-01-02',size:1}];
let undoBody=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F1'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('/trashmark')>=0)return Promise.resolve({status:200,json:()=>Promise.resolve({marked:1})});
   if(u.indexOf('/trashundo')>=0){undoBody=JSON.parse(opts.body);return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({restored_count:undoBody.stems.length,too_late:[]})});}
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
function key(k){doc.dispatchEvent(new window.KeyboardEvent('keydown',{key:k,bubbles:true}));}
setTimeout(()=>{ try{
 // T1: help overlay via ? key
 key('?');
 console.log('=== T1 help overlay ===');
 console.log('helpScrim shown:',doc.getElementById('helpScrim').classList.contains('show')?'PASS':'FAIL');
 key('Escape');
 // T2: delete -> undo button
 var f1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F1')f1=f;});
 click(f1);
 setTimeout(()=>{
   var tiles=doc.querySelectorAll('#photoGrid .tile');
   click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
   click(doc.getElementById('bulkDelete'));
   setTimeout(()=>{
     var undoBtn=doc.querySelector('#toast .toast-undo');
     console.log('=== T2 undo button on delete toast ===');
     console.log('undo button present:',!!undoBtn?'PASS':'FAIL');
     if(undoBtn){ click(undoBtn);
       setTimeout(()=>{ console.log('undo body:',JSON.stringify(undoBody));
         console.log(undoBody&&undoBody.stems.length===2?'PASS undo sent 2 stems':'FAIL'); process.exit(0); },150);
     } else process.exit(1);
   },200);
 },200);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person_1',file:'by-chat/person_1/a1.jpg',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01',size:1000},
 {stem:'a2',chat:'person_1',file:'by-chat/person_1/a2.jpg',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02',size:2000},
];
const folders=['person_1','EmptyFolder'];   // EmptyFolder has no items
let delBody=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(folders)});
   if(u.indexOf('/trashbatch')>=0){ delBody=JSON.parse(opts.body); return Promise.resolve({status:200,json:()=>Promise.resolve({deleted:delBody.stems.length})}); }
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=(m)=>{window.__a=m;};window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};window.AbortController=window.AbortController||function(){this.signal={};this.abort=function(){};};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 console.log('=== T1 empty folder shows on landing ===');
 var names=[].map.call(doc.querySelectorAll('#folderGrid .folder .fname'),e=>e.textContent);
 console.log('folders shown:',names.join(','));
 console.log(names.indexOf('EmptyFolder')>=0?'PASS empty folder visible':'FAIL empty folder missing');
 console.log('=== T2 batch delete ===');
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 var tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[1].querySelector('.selbox'));
 click(doc.getElementById('bulkDelete'));
 setTimeout(()=>{
   console.log('trashbatch body:',JSON.stringify(delBody));
   var ok=delBody&&delBody.chat==='person_1'&&delBody.stems.length===2;
   console.log(ok?'PASS one /trashbatch with both stems':'FAIL');
 },200);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);

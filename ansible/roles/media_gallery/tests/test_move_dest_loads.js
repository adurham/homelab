const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'F1',file:'by-chat/F1/a1.jpg',thumb:'thumb/F1/a1.jpg',type:'image',date:'2026-01-02',size:1}];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F1','F2'])});
   if(u.indexOf('/movemark')>=0)return Promise.resolve({status:200,json:()=>Promise.resolve({marked:1})});
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F1')p1=f;});
 click(p1);
 var tile=doc.querySelector('#photoGrid .tile');
 click(tile.querySelector('.selbox'));
 click(doc.getElementById('bulkMove'));
 var p2=null;doc.querySelectorAll('#bulkMoveMenu button').forEach(b=>{if(b.textContent.indexOf('F2')>=0)p2=b;});
 click(p2);
 setTimeout(()=>{
   // go back to landing, then into F2
   click(doc.getElementById('backBtn'));
   var f2=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='F2')f2=f;});
   if(!f2){console.log('FAIL: F2 folder not on landing');process.exit(1);}
   click(f2);
   setTimeout(()=>{
     var t=doc.querySelector('#photoGrid .tile');
     var img=t?t.querySelector('img'):null;
     var src=img?(img.getAttribute('data-src')||img.getAttribute('src')||''):'NO TILE';
     console.log('F2 tile present:',!!t,'| a1 thumb src:',src);
     console.log(src.indexOf('/F1/')>=0?'PASS: moved item shows in F2 but loads thumb from ORIGINAL F1 path (no 404)':'FAIL: '+src);
     process.exit(0);
   },250);
 },200);
}catch(e){console.log('EXC:',e.message);process.exit(1);} },800);

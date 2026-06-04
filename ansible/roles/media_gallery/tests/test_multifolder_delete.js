const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'F1',file:'f',thumb:'thumb/F1/a1.jpg',type:'image',date:'2026-01-01',size:1},
 {stem:'b1',chat:'F2',file:'f',thumb:'thumb/F2/b1.jpg',type:'image',date:'2026-01-02',size:1},
 {stem:'c1',chat:'F3',file:'f',thumb:'thumb/F3/c1.jpg',type:'image',date:'2026-01-03',size:1},
 {stem:'d1',chat:'F4',file:'f',thumb:'thumb/F4/d1.jpg',type:'image',date:'2026-01-04',size:1}];
const rmdirCalls=[];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F1','F2','F3','F4'])});
   if(u.indexOf('/rmdir/')>=0){rmdirCalls.push(decodeURIComponent(u.split('/rmdir/')[1]));return Promise.resolve({status:200,json:()=>Promise.resolve({removed:true})});}
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
 window.requestAnimationFrame=(cb)=>setTimeout(cb,0);
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 var folders=doc.querySelectorAll('#folderGrid .folder');
 console.log('=== T1 folder selboxes present ===');
 var withSel=[].filter.call(folders,f=>f.querySelector('.fselbox')).length;
 console.log('folders with selbox:',withSel,'(expect 4)', withSel>=4?'PASS':'FAIL');
 // select 3 folders
 var picked=0;
 folders.forEach(f=>{ if(picked<3 && f.dataset.chat && f.dataset.chat!=='*'){ var sb=f.querySelector('.fselbox'); if(sb){ click(sb); picked++; } } });
 var bar=doc.getElementById('fbulkBar');
 console.log('=== T2 fbulk bar ===');
 console.log('fbulkBar shown:',bar.classList.contains('show'),'count text:',doc.getElementById('fbulkCount').textContent);
 console.log((bar.classList.contains('show'))?'PASS bar visible':'FAIL');
 // delete folders
 click(doc.getElementById('fbulkDelete'));
 setTimeout(()=>{
   console.log('=== T3 parallel rmdir + stacked progress ===');
   console.log('rmdir calls:',rmdirCalls.length,'->',rmdirCalls.join(','),'(expect 3)');
   var mp=doc.getElementById('mprogScrim');
   console.log('multi-progress dialog was shown:', mp.className.indexOf('show')>=0);
   console.log(rmdirCalls.length===3?'PASS all 3 folders deleted':'FAIL');
 },400);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);

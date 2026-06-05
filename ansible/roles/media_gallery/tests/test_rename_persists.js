const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// STALE manifest (server hasn't rebuilt yet) — still has OLD folder name
const staleManifest=[
 {stem:'a1',chat:'OldName',thumb:'thumb/OldName/a1.jpg',file:'by-chat/OldName/a1.jpg',type:'image',date:'2026-01-01',size:1}];
// shared localStorage across the two "page loads"
var lsStore={};
function mkLS(){return {getItem:k=>k in lsStore?lsStore[k]:null,setItem:(k,v)=>{lsStore[k]=String(v);},removeItem:k=>{delete lsStore[k];}};}
function load(){return new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(staleManifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['OldName'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('/rename/')>=0)return Promise.resolve({status:200,json:()=>Promise.resolve({renamed:'OldName',to:'NewName'})});
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=(m,d)=>'NewName';window.scrollTo=()=>{};
 Object.defineProperty(window,'localStorage',{value:mkLS()});
}});}
function folderNames(doc){return [].map.call(doc.querySelectorAll('#folderGrid .folder .fname'),e=>e.textContent);}
// SESSION 1: rename OldName -> NewName
var d1=load();
setTimeout(()=>{ try{
 var doc=d1.window.document;
 console.log('session1 folders before:',folderNames(doc).join(','));
 // right-click OldName -> Rename
 var f=null;doc.querySelectorAll('#folderGrid .folder').forEach(x=>{if(x.dataset.chat==='OldName')f=x;});
 f.dispatchEvent(new d1.window.MouseEvent('contextmenu',{bubbles:true,clientX:10,clientY:10}));
 var menu=doc.getElementById('ctxMenu');var rn=null;menu.querySelectorAll('button').forEach(b=>{if(b.textContent.indexOf('Rename')>=0)rn=b;});
 rn.dispatchEvent(new d1.window.MouseEvent('click',{bubbles:true}));
 setTimeout(()=>{
   console.log('session1 folders after rename:',folderNames(doc).join(','));
   console.log('lsStore keys:',Object.keys(lsStore).join(','),'| rename=',lsStore['gal_pendingRename']);
   // SESSION 2: REFRESH — fresh load, STALE manifest (still OldName), but localStorage has the pending rename
   var d2=load();
   setTimeout(()=>{
     var doc2=d2.window.document;
     var names=folderNames(doc2);
     console.log('session2 (after refresh) folders:',names.join(','));
     console.log(names.indexOf('NewName')>=0 && names.indexOf('OldName')<0?'PASS rename survived refresh':'FAIL rename reverted to OldName');
     process.exit(0);
   },700);
 },200);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

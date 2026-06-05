const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// STALE: manifest + folders.json still list the folder being deleted (server rebuild not landed)
const manifest=[
 {stem:'a1',chat:'DelMe',thumb:'thumb/DelMe/a1.jpg',file:'by-chat/DelMe/a1.jpg',type:'image',date:'2026-01-01',size:1},
 {stem:'b1',chat:'KeepMe',thumb:'thumb/KeepMe/b1.jpg',file:'by-chat/KeepMe/b1.jpg',type:'image',date:'2026-01-02',size:1}];
const folders=['DelMe','KeepMe'];
var lsStore={};
function mkLS(){return {getItem:k=>k in lsStore?lsStore[k]:null,setItem:(k,v)=>{lsStore[k]=String(v);},removeItem:k=>{delete lsStore[k];}};}
function load(){return new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(folders.slice())});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('/rmdir/')>=0)return Promise.resolve({status:200,json:()=>Promise.resolve({removed:'DelMe'})});
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
 Object.defineProperty(window,'localStorage',{value:mkLS()});
}});}
function fnames(doc){return [].map.call(doc.querySelectorAll('#folderGrid .folder'),f=>f.dataset.chat).filter(Boolean);}
var d1=load();
setTimeout(()=>{ try{
 var doc=d1.window.document;
 console.log('before:',fnames(doc).join(','));
 var f=null;doc.querySelectorAll('#folderGrid .folder').forEach(x=>{if(x.dataset.chat==='DelMe')f=x;});
 f.dispatchEvent(new d1.window.MouseEvent('contextmenu',{bubbles:true,clientX:10,clientY:10}));
 var menu=doc.getElementById('ctxMenu');var del=null;menu.querySelectorAll('button').forEach(b=>{if(b.textContent.indexOf('Delete folder')>=0)del=b;});
 del.dispatchEvent(new d1.window.MouseEvent('click',{bubbles:true}));
 setTimeout(()=>{
   console.log('after delete (session1):',fnames(doc).join(','));
   console.log('pendingRmdir:',lsStore['gal_pendingRmdir']);
   // REFRESH: stale manifest+folders.json STILL list DelMe
   var d2=load();
   setTimeout(()=>{
     var names=fnames(d2.window.document);
     console.log('after refresh (session2):',names.join(','));
     console.log(names.indexOf('DelMe')<0 && names.indexOf('KeepMe')>=0?'PASS delete survived refresh':'FAIL DelMe came back');
     process.exit(0);
   },700);
 },250);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person1',thumb:'thumb/person1/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:1},
 {stem:'a2',chat:'person1',thumb:'thumb/person1/a2.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
const fmeta={"person1":{"cover":"a2","chat_ids":["100000001"]}};
let coverBody=null, chatidBody=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['person1'])});
   if(u.indexOf('/foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(fmeta)))});
   if(u.indexOf('/setcover')>=0){coverBody=JSON.parse(opts.body);return Promise.resolve({status:200,json:()=>Promise.resolve({})});}
   if(u.indexOf('/setchatids')>=0){chatidBody=JSON.parse(opts.body);return Promise.resolve({status:200,json:()=>Promise.resolve({})});}
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=(m,d)=>'999,888';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el,opts){el.dispatchEvent(new window.MouseEvent('click',Object.assign({bubbles:true,cancelable:true},opts||{})));}
function rclick(el,x,y){el.dispatchEvent(new window.MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:x||100,clientY:y||100}));}
setTimeout(()=>{ try{
 console.log('=== T1 cover from folderMeta (person1 cover=a2 -> tile shows a2 thumb) ===');
 var p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person1')p1=f;});
 var cov=p1.querySelector('img.cover');
 console.log('person1 cover src:',cov?cov.getAttribute('src'):'none');
 console.log(cov&&cov.getAttribute('src').indexOf('a2')>=0?'PASS uses pinned cover a2':'FAIL (should be a2 not a1)');
 console.log('=== T2 folder context menu -> Map chat IDs ===');
 rclick(p1,150,150);
 var menu=doc.getElementById('ctxMenu');
 var labels=[].map.call(menu.querySelectorAll('button'),b=>b.textContent);
 console.log('folder ctx items:',labels.join(' | '));
 var mapBtn=null;menu.querySelectorAll('button').forEach(b=>{if(b.textContent.indexOf('Map source')>=0)mapBtn=b;});
 if(mapBtn){click(mapBtn); setTimeout(()=>{
   console.log('setchatids body:',JSON.stringify(chatidBody));
   console.log(chatidBody&&chatidBody.folder==='person1'&&chatidBody.chat_ids.length===2?'PASS chat-id mapping sent':'FAIL');
   process.exit(0);
 },100);} else {console.log('FAIL no Map button');process.exit(1);}
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },800);

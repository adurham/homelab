const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'Real',thumb:'thumb/Real/a1.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['Real'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('trashqueue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:17,reaped:3,failed:0})});
   if(u.indexOf('movequeue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0,moved:0,failed:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 click(doc.getElementById('bgTasks'));   // open activity log
 setTimeout(()=>{
   var body=doc.getElementById('tkBody').textContent;
   console.log('activity log body:',JSON.stringify(body.slice(0,160)));
   console.log(body.indexOf('Deleting 17')>=0?'PASS shows live deleting 17':'FAIL no live queue');
   console.log(body.indexOf('No activity')<0?'PASS not empty':'FAIL says no activity');
   process.exit(0);
 },300);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

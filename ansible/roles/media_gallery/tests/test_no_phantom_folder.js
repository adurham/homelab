const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// manifest with one normal item AND one with empty chat (transient bad state)
const manifest=[
 {stem:'a1',chat:'Real',thumb:'thumb/Real/a1.jpg',file:'f',type:'image',date:'2026-01-01',size:1},
 {stem:'x1',chat:'',thumb:'thumb//x1.jpg',file:'f',type:'image',date:'2026-01-02',size:1}];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['Real'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
setTimeout(()=>{ try{
 var names=[].map.call(doc.querySelectorAll('#folderGrid .folder'),f=>f.dataset.chat).filter(Boolean);
 console.log('folder tiles:',names.join(','));
 var bad=names.filter(n=>n==='(unknown)'||n===''||n==='undefined');
 console.log(bad.length===0 && names.indexOf('Real')>=0?'PASS no phantom folder, Real present':'FAIL phantom: '+bad.join(','));
 process.exit(0);
}catch(e){console.log('EXC:',e.message);process.exit(1);} },700);

const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[{stem:'a1',chat:'Real',thumb:'thumb/Real/a1.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
let mkdirCalled=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['Real'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('/mkdir/')>=0){mkdirCalled=decodeURIComponent(u.split('/mkdir/')[1]);return Promise.resolve({status:200,json:()=>Promise.resolve({})});}
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'BrandNew';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 var tiles=[].map.call(doc.querySelectorAll('#folderGrid .folder'),f=>f.dataset.chat||(f.classList.contains('newfolder')?'NEWFOLDER':'?'));
 console.log('folder tiles:',tiles.join(','));
 console.log('=== T1 no All-items (*) tile ==='); console.log(tiles.indexOf('*')<0?'PASS no All items':'FAIL All items present');
 console.log('=== T2 no New-folder tile ==='); console.log(tiles.indexOf('NEWFOLDER')<0 && tiles.indexOf('?')<0?'PASS no newfolder tile':'FAIL newfolder tile present');
 console.log('=== T3 header New folder button works ===');
 var btn=doc.getElementById('newFolderBtn'); console.log('button present:',!!btn);
 click(btn);
 setTimeout(()=>{ console.log('mkdir called with:',mkdirCalled); console.log(mkdirCalled==='BrandNew'?'PASS button creates folder':'FAIL'); process.exit(0); },150);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },700);

const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
// STALE manifest: server still returns a1,a2,a3 in person_1 even after we move a1,a3
const staleManifest=[
 {stem:'a1',chat:'person_1',file:'by-chat/person_1/a1.jpg',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01'},
 {stem:'a2',chat:'person_1',file:'by-chat/person_1/a2.jpg',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02'},
 {stem:'a3',chat:'person_1',file:'by-chat/person_1/a3.jpg',thumb:'thumb/person_1/a3.jpg',type:'image',date:'2026-01-03'},
 {stem:'b1',chat:'person_2',file:'by-chat/person_2/b1.jpg',thumb:'thumb/person_2/b1.jpg',type:'image',date:'2026-01-04'},
];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(staleManifest)))});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=(m)=>{window.__a=m;};window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 let p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 let tiles=doc.querySelectorAll('#photoGrid .tile');
 console.log('person_1 tiles before move:',tiles.length,'(expect 3)');
 click(tiles[0].querySelector('.selbox')); click(tiles[2].querySelector('.selbox')); // a1,a3
 click(doc.getElementById('bulkMove'));
 let p2=null;doc.querySelectorAll('#bulkMoveMenu button').forEach(b=>{if(b.textContent.indexOf('person_2')>=0)p2=b;});
 click(p2);
 // wait for move chain + the immediate (stale) reloadManifest to run
 setTimeout(()=>{
   let after=doc.querySelectorAll('#photoGrid .tile').length;
   console.log('person_1 tiles AFTER move + stale refetch:',after,'(expect 1 — a2 only)');
   console.log(after===1?'>>> PASS: moved files did NOT reappear <<<':'>>> FAIL: files came back (the bug) <<<');
   // and progress dialog showed?
   console.log('progress dialog was shown:', doc.getElementById('progScrim').className.indexOf('show')>=0 || 'auto-closed');
 },500);
}catch(e){console.log('EXC:',e.message,e.stack);} },800);

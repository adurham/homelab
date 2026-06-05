const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'person_1',file:'by-chat/person_1/a1.jpg',thumb:'thumb/person_1/a1.jpg',type:'image',date:'2026-01-01'},
 {stem:'a2',chat:'person_1',file:'by-chat/person_1/a2.jpg',thumb:'thumb/person_1/a2.jpg',type:'image',date:'2026-01-02'},
 {stem:'a3',chat:'person_1',file:'by-chat/person_1/a3.jpg',thumb:'thumb/person_1/a3.jpg',type:'image',date:'2026-01-03'},
 {stem:'b1',chat:'person_2',file:'by-chat/person_2/b1.jpg',thumb:'thumb/person_2/b1.jpg',type:'image',date:'2026-01-04'},
];
let batchBody=null;
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(manifest)});
   if(u.indexOf('/movemark')>=0){ batchBody=JSON.parse(opts.body); return Promise.resolve({status:200,json:()=>Promise.resolve({marked:batchBody.stems.length})}); }
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=(m)=>{window.__a=m;};window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 let p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 let tiles=doc.querySelectorAll('#photoGrid .tile');
 click(tiles[0].querySelector('.selbox')); click(tiles[2].querySelector('.selbox'));
 click(doc.getElementById('bulkMove'));
 let p2=null; doc.querySelectorAll('#bulkMoveMenu button').forEach(b=>{ if(b.textContent.indexOf('person_2')>=0) p2=b; });
 click(p2);
 setTimeout(()=>{
   const ok = batchBody && batchBody.src==='person_1' && batchBody.dest==='person_2' &&
              batchBody.stems.length===2 && batchBody.stems.indexOf('a1')>=0 && batchBody.stems.indexOf('a3')>=0;
   console.log('batch body:', JSON.stringify(batchBody));
   console.log(ok?'>>> PASS: one /movemark with both stems to person_2 <<<':'>>> FAIL <<<');
 },300);
}catch(e){console.log('EXCEPTION:',e.message);} },800);

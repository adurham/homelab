const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[
 {stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',type:'image',date:'2026-01-03',size:1},
 {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',type:'image',date:'2026-01-02',size:1},
 {stem:'a3',chat:'F',thumb:'thumb/F/a3.jpg',file:'f',type:'image',date:'2026-01-01',size:1}];
// dedup.json: ONE group of 3 (a1 keep, a2+a3 delete by default)
const dedup={generated:'2026-06-04',hamming:6,scanned:3,dup_groups:1,dup_items:3,
 groups:[[{stem:'a1',chat:'F',thumb:'thumb/F/a1.jpg',file:'f',size:1,date:'2026-01-03'},
          {stem:'a2',chat:'F',thumb:'thumb/F/a2.jpg',file:'f',size:1,date:'2026-01-02'},
          {stem:'a3',chat:'F',thumb:'thumb/F/a3.jpg',file:'f',size:1,date:'2026-01-01'}]]};
let markCalls=[];
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url,opts)=>{const u=String(url);
   if(u.indexOf('manifest.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))});
   if(u.indexOf('folders.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(['F'])});
   if(u.indexOf('foldermeta')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
   if(u.indexOf('dedup.json')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(dedup)))});  // STALE: always returns all 3
   if(u.indexOf('/trashmark')>=0){markCalls.push(JSON.parse(opts.body));return Promise.resolve({status:200,json:()=>Promise.resolve({marked:1})});}
   if(u.indexOf('queue')>=0)return Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({queued:0})});
   return Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});};
 window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el){el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true}));}
setTimeout(()=>{ try{
 click(doc.getElementById('dedupBtn'));
 setTimeout(()=>{
   console.log('initial cards:',doc.querySelectorAll('.dupcard').length,'(3)');
   console.log('first trash...');
   click(doc.getElementById('dupTrash'));
   setTimeout(()=>{
     console.log('cards after 1st delete:',doc.querySelectorAll('.dupcard').length,'(expect 0 - group went to <2 members)');
     console.log('1st trashmark calls:',JSON.stringify(markCalls));
     markCalls=[];
     // simulate user clicking Trash marked AGAIN (or it re-rendered stale)
     var tr=doc.getElementById('dupTrash');
     if(tr){ click(tr); setTimeout(()=>{
       console.log('2nd trashmark calls (SHOULD BE EMPTY):',JSON.stringify(markCalls));
       console.log(markCalls.length===0?'PASS no double-delete':'FAIL re-deleted same items');
       process.exit(0);
     },150); } else { console.log('dupTrash gone (expected if view empty) - PASS'); process.exit(0); }
   },200);
 },200);
}catch(e){console.log('EXC:',e.message,e.stack);process.exit(1);} },800);
